#!/usr/bin/env bash
# Install Claude Code dotfiles into ~/.claude.
#
# Default: symlink hook scripts + statusline so `git pull` updates them live.
# Safe by design: anything it would replace is backed up first, and it NEVER
# clobbers an existing settings.json (which may hold your API keys).
#
# Usage:
#   ./install.sh            # symlink hooks + statusline, seed settings/overrides if absent
#   ./install.sh --copy     # copy instead of symlink (no live link to the repo)
#   ./install.sh --force-settings   # overwrite ~/.claude/settings.json (after backup)
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOKS_DIR="$CLAUDE_DIR/hooks"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$CLAUDE_DIR/backups/dotfiles-$STAMP"

MODE="symlink"
FORCE_SETTINGS=0
for arg in "$@"; do
  case "$arg" in
    --copy) MODE="copy" ;;
    --force-settings) FORCE_SETTINGS=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$HOOKS_DIR"

backup() {  # back up $1 into BACKUP_DIR (preserving basename) if it exists
  local f="$1"
  if [ -e "$f" ] || [ -L "$f" ]; then
    mkdir -p "$BACKUP_DIR"
    cp -P "$f" "$BACKUP_DIR/" 2>/dev/null || true
  fi
}

place() {  # place repo file $1 at dest $2 (symlink or copy), backing up first
  local src="$1" dest="$2"
  backup "$dest"
  rm -f "$dest"
  if [ "$MODE" = "symlink" ]; then
    ln -s "$src" "$dest"
  else
    cp "$src" "$dest"
  fi
  echo "  $MODE  $dest"
}

echo "Installing Claude Code dotfiles from $REPO_DIR -> $CLAUDE_DIR ($MODE)"

# 1. Hook scripts
for f in handoff_reminder.py project_session_start.py notify_local.py; do
  place "$REPO_DIR/hooks/$f" "$HOOKS_DIR/$f"
done

# 2. Statusline
place "$REPO_DIR/statusline/statusline.py" "$CLAUDE_DIR/statusline.py"

# 3. project-overrides.json — seed from example only if absent (machine-specific)
if [ ! -e "$HOOKS_DIR/project-overrides.json" ]; then
  cp "$REPO_DIR/hooks/project-overrides.json.example" "$HOOKS_DIR/project-overrides.json"
  echo "  seed   $HOOKS_DIR/project-overrides.json (edit with your project paths)"
else
  echo "  keep   $HOOKS_DIR/project-overrides.json (already present)"
fi

# 4. settings.json — merge hooks/statusLine into existing settings, preserving user keys
SETTINGS="$CLAUDE_DIR/settings.json"
if [ ! -e "$SETTINGS" ]; then
  cp "$REPO_DIR/settings.json" "$SETTINGS"
  echo "  seed   $SETTINGS (from template)"
elif [ "$FORCE_SETTINGS" = "1" ]; then
  backup "$SETTINGS"
  cp "$REPO_DIR/settings.json" "$SETTINGS"
  echo "  force  $SETTINGS (old one backed up)"
elif command -v jq &>/dev/null; then
  backup "$SETTINGS"
  # Deep-merge: existing settings win for scalar keys; template wins for hooks/statusLine
  jq -s '.[0] * .[1]' "$SETTINGS" "$REPO_DIR/settings.json" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
  echo "  merge  $SETTINGS (hooks + statusLine merged in, your keys preserved)"
else
  cp "$REPO_DIR/settings.json" "$SETTINGS.dotfiles-new"
  echo "  WARN   jq not found — wrote template to $SETTINGS.dotfiles-new"
  echo "         install jq and re-run, or merge manually"
fi

[ -d "$BACKUP_DIR" ] && echo "Backups saved under $BACKUP_DIR"
echo "Done. Restart Claude Code (or /hooks) to pick up changes."
