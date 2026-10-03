#!/usr/bin/env python3
"""Status line: user@host:cwd | model | think | ctx | 5hr quota | weekly quota"""

import json, sys, os, time, subprocess
from datetime import datetime

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
# Collapse $HOME to ~, then keep only the last two segments (parent / current
# dir); anything above is replaced by a leading ~. So /mnt/data/proj/my_repo
# renders as ~/proj/my_repo and ~/.config/nvim/lua as ~/nvim/lua. Paths that are
# already two segments or fewer (and not under $HOME) keep their real /-prefix.
_home = os.path.expanduser("~")
_full = _cwd.replace(_home, "~", 1) if _cwd.startswith(_home) else _cwd

def shorten_path(p):
    home = p.startswith("~")
    segs = [s for s in (p[1:] if home else p).split("/") if s]
    if not segs:
        return "~" if home else "/"
    tail = segs[-2:]                       # parent + current dir
    truncated = home or len(segs) > len(tail)
    return ("~/" if truncated else "/") + "/".join(tail)

wd = shorten_path(_full)

# ── ANSI colors ──────────────────────────────────────────────────────────────
reset = "\033[00m"

def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"

def _palette(**roles):
    return {role: _rgb(color) for role, color in roles.items()}

# Pick one with CC_STATUSLINE_THEME (e.g. in settings.json "env"); unknown -> default.
# default uses the terminal's own 16 colors, mono uses none (dim + bold only).
THEMES = {
    "default": {
        "muted": "\033[02m",    "path": "\033[01;34m", "branch": "\033[01;33m",
        "ok":    "\033[01;32m", "warn": "\033[01;33m", "bad":    "\033[01;91m",
        "accent": "\033[01;36m", "add": "\033[01;32m", "del":    "\033[01;31m",
    },
    "tokyo": _palette(muted="#565f89", path="#7aa2f7", branch="#e0af68", ok="#9ece6a", warn="#e0af68",
                      bad="#f7768e", accent="#7dcfff", add="#9ece6a", **{"del": "#f7768e"}),
    "nord": _palette(muted="#616e88", path="#81a1c1", branch="#ebcb8b", ok="#a3be8c", warn="#ebcb8b",
                     bad="#bf616a", accent="#88c0d0", add="#a3be8c", **{"del": "#bf616a"}),
    "solarized": _palette(muted="#586e75", path="#268bd2", branch="#b58900", ok="#859900", warn="#b58900",
                          bad="#dc322f", accent="#2aa198", add="#859900", **{"del": "#dc322f"}),
    "dracula": _palette(muted="#6272a4", path="#bd93f9", branch="#f1fa8c", ok="#50fa7b", warn="#ffb86c",
                        bad="#ff5555", accent="#8be9fd", add="#50fa7b", **{"del": "#ff5555"}),
    "mono": {
        "muted": "\033[02m", "path": "", "branch": "", "ok": "", "warn": "",
        "bad": "\033[01m", "accent": "", "add": "", "del": "",
    },
}
_theme = THEMES.get(os.getenv("CC_STATUSLINE_THEME", "default").strip().lower(), THEMES["default"])

green      = _theme["ok"]
blue       = _theme["path"]
yellow     = _theme["warn"]
branch_c   = _theme["branch"]
red        = _theme["del"]
bright_red = _theme["bad"]
cyan       = _theme["accent"]
add_c      = _theme["add"]
dim        = _theme["muted"]

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

def git_uncommitted_diff(cwd):
    """(added, removed) lines for uncommitted tracked changes vs HEAD.

    `git diff --numstat HEAD` covers both staged and unstaged changes; untracked
    files are not counted. Returns None outside a repo / with no HEAD yet."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--numstat", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, cwd=cwd,
        )
    except Exception:
        return None
    add = rem = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            add += int(parts[0])
            rem += int(parts[1])
    return add, rem

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
    """Cumulative tokens for this session, split into fresh vs cache-read.

    Returns (work, cache_read): `work` = input + output + cache_creation (tokens
    billed at full rate — the real processing), `cache_read` = cached-prefix
    reads (billed ~0.1×). Lumping the two inflates the count, so the status line
    shows them apart. Incremental: a per-session offset cache means each render
    only reads bytes appended since the last render, so cost stays O(new)."""
    if not tp or not sid:
        return 0, 0
    try:
        size = os.stat(tp).st_size
    except OSError:
        return 0, 0
    cache_file = os.path.join(TOK_CACHE_DIR, f"{sid}.json")
    offset = 0
    work = 0
    cread = 0
    try:
        with open(cache_file) as f:
            cc = json.load(f)
        # Resume only from a v2 cache (has "work"); older files lack the split,
        # so recount from 0 rather than mislabel their lumped total.
        if cc.get("size", 0) <= size and "work" in cc:
            offset = cc.get("offset", 0)
            work   = cc.get("work", 0)
            cread  = cc.get("cread", 0)
    except Exception:
        pass                                      # shrank/rotated/missing → recount
    try:
        with open(tp, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return work, cread
    for line in chunk.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = (d.get("message") or {}).get("usage") or d.get("usage")
        if not u:
            continue
        work += (
            (u.get("input_tokens") or 0)
            + (u.get("output_tokens") or 0)
            + (u.get("cache_creation_input_tokens") or 0)
        )
        cread += (u.get("cache_read_input_tokens") or 0)
    try:
        os.makedirs(TOK_CACHE_DIR, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(
                {"offset": offset + len(chunk), "work": work, "cread": cread, "size": size},
                f,
            )
    except Exception:
        pass
    return work, cread

def fmt_countdown(epoch):
    """Return 'Xh Ym' or 'Xm' until the given Unix epoch (seconds)."""
    try:
        secs = int(epoch - time.time())
        if secs <= 0: return "now"
        h, rem = divmod(secs, 3600)
        mins   = rem // 60
        if h:    return f"{h}h{mins:02d}m"
        if mins: return f"{mins}m"
        return   f"{secs}s"
    except Exception:
        return "?"

METRICS_DIR = os.path.expanduser("~/.claude/statusline-metrics")
SPEED_STALE_S = 300   # 5 min after the last request the speed segment turns grey
SPEED_WINDOW = 5      # requests the speed segment aggregates

def last_request_metrics(session_id):
    """The cc-turn-metrics mod's record of this session's last request, or None.

    No file means the mod is not loaded here (or no request has finished yet).
    """
    if not session_id:
        return None
    try:
        with open(os.path.join(METRICS_DIR, f"{session_id}.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def fmt_speed(mt):
    """Render the speed segment `<tok/s> tok/s (<ttft>s)`, or "" to hide it.

    `mt` is the mod's file: the latest request at the top level (`at`, epoch ms
    when it finished) and the last requests under `history`. Over the last
    SPEED_WINDOW of them:
      tok/s  token-weighted, sum(output_tokens) / sum(gen_ms), skipping samples
             with no speed (tiny replies, a response that arrived in one burst);
             short tool-call replies stream ~30% faster than long text, so a
             plain last value jumps between request kinds
      TTFT   median, so one slow request does not move it
    """
    if not mt:
        return ""
    recent = (mt.get("history") or [mt])[-SPEED_WINDOW:]
    ttfts = sorted(r["ttft_ms"] for r in recent if r.get("ttft_ms") is not None)
    if not ttfts:
        return ""
    n = len(ttfts)
    med = ttfts[n // 2] if n % 2 else (ttfts[n // 2 - 1] + ttfts[n // 2]) / 2
    ttft = f"{med / 1000:.1f}s"
    timed = [r for r in recent if r.get("tps") is not None and r.get("gen_ms")]
    gen_ms = sum(r["gen_ms"] for r in timed)
    tps = f"{sum(r['output_tokens'] for r in timed) / gen_ms * 1000:.0f}" if gen_ms else "–"
    # Past SPEED_STALE_S since the last request finished it describes an old moment: grey.
    stale = time.time() - mt.get("at", 0) / 1000 > SPEED_STALE_S
    if stale:
        return f"{dim}{tps} tok/s ({ttft}){reset}"
    return f"{cyan}{tps}{reset} tok/s {dim}({reset}{ttft}{dim}){reset}"

# ── Quota data ────────────────────────────────────────────────────────────────
# Claude Code passes the 5h / 7d rate limits on stdin (`rate_limits`, claude.ai
# Pro/Max only). It is absent until the session's first API response, so the
# quota segments simply stay hidden until then. No network or credential access.
quota = data.get("rate_limits") or {}

# ── Build status line (two lines) ─────────────────────────────────────────────
SEP = f" {dim}│{reset} "

def join(parts):
    return SEP.join(p for p in parts if p)

# ── Line 1: identity / location / model / think / context (the "now" state) ────
l1 = [f"{green}{user}@{host}{reset}:{blue}{wd}{reset}"]

# Git branch (attached to the cwd segment, not separated). Use the session's
# workspace dir, not the process cwd, which can differ (e.g. worktree sessions).
try:
    import subprocess
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        stderr=subprocess.DEVNULL, text=True, cwd=_cwd
    ).strip()
    if branch:
        # Dirty = any staged or unstaged tracked change, the same set the Δ
        # segment counts (untracked files excluded; works before the first commit).
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            stderr=subprocess.DEVNULL, text=True, cwd=_cwd
        ).strip())
        marker = f"{red}✗{reset}" if dirty else f"{green}✓{reset}"
        l1[0] += f" {dim}({reset}{branch_c}{branch}{reset}{marker}{dim}){reset}"
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
        l1.append(f"🧠 off")
    elif _effort_level:
        col = _effort_colors.get(_effort_level, cyan)
        l1.append(f"🧠 {col}{_effort_level}{reset}")
    elif _thinking_on:
        l1.append(f"🧠 {green}on{reset}")

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

# Speed of the last few main-loop requests: `85 tok/s (1.7s)`, decode speed then TTFT.
# Claude Code measures TTFT itself but does not pass it to the status line, so the
# cc-turn-metrics mod times each request's stream into
# ~/.claude/statusline-metrics/<session>.json.
_speed = fmt_speed(last_request_metrics(data.get("session_id")))
if _speed:
    l1.append(_speed)

# ── Line 2: time / cumulative usage / budgets (metrics over time) ──────────────
l2 = []

# Local time. A space follows every icon: terminals disagree on how wide emoji are,
# and the next character landed on top of them.
l2.append(f"{dim}🕐 {reset}{datetime.now().astimezone().strftime('%H:%M')}")

# Session runtime
_dur = cost.get("total_duration_ms")
if _dur:
    l2.append(f"{dim}⏱ {reset}{fmt_duration(_dur)}")

# Uncommitted working-tree changes vs HEAD (staged + unstaged)
_diff = git_uncommitted_diff(_cwd)
if _diff and (_diff[0] or _diff[1]):
    l2.append(f"Δ {add_c}+{_diff[0]}{reset}/{red}-{_diff[1]}{reset}")

# Tokens and prompt cache as one segment: `1.5M tok +59.5M cache (59m · 2 miss)`.
# `work` is billed at full rate; cache reads are ~0.1x, kept apart so the count
# isn't inflated by re-reading a large cached context. In the brackets: how long
# the cached prefix stays warm (Claude Code >= 2.1.251, `prompt_cache`), then the
# miss count. Quiet except for the last minute and a cold cache. The 5m/1h TTL
# runs out while you are idle, so the countdown only stays honest with
# "refreshInterval" set on the statusLine. A warm flag past its expiry counts as
# cold. No symbols of uncertain width here (they overlapped the digits next to them).
_work, _cread = session_tokens(transcript_path, data.get("session_id"))
_pc = data.get("prompt_cache") or {}
_note = []
if _pc.get("caching_observed"):
    _exp = _pc.get("expires_at")
    _left = (_exp - time.time()) if _exp else 0
    if _pc.get("warm") and _left > 0:
        _note.append(f"{yellow if _left < 60 else dim}{fmt_countdown(_exp)}{reset}")
    else:
        _cold = f"{bright_red}cold{reset}"
        if _pc.get("recache_tokens_if_cold"):
            _cold += f"{dim} ~{fmt_tokens(_pc['recache_tokens_if_cold'])} to re-cache{reset}"
        _note.append(_cold)
    if _pc.get("misses"):
        _note.append(f"{dim}{_pc['misses']} miss{reset}")
if _work or _cread or _note:
    parts = []
    if _work or _cread:
        parts.append(f"{cyan}{fmt_tokens(_work)}{reset} tok")
    if _cread:
        parts.append(f"{dim}+{fmt_tokens(_cread)} cache{reset}")
    elif _note:
        parts.append(f"{dim}cache{reset}")
    seg = " ".join(parts)
    if _note:
        _dot = f" {dim}·{reset} "
        seg += f" {dim}({reset}{_dot.join(_note)}{dim}){reset}"
    l2.append(seg)

# Session cost
_usd = cost.get("total_cost_usd")
if _usd:
    l2.append(f"${_usd:.2f}")

# 5-hour quota  (space after ↻ so the countdown can't touch the glyph)
five = quota.get("five_hour", {})
five_pct = five.get("used_percentage")
if five_pct is not None:
    fc = color_for_pct(five_pct)
    cd = fmt_countdown(five["resets_at"]) if five.get("resets_at") else "?"
    l2.append(f"5h {fc}{bar(five_pct)} {five_pct:.0f}%{reset} ↻ {cd}")

# 7-day quota
seven = quota.get("seven_day", {})
seven_pct = seven.get("used_percentage")
if seven_pct is not None:
    sc = color_for_pct(seven_pct)
    cd = fmt_countdown(seven["resets_at"]) if seven.get("resets_at") else "?"
    l2.append(f"7d {sc}{bar(seven_pct)} {seven_pct:.0f}%{reset} ↻ {cd}")

# Long-session flag (transcript size/turns) — replaces the handoff_reminder Stop hook
if long_session(transcript_path):
    l2.append(f"{bright_red}⚑handoff{reset}")

print(join(l1))
print(join(l2))
