#!/usr/bin/env python3
"""Cross-platform desktop notification for Claude Code — only for moments that matter.

No network, no subscription service. Pops a *native* desktop notification on the
current machine. Auto-detects the platform:

  - WSL2   -> Windows toast via powershell.exe
  - macOS  -> `osascript -e 'display notification ...'`
  - Linux  -> `notify-send` (libnotify)
  - else   -> silently no-op

Wire it on both the `Notification` and `Stop` events (see settings.json):

  - Notification event  -> ALWAYS notify, prominently (Claude needs permission /
    input / a choice, or is idle waiting).
  - Stop event          -> notify ONLY if this turn kept Claude busy for at least
    CC_BUSY_THRESHOLD_S seconds (default 60). Measured from a turn-start marker
    written by a tiny UserPromptSubmit hook. Quick Q&A turns stay silent; a long
    training run / download finishing will fire.

Marker files live under XDG_RUNTIME_DIR (falls back to /tmp).
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
TURN_START = os.path.join(RUNTIME, ".cc_turn_start")
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
    return shutil.which("powershell.exe") or (
        "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
        if os.path.exists(
            "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        else None
    )


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


def _notify_wsl(title: str, body: str, urgent: bool) -> bool:
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
    if _is_wsl():
        return _notify_wsl(title, body, urgent)
    if platform.system() == "Darwin":
        return _notify_macos(title, body, urgent)
    if platform.system() == "Linux":
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


def turn_elapsed() -> float:
    """Seconds since the turn started; large if the marker is missing."""
    try:
        with open(TURN_START) as fh:
            return time.time() - float(fh.read().strip())
    except Exception:
        return float("inf")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    event = data.get("hook_event_name", "")
    cwd = os.path.basename(data.get("cwd", "") or os.getcwd())

    if event == "Notification":
        # Claude wants permission / input / a choice — always, prominently.
        notify(
            S["need_you"].format(cwd=cwd),
            data.get("message", S["need_you_body"]),
            urgent=True,
        )
    else:  # Stop / SubagentStop — only when the turn was actually long-running.
        elapsed = turn_elapsed()
        if elapsed < BUSY_THRESHOLD_S:
            return 0
        # A missing turn-start marker yields inf; `int(inf // 60)` is int(nan)
        # which raises. Treat "unknown duration" as 0 min (empty suffix).
        mins = int(elapsed // 60) if elapsed != float("inf") else 0
        suffix = S["elapsed"].format(mins=mins) if mins >= 1 else ""
        notify(
            S["done"].format(cwd=cwd),
            S["done_body"].format(suffix=suffix).strip(),
            urgent=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
