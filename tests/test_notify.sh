#!/usr/bin/env bash
# The turn-end notification fires only for a long turn the user started in that
# session: not for a subagent, not for a turn Claude re-enters after a background
# task reports back, and not when another session's prompt is the recent one.
source "$(dirname "$0")/lib.sh"
cat > "$TMP/run.py" <<'PY'
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("n", sys.argv[1])
n = importlib.util.module_from_spec(spec); spec.loader.exec_module(n)
sent = []
n._dispatch = lambda title, body, urgent: sent.append(title) or True
sys.stdin = io.StringIO(sys.argv[2])
n.main()
print(len(sent))
PY
# Each call is a fresh process; the debounce marker is cleared so calls are independent.
ev() { rm -f "$TMP/.cc_last_toast"; XDG_RUNTIME_DIR="$TMP" python3 "$TMP/run.py" "$REPO/hooks/notify_local.py" "$1"; }
prompt() { ev "{\"hook_event_name\":\"UserPromptSubmit\",\"session_id\":\"$1\"}" >/dev/null
           echo $(( $(date +%s) - $2 )) > "$TMP/.cc_turn_start_$1"; }  # backdate the start
stop() { ev "{\"hook_event_name\":\"${2:-Stop}\",\"session_id\":\"$1\",\"cwd\":\"/x\"${3:-}}"; }

eq "$(stop s1)" 0 "no prompt recorded"
prompt s1 0; [ -s "$TMP/.cc_turn_start_s1" ] || fail "UserPromptSubmit wrote no marker"
prompt s1 120; eq "$(stop s1)" 1 "long user turn"
eq "$(stop s1)" 0 "re-entered turn after a background task"
prompt s1 120; eq "$(stop s1 SubagentStop)" 0 "SubagentStop"
eq "$(stop s1 Stop ',"agent_id":"a1"')" 0 "event from a subagent"
prompt s1 10; eq "$(stop s1)" 0 "short turn"
prompt s1 120; prompt s2 5
eq "$(stop s1)" 1 "s2's fresh prompt does not shorten s1's turn"
eq "$(stop s2)" 0 "s2's own short turn"
eq "$(ev '{"hook_event_name":"Notification","session_id":"s1","message":"m"}')" 1 "Notification always fires"
