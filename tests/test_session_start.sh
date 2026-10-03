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
