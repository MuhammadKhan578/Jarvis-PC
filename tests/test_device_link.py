"""Offline tests for the real local-network Device Link (no sockets are bound)."""
from __future__ import annotations

import email.message
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jarvis_core
from jarvis_core import core, device_link, tools

BOUNDARY = "----jarvis-device-link-test-boundary"
FILE_BYTES = b"REAL FILE BYTES FROM PHONE\x00\x01\x02"


def _multipart(filename: str, content: bytes) -> bytes:
    head = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{BOUNDARY}--\r\n".encode("utf-8")
    return head + content + tail


class DeviceLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-device-link-")
        self.tmp = Path(self.tmp_obj.name)
        self.old = {}
        for obj, name, value in (
            (core, "CONFIG_FILE", str(self.tmp / "config.json")),
            (core, "DATA_DIR", str(self.tmp / "data")),
            (core, "AUDIT_FILE", str(self.tmp / "audit.jsonl")),
        ):
            self.old[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        self.old_safe_mode = core._SAFETY.get("safe_mode", True)
        self.old_server = device_link._SERVER
        core._SAFETY["safe_mode"] = True
        device_link._SERVER = None

        say_patcher = mock.patch.object(core, "say_lang")
        ip_patcher = mock.patch.object(device_link, "lan_ip", return_value="192.168.1.20")
        self.say = say_patcher.start()
        self.ip = ip_patcher.start()
        self.addCleanup(say_patcher.stop)
        self.addCleanup(ip_patcher.stop)

    def tearDown(self):
        for (obj, name), value in self.old.items():
            setattr(obj, name, value)
        core._SAFETY["safe_mode"] = self.old_safe_mode
        device_link._SERVER = self.old_server
        self.tmp_obj.cleanup()

    # -- helpers ---------------------------------------------------------
    def _request(self, path, method="POST", body=b"", headers=None):
        handler = device_link.DeviceLinkHandler.__new__(device_link.DeviceLinkHandler)
        handler.path = path
        hdrs = email.message.Message()
        for key, value in (headers or {}).items():
            hdrs[key] = str(value)
        handler.headers = hdrs
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        payload = handler.wfile.getvalue().decode("utf-8", "replace")
        return json.loads(payload), handler

    def _pair(self) -> str:
        code = device_link.new_pairing_code()
        result = device_link.pair_with_code(code)
        self.assertTrue(result["ok"], result)
        return result["token"]

    def _upload(self, token: str, filename="photo.bin", content=FILE_BYTES):
        body = _multipart(filename, content)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
            "Content-Length": str(len(body)),
            "X-Jarvis-Token": token,
        }
        return self._request("/link/upload", body=body, headers=headers)

    def _uploaded_id(self) -> str:
        token = self._pair()
        result, _ = self._upload(token)
        self.assertTrue(result["ok"], result)
        return result["id"]

    # -- pairing ---------------------------------------------------------
    def test_pairing_rejects_wrong_code_and_limits_attempts(self):
        code = device_link.new_pairing_code()
        self.assertRegex(code, r"^\d{6}$")
        wrong = "000000" if code != "000000" else "111111"
        first = device_link.pair_with_code(wrong)
        self.assertFalse(first["ok"])
        self.assertIn("Wrong pairing code", first["message"])
        self.assertNotIn("token", first)

        for _ in range(device_link.MAX_PAIR_ATTEMPTS - 1):
            failed = device_link.pair_with_code(wrong)
            self.assertFalse(failed["ok"])
        limited = device_link.pair_with_code(code)
        self.assertFalse(limited["ok"])
        self.assertIn("Too many wrong", limited["message"])

    def test_valid_pair_returns_token_once_and_stores_it_protected(self):
        code = device_link.new_pairing_code()
        state = core.read_json(device_link.state_path(), {})
        self.assertEqual(state["pair_code"], code)
        result = device_link.pair_with_code(code)
        self.assertTrue(result["ok"])
        self.assertRegex(result["token"], r"^[\w-]{20,}$")
        stored = core.read_json(device_link.state_path(), {})
        self.assertNotEqual(stored["token"], result["token"])
        self.assertEqual(core.unprotect_secret(stored["token"]), result["token"])
        self.assertTrue(device_link.token_ok(result["token"]))
        self.assertFalse(device_link.token_ok("not-the-token"))
        replay = device_link.pair_with_code(code)
        self.assertFalse(replay["ok"])               # strictly one-time

    def test_upload_with_metadata_field_first_keeps_real_file_bytes(self):
        """Regression: a text field before the file must not become the upload."""
        boundary = "----jarvis-device-link-metadata-first"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="filename"\r\n\r\n'
            "report.txt\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="real.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8") + FILE_BYTES + f"\r\n--{boundary}--\r\n".encode("utf-8")
        token = self._pair()
        result, _ = self._request("/link/upload", body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "X-Jarvis-Token": token,
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["name"], "real.zip")
        self.assertEqual(result["size"], len(FILE_BYTES))
        rec = device_link.list_pending()[0]
        with open(rec["staged_path"], "rb") as handle:
            self.assertEqual(handle.read(), FILE_BYTES)

    def test_upload_requires_token(self):
        result, handler = self._upload("")
        self.assertFalse(result["ok"])
        self.assertIn("X-Jarvis-Token", result["message"])
        handler.send_response.assert_called_once_with(401)
        self.assertEqual(device_link.list_pending(), [])

    # -- upload vs final save --------------------------------------------
    def test_upload_stages_pending_and_asks_destination_without_saving(self):
        token = self._pair()
        result, handler = self._upload(token, filename="report.txt")
        handler.send_response.assert_called_once_with(200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "need_destination")
        self.assertIn("NOT been saved", result["message"])
        self.assertNotIn("path", result)

        pending = device_link.list_pending()
        self.assertEqual(len(pending), 1)
        rec = pending[0]
        self.assertEqual(rec["id"], result["id"])
        self.assertEqual(rec["name"], "report.txt")
        self.assertEqual(rec["size"], len(FILE_BYTES))
        staged = Path(rec["staged_path"])
        self.assertEqual(staged.parent, Path(device_link.incoming_dir()))
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), FILE_BYTES)

        self.say.assert_called_once()
        en, roman, _urdu = self.say.call_args[0]
        self.assertIn("report.txt", en)
        self.assertIn("D:\\backup", en)
        self.assertIn("report.txt", roman)
        self.assertIn("kaha save karna hai", roman)
        self.assertFalse((self.tmp / "report.txt").exists())

    def test_save_asks_confirmation_when_target_exists(self):
        file_id = self._uploaded_id()
        target = self.tmp / "existing.txt"
        target.write_bytes(b"OLD CONTENT - MUST NOT CHANGE")
        result = device_link.save_file(file_id, str(target), confirmed=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["confirmation_required"])
        self.assertIn("CONFIRMATION REQUIRED", result["message"])
        self.assertEqual(target.read_bytes(), b"OLD CONTENT - MUST NOT CHANGE")
        self.assertEqual(len(device_link.list_pending()), 1)
        record = core.read_json(device_link._record_path(file_id), {})
        self.assertEqual(record["status"], "need_destination")
        self.assertEqual(record["requested_destination"], str(target))
        self.assertTrue(Path(record["staged_path"]).is_file())

    def test_confirmed_save_writes_real_bytes_and_clears_pending(self):
        file_id = self._uploaded_id()
        target = self.tmp / "newdir" / "photo.bin"
        result = device_link.save_file(file_id, str(target), confirmed=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["size"], len(FILE_BYTES))
        self.assertEqual(Path(result["path"]).read_bytes(), FILE_BYTES)
        self.assertEqual(result["path"], str(target))
        self.assertEqual(device_link.list_pending(), [])

        record = core.read_json(device_link._record_path(file_id), {})
        self.assertEqual(record["status"], "saved")
        self.assertEqual(record["final_path"], str(target))
        self.assertFalse(Path(record["staged_path"]).exists())
        self.assertIn(str(target), self.say.call_args[0][0])

        replay = device_link.save_file(file_id, str(target), confirmed=True)
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["status"], "saved")

    def test_save_endpoint_honours_confirmation_flag(self):
        token = self._pair()
        upload, _ = self._upload(token, filename="conflict.txt")
        self.assertTrue(upload["ok"])
        target = self.tmp / "conflict.txt"
        target.write_bytes(b"ORIGINAL")
        body = json.dumps({"id": upload["id"], "destination": str(target),
                           "confirmed": False}).encode("utf-8")
        first, _ = self._request("/link/save", body=body, headers={
            "Content-Type": "application/json", "Content-Length": str(len(body)),
            "X-Jarvis-Token": token})
        self.assertFalse(first["ok"])
        self.assertIn("CONFIRMATION REQUIRED", first["message"])
        self.assertEqual(target.read_bytes(), b"ORIGINAL")

        body = json.dumps({"id": upload["id"], "destination": str(target),
                           "confirmed": True}).encode("utf-8")
        second, _ = self._request("/link/save", body=body, headers={
            "Content-Type": "application/json", "Content-Length": str(len(body)),
            "X-Jarvis-Token": token})
        self.assertTrue(second["ok"])
        self.assertEqual(target.read_bytes(), FILE_BYTES)

    def test_save_endpoint_accepts_mobile_file_id_and_confirm_alias(self):
        """The Android client sends file_id; it must reach the real save code."""
        token = self._pair()
        upload, _ = self._upload(token, filename="mobile.zip")
        target = self.tmp / "mobile.zip"
        target.write_bytes(b"DO NOT OVERWRITE")
        headers = {"Content-Type": "application/json",
                   "Content-Length": "0", "X-Jarvis-Token": token}

        gate_body = json.dumps({"file_id": upload["id"], "destination": str(target)}).encode()
        headers["Content-Length"] = str(len(gate_body))
        gate, _ = self._request("/link/save", body=gate_body, headers=headers)
        self.assertFalse(gate["ok"])
        self.assertTrue(gate["confirmation_required"])
        self.assertEqual(target.read_bytes(), b"DO NOT OVERWRITE")

        # Explicit confirmation with no destination reuses the asked-for path.
        confirm_body = json.dumps({"file_id": upload["id"], "confirm": True}).encode()
        headers["Content-Length"] = str(len(confirm_body))
        done, _ = self._request("/link/save", body=confirm_body, headers=headers)
        self.assertTrue(done["ok"], done)
        self.assertEqual(target.read_bytes(), FILE_BYTES)

    # -- command channel --------------------------------------------------
    def test_command_endpoint_routes_text_and_returns_captured_reply(self):
        token = self._pair()
        seen = []

        def hook(text, g=None):
            seen.append(text)
            core.say_lang("PC Jarvis reply: it is five o clock", "Waqt paanch baje", "وقت پانچ بجے")
            return True

        body = json.dumps({"text": "what time is it"}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body)),
                   "X-Jarvis-Token": token}
        with mock.patch.object(jarvis_core, "command_hook", side_effect=hook) as routed:
            result, handler = self._request("/link/command", body=body, headers=headers)
            alias, _ = self._request("/link/call", body=body, headers=headers)
        self.assertEqual(routed.call_count, 2)
        self.assertEqual(seen, ["what time is it", "what time is it"])
        self.assertTrue(result["ok"])
        self.assertIn("PC Jarvis reply", result["reply"])
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(alias["reply"], result["reply"])  # /link/call is an alias

    # -- honest status and registration ----------------------------------
    def test_status_and_pending_are_honest(self):
        status = device_link.status_info()
        self.assertFalse(status["running"])
        self.assertEqual(status["port"], 8766)
        self.assertEqual(status["ip"], "192.168.1.20")
        self.assertFalse(status["paired"])
        self.assertEqual(status["pending_count"], 0)

        response, _ = self._request("/link/status", method="GET")
        self.assertEqual(response, status)
        pending, _ = self._request("/link/pending", method="GET")
        self.assertEqual(pending["ok"], True)
        self.assertEqual(pending["count"], 0)
        self.assertEqual(pending["pending"], [])

        token = self._pair()
        uploaded, _ = self._upload(token, filename="a.txt")
        self.assertTrue(uploaded["ok"])
        now = device_link.status_info()
        self.assertTrue(now["paired"])
        self.assertEqual(now["pending_count"], 1)
        listed, _ = self._request("/link/pending", method="GET")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["pending"][0]["name"], "a.txt")

    def test_tools_and_voice_helpers_are_registered(self):
        names = {getattr(fn, "__name__", "") for fn in tools.TOOL_FUNCTIONS}
        self.assertTrue({
            "device_link_operation", "device_link_start", "device_link_stop",
            "device_link_code", "device_link_pending", "device_link_save",
        }.issubset(names))
        self.assertIn("8766", device_link.device_link_code())
        self.assertIn("192.168.1.20", device_link.device_link_code())
        self.assertIn("not running", device_link.device_link_stop().lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
