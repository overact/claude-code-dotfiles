# claude-code-dotfiles

Portable, machine-agnostic [Claude Code](https://claude.com/claude-code) hooks
and status line. Clone on any device, run `./install.sh`, and your terminal
gets the same status line, session-start context injection, handoff reminders,
and desktop notifications.

Everything here is **generic** — no hardcoded usernames, no absolute paths, no
secrets. Machine-specific bits (project paths, API keys) stay local and
gitignored.

## What's inside

| Path | Scope | What it does |
|---|---|---|
| `statusline/statusline.py` | status line | `user@host:cwd (branch✓) │ model │ 🧠effort │ ctx% │ 5h quota │ 7d quota`. Quota pulled from the local OAuth credential and cached 180 s. |
| `hooks/project_session_start.py` | `SessionStart` | Auto-detects the git root and injects "read these first" files (`AGENTS.md`, `CLAUDE.md`, `docs/…`), open `TODO.md` items, and the latest handoff note. Per-project tweaks via `project-overrides.json`. |
| `hooks/handoff_reminder.py` | `Stop` | Reminds you to write a handoff note when a session gets long (≥4 MB transcript or ≥50 user turns). |
| `hooks/notify_local.py` | `Notification` + `Stop` | Native desktop notification — **WSL2 / native Windows / macOS / Linux**, auto-detected. Fires on "needs your input", and on turn-end only if the turn ran ≥`CC_BUSY_THRESHOLD_S` (60 s). |
| `settings.json` | user settings | Template wiring all of the above with `$HOME`-relative paths. **No secrets.** |
| `examples/project-hooks/` | per-project | Templates for repo-scoped hooks (config validation, regression tests). Not synced as user config — see that folder's README. |

## Install

```bash
git clone https://github.com/overact/claude-code-dotfiles.git
cd claude-code-dotfiles
./install.sh            # symlinks hooks + statusline into ~/.claude
```

`install.sh` is non-destructive:

- **Symlinks** hook scripts + `statusline.py` into `~/.claude/` (so `git pull`
  updates them live). Use `--copy` for plain copies instead.
- Backs up anything it replaces to `~/.claude/backups/dotfiles-<timestamp>/`.
- Seeds `~/.claude/hooks/project-overrides.json` from the example **only if
  absent**.
- **Never silently overwrites `~/.claude/settings.json`** (it may hold your API
  keys). If one exists, the template is written alongside as
  `settings.json.dotfiles-new` for you to merge. Force with `--force-settings`.

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
the git root, advertises any of `AGENTS.md` / `CLAUDE.md` / `changes.md` /
`docs/**/README.md` that exist, reads `TODO.md`, and surfaces the newest
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
