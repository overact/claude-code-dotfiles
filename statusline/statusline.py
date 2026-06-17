#!/usr/bin/env python3
"""Status line: user@host:cwd | model | think | ctx | 5hr quota | weekly quota"""

import json, sys, os, time
from datetime import datetime, timezone

data = json.loads(sys.stdin.read())
m = data.get("model", {})
c = data.get("context_window", {})
e = data.get("effort", {}) or {}
t = data.get("thinking", {}) or {}
cost = data.get("cost", {}) or {}
transcript_path = data.get("transcript_path")


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

SESSION_MIN_BYTES = 4_000_000   # ~4 MiB transcript
SESSION_MIN_TURNS = 50

def long_session(tp):
    """True when the transcript is large (≥4MB) or long (≥50 user turns).

    Mirrors the old handoff_reminder Stop hook so that signal lives in the
    status line instead of polluting context. Size is an O(1) stat; turns are
    only counted when the file is still under the byte threshold (bounded read).
    """
    if not tp:
        return False
    try:
        size = os.stat(tp).st_size
    except OSError:
        return False
    if size >= SESSION_MIN_BYTES:
        return True
    try:
        turns = 0
        with open(tp, "rb") as f:
            for line in f:
                if b'"role":"user"' in line:
                    turns += 1
        return turns >= SESSION_MIN_TURNS
    except OSError:
        return False

def fmt_duration(ms):
    """Compact wall-clock duration from milliseconds: '2h05m', '7m12s', '9s'."""
    try:
        s = int(ms // 1000)
    except Exception:
        return "?"
    h, rem = divmod(s, 3600)
    mn, sec = divmod(rem, 60)
    if h:  return f"{h}h{mn:02d}m"
    if mn: return f"{mn}m{sec:02d}s"
    return f"{sec}s"

TOK_CACHE_DIR = os.path.expanduser("~/.claude/.statusline-tokens")

def session_tokens(tp, sid):
    """Cumulative tokens for this session (input+output+cache), parsed from the
    transcript. Incremental: a per-session offset cache means each render only
    reads bytes appended since the last render, so cost stays O(new content)."""
    if not tp or not sid:
        return 0
    try:
        size = os.stat(tp).st_size
    except OSError:
        return 0
    cache_file = os.path.join(TOK_CACHE_DIR, f"{sid}.json")
    offset = 0
    total = 0
    try:
        with open(cache_file) as f:
            cc = json.load(f)
        if cc.get("size", 0) <= size:            # file grew or unchanged → resume
            offset = cc.get("offset", 0)
            total  = cc.get("total", 0)
    except Exception:
        pass                                      # shrank/rotated/missing → recount
    try:
        with open(tp, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return total
    for line in chunk.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = (d.get("message") or {}).get("usage") or d.get("usage")
        if not u:
            continue
        total += (
            (u.get("input_tokens") or 0)
            + (u.get("output_tokens") or 0)
            + (u.get("cache_creation_input_tokens") or 0)
            + (u.get("cache_read_input_tokens") or 0)
        )
    try:
        os.makedirs(TOK_CACHE_DIR, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump({"offset": offset + len(chunk), "total": total, "size": size}, f)
    except Exception:
        pass
    return total

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

# ── Build status line (two lines) ─────────────────────────────────────────────
SEP = f" {dim}│{reset} "

def join(parts):
    return SEP.join(p for p in parts if p)

# ── Line 1: identity / location / model / think / context (the "now" state) ────
l1 = [f"{green}{user}@{host}{reset}:{blue}{wd}{reset}"]

# Git branch (attached to the cwd segment, not separated)
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
        l1[0] += f" {dim}({reset}{yellow}{branch}{reset}{marker}{dim}){reset}"
except Exception:
    pass

# Model
model = m.get("display_name", "")
if model:
    l1.append(f"{cyan}{model}{reset}")

# Think mode: effort.level (low/medium/high/xhigh/max) + thinking.enabled
_effort_level = e.get("level")
_thinking_on = t.get("enabled")
if _effort_level or _thinking_on is not None:
    _effort_colors = {
        "low": dim, "medium": green, "high": yellow, "xhigh": red, "max": bright_red,
    }
    if _thinking_on is False:
        l1.append(f"🧠off")
    elif _effort_level:
        col = _effort_colors.get(_effort_level, cyan)
        l1.append(f"{col}🧠{_effort_level}{reset}")
    elif _thinking_on:
        l1.append(f"{green}🧠on{reset}")

# Context window + actionable hint
pct = c.get("used_percentage")
if pct is not None:
    win = c.get("context_window_size")
    ctx_color = color_for_pct(pct)
    ctx_str = f"{ctx_color}{pct}%{reset}"
    if win:
        ctx_str += f"/{fmt_ctx_window(win)}"
    seg = f"ctx {ctx_str}"
    if pct >= 80:
        seg += f" {bright_red}→ handoff?{reset}"
    elif pct >= 75:
        seg += f" {yellow}→ /compact?{reset}"
    l1.append(seg)

# ── Line 2: time / cumulative usage / budgets (metrics over time) ──────────────
l2 = []

# Local time
l2.append(f"{dim}🕐{reset}{datetime.now().astimezone().strftime('%H:%M')}")

# Session runtime
_dur = cost.get("total_duration_ms")
if _dur:
    l2.append(f"⏱{fmt_duration(_dur)}")

# Lines changed this session (from cost; free)
_la = cost.get("total_lines_added") or 0
_lr = cost.get("total_lines_removed") or 0
if _la or _lr:
    l2.append(f"Δ {green}+{_la}{reset}/{red}-{_lr}{reset}")

# Session token consumption (incremental transcript parse)
_tok = session_tokens(transcript_path, data.get("session_id"))
if _tok:
    l2.append(f"{cyan}{fmt_tokens(_tok)}{reset} tok")

# Session cost
_usd = cost.get("total_cost_usd")
if _usd:
    l2.append(f"${_usd:.2f}")

# 5-hour quota  (space after ↻ so the countdown can't touch the glyph)
five = quota.get("five_hour", {})
five_pct = five.get("utilization")
if five_pct is not None:
    fc = color_for_pct(five_pct)
    cd = fmt_countdown(five.get("resets_at", "")) if five.get("resets_at") else "?"
    l2.append(f"5h {fc}{bar(five_pct)} {five_pct:.0f}%{reset} ↻ {cd}")

# 7-day quota
seven = quota.get("seven_day", {})
seven_pct = seven.get("utilization")
if seven_pct is not None:
    sc = color_for_pct(seven_pct)
    cd = fmt_countdown(seven.get("resets_at", "")) if seven.get("resets_at") else "?"
    l2.append(f"7d {sc}{bar(seven_pct)} {seven_pct:.0f}%{reset} ↻ {cd}")

# Long-session flag (transcript size/turns) — replaces the handoff_reminder Stop hook
if long_session(transcript_path):
    l2.append(f"{bright_red}⚑handoff{reset}")

print(join(l1))
print(join(l2))
