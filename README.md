# claude-code-dotfiles

Portable, machine-agnostic [Claude Code](https://claude.com/claude-code) hooks
and status line. Clone on any device, run `./install.sh`, and your terminal
gets the same status line, session-start context injection and desktop
notifications.

Everything here is **generic** — no hardcoded usernames, no absolute paths, no
secrets. Machine-specific bits (project paths, API keys) stay local and
gitignored.

## What's inside

| Path | Scope | What it does |
|---|---|---|
| `statusline/statusline.py` | status line | `user@host:cwd (branch✓) │ model │ 🧠effort │ ctx% │ 5h quota │ 7d quota`. Quota read from the `rate_limits` field Claude Code passes on stdin (Pro/Max only; hidden until the session's first API response). Also shows how long the prompt cache stays warm, merged with the token count, e.g. `1.5M tok +59.5M cache (59m · 2 miss)`, from `prompt_cache` (Claude Code ≥ 2.1.251); the template sets `refreshInterval: 30` so the countdown keeps ticking while idle. After ctx, the speed of the last 5 main-loop requests, e.g. `81 tok/s (0.8s)`: token-weighted decode speed, then median time to first token, grey 5 minutes after the last request; fed by the `cc-turn-metrics` mod below. Colors: set `CC_STATUSLINE_THEME` under `env` in `settings.json` (not in the `statusLine` command: `install.sh` lays the template's `statusLine` over yours) to `default`, `tokyo`, `nord`, `solarized`, `dracula` or `mono`. |
| `mods/cc-turn-metrics/` | mod (function hooks) | Times every main-loop model request as it streams (TTFT to the `message_start` envelope; output tokens over decode time) into `~/.claude/statusline-metrics/<session>.json` for the status line, since Claude Code does not pass these on stdin. Linked to `~/.claude/mods/` and loaded in every session through `CLAUDE_CODE_PLUGIN_DIRS` in `settings.json`. Tests: `claude plugin test mods/cc-turn-metrics`. |
| `hooks/project_session_start.py` | `SessionStart` | Auto-detects the git root (a home directory under git does not count) and injects "read these first" files (`changes.md`, `docs/…`; `AGENTS.md` only when a `CLAUDE.md` exists without an `@AGENTS.md` import, since Claude Code already loads it otherwise), open `TODO.md` items, and the latest handoff note. Per-project tweaks via `project-overrides.json`. |
| `hooks/notify_local.py` | `Notification` + `Stop` | Native desktop notification — **WSL2 / native Windows / macOS / Linux**, auto-detected. Fires on "needs your input", and on turn-end only if the turn ran ≥`CC_BUSY_THRESHOLD_S` (60 s). |
| `tests/` | checks | `bash tests/run.sh`: the settings merge in `install.sh`, the status line (incl. the speed segment) and the SessionStart hook, each in a throwaway `HOME`. Run it before pushing. |
| `settings.json` | user settings | Template wiring all of the above with `$HOME`-relative paths. **No secrets.** |
| `examples/project-hooks/` | per-project | Templates for repo-scoped hooks (config validation, regression tests). Not synced as user config — see that folder's README. |

## Install

```bash
git clone https://github.com/overact/claude-code-dotfiles.git
cd claude-code-dotfiles
./install.sh            # symlinks hooks + statusline + mods into ~/.claude
```

`install.sh` is non-destructive:

- **Symlinks** hook scripts + `statusline.py` into `~/.claude/` (so `git pull`
  updates them live). Use `--copy` for plain copies instead.
- Backs up anything it replaces to `~/.claude/backups/dotfiles-<timestamp>/`.
- Seeds `~/.claude/hooks/project-overrides.json` from the example **only if
  absent**.
- **Never silently overwrites `~/.claude/settings.json`** (it may hold your API
  keys). If one exists, it is backed up and the template is merged in with `jq`:
  your values win for every key, except that the template's `hooks` (per event)
  and `statusLine` are laid over yours, and its `CLAUDE_CODE_PLUGIN_DIRS` entries
  are appended to your list rather than replacing it. Without `jq`, the template
  is written alongside as `settings.json.dotfiles-new` for you to merge. Replace
  outright with `--force-settings`.

Then restart Claude Code (or run `/hooks` to reload).

### Custom config dir

If your Claude config lives somewhere other than `~/.claude`, set
`CLAUDE_CONFIG_DIR` before running `install.sh`.

## Secrets & machine-specific config — keep them OUT of the repo

This repo is public; treat it as such.

- **API keys / tokens**: do **not** put them in the synced `settings.json`.
  Either keep them in your own `~/.claude/settings.json` (gitignored, the
  installer won't overwrite it) or, cleaner, `export` them from your shell
  profile (`~/.bashrc`, `~/.zshrc`) — Claude Code inherits the shell env.
- **Per-project paths**: live in `~/.claude/hooks/project-overrides.json`,
  seeded from `project-overrides.json.example` and gitignored.

## Tunables (env vars)

| Var | Default | Effect |
|---|---|---|
| `CC_BUSY_THRESHOLD_S` | `60` | A `Stop` turn must exceed this many seconds to fire a "task done" notification. |
| `CC_NOTIFY_DEBOUNCE_S` | `8` | Collapse duplicate notifications fired within this window. |
| `CC_NOTIFY_LANG` | `zh` | Notification text language — `zh` or `en`. |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Where the installer writes (read at install time). |

## project_session_start: per-project overrides

Copy `hooks/project-overrides.json.example` to
`~/.claude/hooks/project-overrides.json` and key it by absolute project root:

```json
{
  "/abs/path/to/project": {
    "note": "One-line project identity injected at session start.",
    "todo": "/abs/path/to/project/TODO.md",
    "handoff_dir": "/abs/path/to/project/docs/handoffs",
    "extra_files": ["/abs/path/to/project/docs/decisions/README.md"]
  }
}
```

All fields optional. Without an override the hook still works: it auto-detects
the git root, advertises any of `changes.md` / `docs/**/README.md` (and `AGENTS.md`
when Claude Code would not load it by itself) that exist, reads `TODO.md`, and surfaces the newest
`docs/handoffs/*.md`.

## Requirements

- `python3` on `PATH` (hooks + status line are stdlib-only). On native Windows
  the interpreter is usually `python` — change `python3` to `python` in the
  hook/statusLine commands in your `settings.json`.
- Desktop notifications need: WSL2/native Windows → `powershell` (or `pwsh`);
  macOS → `osascript`; Linux → `notify-send` (`libnotify`). Missing tool →
  notifications no-op silently, nothing else breaks.

## License

MIT — see [LICENSE](LICENSE).
