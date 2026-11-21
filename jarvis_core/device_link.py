"""Real local-network Device Link between a paired Android phone and Jarvis PC.

This is a plain stdlib HTTP service (``ThreadingHTTPServer``) that listens on the
LAN.  A phone on the same Wi-Fi / hotspot can pair once with a short-lived code,
send a file, and then Jarvis asks out loud where to save it.  Nothing is written
to a final location until an explicit destination is supplied and any overwrite
is confirmed.  All state lives in the gitignored ``jarvis_data/device_link/``
folder.

No cloud, no internet, no phone number and no Twilio account are involved here;
the Twilio phone line (``jarvis_core.phone_line``) is a separate feature.
"""
from __future__ import annotations

import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
from datetime import datetime

from . import core, phone_line

DEFAULT_HOST = "0.0.0.0"          # LAN binding, not just localhost
DEFAULT_PORT = 8766
CONFIG_PORT_KEY = "device_link_port"
CONFIG_DIR_KEY = "device_link_data_dir"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024      # 200 MB hard cap
PAIR_CODE_TTL = 600                       # 10 minutes
MAX_PAIR_ATTEMPTS = 5
TOKEN_HEADER = "X-Jarvis-Token"
_READ_CHUNK = 64 * 1024

_SERVER = None
_SERVER_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Paths, config and network identity
# ---------------------------------------------------------------------------
def _port(port=0) -> int:
    """Configured port, falling back to 8766 (tool arguments win over config)."""
    try:
        chosen = int(port or 0)
    except (TypeError, ValueError):
        chosen = 0
    if chosen > 0:
        return chosen
    try:
        configured = int(core.config_get(CONFIG_PORT_KEY, DEFAULT_PORT) or DEFAULT_PORT)
    except (TypeError, ValueError):
        configured = DEFAULT_PORT
    return configured if configured > 0 else DEFAULT_PORT


def runtime_dir() -> str:
    """Gitignored runtime folder: jarvis_data/device_link (or a config override)."""
    custom = str(core.config_get(CONFIG_DIR_KEY, "") or "").strip()
    base = os.path.expanduser(custom) if custom else core.DATA_DIR
    return os.path.join(os.path.abspath(base), "device_link")


def state_path() -> str:
    return os.path.join(runtime_dir(), "state.json")


def pending_dir() -> str:
    return os.path.join(runtime_dir(), "pending")


def incoming_dir() -> str:
    return os.path.join(runtime_dir(), "incoming")


def _ensure_dirs() -> None:
    for folder in (runtime_dir(), pending_dir(), incoming_dir()):
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as exc:
            core.log(f"device link could not create {folder}: {exc}")


def lan_ip() -> str:
    """Best-effort LAN IPv4. UDP connect picks the local route without traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Persistent state: one-time code + protected token
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    data = core.read_json(state_path(), {})
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> bool:
    _ensure_dirs()
    return core.write_json(state_path(), state)


def new_pairing_code() -> str:
    """Generate a fresh 6-digit code valid for 10 minutes; invalidates old token."""
    with _STATE_LOCK:
        _ensure_dirs()
        state = _load_state()
        code = f"{secrets.randbelow(1000000):06d}"
        state["pair_code"] = code
        state["code_expires"] = time.time() + PAIR_CODE_TTL
        state["attempts"] = 0
        state["token"] = ""            # a new code unpairs any previous phone
        state["paired_at"] = None
        _save_state(state)
        return code


def pair_with_code(code="") -> dict:
    """Exchange a valid one-time code for a random token (returned once)."""
    supplied = str(code or "").strip()
    with _STATE_LOCK:
        _ensure_dirs()
        state = _load_state()
        expected = str(state.get("pair_code") or "")
        expires = float(state.get("code_expires") or 0)
        attempts = int(state.get("attempts") or 0)

        if not expected:
            return {"ok": False, "message":
                    "No pairing code is active. Run 'device link code' on the PC first."}
        if time.time() > expires:
            state["pair_code"] = ""
            state["code_expires"] = 0
            state["attempts"] = 0
            _save_state(state)
            return {"ok": False, "message":
                    "That pairing code has expired. Run 'device link code' on the PC for a new one."}
        if attempts >= MAX_PAIR_ATTEMPTS:
            return {"ok": False, "message":
                    "Too many wrong pairing attempts. Run 'device link code' on the PC for a new code."}
        if not hmac.compare_digest(supplied, expected):
            state["attempts"] = attempts + 1
            _save_state(state)
            left = max(0, MAX_PAIR_ATTEMPTS - state["attempts"])
            return {"ok": False, "message":
                    f"Wrong pairing code. {left} attempt(s) left before this code is cancelled."}

        token = secrets.token_urlsafe(32)
        state["token"] = core.protect_secret(token, "jarvis-device-link-token")
        state["pair_code"] = ""        # strictly one-time
        state["code_expires"] = 0
        state["attempts"] = 0
        state["paired_at"] = datetime.now().isoformat(timespec="seconds")
        _save_state(state)
        core.audit("device_link_pair", "pair code accepted", "token issued", risk="high")
        return {"ok": True, "token": token,
                "message": "Paired. Store this token on the phone; it is not shown again."}


def token_ok(token="") -> bool:
    """Constant-time compare against the locally protected token."""
    supplied = str(token or "").strip()
    if not supplied:
        return False
    stored = core.unprotect_secret(str(_load_state().get("token") or ""))
    return bool(stored) and hmac.compare_digest(supplied, stored)


# ---------------------------------------------------------------------------
# Pending records
# ---------------------------------------------------------------------------
def _record_path(file_id="") -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(file_id or ""))[:80]
    return os.path.join(pending_dir(), safe + ".json") if safe else ""


def list_pending() -> list[dict]:
    """Only files still waiting for a destination are 'pending'."""
    _ensure_dirs()
    out: list[dict] = []
    try:
        names = sorted(os.listdir(pending_dir()))
    except Exception:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        rec = core.read_json(os.path.join(pending_dir(), name), {})
        if isinstance(rec, dict) and rec.get("status") == "need_destination":
            out.append(rec)
    return out


def _final_target(destination="", name="upload.bin") -> tuple[str, str]:
    """Resolve a phone-supplied destination to a real absolute final path."""
    raw = str(destination or "").strip().strip('"')
    resolved = os.path.abspath(core.resolve_path(raw))
    runtime = os.path.abspath(runtime_dir())
    if resolved.lower() == runtime.lower() or resolved.lower().startswith(runtime.lower() + os.sep):
        return "", "Destination cannot be inside the Device Link runtime folder."
    safe_name = core.safe_filename(name, default="upload.bin")
    if raw.endswith(("/", "\\")) or os.path.isdir(resolved) or resolved.lower().endswith(("\\", "/")):
        final = os.path.join(resolved, safe_name)
    else:
        final = resolved
        if os.path.isdir(final):
            final = os.path.join(final, safe_name)
    return final, ""


def save_file(file_id="", destination="", confirmed=False) -> dict:
    """Copy a staged upload to the requested final path, honestly."""
    path = _record_path(file_id)
    if not path or not os.path.isfile(path):
        return {"ok": False, "status": "not_found",
                "message": "No pending file with that id. Nothing was saved."}
    record = core.read_json(path, {}) or {}
    if record.get("status") != "need_destination":
        return {"ok": False, "status": str(record.get("status", "unknown")),
                "message": "That file was already handled. No new save was made."}

    staged = str(record.get("staged_path") or "")
    if not staged or not os.path.isfile(staged):
        return {"ok": False, "status": "staged_missing",
                "message": "The staged copy is missing, so no final file was written."}
    name = str(record.get("name") or "upload.bin")
    expected = int(record.get("size") or 0)
    final, error = _final_target(destination, name)
    if error:
        return {"ok": False, "status": "invalid_destination", "message": error}

    if os.path.exists(final) and not bool(confirmed):
        detail = (f"Overwrite the existing file {final} with the phone upload "
                  f"{name} ({expected} bytes)")
        gate = core.guard("device_link_save", False, detail)
        if not gate:  # keep the overwrite gate even if safe_mode was turned off
            gate = ("CONFIRMATION REQUIRED: " + detail + " Nothing has been overwritten. "
                    "Ask clearly, then call save again with confirmed=true.")
        record["requested_destination"] = destination
        core.write_json(path, record)
        return {"ok": False, "confirmation_required": True, "status": "need_destination",
                "id": file_id, "path": final, "size": expected, "message": gate}

    try:
        os.makedirs(os.path.dirname(final) or ".", exist_ok=True)
        shutil.copyfile(staged, final)
        actual = os.path.getsize(final)
        if actual != expected:
            raise RuntimeError(f"size mismatch: expected {expected} bytes, found {actual}")
        os.remove(staged)
    except Exception as exc:
        return {"ok": False, "status": "save_failed",
                "message": "Save failed: " + core.truncate(str(exc), 300) +
                           " The staged copy was kept; no success is claimed."}

    record["status"] = "saved"
    record["final_path"] = final
    record["saved_at"] = datetime.now().isoformat(timespec="seconds")
    core.write_json(path, record)
    core.audit("device_link_save", f"id={file_id}", f"path={final} size={actual}")
    core.say_lang(
        f"File saved to {final}. Size {actual} bytes.",
        f"File save ho gaya: {final}. Size {actual} bytes.",
        f"فائل محفوظ ہو گئی: {final}. سائز {actual} بائٹس۔")
    return {"ok": True, "id": file_id, "path": final, "size": actual,
            "status": "saved", "message": "Saved to the real path shown."}


# ---------------------------------------------------------------------------
# Streaming multipart upload (stdlib only)
# ---------------------------------------------------------------------------
class _BodyReader:
    """Length-limited reader so header lines and chunks share one byte budget."""

    def __init__(self, rfile, length=0):
        self.rfile = rfile
        self.buffer = b""
        try:
            self.remaining = max(0, int(length or 0))
        except (TypeError, ValueError):
            self.remaining = 0

    def pushback(self, data: bytes) -> None:
        """Return bytes to the front of the stream (used between multipart parts)."""
        if data:
            self.buffer = bytes(data) + self.buffer

    def read(self, size=_READ_CHUNK) -> bytes:
        if self.buffer:
            size = max(0, int(size))
            head, self.buffer = self.buffer[:size], self.buffer[size:]
            return head
        if self.remaining <= 0:
            return b""
        size = min(int(size), self.remaining)
        data = self.rfile.read(size)
        self.remaining -= len(data)
        return data

    def readline(self, limit=8192) -> bytes:
        buf = bytearray()
        while len(buf) < limit:
            byte = self.read(1)
            if not byte:
                break
            buf.extend(byte)
            if byte == b"\n":
                break
        return bytes(buf)

    def drain(self) -> None:
        while self.remaining > 0:
            if not self.read(_READ_CHUNK):
                break


def _boundary(content_type="") -> str:
    match = re.search(r'boundary\s*=\s*(?:"([^"]+)"|([^;\s]+))', content_type or "", re.I)
    if not match:
        return ""
    return str(match.group(1) or match.group(2) or "").strip()


def _filename(content_disposition="") -> str:
    cd = str(content_disposition or "")
    match = re.search(r"filename\*\s*=\s*(?:UTF-8''|\"\")?([^;\r\n]+)", cd, re.I)
    if match:
        return urllib.parse.unquote(match.group(1).strip().strip('"')) or "upload.bin"
    match = re.search(r'filename\s*=\s*"([^"]*)"', cd, re.I)
    if match:
        return match.group(1) or "upload.bin"
    match = re.search(r"filename\s*=\s*([^;\r\n]+)", cd, re.I)
    return match.group(1).strip() if match else "upload.bin"


def _discard_staged(file_id: str) -> None:
    try:
        for name in os.listdir(incoming_dir()):
            if name.startswith(file_id + "_"):
                os.remove(os.path.join(incoming_dir(), name))
    except Exception:
        pass


def _read_part_headers(reader: _BodyReader, delim: bytes) -> dict[str, str] | None:
    """Find the next boundary and read that part's headers; None means end."""
    while True:
        line = reader.readline(8192)
        if not line:
            return None
        stripped = line.rstrip(b"\r\n")
        if stripped == delim + b"--":
            return None
        if stripped == delim:
            break
    headers: dict[str, str] = {}
    while True:
        line = reader.readline(8192)
        if not line:
            raise ValueError("Upload ended before the part headers were complete.")
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.decode("ascii", "replace").strip().lower()] = \
                value.decode("utf-8", "replace").strip()
    return headers


def _stream_part_body(reader: _BodyReader, delim: bytes, handle=None) -> int:
    """Stream one part's bytes to handle (or discard); stop before next boundary."""
    marker = b"\r\n" + delim
    total = 0
    tail = b""
    while True:
        chunk = reader.read(_READ_CHUNK)
        if not chunk:
            break
        data = tail + chunk
        index = data.find(marker)
        if index >= 0:
            if handle is not None and index:
                handle.write(data[:index])
                total += index
            # Leave '--boundary...' for the next header read, dropping only '\r\n'.
            reader.pushback(data[index + 2:])
            break
        keep = len(marker) - 1
        if len(data) > keep:
            outgoing = data[:-keep]
            if handle is not None:
                handle.write(outgoing)
            total += len(outgoing)
            tail = data[-keep:]
        else:
            tail = data
        if total > MAX_UPLOAD_BYTES:
            raise ValueError(f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    return total


def _stream_multipart_file(reader: _BodyReader, boundary: str, file_id: str) -> tuple[str, str, int]:
    """Skip metadata parts and stream the FIRST real file part into staging."""
    delim = b"--" + boundary.encode("utf-8", "replace")
    while True:
        headers = _read_part_headers(reader, delim)
        if headers is None:
            break
        disposition = headers.get("content-disposition", "")
        filename = _filename(disposition)
        is_file = bool(re.search(r'filename\*?\s*=', disposition, re.I)) or bool(
            re.search(r'(?:^|;)\s*name\s*=\s*(?:"file"|file(?:\s|;|$))', disposition, re.I))
        if not is_file:
            _stream_part_body(reader, delim)  # discard text field
            continue
        name = core.safe_filename(filename)
        staged = os.path.join(incoming_dir(), f"{file_id}_{name}")
        with open(staged, "wb") as handle:
            size = _stream_part_body(reader, delim, handle)
        reader.drain()
        return name, staged, size
    raise ValueError("Upload had no file part. Nothing was staged.")


def upload_from_request(rfile, headers) -> tuple[dict, int]:
    """Parse one multipart file, stage it, and create a pending record."""
    try:
        length = int(headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        length = 0
    if length > MAX_UPLOAD_BYTES + (1024 * 1024):
        return {"ok": False, "message": "Upload exceeds the 200 MB limit. Nothing was staged."}, 413
    boundary = _boundary(headers.get("Content-Type", ""))
    if not boundary:
        return {"ok": False, "message": "Expected multipart/form-data with a boundary. Nothing was staged."}, 400

    file_id = secrets.token_hex(8)
    _ensure_dirs()
    try:
        name, staged, size = _stream_multipart_file(_BodyReader(rfile, length), boundary, file_id)
    except ValueError as exc:
        _discard_staged(file_id)
        return {"ok": False, "message": str(exc) + " Nothing was staged."}, 400
    except Exception as exc:
        _discard_staged(file_id)
        return {"ok": False, "message": "Upload failed: " + core.truncate(str(exc), 240) +
                " Nothing was staged."}, 400

    if size > MAX_UPLOAD_BYTES:
        _discard_staged(file_id)
        return {"ok": False, "message": "Upload exceeds the 200 MB limit. Nothing was staged."}, 413
    if size <= 0:
        _discard_staged(file_id)
        return {"ok": False, "message": "The uploaded file was empty. Nothing was staged."}, 400

    record = {
        "id": file_id,
        "name": name,
        "size": size,
        "staged_path": staged,
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "status": "need_destination",
    }
    if not core.write_json(_record_path(file_id), record):
        _discard_staged(file_id)
        return {"ok": False, "message": "Could not record the upload locally. Nothing was saved."}, 500

    core.say_lang(
        f"File received: {name}. Where should I save it on this PC? "
        f"Tell me a path such as Downloads or D:\\backup.",
        f"File mil gayi: {name}. PC par kaha save karna hai? "
        f"Paths batao jaise Downloads ya D:\\backup.",
        f"فائل مل گئی: {name}۔ اس پی سی پر کہاں محفوظ کروں؟ راستہ بتائیں جیسے Downloads یا D:\\backup۔")
    return {
        "ok": True,
        "id": file_id,
        "name": name,
        "size": size,
        "status": "need_destination",
        "message": "File staged on this PC only. It has NOT been saved to a final location yet.",
    }, 200


# ---------------------------------------------------------------------------
# Pure helpers used by the HTTP handler (also easy to test offline)
# ---------------------------------------------------------------------------
def status_info() -> dict:
    with _SERVER_LOCK:
        running = _SERVER is not None
    return {
        "ok": True,
        "service": "jarvis-device-link",
        "running": running,
        "port": _port(0),
        "ip": lan_ip(),
        "paired": bool(_load_state().get("token")),
        "pending_count": len(list_pending()),
        "staging_dir": incoming_dir(),
    }


def run_command(text="") -> dict:
    """Route phone text through command_hook, returning the captured spoken reply."""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "reply": "I did not receive a command. No action was taken."}
    return {"ok": True, "text": text, "reply": phone_line._run_command(text)}


def _authorized(headers, body=None) -> bool:
    token = str(headers.get(TOKEN_HEADER, "") or "")
    if not token and isinstance(body, dict):
        token = str(body.get("token") or "")
    return token_ok(token)


# ---------------------------------------------------------------------------
# stdlib HTTP server
# ---------------------------------------------------------------------------
class DeviceLinkHandler(http.server.BaseHTTPRequestHandler):
    server_version = "JarvisDeviceLink/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        core.log("device link HTTP: " + (fmt % args))

    def _send_json(self, data: dict, code: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 1024 * 1024)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        self._route(False)

    def do_POST(self):
        self._route(True)

    def _route(self, is_post: bool) -> None:
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in urllib.parse.parse_qs(
            parts.query, keep_blank_values=True).items()}

        if path == "/link/status":
            self._send_json(status_info())
            return

        if path == "/link/pending":
            items = list_pending()
            self._send_json({"ok": True, "pending": items, "count": len(items)})
            return

        if path == "/link/pair":
            body = self._read_json() if is_post else {}
            code = str(body.get("code") or query.get("code") or "")
            result = pair_with_code(code)
            self._send_json(result, 200 if result.get("ok") else 401)
            return

        if path == "/link/upload":
            if not is_post:
                self._send_json({"ok": False, "message": "Upload requires POST."}, 405)
            elif not token_ok(self.headers.get(TOKEN_HEADER, "")):
                self._send_json({"ok": False, "message": "Missing or invalid X-Jarvis-Token. Pair first."}, 401)
            else:
                result, code = upload_from_request(self.rfile, self.headers)
                self._send_json(result, code)
            return

        if path in ("/link/save", "/link/command", "/link/call"):
            if not is_post:
                self._send_json({"ok": False, "message": "This endpoint requires POST."}, 405)
                return
            body = self._read_json()
            if not _authorized(self.headers, body):
                self._send_json({"ok": False, "message": "Missing or invalid X-Jarvis-Token. Pair first."}, 401)
                return
            if path == "/link/save":
                file_id = str(body.get("id", "") or body.get("file_id", "") or "")
                destination = str(body.get("destination", "") or "")
                confirmed = any(bool(body.get(k, False)) for k in
                                ("confirmed", "confirm", "overwrite"))
                rp = _record_path(file_id)
                rec = {}
                if rp and os.path.isfile(rp):
                    rec = core.read_json(rp, {}) or {}
                if destination and confirmed and rec.get("status") == "need_destination":
                    # Keep the real path for a later explicit "confirm save".
                    rec["requested_destination"] = destination
                    core.write_json(rp, rec)
                if not destination:
                    destination = str(rec.get("requested_destination") or "")
                result = save_file(file_id, destination, confirmed=confirmed)
                self._send_json(result, 200)
                return
            result = run_command(body.get("text", ""))
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        self._send_json({"ok": False, "message": "Unknown Device Link endpoint."}, 404)


def _serve(server) -> None:
    try:
        server.serve_forever(poll_interval=0.25)
    except Exception as exc:
        core.log(f"device link server stopped unexpectedly: {exc}")


def start_server(host="", port=8766) -> str:
    """Start the LAN listener in a daemon thread (non-blocking)."""
    global _SERVER
    bind_host = str(host or DEFAULT_HOST).strip() or DEFAULT_HOST
    actual_port = _port(port)
    with _SERVER_LOCK:
        if _SERVER is not None:
            return f"Device Link is already running on {_SERVER.server_address}."
        try:
            server = http.server.ThreadingHTTPServer((bind_host, actual_port), DeviceLinkHandler)
        except Exception as exc:
            return (f"Could not start Device Link on {bind_host}:{actual_port}: " +
                    core.truncate(str(exc), 240))
        _SERVER = server
    threading.Thread(target=_serve, args=(server,), name="jarvis-device-link", daemon=True).start()
    ip = lan_ip()
    return (f"Device Link started on http://{ip}:{server.server_address[1]} "
            f"(bound to {bind_host}:{server.server_address[1]}). On the phone enter that IP, "
            "the port and the code from 'device link code'. Local network only.")


def stop_server() -> str:
    global _SERVER
    with _SERVER_LOCK:
        server = _SERVER
        if server is None:
            return "Device Link is not running."
        try:
            server.shutdown()
            server.server_close()
        except Exception as exc:
            return "Could not stop Device Link cleanly: " + core.truncate(str(exc), 240)
        _SERVER = None
    return "Device Link stopped."


# ---------------------------------------------------------------------------
# Tool entry points (voice-friendly, honest strings)
# ---------------------------------------------------------------------------
def device_link_operation(action="status", host="", port=8766, code="", file_id="",
                          destination="", confirmed=False) -> str:
    """Run the local phone-to-PC Device Link.

    actions: status, start, stop, code, pending, save.
    'code' gives the 10-minute pairing code plus the LAN IP/port for the phone.
    'save' uses the newest pending file when file_id is omitted; it asks for
    confirmation before overwriting an existing target.
    """
    a = str(action or "status").strip().lower()
    if a in ("show", "info"):
        a = "status"
    if a in ("begin", "serve", "listen"):
        a = "start"
    if a in ("pair_code", "pairing", "pair"):
        a = "code"
    if a == "files":
        a = "pending"

    if a == "status":
        s = status_info()
        return (f"Device Link: {'running' if s['running'] else 'stopped'}; LAN IP {s['ip']}; "
                f"port {s['port']}; paired={'yes' if s['paired'] else 'no'}; "
                f"pending files: {s['pending_count']}. See docs/PC_LINK.md for phone steps.")
    if a == "start":
        return start_server(host=host, port=port)
    if a == "stop":
        return stop_server()
    if a == "code":
        fresh = new_pairing_code()
        s = status_info()
        return (f"Pairing code {fresh} is valid for 10 minutes. On the phone use IP {s['ip']}, "
                f"port {s['port']} and this code. Run 'device link start' first if the link is stopped.")
    if a == "pending":
        items = list_pending()
        if not items:
            return "No pending file from the phone. Send a file from the paired phone first."
        lines = [f"{r.get('id')}: {r.get('name')} ({r.get('size')} bytes)" for r in items[:10]]
        return "Pending phone files:\n" + "\n".join(lines)
    if a == "save":
        target_id = str(file_id or "").strip()
        if not target_id:
            items = list_pending()
            target_id = str(items[0].get("id") or "") if items else ""
        if not target_id:
            return "There is no pending file from the phone, so nothing was saved."
        result = save_file(target_id, destination, confirmed=confirmed)
        if result.get("ok"):
            return f"Saved {result['size']} bytes to {result['path']}."
        return str(result.get("message") or "Save failed. Nothing was saved.")
    if a in ("confirm", "confirm_save", "yes", "haan"):
        items = list_pending()
        target_id = str(file_id or "").strip()
        record = None
        if target_id:
            rp = _record_path(target_id)
            record = core.read_json(rp, {}) if rp else {}
        elif items:
            record = items[0]
            target_id = str(record.get("id") or "")
        if not target_id or not record:
            return "There is no pending file from the phone, so nothing was confirmed."
        dest = str(destination or "").strip() or str(record.get("requested_destination") or "")
        if not dest:
            return ("No destination was asked for yet, so nothing was overwritten. "
                    "Tell Jarvis where to save the file first.")
        result = save_file(target_id, dest, confirmed=True)
        if result.get("ok"):
            return f"Saved {result['size']} bytes to {result['path']}."
        return str(result.get("message") or "Save failed. Nothing was saved.")
    return (f"Unknown device link action '{action}'. "
            "Use status, start, stop, code, pending, save or confirm.")


def device_link_start(host="", port=8766) -> str:
    """Start the Device Link LAN listener on port 8766 by default."""
    return device_link_operation("start", host=host, port=port)


def device_link_stop() -> str:
    """Stop the Device Link LAN listener."""
    return device_link_operation("stop")


def device_link_code() -> str:
    """Show a fresh one-time pairing code with the phone's IP/port."""
    return device_link_operation("code")


def device_link_pending() -> str:
    """List files a paired phone sent that still need a destination."""
    return device_link_operation("pending")


def device_link_save(file_id="", destination="", confirmed=False) -> str:
    """Save a pending phone upload to a real path after explicit confirmation."""
    return device_link_operation("save", file_id=file_id, destination=destination,
                                 confirmed=confirmed)


def device_link_confirm(file_id="", destination="") -> str:
    """Confirm the previously requested overwrite after an explicit 'haan'."""
    return device_link_operation("confirm", file_id=file_id, destination=destination)
