"""Read and send email through the real Gmail web interface in Brave.

The user asked for the visible path: open Brave, open Gmail, write the
message in Gmail's own compose window, and press Send there.  This module
does exactly that through the Chrome DevTools Protocol.  It can also read the
inbox list (sender, subject, snippet, unread flag) without opening messages,
then mark the messages it reported as read through Gmail's own toolbar when the
caller asks for that.

The automation browser uses your normal Brave profile when
``browser_profile_dir`` points at it (the default setup), or its own profile
otherwise.  Nothing is reported as sent unless Gmail itself confirms it.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from . import browser, core

INBOX_URL = "https://mail.google.com/mail/u/0/#inbox"
COMPOSE_URL = "https://mail.google.com/mail/u/0/#inbox?compose=new"
SIGNIN_URL = ("https://accounts.google.com/ServiceLogin?service=mail"
              "&continue=https%3A%2F%2Fmail.google.com%2Fmail%2Fu%2F0%2F")

_TO_SELECTORS = [
    'div[role="dialog"] input[aria-label="To recipients"]',
    'div[role="dialog"] input[aria-label*="To recipients"]',
    'div[role="dialog"] textarea[name="to"]',
    'div[role="dialog"] input[name="to"]',
    'div[role="dialog"] input[peoplekit-id]',
    'input[aria-label="To recipients"]',
    'textarea[name="to"]',
]
_SUBJECT_SELECTORS = [
    'div[role="dialog"] input[name="subjectbox"]',
    'div[role="dialog"] input[aria-label*="Subject"]',
    'input[name="subjectbox"]',
    'input[aria-label*="Subject"]',
]
_BODY_SELECTORS = [
    'div[role="dialog"] div[aria-label*="Message Body"]',
    'div[role="dialog"] div[contenteditable="true"][role="textbox"]',
    'div[aria-label*="Message Body"]',
    'div[contenteditable="true"][role="textbox"]',
]

_COMPOSE_OPEN_JS = (
    "!!(document.querySelector('div[role=\"dialog\"] input[name=\"subjectbox\"]')"
    " || document.querySelector('div[role=\"dialog\"] div[aria-label*=\"Message Body\"]')"
    " || document.querySelector('div[role=\"dialog\"] div[contenteditable=\"true\"]'))"
)

_SEND_JS = """(() => {
  const root = document.querySelector('div[role="dialog"]') || document;
  const els = [...root.querySelectorAll('div[role="button"], button')];
  let el = els.find(e => {
    const a = (e.getAttribute('aria-label') || '').toLowerCase();
    return a.startsWith('send') && !a.includes('feedback') && !a.includes('settings');
  });
  if (!el) el = els.find(e => (e.innerText || '').trim().toLowerCase() === 'send');
  if (!el) return null;
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2});
})()"""

_ERROR_HINTS = (
    "couldn't send", "could not send", "message not sent", "error sending",
    "please make sure all recipients are valid", "invalid recipient",
    "something went wrong",
)


def _ensure_brave() -> str:
    """Make sure the debug browser on port 9222 is Brave, not Edge/Chrome."""
    if browser._running():
        info = browser._json("/json/version") or {}
        name = str(info.get("Browser") or "").lower()
        if not name or "brave" in name:
            return "Brave automation window is ready."
        browser.quit_browser()
        time.sleep(1.0)
    return browser.ensure_browser("brave")


def _mail_tab() -> dict | None:
    for tab in browser._tabs():
        url = (tab.get("url") or "").lower()
        if "mail.google.com" in url:
            return tab
    return None


def _current_url(tab: dict) -> str:
    try:
        cur = browser._pick_tab(tab.get("id", "")) or tab
        return (cur.get("url") or "").lower()
    except Exception:
        return (tab.get("url") or "").lower()


def _signed_in(tab: dict) -> bool:
    """True only when the real mailbox is visible, not Google's sign-in page."""
    url = _current_url(tab)
    if "accounts.google.com" in url or "workspace.google.com" in url:
        return False
    if "mail.google.com" not in url:
        return False
    try:
        text = browser._read(tab) or ""
    except Exception:
        text = ""
    low = text.lower()
    if not low:
        return False
    if "sign in" in low and "compose" not in low and "inbox" not in low:
        return False
    try:
        has_compose = bool(browser._eval(
            tab,
            "!!document.querySelector('div[role=\"button\"][gh=\"cm\"],"
            " div[role=\"button\"][aria-label*=\"Compose\"],"
            " div[role=\"button\"][aria-label*=\"compose\"]')"))
    except Exception:
        has_compose = False
    return has_compose or ("inbox" in low and "sign in" not in low)


def _bring_to_front():
    """Raise the automation Brave window so the user can sign in / watch it."""
    try:
        import psutil
        import win32con
        import win32gui
        import win32process
    except Exception:
        return
    profile = browser.profile_dir().lower()
    pids = set()
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if "brave" in name or ("brave" in cmd and profile and profile in cmd):
                    pids.add(proc.info["pid"])
            except Exception:
                continue
    except Exception:
        return
    if not pids:
        return
    found = []

    def _visit(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids and win32gui.GetWindowText(hwnd):
                found.append(hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_visit, None)
        for hwnd in found:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
    except Exception:
        pass


def open_gmail(compose: bool = False, timeout: float = 25.0) -> dict:
    """Open Gmail in the automation Brave window and report the real state."""
    started = _ensure_brave()
    if not browser._running():
        return {"ok": False, "signed_in": False, "tab": None, "message": started}

    tab = _mail_tab()
    if tab is None:
        tab = browser._new_tab(INBOX_URL)
        if tab is None:
            return {"ok": False, "signed_in": False, "tab": None,
                    "message": "I could not open a Brave tab for Gmail."}
        time.sleep(1.5)

    try:
        browser._activate(tab.get("id", ""))
    except Exception:
        pass

    # Wait for the page to settle.  Gmail can briefly show the marketing page
    # or a blank tab while it decides whether the session is valid.
    deadline = time.time() + timeout
    target = COMPOSE_URL if compose else INBOX_URL
    navigated = False
    while time.time() < deadline:
        url = _current_url(tab)
        if "accounts.google.com" in url or "workspace.google.com" in url:
            break
        if "mail.google.com" in url and _signed_in(tab):
            if compose and not navigated:
                try:
                    browser._navigate(tab, target)
                except Exception:
                    pass
                navigated = True
                time.sleep(1.5)
                continue
            try:
                browser._activate(tab.get("id", ""))
            except Exception:
                pass
            return {"ok": True, "signed_in": True, "tab": tab,
                    "message": "Gmail is open and signed in."}
        if not navigated:
            try:
                browser._navigate(tab, target)
            except Exception:
                pass
            navigated = True
        time.sleep(0.5)

    # The mailbox was not available: send the user to Google's sign-in page.
    if not _signed_in(tab):
        try:
            browser._navigate(tab, SIGNIN_URL)
            time.sleep(1.5)
            browser._activate(tab.get("id", ""))
        except Exception:
            pass
        _bring_to_front()
        return {
            "ok": True, "signed_in": False, "tab": tab,
            "message": ("Gmail is open in Brave, but it is not signed in. "
                        "Sign in once in that Brave window, then say 'send it' "
                        "again. The email draft is still saved."),
        }
    return {"ok": True, "signed_in": True, "tab": tab,
            "message": "Gmail is open and signed in."}


def _focus(tab: dict, selectors: list[str]) -> bool:
    script = (
        "(() => { const sels = " + json.dumps(selectors) + ";"
        " for (const s of sels) { const el = document.querySelector(s);"
        "  if (el && el.offsetParent !== null) { el.focus();"
        "   try { el.click(); } catch (e) {} return true; } }"
        " return false; })()"
    )
    try:
        return bool(browser._eval(tab, script))
    except Exception:
        return False


def _insert_text(tab: dict, text: str) -> bool:
    try:
        browser._ws_call(tab, "Input.insertText", {"text": text or ""})
        return True
    except Exception:
        pass
    script = (
        "(() => { const el = document.activeElement; if (!el) return false;"
        " const t = " + json.dumps(text or "") + ";"
        " if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {"
        "  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype"
        "    : HTMLInputElement.prototype;"
        "  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;"
        "  if (setter) setter.call(el, t); else el.value = t;"
        "  el.dispatchEvent(new Event('input', {bubbles: true}));"
        "  el.dispatchEvent(new Event('change', {bubbles: true}));"
        " } else {"
        "  el.focus();"
        "  try { document.execCommand('insertText', false, t); }"
        "  catch (e) { el.textContent = t; }"
        "  el.dispatchEvent(new InputEvent('input', {bubbles: true, data: t,"
        "    inputType: 'insertText'}));"
        " } return true; })()"
    )
    try:
        return bool(browser._eval(tab, script))
    except Exception:
        return False


def _press_enter(tab: dict):
    for kind in ("keyDown", "keyUp"):
        try:
            browser._ws_call(tab, "Input.dispatchKeyEvent", {
                "type": kind, "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
            })
        except Exception:
            pass


def _compose_values(tab: dict) -> dict:
    script = (
        "(() => {"
        " const pick = (sels, prop) => { for (const s of sels) {"
        "  const el = document.querySelector(s); if (el) return String("
        "   el[prop] ?? el.innerText ?? el.textContent ?? ''); } return ''; };"
        " const dlg = document.querySelector('div[role=\"dialog\"]') || document.body;"
        " return JSON.stringify({subject: pick(" + json.dumps(_SUBJECT_SELECTORS) + ", 'value'),"
        "  body: pick(" + json.dumps(_BODY_SELECTORS) + ", 'innerText'),"
        "  dialog_text: (dlg.innerText || '').slice(0, 4000)});"
        "})()"
    )
    try:
        raw = browser._eval(tab, script)
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _fill_compose(tab: dict, to: str, subject: str, body: str) -> str:
    if not _focus(tab, _TO_SELECTORS):
        return "I could not find the To field in Gmail, so nothing was sent."
    _insert_text(tab, to)
    _press_enter(tab)
    time.sleep(0.6)

    if not _focus(tab, _SUBJECT_SELECTORS):
        return "I could not find the Subject field in Gmail, so nothing was sent."
    _insert_text(tab, subject or "")
    time.sleep(0.3)

    if not _focus(tab, _BODY_SELECTORS):
        return "I could not find the message body in Gmail, so nothing was sent."
    _insert_text(tab, body or "")
    time.sleep(0.6)

    values = _compose_values(tab)
    dialog_text = str(values.get("dialog_text") or "")
    if to and to.lower() not in dialog_text.lower():
        return "Gmail did not accept the recipient address, so nothing was sent."
    if subject and subject.strip().lower() not in str(values.get("subject") or "").lower():
        return "Gmail did not keep the subject, so nothing was sent."
    expected = " ".join((body or "").split())[:48].lower()
    actual = " ".join(str(values.get("body") or "").split()).lower()
    if expected and expected not in actual:
        return "Gmail did not keep the message body, so nothing was sent."
    return ""


def _click_send(tab: dict) -> bool:
    try:
        raw = browser._eval(tab, _SEND_JS)
    except Exception:
        raw = None
    point = None
    if isinstance(raw, str) and raw:
        try:
            point = json.loads(raw)
        except Exception:
            point = None
    elif isinstance(raw, dict):
        point = raw
    if point:
        try:
            for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
                browser._ws_call(tab, "Input.dispatchMouseEvent", {
                    "type": kind, "x": float(point["x"]), "y": float(point["y"]),
                    "button": "left", "clickCount": 1,
                })
            return True
        except Exception:
            pass
    # JavaScript click is a fallback; Runtime.evaluate uses userGesture=True.
    script = (
        "(() => { const root = document.querySelector('div[role=\"dialog\"]') || document;"
        " const els = [...root.querySelectorAll('div[role=\"button\"], button')];"
        " let el = els.find(e => { const a = (e.getAttribute('aria-label') || '').toLowerCase();"
        "  return a.startsWith('send') && !a.includes('feedback') && !a.includes('settings'); });"
        " if (!el) el = els.find(e => (e.innerText || '').trim().toLowerCase() === 'send');"
        " if (!el) return false; el.click(); return true; })()"
    )
    try:
        return bool(browser._eval(tab, script))
    except Exception:
        return False


def _error_text(low: str) -> str:
    for hint in _ERROR_HINTS:
        at = low.find(hint)
        if at >= 0:
            return low[max(0, at - 50):at + 140].strip()
    return ""


def _wait_result(tab: dict, timeout: float = 40.0, had_toast: bool = False) -> tuple[bool, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            text = browser._read(tab) or ""
        except Exception:
            text = ""
        low = text.lower()
        if not had_toast and ("message sent" in low or "your message has been sent" in low):
            return True, ""
        error = _error_text(low)
        if error:
            return False, "Gmail said: " + core.truncate(error, 160)
        try:
            compose_open = bool(browser._eval(tab, _COMPOSE_OPEN_JS))
        except Exception:
            compose_open = True
        if not compose_open and text:
            # The compose pane closed without an error notice: Gmail accepted
            # the message and showed its usual toast/undo bar.
            return True, ""
        time.sleep(0.6)
    return False, "Gmail did not show a confirmation within the time limit."


def send_via_gmail(to: str, subject: str, body: str, timeout: float = 75.0) -> str:
    """Write and send the message in Gmail.  Returns an honest result string."""
    to = (to or "").strip()
    if not to:
        return "No recipient address was given."
    state = open_gmail(compose=True)
    if not state.get("ok"):
        return str(state.get("message") or "I could not open Gmail in Brave.")
    if not state.get("signed_in"):
        return str(state.get("message") or "Gmail is not signed in.")

    tab = _mail_tab() or state.get("tab")
    if not tab:
        return "I could not find the Gmail tab, so nothing was sent."

    # Wait for Gmail's compose pane.  On a slow connection this can take a
    # little while after the inbox first appears.
    deadline = time.time() + 25.0
    while time.time() < deadline:
        try:
            if browser._eval(tab, _COMPOSE_OPEN_JS):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        return ("I opened Gmail, but the compose window did not appear, "
                "so nothing was sent. The draft is still saved.")

    problem = _fill_compose(tab, to, subject or "", body or "")
    if problem:
        return problem + " The draft is still saved."

    _bring_to_front()
    try:
        before = (browser._read(tab) or "").lower()
    except Exception:
        before = ""
    had_toast = "message sent" in before or "your message has been sent" in before
    if not _click_send(tab):
        return "I filled the Gmail draft but could not find Send, so nothing was sent."

    ok, detail = _wait_result(tab, timeout, had_toast=had_toast)
    if ok:
        return f"Gmail sent to {to}."
    return ("I clicked Send in Gmail, but I could not confirm that the message "
            "was sent. " + (detail or "") + " The draft is still saved.")


def close_gmail() -> str:
    """Close the Gmail tab without touching the saved draft."""
    tab = _mail_tab()
    if tab is None:
        return "The Gmail tab is not open in the automation browser."
    ok = browser._close_tab(tab.get("id", ""))
    return "I closed the Gmail tab." if ok else "I could not close the Gmail tab."


def gmail_status() -> str:
    if not browser._running():
        return "The automation Brave window is not running."
    tab = _mail_tab()
    if tab is None:
        return "Brave is running, but Gmail is not open."
    return ("Gmail is open and signed in." if _signed_in(tab)
            else "Gmail is open but not signed in.")


# --------------------------------------------------------------------------
# Reading the inbox (list only: opening a row would mark it read)
# --------------------------------------------------------------------------
_INBOX_ROWS_JS = r"""(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll('tr.zA')];
  const out = rows.map((r, i) => {
    const senderEl = r.querySelector('.yW span');
    const subjEl = r.querySelector('.y6 span') || r.querySelector('.y6');
    const snipEl = r.querySelector('.y2');
    const dateEl = r.querySelector('.xW span') || r.querySelector('.xW');
    let snippet = clean(snipEl && snipEl.innerText).replace(/^[\-–—]\s*/, '');
    return {
      index: i,
      sender: clean(senderEl && (senderEl.getAttribute('name') || senderEl.innerText)),
      email: clean(senderEl && senderEl.getAttribute('email')),
      subject: clean(subjEl && subjEl.innerText),
      snippet: snippet.slice(0, 400),
      date: clean(dateEl && dateEl.innerText),
      unread: r.classList.contains('zE'),
      attachment: !!r.querySelector('.brb, .aZo')
    };
  });
  return JSON.stringify(out);
})()"""

_MESSAGE_JS = r"""(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const root = document.querySelector('div[role="main"]') || document;
  const subjEl = root.querySelector('h2.hP');
  const senderEl = root.querySelector('span.gD') || root.querySelector('.go');
  let sender = clean(senderEl && senderEl.innerText);
  if (senderEl && senderEl.getAttribute('email')) {
    const name = senderEl.getAttribute('name') || sender;
    sender = name + ' <' + senderEl.getAttribute('email') + '>';
  }
  const dateEl = root.querySelector('span.g3') || root.querySelector('.gK');
  const bodies = [...root.querySelectorAll('div.a3s')]
    .map(e => (e.innerText || '').trim()).filter(Boolean);
  const body = bodies.join('\n\n---\n\n');
  return JSON.stringify({
    found: !!body,
    subject: clean(subjEl && subjEl.innerText),
    sender: sender,
    date: clean(dateEl && dateEl.innerText),
    body: body.slice(0, 9000)
  });
})()"""

_MARK_UNREAD_JS = r"""(() => {
  const root = document.querySelector('div[role="main"]') || document;
  const els = [...root.querySelectorAll('[role="button"], button')];
  const el = els.find(e => {
    const label = ((e.getAttribute('aria-label') || '') + ' ' +
                   (e.getAttribute('data-tooltip') || '')).toLowerCase();
    return label.includes('mark as unread');
  });
  if (!el) return false;
  el.click();
  return true;
})()"""

# Rows with their checkbox state, used when marking mail read.
_MARK_ROWS_JS = r"""(() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  return JSON.stringify([...document.querySelectorAll('tr.zA')].map((r, i) => {
    const senderEl = r.querySelector('.yW span');
    const subjEl = r.querySelector('.y6 span') || r.querySelector('.y6');
    const cb = r.querySelector('div[role="checkbox"]');
    return {
      index: i,
      sender: clean(senderEl && (senderEl.getAttribute('name') || senderEl.innerText)),
      subject: clean(subjEl && subjEl.innerText),
      unread: r.classList.contains('zE'),
      checked: cb ? cb.getAttribute('aria-checked') === 'true' : false
    };
  }));
})()"""

_SELECT_ROWS_JS = r"""(() => {
  const rows = [...document.querySelectorAll('tr.zA')];
  const idx = %s;
  let n = 0;
  for (const i of idx) {
    const r = rows[i];
    if (!r) continue;
    const cb = r.querySelector('div[role="checkbox"]');
    if (cb && cb.getAttribute('aria-checked') !== 'true') { cb.click(); n++; }
  }
  return n;
})()"""

_UNCHECK_ROWS_JS = r"""(() => {
  const keys = %s;
  const rows = [...document.querySelectorAll('tr.zA')];
  let n = 0;
  for (const r of rows) {
    const cb = r.querySelector('div[role="checkbox"]');
    if (!cb || cb.getAttribute('aria-checked') !== 'true') continue;
    const senderEl = r.querySelector('.yW span');
    const subjEl = r.querySelector('.y6 span') || r.querySelector('.y6');
    const sender = senderEl ? (senderEl.getAttribute('name') || senderEl.innerText) : '';
    const subject = subjEl ? subjEl.innerText : '';
    const key = sender.replace(/\s+/g, ' ').trim().toLowerCase() + '\u0000' +
                subject.replace(/\s+/g, ' ').trim().toLowerCase();
    if (keys.includes(key)) { cb.click(); n++; }
  }
  return n;
})()"""

# The toolbar button may be hidden until rows are selected.  Its centre is
# returned so the caller can send a real mouse click (Gmail ignores a bare
# HTMLElement.click() on this toolbar control).
_MARK_BUTTON_JS = r"""(() => {
  const main = document.querySelector('div[role="main"]') || document;
  const btns = [...main.querySelectorAll('[role="button"], button')]
    .filter(e => (e.getAttribute('aria-label') || '').toLowerCase() === 'mark as read');
  const btn = btns.find(e => !!(e.offsetWidth || e.offsetHeight));
  if (!btn) return '';
  btn.scrollIntoView({block: 'center'});
  const b = btn.getBoundingClientRect();
  return JSON.stringify({x: b.left + b.width / 2, y: b.top + b.height / 2});
})()"""

# Select unread rows by sender + subject (with a count per sender/subject).
# Selecting by list position is unsafe: Gmail can re-sort or insert new mail
# between reading the list and clicking, which marked the wrong rows and made
# the confirmation look like a failure.
_SELECT_BY_KEYS_JS = r"""(() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const specs = %s;
  const rows = [...document.querySelectorAll('tr.zA')];
  let n = 0;
  for (const row of rows) {
    if (!row.classList.contains('zE')) continue;
    const senderEl = row.querySelector('.yW span');
    const subjEl = row.querySelector('.y6 span') || row.querySelector('.y6');
    const sender = norm(senderEl && (senderEl.getAttribute('name') || senderEl.innerText));
    const subject = norm(subjEl && subjEl.innerText);
    for (const spec of specs) {
      if (spec[2] > 0 && spec[0] === sender && spec[1] === subject) {
        const cb = row.querySelector('div[role="checkbox"]');
        if (cb) {
          if (cb.getAttribute('aria-checked') !== 'true') cb.click();
          spec[2] -= 1;
          n++;
        }
        break;
      }
    }
  }
  return n;
})()"""


def _json_value(raw, default):
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return default
    return default


def _load_rows(tab: dict) -> list:
    return _json_value(browser._eval(tab, _INBOX_ROWS_JS), [])


def _wait_rows(tab: dict, timeout: float = 35.0, want: int = 1) -> list:
    deadline = time.time() + timeout
    last: list = []
    while time.time() < deadline:
        try:
            rows = _load_rows(tab)
        except Exception:
            rows = []
        if rows:
            last = rows
        if len(rows) >= want:
            return rows
        time.sleep(0.6)
    return last


def _mark_key(row: dict) -> str:
    sender = re.sub(r"\s+", " ", (row.get("sender") or "")).strip().lower()
    subject = re.sub(r"\s+", " ", (row.get("subject") or "")).strip().lower()
    return sender + "\x00" + subject


def _unread_counts(rows, targets) -> dict:
    """Count the unread rows that match the reported sender/subject pairs."""
    counts: dict = {}
    for row in rows or []:
        key = _mark_key(row)
        if key in targets and row.get("unread"):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _select_by_keys(tab: dict, targets) -> int:
    """Tick the checkboxes of the reported unread rows (sender + subject)."""
    specs = []
    for key, count in targets.items():
        sender, _, subject = key.partition("\x00")
        specs.append([sender, subject, int(count)])
    try:
        return int(browser._eval(tab, _SELECT_BY_KEYS_JS % json.dumps(specs)) or 0)
    except Exception:
        return 0


def _load_mark_rows(tab: dict) -> list:
    return _json_value(browser._eval(tab, _MARK_ROWS_JS), [])


def _wait_mark_rows(tab: dict, timeout: float = 12.0) -> list:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            rows = _load_mark_rows(tab)
        except Exception:
            rows = []
        if rows:
            return rows
        time.sleep(0.5)
    return []


def _click_point(tab: dict, point: dict) -> bool:
    try:
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            browser._ws_call(tab, "Input.dispatchMouseEvent", {
                "type": kind, "x": float(point["x"]), "y": float(point["y"]),
                "button": "left", "clickCount": 1,
            })
        return True
    except Exception:
        return False


def _uncheck_rows(tab: dict, keys) -> int:
    if not keys:
        return 0
    try:
        return int(browser._eval(tab, _UNCHECK_ROWS_JS % json.dumps(list(keys))) or 0)
    except Exception:
        return 0


def _search_url(query: str, unread_only: bool) -> str:
    if query:
        return ("https://mail.google.com/mail/u/0/#search/"
                + urllib.parse.quote(query))
    if unread_only:
        return "https://mail.google.com/mail/u/0/#search/is%3Aunread"
    return INBOX_URL


def read_inbox(limit: int = 8, query: str = "", unread_only: bool = False,
               timeout: float = 40.0) -> dict:
    """List Gmail inbox rows without opening them.

    Returns ``{"ok", "signed_in", "messages", "message", "url"}``.  Each message
    is ``{sender, email, subject, snippet, date, unread, attachment}``.  This
    function only lists rows and never changes their unread flag; call
    :func:`mark_inbox_read` with these messages afterwards to mark them read.
    """
    try:
        limit = max(1, min(int(limit or 8), 25))
    except Exception:
        limit = 8

    state = open_gmail(compose=False)
    if not state.get("ok"):
        return {"ok": False, "signed_in": False, "messages": [],
                "message": str(state.get("message") or
                               "I could not open Gmail in Brave.")}
    tab = state.get("tab")
    if tab is None:
        return {"ok": False, "signed_in": False, "messages": [],
                "message": "I could not find the Gmail tab in Brave."}
    if not state.get("signed_in"):
        return {"ok": False, "signed_in": False, "messages": [],
                "message": str(state.get("message") or
                               "Gmail is open in Brave, but it is not signed in. "
                               "Sign in once in that Brave window, then ask again.")}

    target = _search_url(query, unread_only)
    if target not in _current_url(tab):
        try:
            browser._navigate(tab, target)
        except Exception:
            pass
        time.sleep(1.0)

    rows = _wait_rows(tab, timeout=timeout)
    if not rows:
        # One slow second chance: the inbox list can render after the chrome.
        time.sleep(2.0)
        rows = _wait_rows(tab, timeout=8.0)
    if unread_only:
        rows = [r for r in rows if r.get("unread")]
    return {"ok": True, "signed_in": True, "messages": rows[:limit],
            "message": "", "url": _current_url(tab)}


def read_message(index: int = 0, query: str = "", unread_only: bool = False,
                 keep_unread: bool = False, timeout: float = 30.0) -> dict:
    """Open one inbox message by list position and return its text.

    Opening a message marks it read in Gmail, which is what the user asked for
    when they say "read that email".  Pass ``keep_unread`` only when the caller
    explicitly wants the unread flag restored afterwards.
    """
    try:
        index = max(0, int(index or 0))
    except Exception:
        index = 0

    listed = read_inbox(limit=max(10, index + 1), query=query,
                        unread_only=unread_only)
    if not listed.get("ok"):
        return {"ok": False, "message": listed.get("message") or
                "I could not read the inbox.", "data": {}}
    msgs = listed.get("messages") or []
    if index >= len(msgs):
        return {"ok": False, "message":
                "There is no email at that position in the list.", "data": {}}
    row = msgs[index]

    state = open_gmail(compose=False)
    tab = state.get("tab")
    if tab is None:
        return {"ok": False, "message": "I could not find the Gmail tab.",
                "data": {}}

    click_js = ("(() => { const rows = [...document.querySelectorAll('tr.zA')];"
                f" const r = rows[{index}]; if (!r) return false;"
                " r.click(); return true; })()")
    try:
        clicked = browser._eval(tab, click_js)
    except Exception:
        clicked = False
    if not clicked:
        return {"ok": False, "message": "I could not open that email.",
                "data": {}}

    deadline = time.time() + timeout
    data = {}
    while time.time() < deadline:
        try:
            data = _json_value(browser._eval(tab, _MESSAGE_JS), {}) or {}
        except Exception:
            data = {}
        if data.get("body"):
            break
        time.sleep(0.6)

    if not data.get("body"):
        return {"ok": False, "message":
                "Gmail opened the message but its text did not load.",
                "data": data or {}}

    if keep_unread and row.get("unread"):
        try:
            browser._eval(tab, _MARK_UNREAD_JS)
            time.sleep(0.8)
        except Exception:
            pass

    try:
        browser._navigate(tab, INBOX_URL)
    except Exception:
        pass
    return {"ok": True, "message": "", "data": data}


def mark_inbox_read(messages=None, indices=None, url: str = "",
                    timeout: float = 18.0) -> dict:
    """Mark inbox messages as read through Gmail's own row selection.

    ``messages`` are the dicts returned by :func:`read_inbox`; only the ones
    whose ``unread`` flag is true are marked.  ``indices`` can be used instead
    when the caller only has row positions.  The list is checked again
    afterwards, and a count is reported only when Gmail itself shows those rows
    as read.  Nothing is claimed on a failure.
    """
    result = {"ok": False, "marked": 0, "message": ""}
    state = open_gmail(compose=False)
    if not state.get("ok"):
        result["message"] = str(state.get("message") or "I could not open Gmail.")
        return result
    tab = state.get("tab")
    if tab is None:
        result["message"] = "I could not find the Gmail tab."
        return result
    if not state.get("signed_in"):
        result["message"] = str(state.get("message") or
                                "Gmail is open but not signed in.")
        return result

    if url and url != _current_url(tab):
        try:
            browser._navigate(tab, url)
            time.sleep(1.0)
        except Exception:
            pass

    rows = _wait_mark_rows(tab, timeout=12.0)
    if not rows:
        result["message"] = "Gmail did not show the message list."
        return result

    targets: dict = {}          # key -> how many rows were reported to me
    chosen: list = []
    if messages is not None:
        for m in messages:
            if not m.get("unread"):
                continue
            key = _mark_key(m)
            targets[key] = targets.get(key, 0) + 1
        if not targets:
            result.update(ok=True, message="Those emails were already read.")
            return result
        remaining = dict(targets)
        for row in rows:
            if not row.get("unread"):
                continue
            key = _mark_key(row)
            if remaining.get(key, 0) > 0:
                chosen.append(row.get("index"))
                remaining[key] -= 1
    elif indices is not None:
        wanted = set()
        for i in indices or []:
            try:
                wanted.add(int(i))
            except Exception:
                continue
        for row in rows:
            if row.get("index") in wanted and row.get("unread"):
                chosen.append(row["index"])
                key = _mark_key(row)
                targets[key] = targets.get(key, 0) + 1
    else:
        for row in rows:
            if row.get("unread"):
                chosen.append(row["index"])
                key = _mark_key(row)
                targets[key] = targets.get(key, 0) + 1

    if not chosen:
        result.update(ok=True, message="Those emails were already read.")
        return result

    # Count the unread rows for these keys before Gmail acts.
    before: dict = {}
    for row in rows:
        key = _mark_key(row)
        if key in targets and row.get("unread"):
            before[key] = before.get(key, 0) + 1

    print(f"[Gmail] marking {len(chosen)} row(s); "
          f"unread before: {sum(before.values())}")

    # Gmail ignores injected mouse clicks while its window is minimised, and it
    # can be minimised or covered while Jarvis talks in the HUD.  Bring the
    # Brave window back before touching the toolbar.
    _bring_to_front()
    time.sleep(0.4)

    after = dict(before)
    for attempt in range(1, 4):
        selected = _select_by_keys(tab, targets)
        if not selected:
            break

        point = None
        deadline = time.time() + 8.0
        while time.time() < deadline:
            try:
                raw = browser._eval(tab, _MARK_BUTTON_JS)
            except Exception:
                raw = ""
            if raw:
                try:
                    point = json.loads(raw)
                except Exception:
                    point = None
                if point:
                    break
            time.sleep(0.3)
        if not point:
            if attempt == 1:
                _uncheck_rows(tab, targets)
                result["message"] = ("Gmail did not show the Mark as read "
                                     "button, so nothing was marked read.")
                return result
            break

        _click_point(tab, point)
        print(f"[Gmail] clicked Mark as read at {point} "
              f"(attempt {attempt}, {selected} row(s) selected)")

        # If the first click landed while Gmail was redrawing, select again and
        # click once more instead of reporting a false failure.
        settle = time.time() + 2.5
        progressed = False
        while time.time() < settle:
            time.sleep(0.7)
            after = _unread_counts(_load_mark_rows(tab), targets)
            if sum(after.values()) < sum(before.values()):
                progressed = True
                break
        if progressed:
            break

    deadline = time.time() + timeout
    remaining_total = 0
    while time.time() < deadline:
        time.sleep(0.7)
        after = _unread_counts(_load_mark_rows(tab), targets)
        remaining_total = 0
        for key, count in targets.items():
            expected = max(0, before.get(key, 0) - count)
            remaining_total += max(0, after.get(key, 0) - expected)
        if remaining_total == 0:
            break

    print(f"[Gmail] unread after: {sum(after.values())} "
          f"(remaining {remaining_total})")

    marked = 0
    for key, count in targets.items():
        marked += max(0, before.get(key, 0) - after.get(key, 0))
    marked = min(marked, len(chosen))

    _uncheck_rows(tab, targets)

    if remaining_total:
        result["marked"] = marked
        result["message"] = ("Gmail did not confirm that all of those emails "
                             "were marked read; some may still be unread.")
        return result

    result.update(ok=True, marked=marked, message="")
    return result
