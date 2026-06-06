# Example project-level hooks

These are **templates**, not drop-in files. They show the pattern the user-level
hooks deliberately avoid: project-specific automation that only makes sense
inside one repo (validating that repo's configs, running that repo's test
suite).

| File | Event | What it does |
|---|---|---|
| `validate_config.py` | `PostToolUse(Write\|Edit)` | When a config file is edited, validate it immediately and surface pass/fail. Catches a bad config before an expensive job consumes it. |
| `run_regression_tests.py` | `PostToolUse(Write\|Edit)`, async | When a source file is edited, run the test suite in the background; on failure, `asyncRewake` wakes the model with the error. |
| `settings.local.json.example` | — | How to wire both into `<project>/.claude/settings.local.json`. |

## How to adapt

1. Copy the `.py` files into your repo at `<project>/.claude/hooks/`.
2. Edit the marked `--- EDIT ... ---` lines: the path match condition and the
   validate/test command.
3. Copy the wiring from `settings.local.json.example` into your repo's
   `.claude/settings.json` (shared) or `.claude/settings.local.json` (local).
4. Both use `$CLAUDE_PROJECT_DIR`, which Claude Code expands to the project root
   for project-level hooks — so no absolute paths to hand-edit per machine.

## Why these are NOT in the synced user config

User-level hooks run for **every** project. A hook that imports one repo's
package or runs one repo's `pytest` would break or waste time everywhere else.
Keep that kind of automation project-scoped.
