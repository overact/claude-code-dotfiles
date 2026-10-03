#!/usr/bin/env bash
# The status line renders from stdin alone, and its speed segment aggregates the
# cc-turn-metrics file: token-weighted tok/s and median TTFT over the last 5.
source "$(dirname "$0")/lib.sh"
mkdir -p "$TMP/.claude/statusline-metrics"
now=$(python3 -c 'import time; print(int(time.time() * 1000))')
python3 - "$TMP/.claude/statusline-metrics/s1.json" "$now" <<'PY'
import json, sys
path, now = sys.argv[1], int(sys.argv[2])
hist = [  # (output_tokens, gen_ms, ttft_ms); the tiny reply has no speed
    (162, 1788, 806), (90, 787, 853), (89, 713, 932), (91, 797, 868), (4, 7, 900)]
h = [{"at": now, "output_tokens": t, "gen_ms": g, "ttft_ms": f, "tps": None if t < 5 else round(t / g * 1000, 1)} for t, g, f in hist]
json.dump({**h[-1], "history": h}, open(path, "w"))
PY
render() { echo "$1" | HOME="$TMP" python3 "$REPO/statusline/statusline.py" | sed 's/\x1b\[[0-9;]*m//g'; }
out=$(render '{"session_id":"s1","model":{"display_name":"Opus"},"context_window":{"used_percentage":77,"context_window_size":1000000},"cost":{"total_duration_ms":5000}}')
line1=$(echo "$out" | head -1)
case "$line1" in *"ctx 77%/1M → /compact?"*) ;; *) fail "ctx hint missing: $line1";; esac
# 432 tokens / 4085 ms = 106 tok/s; median TTFT of 806 853 868 900 932 = 868 ms
case "$line1" in *"106 tok/s (0.9s)"*) ;; *) fail "speed segment wrong: $line1";; esac
eq "$(echo "$out" | wc -l | tr -d ' ')" 2 "two rows"
# no metrics file: the segment hides and nothing breaks
out=$(render '{"session_id":"none","model":{"display_name":"Opus"}}')
case "$out" in *"tok/s"*) fail "speed shown without a metrics file";; esac
