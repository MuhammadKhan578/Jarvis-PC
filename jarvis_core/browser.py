"""Real browser automation through the Chrome DevTools Protocol (no Selenium)."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.parse

from . import core

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import websocket  # websocket-client
except Exception:  # pragma: no cover
    websocket = None

PORT = 9222
BASE = f"http://127.0.0.1:{PORT}"
_SHOTS = os.path.join(core.DATA_DIR, "screenshots")
os.makedirs(_SHOTS, exist_ok=True)

_BROWSER_PATHS = {
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
}


def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def _find_exe(key: str) -> str | None:
    key = (key or "chrome").lower().strip()
    fn = core.G.get("_find_browser")
    if fn:
        try:
            p = fn(key)
            if p and os.path.exists(p):
                return p
        except Exception:
            pass
    for raw in _BROWSER_PATHS.get(key, []):
        p = _expand(raw)
        if os.path.exists(p):
            return p
    # generic fallbacks
    for key2 in ("chrome", "edge", "brave"):
        if key2 == key:
            continue
        for raw in _BROWSER_PATHS.get(key2, []):
            p = _expand(raw)
            if os.path.exists(p):
                return p
    return None


def _json(path: str, method: str = "get", timeout: float = 3):
    if requests is None:
        return None
    try:
        r = getattr(requests, method)(BASE + path, timeout=timeout)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


def _running() -> bool:
    return _json("/json/version", timeout=1.5) is not None


def profile_dir() -> str:
    """The user-data directory used by the automation browser.

    By default this is Jarvis's own profile.  A user can point it at a copy of
    their normal Brave profile (config ``browser_profile_dir`` or the
    ``JARVIS_BROWSER_PROFILE`` environment variable) so Gmail is already signed
    in.  Keeping it configurable avoids ever touching the live profile.
    """
    raw = (os.environ.get("JARVIS_BROWSER_PROFILE")
           or core.load_config().get("browser_profile_dir") or "")
    path = core.resolve_path(str(raw)) if raw else core.BROWSER_PROFILE_DIR
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = core.BROWSER_PROFILE_DIR
    return path


_JARVIS_TABS: set[str] = set()


def _real_profile_paths() -> set[str]:
    """Known live browser profile directories on this PC."""
    roots = [
        os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\User Data"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data"),
        os.path.expandvars(r"%AppData%\BraveSoftware\Brave-Browser\User Data"),
        os.path.expandvars(r"%AppData%\Google\Chrome\User Data"),
        os.path.expandvars(r"%AppData%\Microsoft\Edge\User Data"),
    ]
    return {os.path.normcase(os.path.abspath(p)) for p in roots if p and "%" not in p}


def uses_live_profile() -> bool:
    """True when automation is pointed at a user browser profile, not Jarvis's own."""
    try:
        path = os.path.normcase(os.path.abspath(profile_dir()))
        if path in _real_profile_paths():
            return True
        own = os.path.normcase(os.path.abspath(core.BROWSER_PROFILE_DIR))
        data = os.path.normcase(os.path.abspath(core.DATA_DIR))
        # A custom profile outside Jarvis's data folder is treated as the user's
        # own browser: never kill its processes.
        return path != own and not path.startswith(data + os.sep)
    except Exception:
        return False


def _browser_processes(key: str = "") -> int:
    try:
        import psutil
    except Exception:
        return 0
    names = {"brave": "brave.exe", "chrome": "chrome.exe", "edge": "msedge.exe"}
    wanted = names.get((key or "").lower())
    count = 0
    for p in psutil.process_iter(["name"]):
        try:
            name = (p.info.get("name") or "").lower()
            if wanted:
                if name == wanted:
                    count += 1
            elif name in names.values():
                count += 1
        except Exception:
            continue
    return count


def ensure_browser(browser_key: str = "") -> str:
    """Start a debug-enabled browser if needed. Returns a status string."""
    if _running():
        return "Browser debug port is already available."
    key = (browser_key or core.G.get("PREFERRED_BROWSER") or "chrome").lower().strip()
    if key not in _BROWSER_PATHS:
        key = "chrome"
    exe = _find_exe(key)
    if not exe:
        return "I could not find Chrome, Edge or Brave on this PC."
    if uses_live_profile() and _browser_processes(key):
        return ("Brave is already open without automation control. Close Brave once, "
                "then ask again; I will reopen it with the automation port and your "
                "Gmail sign-in intact.")
    profile = profile_dir()
    args = [
        exe,
        f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--disable-notifications",
        "--start-maximized",
        "about:blank",
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"Could not start {key}: {e}"
    for _ in range(40):
        time.sleep(0.35)
        if _running():
            actual = os.path.splitext(os.path.basename(exe))[0].lower()
            name = {"msedge": "Edge", "chrome": "Chrome", "brave": "Brave"}.get(actual, actual.title())
            return f"{name} started with automation enabled."
    return f"{key.capitalize()} did not expose the debug port. Close other windows and try again."


def quit_browser() -> str:
    """Close the automation browser, or only its tabs when the profile is live."""
    if not _running():
        return "The automation browser is not running."
    if uses_live_profile():
        # Never kill the user's main browser.  Close only the tabs Jarvis made.
        closed = 0
        for tab_id in list(_JARVIS_TABS):
            if _close_tab(tab_id):
                closed += 1
        _JARVIS_TABS.clear()
        return (f"I closed {closed} tab(s) that I opened. Your main Brave window "
                "is untouched.")
    try:
        import psutil
        profile = profile_dir().lower()
        killed = 0
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or []).lower()
                if profile and profile in cmd:
                    p.kill()
                    killed += 1
            except Exception:
                continue
        for _ in range(20):
            if not _running():
                break
            time.sleep(0.2)
        return f"Automation browser closed ({killed} process(es))." if not _running() else \
            "I asked the automation browser to close, but it is still running."
    except Exception as e:
        return f"Could not close the automation browser: {e}"


def _tabs() -> list[dict]:
    data = _json("/json/list")
    if not isinstance(data, list):
        return []
    return [t for t in data if t.get("type") == "page"]


def _new_tab(url: str = "about:blank") -> dict | None:
    if requests is None:
        return None
    url = url or "about:blank"
    if not re.match(r"^[a-z][a-z0-9+.\-]*:", url, re.I):
        url = "https://" + url
    for method in ("put", "post", "get"):
        try:
            r = getattr(requests, method)(BASE + "/json/new?" + urllib.parse.quote(url, safe=":/?&=#%"), timeout=8)
            if r.status_code < 400:
                data = r.json()
                if data.get("webSocketDebuggerUrl"):
                    if data.get("id"):
                        _JARVIS_TABS.add(str(data["id"]))
                    return data
        except Exception:
            continue
    return None


def _close_tab(tab_id: str) -> bool:
    if requests is None:
        return False
    try:
        requests.get(BASE + "/json/close/" + tab_id, timeout=5)
        _JARVIS_TABS.discard(tab_id)
        return True
    except Exception:
        return False


def _activate(tab_id: str) -> bool:
    if requests is None:
        return False
    try:
        requests.get(BASE + "/json/activate/" + tab_id, timeout=5)
        return True
    except Exception:
        return False


def _pick_tab(tab_id: str = "", url: str = "") -> dict | None:
    tabs = _tabs()
    if tab_id:
        for t in tabs:
            if t.get("id") == tab_id:
                return t
    if url:
        for t in tabs:
            if url in (t.get("url") or ""):
                return t
    return tabs[0] if tabs else None


def _ws_call(tab: dict, method: str, params: dict | None = None, timeout: float = 20):
    if websocket is None:
        raise RuntimeError("websocket-client is not installed")
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("tab has no debugger socket")
    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        payload = {"id": 1, "method": method, "params": params or {}}
        ws.send(json.dumps(payload))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"])[:300])
                return msg.get("result", {})
        raise TimeoutError("CDP call timed out")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _eval(tab: dict, expression: str, await_promise: bool = True):
    res = _ws_call(tab, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": await_promise,
        "userGesture": True,
    })
    result = res.get("result", {})
    if "exceptionDetails" in res:
        raise RuntimeError(str(res["exceptionDetails"])[:300])
    return result.get("value", result.get("description"))


def _js_str(text: str) -> str:
    return json.dumps(text or "", ensure_ascii=False)


def _navigate(tab: dict, url: str):
    if not re.match(r"^[a-z][a-z0-9+.\-]*:", url, re.I):
        url = "https://" + url
    _ws_call(tab, "Page.navigate", {"url": url})
    time.sleep(1.2)
    return url


def _read(tab: dict) -> str:
    try:
        text = _eval(tab, "document.body ? document.body.innerText : ''")
        return (text or "").strip()
    except Exception:
        return ""


def _click(tab: dict, selector: str = "", text: str = "") -> str:
    if selector:
        expr = (
            "(() => { const el = document.querySelector(" + _js_str(selector) + ");"
            " if (!el) return 'NOT_FOUND';"
            " el.scrollIntoView({block:'center'});"
            " el.click();"
            " return 'CLICKED ' + el.tagName + ' ' + (el.innerText || el.value || '').slice(0,120); })()"
        )
    else:
        expr = (
            "(() => { const t = " + _js_str(text.lower()) + ";"
            " const els = [...document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button],summary,label')];"
            " let el = els.find(e => ((e.innerText || e.value || e.getAttribute('aria-label') || '').trim().toLowerCase() === t));"
            " if (!el) el = els.find(e => ((e.innerText || e.value || e.getAttribute('aria-label') || '').trim().toLowerCase().includes(t)));"
            " if (!el) return 'NOT_FOUND';"
            " el.scrollIntoView({block:'center'});"
            " el.click();"
            " return 'CLICKED ' + el.tagName + ' ' + (el.innerText || el.value || '').slice(0,120); })()"
        )
    try:
        return str(_eval(tab, expr))
    except Exception as e:
        return f"Click failed: {e}"


def _type(tab: dict, selector: str, text: str, submit: bool = False) -> str:
    if selector:
        find = "document.querySelector(" + _js_str(selector) + ")"
    else:
        find = ("(document.activeElement && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName)"
                " ? document.activeElement : document.querySelector('input:not([type=hidden]),textarea,[contenteditable=true]'))")
    expr = (
        "(() => { const el = " + find + ";"
        " if (!el) return 'NOT_FOUND';"
        " el.focus(); el.scrollIntoView({block:'center'});"
        " const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : (el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLElement.prototype);"
        " const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;"
        " if (setter) setter.call(el, " + _js_str(text) + "); else el.value = " + _js_str(text) + ";"
        " el.dispatchEvent(new Event('input', {bubbles:true}));"
        " el.dispatchEvent(new Event('change', {bubbles:true}));"
        " " + ("el.form && el.form.requestSubmit ? el.form.requestSubmit() : el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));" if submit else "") +
        " return 'TYPED ' + (el.name || el.id || el.tagName) + ' = ' + (el.value || '').slice(0,120); })()"
    )
    try:
        return str(_eval(tab, expr))
    except Exception as e:
        return f"Typing failed: {e}"


def _screenshot(tab: dict) -> str:
    try:
        res = _ws_call(tab, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        data = base64.b64decode(res.get("data", ""))
        path = os.path.join(_SHOTS, f"browser_{core.stamp()}.png")
        with open(path, "wb") as f:
            f.write(data)
        core.open_path(path)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


def _find(tab: dict, text: str) -> str:
    expr = (
        "(() => { const t = " + _js_str(text.lower()) + ";"
        " const els = [...document.querySelectorAll('a,button,[role=button],input,textarea,select,h1,h2,h3,p,li,span,div')];"
        " const hits = [];"
        " for (const e of els) { const s = (e.innerText || e.value || '').trim();"
        "   if (s && s.toLowerCase().includes(t)) { hits.push({tag:e.tagName, text:s.slice(0,160),"
        "     id:e.id||'', name:e.name||'', cls:(e.className||'').toString().slice(0,80)}); }"
        "   if (hits.length >= 12) break; }"
        " return JSON.stringify(hits); })()"
    )
    try:
        raw = _eval(tab, expr)
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not data:
            return f"No elements containing '{text}'."
        return "\n".join(f"- <{h['tag']}> {h['text']}  id={h['id']} name={h['name']}" for h in data)
    except Exception as e:
        return f"Find failed: {e}"


def browser_operation(action: str = "status", url: str = "", tab_id: str = "",
                      selector: str = "", text: str = "", script: str = "",
                      submit: bool = False) -> str:
    """Drive a real Chromium browser (Chrome/Edge/Brave) through DevTools.

    action:
      status     - is the debug browser running, list tabs
      ensure     - start the automation browser
      open       - open a URL in a new tab
      navigate   - go to a URL in the current tab
      tabs       - list open tabs
      read       - return the visible text of the page
      find       - find elements containing text
      click      - click by selector OR by visible text
      type       - type into a field (selector optional; submit=true presses Enter)
      eval       - run JavaScript and return the result (script)
      screenshot - capture the page
      close      - close a tab
      activate   - bring a tab to the front
      quit       - close the dedicated automation browser
      html       - return the full HTML
      wait       - wait a few seconds (text = seconds)
    """
    a = (action or "status").lower().strip().replace("-", "_")
    if a == "status":
        running = _running()
        if not running:
            return "Automation browser is not running. Use action='ensure' or action='open'."
        tabs = _tabs()
        return "Browser running.\n" + ("\n".join(
            f"- {t.get('title','')} — {t.get('url','')} (id {t.get('id','')})" for t in tabs)
            if tabs else "No page tabs.")
    if a in ("quit", "shutdown", "stop", "exit"):
        return quit_browser()
    if a in ("ensure", "start", "launch"):
        return ensure_browser(text or selector)
    if a in ("open", "new_tab"):
        msg = ensure_browser(text if text in _BROWSER_PATHS else "")
        tab = _new_tab(url or "about:blank")
        if not tab:
            return msg + " But I could not create a tab."
        time.sleep(1.0)
        try:
            _activate(tab["id"])
        except Exception:
            pass
        return f"{msg} Opened: {tab.get('url','')}"
    if a in ("tabs", "list"):
        tabs = _tabs()
        if not tabs:
            return "No browser tabs. Use action='open' first."
        return "\n".join(f"- {t.get('title','')} — {t.get('url','')} (id {t.get('id','')})" for t in tabs)
    if a == "wait":
        try:
            secs = max(0.2, min(30, float(text or 2)))
        except Exception:
            secs = 2
        time.sleep(secs)
        return f"Waited {secs:g} seconds."

    tab = _pick_tab(tab_id, url if a in ("read", "html") else "")
    if tab is None:
        if a in ("open", "ensure"):
            pass
        msg = ensure_browser("")
        if "could not" in msg.lower() or "did not" in msg.lower():
            return msg
        tab = _new_tab("about:blank")
        if tab is None:
            return "No browser tab is available."
        time.sleep(0.8)

    try:
        if a in ("navigate", "goto"):
            target = _navigate(tab, url or text)
            time.sleep(1.0)
            return f"Navigated to {target}"
        if a in ("read", "text"):
            body = _read(tab)
            return body[:12000] if body else "The page has no visible text."
        if a in ("find", "search"):
            return _find(tab, text or selector)
        if a in ("click", "press"):
            return _click(tab, selector, text)
        if a in ("type", "fill"):
            return _type(tab, selector, text, submit)
        if a in ("eval", "js", "script"):
            if not script:
                return "No script given."
            res = _eval(tab, script)
            return json.dumps(res, ensure_ascii=False, indent=2)[:8000] if not isinstance(res, str) else res[:8000]
        if a in ("screenshot", "shot"):
            return _screenshot(tab)
        if a in ("html", "source"):
            html = _eval(tab, "document.documentElement.outerHTML")
            return (html or "")[:15000]
        if a in ("close", "close_tab"):
            ok = _close_tab(tab.get("id", ""))
            return "Tab closed." if ok else "Could not close the tab."
        if a in ("activate", "focus"):
            ok = _activate(tab.get("id", ""))
            return "Tab activated." if ok else "Could not activate the tab."
    except Exception as e:
        return f"Browser operation '{action}' failed: {e}"
    return f"Unknown browser action '{action}'."