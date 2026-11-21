"""Real Twilio-backed voice phone line for Jarvis PC.

No credential is bundled here.  Configuration lives in Jarvis's own config
(``jarvis_data/config.json``); the auth token is stored through
``core.protect_secret`` (DPAPI when available).  Outbound calls are real HTTPS
POSTs to the Twilio REST API and are only claimed successful when Twilio
returns a call SID.  The local webhook is a stdlib ThreadingHTTPServer meant to
be exposed through an HTTPS tunnel (cloudflared/ngrok) for Twilio.
"""
from __future__ import annotations

import base64
import http.server
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

from . import core

CONFIG_KEY = "phone_line"
VOICE = "man"                      # Twilio male voice; no female switching.
LANGUAGE = "en-US"
TWILIO_BASE = "https://api.twilio.com/2010-04-01/Accounts/"
CONSENT_LINE = "Ye call recording ki ja rahi hai / This call is being recorded."
DOCS_PATH = os.path.join(core.BASE_DIR, "docs", "PHONE_LINE.md")
DOCS_URL = "file:///" + DOCS_PATH.replace("\\", "/")

_SERVER = None
_SERVER_LOCK = threading.RLock()
_SPEAK_LOCK = threading.RLock()
_LOG_LOCK = threading.Lock()

_PHONE_DENY_RE = re.compile(
    r"\b(?:delete|remove|erase|wipe|format|shutdown|restart|kill|terminate|"
    r"factory\s+reset|safe\s+mode\s+off|install|uninstall|purchase|buy|pay|"
    r"payment|transfer|email|send\s+mail|bhej\w*)\b", re.I)


# ---------------------------------------------------------------------------
# Paths and configuration (reuse core's config + protected-secret helpers)
# ---------------------------------------------------------------------------
def _recording_dir() -> str:
    """Local, gitignored audio folder (jarvis_data/phone_line_recordings)."""
    return os.path.join(core.DATA_DIR, "phone_line_recordings")


def _transcript_log() -> str:
    return os.path.join(core.DATA_DIR, "phone_line_transcripts.jsonl")


def _load_cfg() -> dict:
    raw = core.config_get(CONFIG_KEY, {}) or {}
    if not isinstance(raw, dict):
        return {}
    cfg = dict(raw)
    cfg["auth_token"] = core.unprotect_secret(str(cfg.get("auth_token") or ""))
    return cfg


def _configured(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else _load_cfg()
    return bool(cfg.get("account_sid") and cfg.get("auth_token") and cfg.get("from_number"))


def callback_number() -> str:
    """The optional number used by the natural-language 'call me' route."""
    return _normalize_number(_load_cfg().get("call_me_number", ""))


def open_docs() -> str:
    """Open the local setup guide and report exactly what was done."""
    if not os.path.isfile(DOCS_PATH):
        return f"Phone line guide not found at {DOCS_PATH}."
    core.open_url(DOCS_URL)
    return f"Opened the phone line setup guide: {DOCS_PATH}"


def _normalize_number(value) -> str:
    """Return a basic E.164 number, or '' when the input is not usable."""
    compact = re.sub(r"[\s\-().]", "", str(value or "").strip())
    if not re.fullmatch(r"\+?\d{8,15}", compact):
        return ""
    return compact if compact.startswith("+") else "+" + compact


def _status_line() -> str:
    cfg = _load_cfg()
    sid = str(cfg.get("account_sid") or "")
    masked_sid = sid[:4] + "…" + sid[-4:] if len(sid) > 8 else ("set" if sid else "none")
    with _SERVER_LOCK:
        running = _SERVER is not None
    return (
        "Phone line: "
        f"enabled={'yes' if cfg.get('enabled', True) else 'no'}; "
        f"Twilio configured={'yes' if _configured(cfg) else 'no'}; "
        f"account SID={masked_sid}; "
        f"from={cfg.get('from_number') or 'not set'}; "
        f"callback={cfg.get('call_me_number') or 'not set'}; "
        f"webhook={'running' if running else 'stopped'}; "
        f"recordings={_recording_dir()}; guide=docs/PHONE_LINE.md"
    )


# ---------------------------------------------------------------------------
# Real Twilio HTTP (urllib only, no new dependencies)
# ---------------------------------------------------------------------------
def _twilio_error(body: str) -> str:
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or "")
    except Exception:
        pass
    return body or ""


def _twilio_request(url: str, fields: dict | None = None, cfg: dict | None = None,
                    method: str = "POST") -> tuple[int, bytes]:
    cfg = cfg if cfg is not None else _load_cfg()
    sid = str(cfg.get("account_sid") or "")
    token = str(cfg.get("auth_token") or "")
    if not sid or not token:
        raise RuntimeError("Twilio account SID and auth token are not configured")
    credentials = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": "Basic " + credentials,
        "Accept": "application/json",
        "User-Agent": "Jarvis-PC-PhoneLine/1.0",
    }
    body = None
    if fields is not None:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            code = int(getattr(response, "status", 0) or response.getcode() or 0)
        return code, raw
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        message = _twilio_error(detail) or detail
        raise RuntimeError(f"HTTP {exc.code} from Twilio: {core.truncate(message, 300)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Twilio network error: " + core.truncate(str(exc.reason), 240)) from exc


def _accounts_url(cfg: dict, path: str) -> str:
    sid = urllib.parse.quote(str(cfg.get("account_sid") or ""), safe="")
    return TWILIO_BASE + sid + "/" + path


def phone_line_call(to_number: str = "", message: str = "", confirmed: bool = False) -> str:
    """Place a REAL outbound call through Twilio after explicit confirmation.

    Returns the SID/status Twilio actually returned, or the real error.  A call
    is never claimed unless Twilio returned a SID.
    """
    detail = (f"Place a real outbound call to {to_number or 'the configured callback number'} "
              f"and relay: {core.truncate(message, 140)}")
    gate = core.guard("phone_line_call", confirmed, detail)
    if gate:
        return gate
    cfg = _load_cfg()
    if not cfg.get("enabled", True):
        return "Phone line is disabled. Enable it with phone_line_operation(action='configure', enabled=True)."
    if not _configured(cfg):
        return ("Twilio is not configured. Set account_sid, auth_token and from_number with "
                "phone_line_operation(action='configure').")
    number = _normalize_number(to_number) or callback_number()
    if not number:
        return "No valid destination number. Use E.164 format, for example +15551234567."
    text = str(message or "").strip()
    if not text:
        return "Give me a short message for the call."
    twiml = _twiml(_say(text))
    try:
        code, raw = _twilio_request(
            _accounts_url(cfg, "Calls.json"),
            {"To": number, "From": str(cfg["from_number"]), "Twiml": twiml}, cfg)
        try:
            data = json.loads(raw.decode("utf-8", "replace")) if raw.strip() else {}
        except Exception:
            data = {}
        sid = str(data.get("sid") or "") if isinstance(data, dict) else ""
        status = str(data.get("status") or "") if isinstance(data, dict) else ""
        if not sid:
            error = str(data.get("message") or "") if isinstance(data, dict) else ""
            return (f"Twilio did not return a call SID (HTTP {code}): "
                    f"{core.truncate(error or core.truncate(raw.decode('utf-8', 'replace'), 240), 300)}. "
                    "No call is claimed.")
        core.audit("phone_line_call", f"to={number}", f"sid={sid} status={status}", risk="high")
        return (f"Twilio accepted the call: SID {sid}, status {status or 'reported by Twilio'}. "
                "Call delivery is a separate Twilio status; I have not verified it.")
    except Exception as exc:
        return f"Twilio call failed: {core.truncate(str(exc), 400)}. No call is claimed."


# ---------------------------------------------------------------------------
# TwiML helpers (all TwiML uses the male voice)
# ---------------------------------------------------------------------------
def _say(text: str, language: str = LANGUAGE) -> str:
    return f'<Say voice="{VOICE}" language="{language}">{escape(core.truncate(text, 900))}</Say>'


def _twiml(*elements: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n' +
            "\n".join(e for e in elements if e) + "\n</Response>\n")


def _say_twiml(text: str) -> str:
    return _twiml(_say(text), "<Hangup/>")


def _field(form: dict | None, key: str) -> str:
    value = (form or {}).get(key, "")
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value or "")


def _query(query: dict | None, key: str) -> str:
    return _field(query, key)


def _is_yes(text: str) -> bool:
    return bool(re.search(r"\b(?:yes|confirm|confirmed|haan|ha|okay|ok|bilkul)\b",
                          str(text or ""), re.I))


def voice_inbound_twiml(method: str = "GET") -> str:
    """Greeting/consent then a speech Gather for the inbound Twilio number."""
    gather = (
        '<Gather input="speech" action="/voice/command" method="POST" '
        f'language="{LANGUAGE}" timeout="6" speechTimeout="auto">'
        + _say("Please state your command. For example: phone line status, "
               "last transcript, or record this call.")
        + "</Gather>"
    )
    return _twiml(
        _say("Jarvis phone line, sir. This call is handled by an automated assistant; "
             "spoken commands may be processed on this PC. Say a command after the prompt."),
        gather,
        _say("No command received. Goodbye."))


def _safe_dispatch(text: str, confirmed: bool = False) -> str:
    """Small, honest command set for calls that the main command hook skips."""
    low = str(text or "").strip().lower()
    if low in ("phone line status", "line status", "phone status", "status"):
        return _status_line()
    if low in ("last transcript", "transcript status", "last call"):
        return last_transcript()
    if low in ("health", "phone line health"):
        return health_json()
    if re.match(r"^(?:what(?:'s|\s+is)?\s+the\s+)?time\b", low) or low in ("time", "waqt"):
        return "The current local time is " + core.now_str() + "."
    if re.match(r"^(?:what(?:'s|\s+is)?\s+the\s+)?date\b", low) or low in ("date", "aaj ki tareekh"):
        return "Today is " + core.now_str() + "."
    return ("I cannot run that command over the phone line yet. Try phone line status, "
            "last transcript, time, or record this call. No action was taken.")


def _run_command(text: str, confirmed: bool = False) -> str:
    """Route speech through command_hook while capturing its spoken reply.

    core.say_lang is patched only for the duration of this call, then restored
    even when the hook raises.  The captured English line is what Twilio says.
    """
    text = str(text or "").strip()
    if not text:
        return "I did not receive a command. No action was taken."
    if _PHONE_DENY_RE.search(text) and "confirm" not in text.lower():
        return "That kind of command is not available over the phone line. No action was taken."
    captured: list[str] = []
    with _SPEAK_LOCK:
        original = core.say_lang

        def capture(*args, **kwargs):
            parts = list(args) + [kwargs.get(k, "") for k in ("en", "roman", "urdu")]
            line = next((str(p) for p in parts if p), "")
            if line:
                captured.append(line)

        core.say_lang = capture
        try:
            import jarvis_core
            handled = bool(jarvis_core.command_hook(text, core.G))
            if not handled:
                captured.append(_safe_dispatch(text, confirmed=confirmed))
        except Exception as exc:
            captured.append("Command failed: " + core.truncate(str(exc), 200))
        finally:
            core.say_lang = original
    reply = " ".join(x.strip() for x in captured if x and x.strip())
    return reply or "Command received, but no spoken reply was produced. No further action is claimed."


def voice_command_twiml(form: dict | None = None, query: dict | None = None) -> str:
    """Handle /voice/command, including the spoken 'confirm' second step."""
    form, query = form or {}, query or {}
    speech = _field(form, "SpeechResult").strip()
    sid = _field(form, "CallSid") or _query(query, "sid")

    if _query(query, "confirm") == "1":
        original = _query(query, "cmd").strip()
        if not _is_yes(speech):
            return _say_twiml("Confirmation not received. No call was placed and nothing was changed.")
        reply = _run_command((original + " confirm").strip(), confirmed=True) if original \
            else _run_command("phone line status", confirmed=True)
        return _say_twiml(reply)

    if not speech:
        return _say_twiml("I did not catch a command. Please call again and speak clearly.")
    if re.search(r"\brecord\b|\brecording\b", speech, re.I):
        return voice_record_twiml({"SpeechResult": speech, "CallSid": sid}, {})
    reply = _run_command(speech)
    if "CONFIRMATION REQUIRED" in reply.upper():
        action = "/voice/command?" + urllib.parse.urlencode(
            {"confirm": "1", "cmd": speech, "sid": sid})
        gather = (
            f'<Gather input="speech" action={quoteattr(action)} method="POST" '
            f'language="{LANGUAGE}" timeout="6" speechTimeout="auto">'
            + _say("Say confirm to proceed, or cancel to do nothing.")
            + "</Gather>"
        )
        return _twiml(_say(core.truncate(reply, 320)), gather,
                      _say("No confirmation received. Goodbye."))
    return _say_twiml(reply)


def _record_start_twiml(speech: str = "", sid: str = "") -> str:
    action = "/voice/record?" + urllib.parse.urlencode({"speech": speech, "sid": sid})
    record = (f'<Record action={quoteattr(action)} method="POST" maxLength="120" '
              'playBeep="true" trim="do-not-trim"/>')
    return _twiml(
        _say(CONSENT_LINE + " Jarvis stores the audio locally on this PC after this notice."),
        record,
        _say("Recording finished. Goodbye."))


def _append_transcript(row: dict):
    path = _transcript_log()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _LOG_LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _download_recording(url: str, cfg: dict) -> bytes:
    host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    if host != "api.twilio.com" and not host.endswith(".twilio.com"):
        raise RuntimeError("Recording URL is not a Twilio domain; download refused")
    _, raw = _twilio_request(url, cfg=cfg, method="GET")
    return raw


def voice_record_twiml(form: dict | None = None, query: dict | None = None) -> str:
    """Announce consent before Record; on callback save audio + honest log."""
    form, query = form or {}, query or {}
    speech = _field(form, "SpeechResult").strip() or _query(query, "speech").strip()
    sid = _field(form, "CallSid") or _query(query, "sid")
    recording_url = _field(form, "RecordingUrl").strip()
    if not recording_url:
        return _record_start_twiml(speech, sid)

    caller = _field(form, "From")
    speech_result = speech or "transcript unavailable"
    recording_path = ""
    error = ""
    try:
        raw = _download_recording(recording_url, _load_cfg())
        folder = _recording_dir()
        os.makedirs(folder, exist_ok=True)
        safe_sid = re.sub(r"[^A-Za-z0-9_-]", "", sid)[:80] or core.stamp()
        recording_path = os.path.join(folder, f"{safe_sid}_{core.stamp()}.wav")
        with open(recording_path, "wb") as fh:
            fh.write(raw)
    except Exception as exc:
        error = core.truncate(str(exc), 300)
    _append_transcript({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "from": caller,
        "sid": sid,
        "speech_result": speech_result,
        "recording": recording_path,
        "recording_url": recording_url,
        "error": error,
    })
    if recording_path:
        note = (" The captured speech command was: " + core.truncate(speech, 240)) if speech \
            else " No automatic transcript is available; only the audio was saved."
        return _say_twiml("Recording saved locally on this PC." + note)
    return _say_twiml("Recording was not saved: " + (error or "unknown error") +
                      ". Nothing else is claimed.")


def health_json() -> str:
    cfg = _load_cfg()
    with _SERVER_LOCK:
        running = _SERVER is not None
    return json.dumps({
        "ok": True,
        "service": "jarvis-phone-line",
        "enabled": bool(cfg.get("enabled", True)),
        "twilio_configured": _configured(cfg),
        "webhook_running": running,
        "transcript_log": _transcript_log(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False)


def last_transcript() -> str:
    path = _transcript_log()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            from collections import deque
            rows = deque(fh, maxlen=1)
        if not rows:
            return "No phone line transcript has been recorded yet."
        row = json.loads(rows[0])
        return (f"Last phone line record: time {row.get('timestamp', '?')}, "
                f"from {row.get('from') or 'unknown'}, SID {row.get('sid') or 'unknown'}, "
                f"speech_result: {row.get('speech_result') or 'transcript unavailable'}, "
                f"audio: {row.get('recording') or 'not saved'}"
                + (f", error: {row.get('error')}" if row.get("error") else "") + ".")
    except FileNotFoundError:
        return "No phone line transcript has been recorded yet."
    except Exception as exc:
        return "Could not read the phone line transcript log: " + core.truncate(str(exc), 200)


# ---------------------------------------------------------------------------
# stdlib webhook server
# ---------------------------------------------------------------------------
class _PhoneHandler(http.server.BaseHTTPRequestHandler):
    server_version = "JarvisPhoneLine/1.0"

    def log_message(self, fmt, *args):
        core.log("phone line HTTP: " + (fmt % args))

    def _send(self, body: str, content_type: str, code: int = 200):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, is_post: bool):
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        form: dict = {}
        if is_post:
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
            except Exception:
                length = 0
            if length:
                raw = self.rfile.read(length).decode("utf-8", "replace")
                form = {k: v[0] for k, v in
                        urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
        if path == "/voice/health":
            self._send(health_json(), "application/json; charset=utf-8")
        elif path == "/voice/inbound":
            self._send(voice_inbound_twiml("POST" if is_post else "GET"),
                       "application/xml; charset=utf-8")
        elif path == "/voice/command":
            if not is_post:
                self._send("Twilio calls this endpoint with POST.", "text/plain; charset=utf-8", 405)
            else:
                self._send(voice_command_twiml(form, query), "application/xml; charset=utf-8")
        elif path == "/voice/record":
            if not is_post:
                self._send("Twilio calls this endpoint with POST.", "text/plain; charset=utf-8", 405)
            else:
                self._send(voice_record_twiml(form, query), "application/xml; charset=utf-8")
        else:
            self._send("Unknown Jarvis phone line endpoint.", "text/plain; charset=utf-8", 404)

    def do_GET(self):
        self._route(False)

    def do_POST(self):
        self._route(True)


def _new_server(port: int = 8765):
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is not None:
            return None, f"Phone line webhook is already running on {_SERVER.server_address}."
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", int(port)), _PhoneHandler)
        except Exception as exc:
            return None, f"Could not start phone line webhook on port {port}: {core.truncate(str(exc), 240)}"
        _SERVER = server
        return server, ""


def _serve(server) -> None:
    try:
        server.serve_forever(poll_interval=0.25)
    except Exception as exc:
        core.log(f"phone line webhook stopped unexpectedly: {exc}")


def _close_server(server) -> str:
    global _SERVER
    with _SERVER_LOCK:
        try:
            if server is not None:
                server.shutdown()
                server.server_close()
        except Exception as exc:
            return "Could not stop the phone line webhook cleanly: " + core.truncate(str(exc), 240)
        if _SERVER is server:
            _SERVER = None
        return "Phone line webhook stopped."


def phone_line_webhook(port: int = 8765) -> str:
    """Serve the Twilio voice webhook locally (blocking). Binds localhost only."""
    server, error = _new_server(port)
    if error:
        return error
    try:
        _serve(server)
    except KeyboardInterrupt:
        pass
    finally:
        result = _close_server(server)
    return result + f" Local webhook was on port {port}."


def _start_webhook(port: int = 8765) -> str:
    server, error = _new_server(port)
    if error:
        return error
    thread = threading.Thread(target=_serve, args=(server,), name="jarvis-phone-line", daemon=True)
    thread.start()
    actual = server.server_address[1]
    return (f"Phone line webhook started on http://127.0.0.1:{actual} (localhost only). "
            "Expose it over HTTPS with cloudflared or ngrok, then set the Twilio voice webhook URL.")


def _stop_webhook() -> str:
    with _SERVER_LOCK:
        server = _SERVER
    if server is None:
        return "Phone line webhook is not running."
    return _close_server(server)


# ---------------------------------------------------------------------------
# Tool entry points
# ---------------------------------------------------------------------------
def phone_line_operation(action: str = "status", account_sid: str = "", auth_token: str = "",
                         from_number: str = "", to_number: str = "", enabled: bool | None = None,
                         port: int = 8765, to: str = "", message: str = "",
                         confirmed: bool = False) -> str:
    """Configure/inspect the real Twilio line and control its local webhook.

    actions: status, configure, call, webhook (blocking), start, stop,
    last_transcript. configure stores SID/number locally and protects the token
    with Jarvis's DPAPI-backed secret helper. Never paste credentials in chat.
    """
    a = str(action or "status").strip().lower()
    if a in ("show", "info"):
        a = "status"
    if a in ("setup", "config"):
        a = "configure"
    if a in ("place", "dial"):
        a = "call"
    if a in ("listen", "serve"):
        a = "webhook"
    if a in ("transcript", "last"):
        a = "last_transcript"

    if a == "configure":
        cfg = _load_cfg()
        changed: dict = {}
        if account_sid:
            changed["account_sid"] = str(account_sid).strip()
        if from_number:
            number = _normalize_number(from_number)
            if not number:
                return "Invalid from_number. Use E.164 format, for example +15551234567."
            changed["from_number"] = number
        if to_number:
            number = _normalize_number(to_number)
            if not number:
                return "Invalid to_number. Use E.164 format, for example +15551234567."
            changed["call_me_number"] = number
        if auth_token:
            changed["auth_token"] = core.protect_secret(
                str(auth_token).strip(), "jarvis-twilio-auth-token")
        if enabled is not None:
            changed["enabled"] = bool(enabled)
        if not changed:
            return ("Phone line configure: give account_sid, auth_token, from_number, "
                    "to_number (callback) and/or enabled.")
        cfg.update(changed)
        stored = dict(cfg)
        stored["auth_token"] = core.protect_secret(str(cfg.get("auth_token") or ""),
                                                   "jarvis-twilio-auth-token")
        core.save_config({CONFIG_KEY: stored})
        core.audit("phone_line_operation:configure", ", ".join(sorted(changed)),
                   "saved locally; token protected", risk="high")
        return "Phone line configuration saved locally. " + _status_line()

    if a == "status":
        return _status_line()
    if a == "call":
        return phone_line_call(to_number=to or "", message=message, confirmed=confirmed)
    if a == "webhook":
        return phone_line_webhook(port=port)
    if a == "start":
        return _start_webhook(port)
    if a == "stop":
        return _stop_webhook()
    if a == "last_transcript":
        return last_transcript()
    return ("Phone line actions: status, configure, call, webhook, start, stop, "
            "last_transcript.")
