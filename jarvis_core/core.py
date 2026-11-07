"""
JARVIS CORE — shared runtime for the Ultimate upgrade.

This package is intentionally side-effect free at import time.  The main
jarvis.py binds its module globals with ``install(globals())`` so every helper
here can call the original Jarvis functions (speak, Gemini clients, screen
vision, ...) without duplicating them.
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from collections import deque
from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CORE_DIR)                      # folder that contains jarvis.py
DATA_DIR = os.path.join(BASE_DIR, "jarvis_data")
REPORTS_DIR = os.path.join(BASE_DIR, "Jarvis_Reports")
DOCS_DIR = os.path.join(BASE_DIR, "Jarvis_Documents")
SKILLS_DIR = os.path.join(BASE_DIR, "jarvis_skills")
BROWSER_PROFILE_DIR = os.path.join(DATA_DIR, "browser_profile")
LOG_FILE = os.path.join(DATA_DIR, "jarvis.log")
AUDIT_FILE = os.path.join(DATA_DIR, "jarvis_audit.jsonl")
CONVERSATION_FILE = os.path.join(DATA_DIR, "conversations.jsonl")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

for _d in (DATA_DIR, REPORTS_DIR, DOCS_DIR, SKILLS_DIR, BROWSER_PROFILE_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

# --------------------------------------------------------------------------
# Bound jarvis.py globals
# --------------------------------------------------------------------------
G: dict = {}
_STATE_LOCK = threading.RLock()
_AUDIT_LOCK = threading.Lock()
_LLM_LOCK = threading.Lock()

CONFIG_DEFAULTS = {
    "safe_mode": True,
    "preferred_browser": "brave",
    "hud": True,
    "auto_learn": True,
    "research_depth": "standard",
    "email": {},
    "email_send_method": "",
}


def bind(g: dict) -> dict:
    """Bind the jarvis.py module globals (called once by install())."""
    global G
    G = g
    return G


def jget(name, default=None):
    return G.get(name, default)


def _event_set(name: str) -> bool:
    ev = G.get(name)
    try:
        return bool(ev and ev.is_set())
    except Exception:
        return False


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------
def now_str() -> str:
    return time.strftime("%A, %d %B %Y, %I:%M %p")


def stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def human_bytes(n) -> str:
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def truncate(text, limit=1200) -> str:
    text = "" if text is None else str(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def slugify(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^\w\s-]+", "", (text or "").lower(), flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s[:limit] or "report").strip("-")


def safe_filename(name: str, default: str = "document") -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (name or "").strip())
    return name[:120] or default


def desktop() -> str:
    return G.get("DESKTOP") or os.path.join(os.path.expanduser("~"), "Desktop")


def resolve_path(path: str) -> str:
    path = (path or "").strip().strip('"')
    if not path:
        return desktop()
    fn = G.get("_resolve_path")
    if fn:
        try:
            return fn(path)
        except Exception:
            pass
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(desktop(), path)
    return path


def open_path(path: str) -> str:
    fn = G.get("open_path")
    if fn:
        try:
            return fn(path)
        except Exception:
            pass
    try:
        os.startfile(path)
        return f"Opened: {path}"
    except Exception as e:
        return f"Could not open: {e}"


def open_url(url: str, browser: str | None = None) -> str:
    fn = G.get("_open_url")
    if fn:
        try:
            fn(url, browser)
            return f"Opened {url}"
        except Exception:
            pass
    try:
        webbrowser.open(url)
        return f"Opened {url}"
    except Exception as e:
        return f"Could not open browser: {e}"


# --------------------------------------------------------------------------
# Logging (tee console output into jarvis_data/jarvis.log)
# --------------------------------------------------------------------------
class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def install_logging():
    if getattr(sys, "_jarvis_tee_installed", False):
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except Exception:
        return
    try:
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
        sys._jarvis_tee_installed = True
        print(f"[Log]: writing to {LOG_FILE}")
    except Exception:
        pass


def log(message: str):
    try:
        print(f"[JARVIS] {message}", flush=True)
    except Exception:
        pass


def run_bg(fn, *args, **kwargs):
    """Run fn in a daemon thread, logging exceptions instead of losing them."""
    def _runner():
        try:
            fn(*args, **kwargs)
        except Exception as e:
            log(f"{getattr(fn, '__name__', 'job')} failed: {e}")
            try:
                with open(os.path.join(DATA_DIR, "errors.log"), "a", encoding="utf-8") as fh:
                    fh.write(f"\n[{now_str()}] {getattr(fn, '__name__', 'job')}\n{traceback.format_exc()}\n")
            except Exception:
                pass
    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    return t


# --------------------------------------------------------------------------
# JSON / config
# --------------------------------------------------------------------------
def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log(f"write_json({path}) failed: {e}")
        return False


def load_config() -> dict:
    cfg = read_json(CONFIG_FILE, {}) or {}
    out = dict(CONFIG_DEFAULTS)
    if isinstance(cfg, dict):
        out.update(cfg)
    return out


def save_config(cfg: dict):
    current = read_json(CONFIG_FILE, {}) or {}
    if not isinstance(current, dict):
        current = {}
    current.update(cfg or {})
    write_json(CONFIG_FILE, current)


def config_get(key, default=None):
    return load_config().get(key, default)


# --------------------------------------------------------------------------
# Speech helpers
# --------------------------------------------------------------------------
def _archive_say(text):
    """Record a spoken reply in the permanent archive, if the memory layer is ready."""
    fn = G.get("_jarvis_archive_say")
    if not fn:
        return
    try:
        fn(text)
    except Exception:
        pass


def say(text: str, urdu: str | None = None):
    _archive_say(text)
    fn = G.get("speak")
    if fn:
        try:
            return fn(text, urdu=urdu) if urdu else fn(text)
        except TypeError:
            try:
                return fn(text)
            except Exception:
                pass
        except Exception:
            pass
    log(text)


def say_lang(en: str, roman: str, urdu: str):
    _archive_say(en)
    fn = G.get("speak_lang")
    if fn:
        try:
            return fn(en, roman, urdu)
        except Exception:
            pass
    log(en)


def _say_when_free(text, urdu=None, delay=0.0):
    if delay:
        time.sleep(delay)
    for _ in range(240):  # up to 2 minutes
        ev = G.get("speaking")
        try:
            busy = bool(ev and ev.is_set())
        except Exception:
            busy = False
        if not busy:
            break
        time.sleep(0.5)
    say(text, urdu)


def say_async(text: str, urdu: str | None = None, delay: float = 0.0):
    threading.Thread(target=_say_when_free, args=(text, urdu, delay), daemon=True).start()


# --------------------------------------------------------------------------
# Gemini helpers
# --------------------------------------------------------------------------
def gen_types():
    return G.get("types")


def gen_config(**kwargs):
    t = gen_types()
    if t is None:
        return None
    return t.GenerateContentConfig(**kwargs)


def parse_json_loose(text):
    """Parse a JSON object/array even if the model wrapped it in prose/fences."""
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    t = str(text).strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if 0 <= a < b:
            try:
                return json.loads(t[a:b + 1])
            except Exception:
                continue
    return None


def llm_text(prompt, system: str | None = None, json_mode: bool = False,
             smart: bool = False, max_tokens: int = 2048, temperature: float | None = None):
    """Generate text with model fallback.  'smart' uses the patient client."""
    t = gen_types()
    if t is None:
        raise RuntimeError("google-genai types not available")
    kwargs = {"max_output_tokens": int(max_tokens)}
    if system:
        kwargs["system_instruction"] = system
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    cfg = t.GenerateContentConfig(http_options=t.HttpOptions(timeout=10000), **kwargs)

    client = G.get("client_smart" if smart else "client_fast") or G.get("client")
    if client is None:
        raise RuntimeError("Gemini client not ready")

    if smart:
        # Try only the two best smart models first.  Then fall straight back to the
        # fast models (which are far more available) instead of spending the whole
        # timeout on 503s from every premium model.
        primary = list(G.get("SMART_CANDIDATES") or [])[:2]
    else:
        primary = list(G.get("MODEL_CANDIDATES") or [])
    fallback = list(G.get("MODEL_CANDIDATES") or [])
    order = []
    for m in primary + fallback:
        if m and m not in order:
            order.append(m)
    dead = G.get("dead_models") or set()
    last = None
    t0 = time.time()
    # A spoken answer must not wait for a long retry chain (this used to take
    # 131 seconds).  Two tries inside a small time budget is enough.
    budget = 7.0 if smart else 5.5
    attempts = 2
    for model in order:
        if model in dead:
            continue
        if attempts <= 0 or time.time() - t0 >= budget:
            break
        for attempt in range(2):
            if attempts <= 0 or time.time() - t0 >= budget:
                break
            attempts -= 1
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                text = getattr(resp, "text", None)
                if text and str(text).strip():
                    return str(text).strip()
            except Exception as e:
                last = e
                err_code = G.get("_err_code")
                code = None
                try:
                    code = err_code(e) if err_code else None
                except Exception:
                    code = None
                if code in (401, 403):
                    raise
                if code == 404:
                    try:
                        dead.add(model)
                    except Exception:
                        pass
                    break
                if code in (429, 500, 502, 503, 504):
                    if code == 504:
                        attempts = 0  # budget gone: stop instead of waiting again
                    break  # overloaded / timed out: next model at once, never retry it
                time.sleep(0.15)
    if last:
        raise last
    raise RuntimeError("No Gemini model produced an answer")


def llm_json(prompt, system: str | None = None, smart: bool = False, fallback=None,
             max_tokens: int = 1200):
    try:
        data = parse_json_loose(llm_text(prompt, system=system, json_mode=True, smart=smart,
                                         max_tokens=max_tokens))
        return data if data is not None else fallback
    except Exception as e:
        log(f"llm_json failed: {e}")
        return fallback


# --------------------------------------------------------------------------
# Audit + safety
# --------------------------------------------------------------------------
def _load_safety_state():
    cfg = load_config()
    return bool(cfg.get("safe_mode", True))


_SAFETY = {"safe_mode": _load_safety_state()}


def safe_mode() -> bool:
    return bool(_SAFETY.get("safe_mode", True))


def set_safe_mode(on: bool):
    _SAFETY["safe_mode"] = bool(on)
    save_config({"safe_mode": bool(on)})
    return _SAFETY["safe_mode"]


def audit(tool: str, args="", result="", risk: str = "normal"):
    rec = {
        "t": time.time(),
        "time": now_str(),
        "tool": tool,
        "args": truncate(args, 600),
        "result": truncate(result, 600),
        "risk": risk,
    }
    try:
        with _AUDIT_LOCK:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def guard(tool: str, confirmed: bool, detail: str) -> str | None:
    """Return a confirmation message when a destructive action is not confirmed."""
    if confirmed or not safe_mode():
        return None
    audit(tool, detail, "blocked: confirmation required", risk="high")
    return (
        "CONFIRMATION REQUIRED: " + detail + " Nothing has been done yet. "
        "Ask the user in plain language and wait for a clear yes. "
        "Only then call the same tool again with confirmed=true."
    )


_DANGEROUS_PS = [
    r"format-volume", r"diskpart", r"\bformat\s+[a-z]:", r"remove-item\s+.*-recurse.*[a-z]:\\?\s*$",
    r"\brd\s+/s\b", r"\bdel\s+/[fsq]\b", r"bcdedit", r"cipher\s+/w", r"\breg\s+delete\b",
    r"vssadmin\s+delete", r"wbadmin\s+delete", r"\btakeown\b", r"icacls\b.*\/reset",
    r"stop-process.*\b(lsass|csrss|winlogon|services)\b", r"set-mppreference.*disable",
    r"netsh\s+advfirewall\s+set\s+.*\boff\b", r"schtasks.*\/delete", r"wmic.*delete",
    r"clear-recyclebin", r"remove-item.*-force.*\\windows",
    r"remove-item.*-recurse.*\\users\b", r"shutdown\s+/[rs]",
]


def powershell_is_dangerous(command: str) -> bool:
    low = (command or "").lower()
    return any(re.search(p, low) for p in _DANGEROUS_PS)


def recent_tool_success(tools=None, seconds: float = 300.0) -> bool:
    """True if a matching tool reported success recently.

    Used by the truth guard: a spoken "done" is only allowed when a real tool
    result backs it up.
    """
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=300)
    except Exception:
        return False
    now = time.time()
    wanted = tuple(tools) if tools else ()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        try:
            when = float(row.get("t") or 0)
        except Exception:
            when = 0.0
        if now - when > seconds:
            continue
        tool = str(row.get("tool") or "")
        if wanted and not any(w in tool for w in wanted):
            continue
        result = str(row.get("result") or "").lower()
        if any(bad in result for bad in (
                "failed", "error", "not configured", "confirmation required",
                "blocked", "could not", "no recipient", "unknown")):
            continue
        return True
    return False


def audit_tail(n: int = 30) -> str:
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=max(1, int(n)))
        out = []
        for line in lines:
            try:
                d = json.loads(line)
                out.append(f"{d.get('time','')} | {d.get('tool','')} | {d.get('risk','')} | "
                           f"{truncate(d.get('args',''), 100)} -> {truncate(d.get('result',''), 100)}")
            except Exception:
                continue
        return "\n".join(out) if out else "The audit log is empty."
    except Exception as e:
        return f"Could not read the audit log: {e}"


# --------------------------------------------------------------------------
# HTML / reports
# --------------------------------------------------------------------------
_REPORT_CSS = """
:root{--bg:#070b12;--panel:#0d1522;--cyan:#00e5ff;--gold:#ffc107;--text:#dbe7f3;--muted:#7a95a8}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at 50% 0%,#102030 0%,#070b12 55%);
     color:var(--text);font-family:'Segoe UI',system-ui,Arial,sans-serif;line-height:1.75}
.wrap{max-width:920px;margin:0 auto;padding:44px 26px 80px}
.brand{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.orb{width:38px;height:38px;border-radius:50%;border:2px solid var(--cyan);
     box-shadow:0 0 18px var(--cyan);position:relative}
.orb::after{content:'';position:absolute;inset:7px;border-radius:50%;
     border:2px solid var(--gold);box-shadow:0 0 12px var(--gold)}
h1{font-size:34px;margin:6px 0 4px;color:#fff;letter-spacing:.5px}
h2{color:var(--cyan);margin-top:34px;border-bottom:1px solid #123;padding-bottom:6px}
h3{color:var(--gold)}
a{color:#67e8f9}
code{background:#101c2b;border:1px solid #1c3046;border-radius:5px;padding:2px 6px;color:#a5f3d0}
pre{background:#0b1420;border:1px solid #1c3046;border-radius:10px;padding:16px;overflow:auto}
pre code{border:0;background:none;padding:0}
blockquote{border-left:3px solid var(--gold);margin:18px 0;padding:8px 18px;color:#b9c9d8;background:#0d1522}
table{border-collapse:collapse;width:100%;margin:18px 0}
th,td{border:1px solid #1c3046;padding:9px 12px;text-align:left}
th{background:#0f1d2c;color:var(--cyan)}
ul,ol{padding-left:26px}
li{margin:6px 0}
.meta{color:var(--muted);font-size:14px;margin-bottom:26px}
.footer{margin-top:50px;color:var(--muted);font-size:13px;border-top:1px solid #123;padding-top:16px}
"""


def _inline_md(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"(?<![\"'=])(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
    return s


def markdown_to_html(md: str) -> str:
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out, in_code, in_ul, in_ol = [], False, False, False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for line in lines:
        fence = line.strip().startswith("```")
        if fence:
            close_lists()
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        s = line.strip()
        if not s:
            close_lists()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close_lists()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline_md(m.group(2))}</h{n}>")
            continue
        if s.startswith(">"):
            close_lists()
            out.append(f"<blockquote>{_inline_md(s.lstrip('> ').strip())}</blockquote>")
            continue
        if re.match(r"^[-*+]\s+", s):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_md(re.sub(r'^[-*+]\s+', '', s))}</li>")
            continue
        if re.match(r"^\d+[.)]\s+", s):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_md(re.sub(r'^\d+[.)]\s+', '', s))}</li>")
            continue
        if set(s) <= set("-—_") and len(s) >= 3:
            close_lists()
            out.append("<hr>")
            continue
        close_lists()
        out.append(f"<p>{_inline_md(s)}</p>")
    if in_code:
        out.append("</code></pre>")
    close_lists()
    return "\n".join(out)


def report_html(title: str, body_md: str, subtitle: str = "") -> str:
    body = markdown_to_html(body_md)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_REPORT_CSS}</style></head><body>"
        "<div class='wrap'><div class='brand'><div class='orb'></div>"
        "<div><div style='letter-spacing:3px;color:#7a95a8;font-size:12px'>J.A.R.V.I.S. // ULTIMATE</div>"
        f"<h1>{html.escape(title)}</h1></div></div>"
        f"<div class='meta'>{html.escape(subtitle or now_str())}</div>"
        f"{body}<div class='footer'>Generated by J.A.R.V.I.S. — "
        f"{html.escape(now_str())}</div></div></body></html>"
    )


def save_report(title: str, markdown: str, open_it: bool = True, subtitle: str = "") -> tuple[str, str]:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    base = f"{slugify(title)}_{stamp()}"
    md_path = os.path.join(REPORTS_DIR, base + ".md")
    html_path = os.path.join(REPORTS_DIR, base + ".html")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(report_html(title, markdown, subtitle))
        if open_it:
            open_url("file:///" + html_path.replace("\\", "/"))
        return md_path, html_path
    except Exception as e:
        log(f"save_report failed: {e}")
        return "", ""


def show_page(title: str, body_md: str):
    """Render a markdown page through Jarvis's existing styled browser page."""
    fn = G.get("show_page")
    if fn:
        try:
            return fn(title, markdown_to_html(body_md))
        except Exception as e:
            log(f"show_page failed: {e}")
    _, html_path = save_report(title, body_md, open_it=True)
    return html_path


def play_beep(freq=1200, ms=120):
    fn = G.get("_beep")
    if fn:
        try:
            fn()
            return
        except Exception:
            pass
    try:
        import winsound
        winsound.Beep(int(freq), int(ms))
    except Exception:
        pass


def _hex_mix(color: str, other: str, amount: float) -> str:
    """Blend two #rrggbb colours; amount=0 -> color, 1 -> other."""
    try:
        a = color.lstrip("#")
        b = other.lstrip("#")
        ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        t = max(0.0, min(1.0, float(amount)))
        return "#{:02x}{:02x}{:02x}".format(
            int(ar * (1 - t) + br * t),
            int(ag * (1 - t) + bg * t),
            int(ab * (1 - t) + bb * t),
        )
    except Exception:
        return color

