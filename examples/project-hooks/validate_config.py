#!/usr/bin/env python3
"""EXAMPLE project-level PostToolUse(Write|Edit) hook.

Pattern: when a config file in this project is edited, validate it IMMEDIATELY
and surface a pass/fail systemMessage — so a malformed config is caught before a
long/expensive job ever consumes it. No-op for any other file. Never blocks
(always exit 0).

This file is a TEMPLATE. To adapt it to your project:
  1. Set PROJECT_ROOT (or read $CLAUDE_PROJECT_DIR, which Claude Code sets for
     project hooks).
  2. Replace the match condition (here: a YAML under configs/).
  3. Replace the validation command with whatever proves the file is good
     (import it, parse it, schema-check it, ...).

Wire it in <project>/.claude/settings.json (NOT settings.local.json if you want
it shared) under:
  "PostToolUse": [ { "matcher": "Write|Edit", "hooks": [ {
    "type": "command",
    "command": "/usr/bin/python3 $CLAUDE_PROJECT_DIR/.claude/hooks/validate_config.py",
    "timeout": 30, "statusMessage": "Validating config…" } ] } ]
"""
import json
import os
import subprocess
import sys

# Prefer the env var Claude Code injects for project hooks; fall back to the
# directory two levels up from this file (<root>/.claude/hooks/<this>).
PROJECT_ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

f = (d.get("tool_input") or {}).get("file_path") or ""
# --- EDIT THIS CONDITION for your project ---
if not (f.endswith(".yaml") and "/configs/" in f and PROJECT_ROOT in f):
    sys.exit(0)

# --- EDIT THIS COMMAND for your project's validator ---
code = (
    "import yaml,sys\n"
    f"yaml.safe_load(open(r'''{f}'''))\n"
    "print('valid YAML')\n"
)
r = subprocess.run(
    ["/usr/bin/python3", "-B", "-c", code],
    cwd=PROJECT_ROOT,
    capture_output=True,
    text=True,
)
name = os.path.basename(f)
if r.returncode == 0:
    out = r.stdout.strip().splitlines()
    print(json.dumps({"systemMessage": f"✓ {name} OK — {out[-1] if out else 'OK'}"}))
else:
    err = (r.stderr.strip().splitlines() or ["(no stderr)"])[-1][:300]
    print(json.dumps({"systemMessage": f"⚠ {name} validation FAILED: {err}"}))
sys.exit(0)
