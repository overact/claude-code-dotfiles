#!/usr/bin/env bash
# install.sh merges the template into an existing settings.json: your keys win,
# the template's hooks (per event) and statusLine are laid over them, and its
# CLAUDE_CODE_PLUGIN_DIRS entries are appended once.
source "$(dirname "$0")/lib.sh"
cfg="$TMP/cfg"; mkdir -p "$cfg"
cat > "$cfg/settings.json" <<'JSON'
{
  "env": { "SECRET_KEY": "keep-me", "CC_BUSY_THRESHOLD_S": "120", "CLAUDE_CODE_PLUGIN_DIRS": "/opt/other-mod" },
  "permissions": { "defaultMode": "default", "allow": ["Bash(ls:*)"] },
  "hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command", "command": "my-own-guard" } ] } ],
             "Stop": [ { "hooks": [ { "type": "command", "command": "old-stop" } ] } ] },
  "statusLine": { "type": "command", "command": "old-statusline", "refreshInterval": 10 },
  "model": "opus"
}
JSON
for run in 1 2; do HOME="$TMP" CLAUDE_CONFIG_DIR="$cfg" bash "$REPO/install.sh" >/dev/null; done
s="$cfg/settings.json"
eq "$(jq -r .env.SECRET_KEY "$s")" keep-me "your env keys survive"
eq "$(jq -r .env.CC_BUSY_THRESHOLD_S "$s")" 120 "your value wins over the template's"
eq "$(jq -r .permissions.defaultMode "$s")" default "your scalar settings win"
eq "$(jq -r .model "$s")" opus
eq "$(jq -r '.hooks.PreToolUse[0].hooks[0].command' "$s")" my-own-guard "your own hook events stay"
eq "$(jq -r '[.hooks.Stop[].hooks[].command] | any(. == "old-stop")' "$s")" false "the template's Stop replaces yours"
eq "$(jq -r .statusLine.command "$s")" "$(jq -r .statusLine.command "$REPO/settings.json")" "template statusLine"
eq "$(jq -r .env.CLAUDE_CODE_PLUGIN_DIRS "$s")" "/opt/other-mod:~/.claude/mods/cc-turn-metrics" "plugin dirs appended once"
[ -L "$cfg/mods/cc-turn-metrics" ] || fail "mods are linked into the config dir"
[ -L "$cfg/statusline.py" ] || fail "statusline is linked"
