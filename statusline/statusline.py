#!/usr/bin/env python3
"""Status line: user@host:cwd | model | think | ctx | 5hr quota | weekly quota"""

import json, sys, os, time
from datetime import datetime, timezone

data = json.loads(sys.stdin.read())
m = data.get("model", {})
c = data.get("context_window", {})
e = data.get("effort", {}) or {}
t = data.get("thinking", {}) or {}


user = os.getenv("USER", "")
host = os.uname().nodename.split(".")[0] if hasattr(os, "uname") else "unknown"
_cwd = data.get("workspace", {}).get("current_dir") or data.get("cwd") or os.getcwd()
# Use full path like \w in PS1, but collapse $HOME to ~
_home = os.path.expanduser("~")
wd = _cwd.replace(_home, "~", 1) if _cwd.startswith(_home) else _cwd

# ── ANSI colors ──────────────────────────────────────────────────────────────
green      = "\033[01;32m"
blue       = "\033[01;34m"
reset      = "\033[00m"
yellow     = "\033[01;33m"
red        = "\033[01;31m"
bright_red = "\033[01;91m"
cyan       = "\033[01;36m"
dim        = "\033[02m"

def color_for_pct(pct):
    if pct is None: return dim
    if pct < 50:  return green
    if pct < 80:  return yellow
    return bright_red

def fmt_tokens(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(int(n))

def fmt_ctx_window(n):
    if n >= 1_000_000: return f"{n/1_000_000:.0f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(int(n))

def bar(pct, width=6):
    """Render a compact filled/empty progress bar."""
    if pct is None: return "?" * width
    filled = round(pct / 100 * width)
    return "▓" * filled + "░" * (width - filled)

def fmt_countdown(iso_ts):
    """Return 'Xh Ym' or 'Xm' until the given ISO timestamp."""
    try:
        target = datetime.fromisoformat(iso_ts).astimezone(timezone.utc)
        now    = datetime.now(timezone.utc)
        secs   = int((target - now).total_seconds())
        if secs <= 0: return "now"
        h, rem = divmod(secs, 3600)
        mins   = rem // 60
        if h:   return f"{h}h{mins:02d}m"
        return  f"{mins}m"
    except Exception:
        return "?"

# ── Quota data (cached 180s) ──────────────────────────────────────────────────
CACHE_FILE  = os.path.expanduser("~/.claude/usage-cache.json")
CACHE_TTL   = 180   # seconds

def load_quota():
    """Fetch usage from Anthropic OAuth API, with file-level caching."""
    # Try cache first
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                cached = json.load(f)
            if time.time() - cached.get("_ts", 0) < CACHE_TTL:
                return cached
    except Exception:
        pass

    # Read OAuth token
    try:
        creds_path = os.path.expanduser("~/.claude/.credentials.json")
        with open(creds_path) as f:
            creds = json.load(f)
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token:
            return {}
    except Exception:
        return {}

    # Call Anthropic usage API
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read())
        result["_ts"] = time.time()
        with open(CACHE_FILE, "w") as f:
            json.dump(result, f)
        return result
    except Exception:
        return {}

quota = load_quota()

# ── Build status line ────────────────────────────────────────────────────────
prompt = f"{green}{user}@{host}{reset}:{blue}{wd}{reset}"

# Git branch
try:
    import subprocess
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        stderr=subprocess.DEVNULL, text=True, cwd=os.getcwd()
    ).strip()
    if branch:
        dirty = subprocess.call(
            ["git", "diff", "--quiet", "--exit-code"],
            stderr=subprocess.DEVNULL, cwd=os.getcwd()
        ) != 0
        marker = f"{red}✗{reset}" if dirty else f"{green}✓{reset}"
        prompt += f" {dim}({reset}{yellow}{branch}{reset}{marker}{dim}){reset}"
except Exception:
    pass

# Model
model = m.get("display_name", "")
if model:
    prompt += f" {dim}│{reset} {cyan}{model}{reset}"

# Think mode: effort.level (low/medium/high/xhigh/max) + thinking.enabled
# Renders as "🧠level" when thinking is enabled; "off" in dim when explicitly disabled;
# nothing when the model doesn't support effort (field absent).
_effort_level = e.get("level")
_thinking_on = t.get("enabled")
if _effort_level or _thinking_on is not None:
    _effort_colors = {
        "low":    dim,
        "medium": green,
        "high":   yellow,
        "xhigh":  red,
        "max":    bright_red,
    }
    if _thinking_on is False:
        prompt += f" {dim}│ 🧠off{reset}"
    elif _effort_level:
        col = _effort_colors.get(_effort_level, cyan)
        prompt += f" {dim}│{reset} {col}🧠{_effort_level}{reset}"
    elif _thinking_on:
        prompt += f" {dim}│{reset} {green}🧠on{reset}"

# Context window + actionable hint
pct = c.get("used_percentage")
if pct is not None:
    win = c.get("context_window_size")
    ctx_color = color_for_pct(pct)
    ctx_str = f"{ctx_color}{pct}%{reset}"
    if win:
        ctx_str += f"/{fmt_ctx_window(win)}"
    prompt += f" {dim}│{reset} ctx {ctx_str}"
    if pct >= 80:
        prompt += f" {bright_red}→ handoff?{reset}"
    elif pct >= 75:
        prompt += f" {yellow}→ /compact?{reset}"

# 5-hour quota
five = quota.get("five_hour", {})
five_pct = five.get("utilization")
five_reset = five.get("resets_at", "")
if five_pct is not None:
    fc = color_for_pct(five_pct)
    countdown = fmt_countdown(five_reset) if five_reset else "?"
    b = bar(five_pct)
    prompt += f" {dim}│{reset} 5h {fc}{b} {five_pct:.0f}%{reset} ↻{countdown}"

# 7-day quota
seven = quota.get("seven_day", {})
seven_pct = seven.get("utilization")
seven_reset = seven.get("resets_at", "")
if seven_pct is not None:
    sc = color_for_pct(seven_pct)
    countdown = fmt_countdown(seven_reset) if seven_reset else "?"
    b = bar(seven_pct)
    prompt += f" {dim}│{reset} 7d {sc}{b} {seven_pct:.0f}%{reset} ↻{countdown}"

print(prompt)
