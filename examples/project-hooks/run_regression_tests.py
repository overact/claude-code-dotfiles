#!/usr/bin/env python3
"""EXAMPLE project-level PostToolUse(Write|Edit) hook — async + asyncRewake.

Pattern: when a source file under your package is edited, run the regression
suite in the BACKGROUND. Silent on pass; on FAIL, exit 2 so `asyncRewake` wakes
the model with the failure message. No-op for any other file.

Caveat: this fires on every matching edit, so a multi-file refactor runs the
suite several times and may wake on transient mid-refactor breakage. Disable it
in <project>/.claude/settings.local.json if that becomes noisy.

This file is a TEMPLATE — edit the marked lines:
  1. PROJECT_ROOT / the source-path match condition.
  2. The test command (drop the `conda run` wrapper if you don't use conda).

Wire it in <project>/.claude/settings.json under "PostToolUse" with:
  "type": "command",
  "command": "/usr/bin/python3 $CLAUDE_PROJECT_DIR/.claude/hooks/run_regression_tests.py",
  "timeout": 120, "async": true, "asyncRewake": true,
  "statusMessage": "Running regression tests…"
"""
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

# --- EDIT: your package dir name and conda env (or remove conda entirely) ---
SRC_MARKER = "/src/"           # only run when an edited .py lives under this dir
CONDA_ENV = ""                  # e.g. "myenv"; leave "" to call python3 directly

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

f = (d.get("tool_input") or {}).get("file_path") or ""
if not (f.endswith(".py") and SRC_MARKER in f and PROJECT_ROOT in f):
    sys.exit(0)

if CONDA_ENV:
    cmd = ["conda", "run", "--no-capture-output", "-n", CONDA_ENV,
           "python3", "-B", "-m", "pytest", "tests/", "-q"]
else:
    cmd = ["/usr/bin/python3", "-B", "-m", "pytest", "tests/", "-q"]

r = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
last = (r.stdout.strip().splitlines() or [""])[-1][:200]
if r.returncode == 0:
    sys.exit(0)  # async, silent on success
print(json.dumps({"systemMessage": f"⚠ tests FAILED after editing "
                  f"{os.path.basename(f)}: {last}"}))
sys.exit(2)  # asyncRewake wakes the model on exit 2
