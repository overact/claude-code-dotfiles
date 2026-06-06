#!/usr/bin/env python3
"""Claude Code Stop hook: remind to write handoff for long sessions. Auto-detects project root."""
from __future__ import annotations

import json
import pathlib
import sys

MIN_TRANSCRIPT_BYTES = 4_000_000
MIN_TURNS = 50


def load_payload() -> dict:
    try:
        return json.load(sys.stdin)
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


def count_user_turns(transcript: pathlib.Path) -> int:
    if not transcript.exists():
        return 0
    count = 0
    try:
        with transcript.open("rb") as f:
            for line in f:
                if b'"role":"user"' in line:
                    count += 1
    except OSError:
        return 0
    return count


def main() -> None:
    data = load_payload()
    output = {"continue": True}

    root = find_git_root(data.get("cwd"))
    if not root:
        print(json.dumps(output))
        return

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        print(json.dumps(output))
        return

    transcript = pathlib.Path(transcript_path)
    try:
        size = transcript.stat().st_size
    except OSError:
        size = 0
    turns = count_user_turns(transcript) if size else 0

    if size >= MIN_TRANSCRIPT_BYTES or turns >= MIN_TURNS:
        output["systemMessage"] = (
            f"Handoff reminder for {root.name}: this session is getting long "
            f"({size // 1024} KiB transcript, ~{turns} user turns)."
        )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
