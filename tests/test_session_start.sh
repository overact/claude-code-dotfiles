#!/usr/bin/env bash
# The SessionStart hook injects project context for a git project, and nothing
# for a home directory kept under git (or a folder inside it).
source "$(dirname "$0")/lib.sh"
mkdir -p "$TMP/home/proj" "$TMP/home/notes"
git -C "$TMP/home" init -q; git -C "$TMP/home/proj" init -q
printf -- '- [ ] ship it\n' > "$TMP/home/proj/TODO.md"
hook() { echo "{\"cwd\":\"$1\",\"source\":\"startup\"}" | HOME="$TMP/home" CLAUDE_CONFIG_DIR="$TMP/cfg" python3 "$REPO/hooks/project_session_start.py"; }
eq "$(hook "$TMP/home")" '{"continue": true}' "home root"
eq "$(hook "$TMP/home/notes")" '{"continue": true}' "folder inside home"
ctx=$(hook "$TMP/home/proj" | jq -r .hookSpecificOutput.additionalContext)
case "$ctx" in *"ship it"*) ;; *) fail "open TODO not injected";; esac
[ ! -e "$TMP/home/proj/docs/handoffs" ] || fail "the hook must not create folders"

# Claude Code loads CLAUDE.md itself, and AGENTS.md too when CLAUDE.md imports it
# or is absent: list AGENTS.md only for a CLAUDE.md without the import, never CLAUDE.md.
listed() { hook "$TMP/home/proj" | jq -r .hookSpecificOutput.additionalContext | grep -c "^- .*/$1\$" || true; }
echo '# rules' > "$TMP/home/proj/AGENTS.md"
eq "$(listed AGENTS.md)" 0 "AGENTS.md alone is auto-loaded"
printf '# Claude notes\n' > "$TMP/home/proj/CLAUDE.md"
eq "$(listed AGENTS.md)" 1 "CLAUDE.md without the import"
eq "$(listed CLAUDE.md)" 0 "CLAUDE.md is never listed"
printf '# Claude notes\n\n@AGENTS.md\n' > "$TMP/home/proj/CLAUDE.md"
eq "$(listed AGENTS.md)" 0 "CLAUDE.md imports AGENTS.md"
case "$(hook "$TMP/home/proj" | jq -r .hookSpecificOutput.additionalContext)" in
  *"prefer reading"*) fail "empty file list still printed its header";; esac
