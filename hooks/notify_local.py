#!/usr/bin/env python3
"""Cross-platform desktop notification for Claude Code — only for moments that matter.

No network, no subscription service. Pops a *native* desktop notification on the
current machine. Auto-detects the platform:

  - WSL2          -> Windows toast via powershell.exe
  - native Windows-> Windows toast via powershell / pwsh
  - macOS         -> `osascript -e 'display notification ...'`
  - Linux         -> `notify-send` (libnotify)
  - else          -> silently no-op

Wire it on the `UserPromptSubmit`, `Notification` and `Stop` events (see
settings.json):

  - UserPromptSubmit    -> record this session's turn start; never notifies.
  - Notification event  -> ALWAYS notify, prominently (Claude needs permission /
    input / a choice, or is idle waiting).
  - Stop event          -> notify ONLY if a turn the user started kept Claude
    busy for at least CC_BUSY_THRESHOLD_S seconds (default 60). Quick Q&A turns
    stay silent; a long training run / download finishing will fire.
    The Stop consumes the session's turn-start marker, so a turn Claude re-enters
    on its own (a background subagent or task reporting back) finds none and
    stays silent. Subagents' own SubagentStop never notifies.

Marker files live under XDG_RUNTIME_DIR (falls back to /tmp), one per session,
so concurrent sessions do not see each other's turns.
Never blocks Claude: any failure exits 0.

Tunables (env vars):
  CC_BUSY_THRESHOLD_S   seconds a Stop turn must exceed to notify (default 60)
  CC_NOTIFY_DEBOUNCE_S  collapse duplicate notifications fired within N s (default 8)
  CC_NOTIFY_LANG        "zh" (default) or "en" for the notification text
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time

BUSY_THRESHOLD_S = int(os.environ.get("CC_BUSY_THRESHOLD_S", "60"))
# Claude Code can fire BOTH `Notification` (waiting-for-input) and `Stop` (turn
# ended) within the same instant at the end of a turn -> two notifications.
# Collapse any second one fired within this window into the first.
DEBOUNCE_S = int(os.environ.get("CC_NOTIFY_DEBOUNCE_S", "8"))
LANG = os.environ.get("CC_NOTIFY_LANG", "zh")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LAST_TOAST = os.path.join(RUNTIME, ".cc_last_toast")

# ── Localised strings ─────────────────────────────────────────────────────────
STRINGS = {
    "zh": {
        "need_you": "🔔 Claude 需要你 · {cwd}",
        "need_you_body": "需要你的输入 / 授权 / 选择",
        "done": "✅ 长任务完成 · {cwd}",
        "done_body": "回合结束，可以回来看了 {suffix}",
        "elapsed": "(耗时约 {mins} 分钟)",
    },
    "en": {
        "need_you": "🔔 Claude needs you · {cwd}",
        "need_you_body": "Waiting for your input / approval / choice",
        "done": "✅ Long task done · {cwd}",
        "done_body": "Turn finished, you can come back {suffix}",
        "elapsed": "(took ~{mins} min)",
    },
}
S = STRINGS.get(LANG, STRINGS["zh"])


# ── Platform detection ────────────────────────────────────────────────────────
def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version") as fh:
            return "microsoft" in fh.read().lower()
    except Exception:
        return False


def _powershell() -> str | None:
    # Works for both WSL (powershell.exe on PATH or under /mnt/c) and native
    # Windows (powershell / pwsh on PATH).
    for name in ("powershell.exe", "powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    fallback = "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
    return fallback if os.path.exists(fallback) else None


# Build the toast XML in PowerShell; pass text via env vars so there is zero
# shell-quoting risk, and XML-escape inside PowerShell. duration is "long"
# (urgent) or "short".
_PS = (
    "$t=[System.Security.SecurityElement]::Escape($env:CC_TITLE);"
    "$b=[System.Security.SecurityElement]::Escape($env:CC_BODY);"
    "$d=$env:CC_DUR;"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
    "ContentType=WindowsRuntime]>$null;"
    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,"
    "ContentType=WindowsRuntime]>$null;"
    '$xml="<toast duration=`"$d`"><visual><binding template=`"ToastText02`">'
    '<text id=`"1`">$t</text><text id=`"2`">$b</text></binding></visual>'
    '<audio src=`"ms-winsoundevent:Notification.Default`"/></toast>";'
    "$doc=[Windows.Data.Xml.Dom.XmlDocument]::new();$doc.LoadXml($xml);"
    "$n=[Windows.UI.Notifications.ToastNotification]::new($doc);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    '"Claude Code").Show($n)'
)


def _notify_powershell(title: str, body: str, urgent: bool) -> bool:
    """Windows toast via PowerShell — used on both WSL2 and native Windows."""
    pwsh = _powershell()
    if not pwsh:
        return False
    env = dict(os.environ)
    env.update(CC_TITLE=title, CC_BODY=body, CC_DUR=("long" if urgent else "short"))
    try:
        subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", _PS],
            capture_output=True,
            timeout=8,
            check=False,
            env=env,
        )
        return True
    except Exception:
        return False


def _notify_macos(title: str, body: str, urgent: bool) -> bool:
    osa = shutil.which("osascript")
    if not osa:
        return False
    # Escape double quotes for the AppleScript string literals.
    t = title.replace('"', '\\"')
    b = body.replace('"', '\\"')
    sound = ' sound name "Submarine"' if urgent else ""
    script = f'display notification "{b}" with title "{t}"{sound}'
    try:
        subprocess.run([osa, "-e", script], capture_output=True, timeout=8, check=False)
        return True
    except Exception:
        return False


def _notify_linux(title: str, body: str, urgent: bool) -> bool:
    sender = shutil.which("notify-send")
    if not sender:
        return False
    try:
        subprocess.run(
            [sender, "-u", "critical" if urgent else "normal", title, body],
            capture_output=True,
            timeout=8,
            check=False,
        )
        return True
    except Exception:
        return False


def _dispatch(title: str, body: str, urgent: bool) -> bool:
    system = platform.system()
    if system == "Windows" or _is_wsl():
        return _notify_powershell(title, body, urgent)
    if system == "Darwin":
        return _notify_macos(title, body, urgent)
    if system == "Linux":
        return _notify_linux(title, body, urgent)
    return False


# ── Debounce + dispatch ───────────────────────────────────────────────────────
def debounced() -> bool:
    """True if a notification was already shown within DEBOUNCE_S (so skip this one)."""
    now = time.time()
    try:
        with open(LAST_TOAST) as fh:
            if now - float(fh.read().strip()) < DEBOUNCE_S:
                return True
    except Exception:
        pass
    try:
        with open(LAST_TOAST, "w") as fh:
            fh.write(str(now))
    except Exception:
        pass
    return False


def notify(title: str, body: str, urgent: bool) -> None:
    if debounced():
        return
    _dispatch(title, body, urgent)


def turn_marker(session_id: str) -> str:
    """Path of this session's turn-start marker."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return os.path.join(RUNTIME, f".cc_turn_start_{safe}")


def start_turn(session_id: str) -> None:
    """UserPromptSubmit: the user started a turn in this session."""
    try:
        with open(turn_marker(session_id), "w") as fh:
            fh.write(str(time.time()))
    except Exception:
        pass


def take_turn(session_id: str) -> float | None:
    """Stop: seconds since this session's user turn started, consuming the marker.

    None when there is no marker: this turn was not started by a user prompt
    (Claude re-entered on its own after a background subagent/task finished),
    or the prompt was submitted before this hook recorded per-session turns.
    """
    path = turn_marker(session_id)
    try:
        with open(path) as fh:
            started = float(fh.read().strip())
    except Exception:
        return None
    try:
        os.remove(path)
    except Exception:
        pass
    return time.time() - started


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    event = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    cwd = os.path.basename(data.get("cwd", "") or os.getcwd())

    if event == "UserPromptSubmit":
        start_turn(session_id)
    elif event == "Notification":
        # Claude wants permission / input / a choice — always, prominently.
        notify(
            S["need_you"].format(cwd=cwd),
            data.get("message", S["need_you_body"]),
            urgent=True,
        )
    else:  # Stop — only when a user-started turn was actually long-running.
        # A subagent finishing is not "the task is done": SubagentStop (or any
        # event carrying agent_id) stays silent even if someone wires it up.
        if event == "SubagentStop" or data.get("agent_id"):
            return 0
        elapsed = take_turn(session_id)
        if elapsed is None or elapsed < BUSY_THRESHOLD_S:
            return 0
        mins = int(elapsed // 60)
        suffix = S["elapsed"].format(mins=mins) if mins >= 1 else ""
        notify(
            S["done"].format(cwd=cwd),
            S["done_body"].format(suffix=suffix).strip(),
            urgent=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
