"""Real, free, LOCAL Asterisk voice line for Jarvis PC.

No Twilio, no paid service, no bundled credential.  This module speaks two real
protocols with the Python standard library only:

* AMI (Asterisk Manager Interface) over a TCP socket, to place a genuine
  Asterisk ``Originate`` only when AMI answers ``Response: Success``.
* FastAGI over a TCP socket, so an Asterisk dialplan can hand a live call to
  this PC.  The call is answered, consent + prompt WAVs are streamed, the
  caller's voice is recorded, and the WAV is transcribed with the same free
  ``speech_recognition`` / Google Web Speech path the PC already uses.  The
  recognised text is routed through ``phone_line._run_command`` so the existing
  safety deny-list and command hook apply to phone speech too.

IMPORTANT / honest scope: Asterisk is free open-source software, but a public
PSTN/SIM phone number still requires a trunk or GSM gateway that the user must
obtain and configure.  ``target`` is only a label passed to the dialplan; it is
NOT dialled as a phone number here.  Every outward-facing string in this module
says so.  Runtime audio/logs live in the gitignored ``jarvis_data`` folder.
"""
from __future__ import annotations

import json
import os
import re
import socket
import socketserver
import threading
import time
from datetime import datetime
from typing import Any

from . import core

CONFIG_KEY = "asterisk_line"
DEFAULTS: dict[str, Any] = {
    "host": "127.0.0.1",
    "ami_port": 5038,
    "username": "",
    "secret": "",
    "outbound_context": "jarvis-out",
    "outbound_extension": "1001",
    "agi_host": "host.docker.internal",
    "agi_port": 4573,
    "stt_language": "en-US",
    # Optional: directory Asterisk (inside WSL) should write recordings into.
    # Empty means auto-convert the Windows folder to /mnt/<drive>/... below.
    "wsl_recordings_dir": "",
}

INBOUND_CONTEXT = "jarvis-in"
INBOUND_EXTEN = "1002"
CALLER_ID = f"Jarvis <{INBOUND_EXTEN}>"
CONSENT_LINE = (
    "This call is being recorded and processed locally on this PC by Jarvis. "
    "Please state your command after the prompt."
)
PROMPT_LINE = "Please say your command now, for example: asterisk line status."
FALLBACK_LINE = "Samajh nahi aaya, dobara boliye."

AMI_TIMEOUT = 10.0
AGI_TIMEOUT = 10.0
_AGI_STATUS_RE = re.compile(r"^(\d{3})\s+result=([^\s]*)", re.I)
_MALE_HINTS = ("david", "mark", "george", "daniel", "male", "ryan", "guy")
_FEMALE_HINTS = ("zira", "hazel", "samantha", "karen", "victoria", "female", "woman")

_SERVER = None
_SERVER_LOCK = threading.RLock()
_TTS_LOCK = threading.RLock()
_LOG_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------------
def _sounds_dir() -> str:
    """Sounds folder the Asterisk container is expected to mount as its sounds dir."""
    return os.path.join(core.DATA_DIR, "asterisk", "sounds", "jarvis")


def _recordings_dir() -> str:
    return os.path.join(core.DATA_DIR, "asterisk_recordings")


def _transcript_log() -> str:
    return os.path.join(core.DATA_DIR, "asterisk_transcripts.jsonl")


def _load_cfg() -> dict:
    """Read config.json's ``asterisk_line`` section, decrypting the AMI secret."""
    raw = core.config_get(CONFIG_KEY, {}) or {}
    cfg = dict(DEFAULTS)
    if isinstance(raw, dict):
        cfg.update(raw)
    cfg["secret"] = core.unprotect_secret(str(cfg.get("secret") or ""))
    for key in ("ami_port", "agi_port"):
        try:
            cfg[key] = int(cfg.get(key) or DEFAULTS[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    for key in ("host", "username", "outbound_context", "outbound_extension",
                "agi_host", "stt_language", "wsl_recordings_dir"):
        cfg[key] = str(cfg.get(key) or DEFAULTS[key])
    return cfg


def _clean(value: Any, limit: int = 200) -> str:
    """Remove AMI/AGI protocol delimiters from a user-supplied value."""
    return re.sub(r"[\r\n\x00|]", " ", str(value or "")).strip()[:limit]


def _wsl_path(path: str) -> str:
    """Windows absolute path -> the /mnt/<drive>/... path WSL sees.

    C:\\Users\\Shahid\\x.wav -> /mnt/c/Users/Shahid/x.wav.  Already-POSIX paths
    are passed through with backslashes normalised.
    """
    text = str(path or "").strip()
    if not text:
        return text
    if text.startswith("/"):
        return text.replace("\\", "/")
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if match:
        return "/mnt/" + match.group(1).lower() + "/" + match.group(2).replace("\\", "/")
    return text.replace("\\", "/")


def _windows_path(path: str) -> str:
    """Reverse :func:`_wsl_path` when a WSL path comes back from Asterisk."""
    text = str(path or "").strip().strip('"\'')
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        return match.group(1).upper() + ":\\" + match.group(2).replace("/", "\\")
    return text


def _recording_target(cfg: dict, windows_path: str) -> str:
    """The filename Asterisk (in WSL) must pass to AGI RECORD FILE."""
    override = str(cfg.get("wsl_recordings_dir") or "").strip()
    if override:
        base = _wsl_path(override).rstrip("/")
        target = base + "/" + os.path.basename(windows_path)
    else:
        target = _wsl_path(windows_path)
    # AGI arguments are space separated; quote a filename that contains spaces.
    return _agi_quote(target)


def _audio_path_from_response(lines: list[str], env: dict, preferred: str) -> str:
    """Prefer the Windows path we built; only fall back to a returned WSL path."""
    if os.path.isfile(preferred):
        return preferred
    candidates = [str(line) for line in lines] + [str(env.get("agi_recording") or "")]
    for line in candidates:
        for token in line.replace('"', " ").split():
            if token.lower().endswith(".wav"):
                local = _windows_path(token)
                if os.path.isfile(local):
                    return local
    return preferred


def _agi_quote(value: str) -> str:
    return '"' + value + '"' if re.search(r"\s", value) else value


def _resolve(cfg: dict, host: str, port: int, username: str, secret: str,
             outbound_context: str, outbound_extension: str, agi_port: int) -> dict:
    """Let explicit non-default arguments override the stored configuration."""
    out = dict(cfg)
    if host:
        out["host"] = _clean(host, 200)
    if port and port != DEFAULTS["ami_port"]:
        out["ami_port"] = int(port)
    if username:
        out["username"] = _clean(username, 120)
    if secret:
        out["secret"] = _clean(secret, 300)
    if outbound_context and outbound_context != DEFAULTS["outbound_context"]:
        out["outbound_context"] = _clean(outbound_context, 120)
    if outbound_extension and outbound_extension != DEFAULTS["outbound_extension"]:
        out["outbound_extension"] = _clean(outbound_extension, 80)
    if agi_port and agi_port != DEFAULTS["agi_port"]:
        out["agi_port"] = int(agi_port)
    return out


def _configure(host: str, port: int, username: str, secret: str,
               outbound_context: str, outbound_extension: str,
               agi_host: str, agi_port: int) -> str:
    updates: dict[str, Any] = {}
    if host:
        updates["host"] = _clean(host, 200)
    if port and port != DEFAULTS["ami_port"]:
        updates["ami_port"] = int(port)
    if username:
        updates["username"] = _clean(username, 120)
    if secret:
        updates["secret"] = core.protect_secret(_clean(secret, 300),
                                                "jarvis-asterisk-ami-secret")
    if outbound_context and outbound_context != DEFAULTS["outbound_context"]:
        updates["outbound_context"] = _clean(outbound_context, 120)
    if outbound_extension and outbound_extension != DEFAULTS["outbound_extension"]:
        updates["outbound_extension"] = _clean(outbound_extension, 80)
    if agi_host and agi_host != DEFAULTS["agi_host"]:
        updates["agi_host"] = _clean(agi_host, 200)
    if agi_port and agi_port != DEFAULTS["agi_port"]:
        updates["agi_port"] = int(agi_port)
    if not updates:
        return ("No Asterisk settings were supplied. Use asterisk configure <host> <username> "
                "<secret> [extension], or asterisk_operation(action='configure', host=..., "
                "username=..., secret=...). Nothing was changed.")

    raw = core.config_get(CONFIG_KEY, {}) or {}
    merged = dict(raw) if isinstance(raw, dict) else {}
    merged.update(updates)
    core.save_config({CONFIG_KEY: merged})
    cfg = _load_cfg()
    core.audit("asterisk_configure", ", ".join(sorted(updates)), "configuration saved locally")
    return (
        "Asterisk line configuration saved locally:\n"
        f"- AMI host: {cfg['host']}:{cfg['ami_port']}\n"
        f"- AMI username: {cfg['username'] or 'not set'}\n"
        "- AMI secret: " + ("set (protected, never printed)" if cfg["secret"] else "not set") + "\n"
        f"- outbound channel: Local/{cfg['outbound_extension']}@{cfg['outbound_context']}\n"
        f"- inbound context/exten: {INBOUND_CONTEXT},{INBOUND_EXTEN},1\n"
        f"- FastAGI advertised host/port: {cfg['agi_host']}:{cfg['agi_port']}\n"
        f"- STT language: {cfg['stt_language']}\n"
        f"- recordings: Windows {_recordings_dir()} -> Asterisk/WSL "
        f"{_recording_target(cfg, os.path.join(_recordings_dir(), 'call.wav'))}\n"
        "  (set wsl_recordings_dir in jarvis_data/config.json to override the /mnt/<drive> path)\n"
        "This is a free local Asterisk line: NOT Twilio and NOT a PSTN/SIM number. "
        "Point the dialplan at agi(agi://host:port/jarvis) and mount "
        "jarvis_data/asterisk/sounds as the Asterisk sounds dir. A real public phone "
        "number still needs a user-provided trunk or GSM/SIM gateway."
    )


def _status() -> str:
    cfg = _load_cfg()
    with _SERVER_LOCK:
        running = _SERVER is not None
    credential_state = ("set" if cfg["username"] and cfg["secret"] else "not set")
    return (
        "Asterisk line: "
        f"FastAGI={'running' if running else 'stopped'} on 0.0.0.0:{cfg['agi_port']}; "
        f"AMI={cfg['host']}:{cfg['ami_port']} (credentials {credential_state}); "
        f"outbound=Local/{cfg['outbound_extension']}@{cfg['outbound_context']}; "
        f"inbound={INBOUND_CONTEXT},{INBOUND_EXTEN},1; "
        f"advertised FastAGI host={cfg['agi_host']}; STT language={cfg['stt_language']}; "
        f"recordings Windows={_recordings_dir()} -> Asterisk/WSL="
        f"{_recording_target(cfg, os.path.join(_recordings_dir(), 'call.wav'))}; "
        "free local Asterisk, NOT Twilio, NOT a PSTN/SIM number. "
        "A public phone number needs a user-provided trunk/SIM gateway."
    )


# ---------------------------------------------------------------------------
# Real AMI client (stdlib socket only)
# ---------------------------------------------------------------------------
class AmiError(RuntimeError):
    """An AMI command failed or the peer did not answer as required."""


def _ami_read_block(fh) -> dict:
    """Read one AMI block (headers terminated by a blank line)."""
    headers: dict[str, str] = {}
    seen = False
    while True:
        raw = fh.readline()
        if not raw:
            if not seen:
                raise AmiError("AMI closed the connection before answering")
            break
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if seen:
                break
            continue
        seen = True
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers


def _ami_action(sock, fh, fields: list[str]) -> dict:
    """Send one AMI action and return its Response block (skipping events)."""
    payload = "\r\n".join(fields) + "\r\n\r\n"
    try:
        sock.sendall(payload.encode("utf-8"))
    except OSError as exc:
        raise AmiError(f"could not send AMI action: {exc}") from exc
    while True:
        headers = _ami_read_block(fh)
        if "response" in headers:
            return headers


def _ami_originate(cfg: dict, target: str) -> str:
    """Login and Originate a real Asterisk call; success only on Response: Success."""
    host = _clean(cfg["host"], 200) or "127.0.0.1"
    port = int(cfg["ami_port"])
    ext = _clean(cfg["outbound_extension"], 80)
    context = _clean(cfg["outbound_context"], 120)
    label = _clean(target, 200)
    sock = None
    fh = None
    try:
        sock = socket.create_connection((host, port), timeout=AMI_TIMEOUT)
        sock.settimeout(AMI_TIMEOUT)
        fh = sock.makefile("rb")
        _ami_read_block(fh)  # Asterisk Call Manager greeting
        login = _ami_action(sock, fh, [
            "Action: Login",
            f"Username: {_clean(cfg['username'], 120)}",
            f"Secret: {_clean(cfg['secret'], 300)}",
        ])
        if str(login.get("response", "")).lower() != "success":
            raise AmiError("AMI login failed: " +
                           str(login.get("message") or login.get("response") or "no response"))

        fields = [
            "Action: Originate",
            f"Channel: Local/{ext}@{context}",
            f"Context: {INBOUND_CONTEXT}",
            f"Exten: {INBOUND_EXTEN}",
            "Priority: 1",
            "Async: true",
            f"CallerID: {CALLER_ID}",
            "Timeout: 30000",
        ]
        if label:
            fields.append(f"Variable: JARVIS_TARGET={label}")
        answer = _ami_action(sock, fh, fields)
        if str(answer.get("response", "")).lower() != "success":
            raise AmiError("AMI Originate rejected: " +
                           str(answer.get("message") or answer.get("response") or "no response"))
        message = str(answer.get("message") or "Originate accepted")
    except (AmiError, OSError, ValueError) as exc:
        return (f"Asterisk call did not succeed: {core.truncate(str(exc), 300)}. "
                "No call is claimed.")
    finally:
        for closer in (fh, sock):
            try:
                if closer is not None:
                    closer.close()
            except Exception:
                pass

    core.audit("asterisk_call", f"channel=Local/{ext}@{context} target={label or 'none'}",
               f"AMI Response: Success - {message}", risk="high")
    detail = (f"AMI accepted the Originate (Response: Success): {message}. "
              f"Ringing local extension {ext} in context {context}; on answer Asterisk "
              f"connects {INBOUND_CONTEXT},{INBOUND_EXTEN},1 to the FastAGI script on "
              f"{cfg['agi_host']}:{cfg['agi_port']}. ")
    if label:
        detail += f"The label '{label}' was passed as JARVIS_TARGET. "
    return (detail + "No PSTN/SIM number was dialed; a public phone number needs a "
            "user-provided trunk/SIM gateway. Answer/delivery is not verified.")


def _call(target: str, confirmed: bool, cfg: dict | None = None) -> str:
    if not confirmed:
        core.audit("asterisk_call", f"target={_clean(target, 120)}",
                   "blocked: confirmation required", risk="high")
        return ("CONFIRMATION REQUIRED: place a real call through the local Asterisk line "
                f"to target label '{_clean(target, 120) or 'none'}' (the configured extension "
                f"rings; no PSTN number is dialed). Nothing has been done yet. Ask the user "
                "in plain language and wait for a clear yes, then call with confirmed=True.")
    return _ami_originate(cfg if cfg is not None else _load_cfg(), target)


# ---------------------------------------------------------------------------
# FastAGI server (stdlib socketserver, daemon threads)
# ---------------------------------------------------------------------------
class _AgiServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _server_running() -> bool:
    with _SERVER_LOCK:
        return _SERVER is not None


def start_agi_server(port: int = 4573) -> str:
    """Start the local FastAGI listener on 0.0.0.0:<port> (daemon thread)."""
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is not None:
            address = getattr(_SERVER, "server_address", None) or ("0.0.0.0", "?")
            return f"FastAGI server is already running on 0.0.0.0:{address[1]}."
        try:
            server = _AgiServer(("0.0.0.0", int(port)), _AgiHandler)
        except Exception as exc:
            return (f"Could not start FastAGI server on 0.0.0.0:{port}: "
                    f"{core.truncate(str(exc), 300)}. No listener is running.")
        thread = threading.Thread(target=server.serve_forever, name="jarvis-fastagi",
                                  daemon=True)
        thread.start()
        _SERVER = server
    core.audit("asterisk_start", f"port={port}", "FastAGI listener started")
    return (f"FastAGI server started on 0.0.0.0:{port} (daemon thread). This is a local "
            "Asterisk listener, not Twilio; Asterisk must be configured to call it at "
            "agi(agi://host:port/jarvis).")


def stop_agi_server() -> str:
    """Stop the FastAGI listener if it is running."""
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is None:
            return "FastAGI server is not running. Nothing was stopped."
        server = _SERVER
        _SERVER = None
    try:
        server.shutdown()
        server.server_close()
    except Exception as exc:
        return f"FastAGI server stop reported an error: {core.truncate(str(exc), 240)}"
    core.audit("asterisk_stop", "", "FastAGI listener stopped")
    return "FastAGI server stopped. Asterisk calls to the old FastAGI URL will now fail."


class _AgiHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(AGI_TIMEOUT)
        except Exception:
            pass
        try:
            _agi_session(self.rfile, self.wfile, self.client_address)
        except Exception as exc:
            core.log(f"asterisk FastAGI handler error: {core.truncate(str(exc), 300)}")


# ---------------------------------------------------------------------------
# FastAGI protocol helpers
# ---------------------------------------------------------------------------
def _read_agi_env(rfile) -> dict:
    """Read ``agi_*`` environment lines until the terminating blank line."""
    env: dict[str, str] = {}
    try:
        for _ in range(200):
            raw = rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                env[key.strip().lower()] = value.strip()
    except (OSError, ValueError):
        pass
    return env


def _agi_command(rfile, wfile, command: str) -> list[str]:
    """Send one AGI command and read its FULL response (never just one line).

    AGI replies end with a blank line and may contain extra lines around the
    ``200 result=...`` status line.  The handler socket has a hard timeout, and
    this loop is line/response capped, so a bad peer cannot hang a call thread.
    """
    try:
        wfile.write((command + "\n").encode("utf-8"))
        wfile.flush()
    except (OSError, ValueError) as exc:
        core.log(f"asterisk AGI write failed ({command}): {exc}")
        return []
    lines: list[str] = []
    try:
        for _ in range(64):
            raw = rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if lines:
                    break
                continue
            lines.append(line)
    except (OSError, ValueError) as exc:
        core.log(f"asterisk AGI read timeout ({command}): {exc}")
    return lines


def _agi_result(lines: list[str]) -> tuple[str, str]:
    for line in reversed(lines):
        match = _AGI_STATUS_RE.match(line.strip())
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _voice_field(voice, name: str) -> str:
    if isinstance(voice, dict):
        return str(voice.get(name) or "")
    return str(getattr(voice, name, "") or "")


def _tts_to_wav(text: str, filename: str, male: bool = True) -> str:
    """Render speech locally with pyttsx3.  Never selects a female voice."""
    os.makedirs(_sounds_dir(), exist_ok=True)
    target = os.path.join(_sounds_dir(), os.path.basename(filename))
    with _TTS_LOCK:
        import pyttsx3  # installed locally; imported lazily so tests stay offline

        engine = pyttsx3.init()
        if male:
            try:
                voices = engine.getProperty("voices") or []
            except Exception:
                voices = []
            chosen = ""
            for voice in voices:
                vname = _voice_field(voice, "name").lower()
                if any(bad in vname for bad in _FEMALE_HINTS):
                    continue
                if any(good in vname for good in _MALE_HINTS):
                    chosen = _voice_field(voice, "id")
                    break
            if chosen:
                try:
                    engine.setProperty("voice", chosen)
                except Exception:
                    pass
        engine.save_to_file(text, target)
        engine.runAndWait()
    if not os.path.isfile(target) or os.path.getsize(target) < 44:
        raise RuntimeError("pyttsx3 did not produce a usable WAV file")
    return target


def _speak(rfile, wfile, text: str, filename: str) -> bool:
    """Stream a locally generated WAV; on TTS failure stream a real beep instead."""
    try:
        path = _tts_to_wav(text, filename, male=True)
    except Exception as exc:
        core.log(f"asterisk TTS failed, streaming beep: {core.truncate(str(exc), 200)}")
        _agi_command(rfile, wfile, 'STREAM FILE beep ""')
        return False
    relative = "jarvis/" + os.path.splitext(os.path.basename(path))[0]
    _agi_command(rfile, wfile, f'STREAM FILE {relative} ""')
    return True


def _transcribe_file(path: str, language: str) -> str:
    """Free local call to Google Web Speech through speech_recognition (no key)."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.AudioFile(path) as source:
        audio = recognizer.record(source)
    return str(recognizer.recognize_google(audio, language=language) or "").strip()


def _append_transcript(row: dict):
    os.makedirs(os.path.dirname(_transcript_log()), exist_ok=True)
    with _LOG_LOCK:
        with open(_transcript_log(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _prune_replies(keep: int = 50):
    """Reply WAVs are gitignored runtime files; keep only the newest few dozen."""
    try:
        directory = _sounds_dir()
        names = sorted(n for n in os.listdir(directory)
                       if n.startswith("reply_") and n.endswith(".wav"))
        for old in names[:-keep]:
            os.remove(os.path.join(directory, old))
    except Exception:
        pass


def _agi_session(rfile, wfile, peer=("unknown", 0)) -> str:
    """Handle one live FastAGI call.  Returns an honest status token."""
    env = _read_agi_env(rfile)
    callerid = str(env.get("agi_callerid") or env.get("agi_calleridname") or "unknown")
    _agi_command(rfile, wfile, "ANSWER")

    _speak(rfile, wfile, CONSENT_LINE, "consent.wav")
    _speak(rfile, wfile, PROMPT_LINE, "prompt.wav")

    cfg = _load_cfg()
    os.makedirs(_recordings_dir(), exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    audio_path = os.path.join(_recordings_dir(), f"call_{stamp}.wav")
    # Asterisk runs in WSL: it must write through /mnt/<drive>, while Python
    # keeps using the original Windows path for reading/transcription.
    recording_target = _recording_target(cfg, audio_path)
    rec_lines = _agi_command(
        rfile, wfile, f"RECORD FILE {recording_target} wav 15000 0 BEEP 2")
    _rec_code, rec_result = _agi_result(rec_lines)
    audio_path = _audio_path_from_response(rec_lines, env, audio_path)

    recognized = ""
    reply = ""
    status = "ok"
    has_audio = bool(rec_result.isdigit() and int(rec_result) > 0 and
                     os.path.isfile(audio_path) and os.path.getsize(audio_path) > 44)
    if not has_audio:
        status = "no_recording"
        reply = "I did not receive a recording. Goodbye."
    else:
        try:
            recognized = _transcribe_file(audio_path, cfg["stt_language"])
        except Exception as exc:
            core.log(f"asterisk STT failed: {core.truncate(str(exc), 240)}")
            recognized = ""
        if not recognized:
            status = "stt_failed"
            reply = FALLBACK_LINE
        else:
            try:
                from . import phone_line
                reply = phone_line._run_command(recognized)
            except Exception as exc:
                status = "command_failed"
                reply = "Command failed: " + core.truncate(str(exc), 160)

    if reply:
        reply_name = f"reply_{stamp}.wav"
        if _speak(rfile, wfile, core.truncate(reply, 400), reply_name):
            _prune_replies()
    _agi_command(rfile, wfile, "HANGUP")

    _append_transcript({
        "t": time.time(),
        "timestamp": core.now_str(),
        "callerid": callerid,
        "peer": str(peer),
        "recognized_text": recognized,
        "reply": reply,
        "audio_path": audio_path,
        "status": status,
    })
    core.audit("asterisk_agi_call", f"callerid={callerid}",
               f"status={status}; recognized={core.truncate(recognized, 120)}; "
               f"reply={core.truncate(reply, 120)}")
    return status


# ---------------------------------------------------------------------------
# Public API (exact names used by the docs and by tools.py)
# ---------------------------------------------------------------------------
def asterisk_operation(action: str = "status", host: str = "", port: int = 5038,
                       username: str = "", secret: str = "",
                       outbound_context: str = "jarvis-out",
                       outbound_extension: str = "1001",
                       agi_host: str = "host.docker.internal", agi_port: int = 4573,
                       target: str = "", confirmed: bool = False) -> str:
    """Manage the free local Asterisk line: status/start/stop/configure/call/call_me.

    ``host``/``port``/``username``/``secret``/context/extension/agi_port override
    the stored config when they differ from the documented defaults.  No secret
    is ever returned.  Calls happen only with confirmed=True and are real AMI
    Originates; ``target`` is a dialplan label, not a PSTN number.
    """
    act = (action or "status").strip().lower()
    if act in ("status", "haal"):
        return _status()
    if act in ("start", "on"):
        chosen_port = (int(agi_port) if agi_port and agi_port != DEFAULTS["agi_port"]
                       else int(_load_cfg()["agi_port"]))
        return start_agi_server(chosen_port)
    if act in ("stop", "off"):
        return stop_agi_server()
    if act in ("configure", "config", "setup"):
        return _configure(host, int(port), username, secret, outbound_context,
                          outbound_extension, agi_host, int(agi_port))
    if act in ("call", "originate", "dial"):
        cfg = _resolve(_load_cfg(), host, port, username, secret, outbound_context,
                       outbound_extension, agi_port)
        return _call(target, confirmed, cfg)
    if act in ("call_me", "callme", "callback"):
        return _call("", confirmed)
    return ("Unknown Asterisk action '" + core.truncate(action, 80) + "'. Use status, start, "
            "stop, configure, call or call_me. Nothing was changed.")


def asterisk_start() -> str:
    """Start the local FastAGI listener (no Twilio, no paid service)."""
    return start_agi_server(int(_load_cfg()["agi_port"]))


def asterisk_stop() -> str:
    """Stop the local FastAGI listener."""
    return stop_agi_server()


def asterisk_status() -> str:
    """Honest status of the free local Asterisk line."""
    return _status()


def asterisk_configure(host: str = "", username: str = "", secret: str = "",
                       outbound_extension: str = "1001", port: int = 5038,
                       agi_port: int = 4573) -> str:
    """Save AMI host/credentials and extensions locally, protecting the secret."""
    return _configure(host, port, username, secret, DEFAULTS["outbound_context"],
                      outbound_extension, DEFAULTS["agi_host"], agi_port)


def asterisk_call(target: str = "", confirmed: bool = False) -> str:
    """Originate a real local Asterisk call after explicit confirmation."""
    return asterisk_operation("call", target=target, confirmed=confirmed)


def asterisk_call_me(confirmed: bool = False) -> str:
    """Ring the configured local extension after explicit confirmation."""
    return asterisk_operation("call_me", confirmed=confirmed)
