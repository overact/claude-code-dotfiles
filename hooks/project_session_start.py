#!/usr/bin/env python3
"""Claude Code SessionStart hook: auto-detect project root and inject context."""

from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import datetime

MAX_TODOS = 5
MAX_HANDOFF_LINES = 40

# Optional per-project overrides: ~/.claude/hooks/project-overrides.json
# Format: { "/abs/path/to/project": { "todo": "/abs/path/to/TODO.md", "note": "..." } }
OVERRIDES_FILE = pathlib.Path.home() / ".claude" / "hooks" / "project-overrides.json"


def load_overrides() -> dict:
    try:
        return json.loads(OVERRIDES_FILE.read_text()) if OVERRIDES_FILE.exists() else {}
    except Exception:
        return {}


def find_git_root(cwd: str | None) -> pathlib.Path | None:
    if not cwd:
        return None
    current = pathlib.Path(cwd).resolve()
    for path in [current, *current.parents]:
        if (path / ".git").exists():
            return path
    return None


def open_todos(path: pathlib.Path) -> list[str]:
    if not path or not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [
        m.group(1)
        for line in text.splitlines()
        if (m := re.match(r"\s*- \[ \]\s+(.+?)\s*$", line))
    ]


def latest_handoff_summary(handoff_dir: pathlib.Path, brief: bool = False) -> str:
    if not handoff_dir.exists():
        return ""
    candidates = [
        f for f in handoff_dir.iterdir() if f.suffix == ".md" and f.stem != "README"
    ]
    if not candidates:
        return ""
    candidates = sorted(candidates, key=handoff_sort_key, reverse=True)
    # On compaction the full handoff is already in the live transcript — a
    # one-line pointer is enough and saves re-injecting ~40 lines every compact.
    if brief:
        return f"Latest handoff on disk: {candidates[0].name} (read if you need it)."
    try:
        lines = candidates[0].read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    excerpt = "\n".join(lines[:MAX_HANDOFF_LINES])
    return f"Latest handoff ({candidates[0].name}):\n{excerpt}"


def handoff_sort_key(path: pathlib.Path) -> tuple[int, float, str]:
    """Prefer YYYY-MM-DD-HHMM-* handoff names; fall back to mtime for legacy names."""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})-(\d{4})-", path.name)
    if match:
        try:
            ts = datetime.strptime("".join(match.groups()), "%Y-%m-%d%H%M").timestamp()
            return (1, ts, path.name)
        except ValueError:
            pass
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (0, mtime, path.name)


def agents_md_auto_loaded(root: pathlib.Path) -> bool:
    """Whether Claude Code loads the root AGENTS.md by itself: by default it does
    when the project has no CLAUDE.md, and always when CLAUDE.md imports it."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return True
    text = claude_md.read_text(encoding="utf-8", errors="replace")
    return any(line.strip() in ("@AGENTS.md", "@./AGENTS.md") for line in text.splitlines())


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    # source: "startup" | "resume" | "clear" | "compact". On compact the prior
    # handoff is already in the live transcript, so inject a trimmed pointer
    # instead of re-dumping it.
    brief = data.get("source") == "compact"

    root = find_git_root(data.get("cwd"))
    # A home directory kept under git is not a project: nothing to inject there.
    if not root or root == pathlib.Path.home().resolve():
        print(json.dumps({"continue": True}))
        return

    overrides = load_overrides().get(str(root), {})

    handoff_dir = (
        pathlib.Path(overrides["handoff_dir"])
        if "handoff_dir" in overrides
        else root / "docs" / "handoffs"
    )

    # Candidate repo files (read those that exist). CLAUDE.md, and AGENTS.md when
    # Claude Code loads it too, are already in context: listing them is noise.
    candidates = [
        *([] if agents_md_auto_loaded(root) else [root / "AGENTS.md"]),
        root / "changes.md",
        root / "docs" / "decisions" / "README.md",
        root / "docs" / "experiments" / "README.md",
        root / "docs" / "handoffs" / "README.md",
    ]
    existing = [str(p) for p in candidates if p.exists()]
    for extra in overrides.get("extra_files", []):
        ep = pathlib.Path(extra)
        if ep.exists() and str(ep) not in existing:
            existing.append(str(ep))

    # TODO: check repo-local TODO.md first, then override path
    todo_path = pathlib.Path(overrides["todo"]) if "todo" in overrides else None
    if todo_path is None:
        for candidate in [root / "TODO.md", root / "docs" / "TODO.md"]:
            if candidate.exists():
                todo_path = candidate
                break
    todos = open_todos(todo_path)
    todo_text = (
        "\n".join(f"- {item}" for item in todos[:MAX_TODOS]) or "- No open TODOs found."
    )

    note = overrides.get("note", f"Project root: {root}")
    handoff_text = latest_handoff_summary(handoff_dir, brief=brief)

    context_parts = [
        f"Project startup context for {root.name}.",
        "",
        note,
        "",
        *(
            ["Before substantive work, prefer reading these project files when relevant:",
             *[f"- {p}" for p in existing], ""]
            if existing else []
        ),
        "Current TODOs:",
        todo_text,
    ]
    if handoff_text:
        context_parts += ["", handoff_text]

    print(
        json.dumps(
            {
                "continue": True,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(context_parts),
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
