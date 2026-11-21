from __future__ import annotations

import html
import json
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import jarvis_core
from jarvis_core import core, phone_line, tools


class _FakeResponse:
    """Minimal urlopen context manager for fully offline Twilio mocks."""

    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def read(self):
        return self.body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PhoneLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-phone-line-")
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
        self.old_server = phone_line._SERVER
        core._SAFETY["safe_mode"] = True
        core.save_config({"safe_mode": True})
        phone_line._SERVER = None
        self.sid = "TEST_ACCOUNT_SID_NOT_REAL"
        self.token = "test-token-not-a-real-secret"
        self.result = phone_line.phone_line_operation(
            "configure", account_sid=self.sid, auth_token=self.token,
            from_number="+15550001111", to_number="+15550002222", enabled=True)
        self.assertIn("configured=yes", self.result)

    def tearDown(self):
        for (obj, name), value in self.old.items():
            setattr(obj, name, value)
        core._SAFETY["safe_mode"] = self.old_safe_mode
        phone_line._SERVER = self.old_server
        self.tmp_obj.cleanup()

    def test_no_call_without_confirmation(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            result = phone_line.phone_line_call("+15550002222", "hello sir")
        self.assertIn("CONFIRMATION REQUIRED", result)
        urlopen.assert_not_called()

    def test_confirmed_call_returns_real_twilio_sid(self):
        payload = json.dumps({"sid": "CA00000000000000000000000000000001",
                              "status": "queued"}).encode("utf-8")
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(payload, 201)) as urlopen:
            result = phone_line.phone_line_call("+15550002222", "hello sir", confirmed=True)
        self.assertIn("CA00000000000000000000000000000001", result)
        self.assertIn("queued", result)
        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, phone_line.TWILIO_BASE + self.sid + "/Calls.json")
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        body = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(body["To"], ["+15550002222"])
        self.assertEqual(body["From"], ["+15550001111"])
        self.assertIn("<Say", body["Twiml"][0])

    def test_recording_twiml_has_consent_before_record(self):
        twiml = phone_line.voice_record_twiml({}, {})
        self.assertIn(phone_line.CONSENT_LINE, twiml)
        self.assertIn("<Record", twiml)
        self.assertLess(twiml.index(phone_line.CONSENT_LINE), twiml.index("<Record"))
        self.assertIn('voice="man"', twiml)
        self.assertIn('action="/voice/record?', twiml)

    def test_command_speech_is_routed_and_spoken_text_captured(self):
        original_say_lang = core.say_lang

        def hook(text, g=None):
            self.assertEqual(text, "what time is it")
            core.say_lang("The captured spoken reply", "Waqt jawab", "وقت جواب")
            return True

        with mock.patch.object(jarvis_core, "command_hook", side_effect=hook) as routed:
            twiml = phone_line.voice_command_twiml(
                {"SpeechResult": "what time is it", "CallSid": "CA1"}, {})
        self.assertIs(core.say_lang, original_say_lang)
        routed.assert_called_once()
        self.assertIn("The captured spoken reply", twiml)
        self.assertIn('<Gather input="speech" action="/voice/command"',
                      phone_line.voice_inbound_twiml())

    def test_recording_callback_logs_honest_transcript_unavailable(self):
        audio = b"RIFF-fake-twilio-audio"
        recording_url = (phone_line.TWILIO_BASE + self.sid +
                         "/Recordings/RE00000000000000000000000000000001")
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(audio, 200)) as urlopen:
            twiml = phone_line.voice_record_twiml({
                "RecordingUrl": recording_url,
                "CallSid": "CA00000000000000000000000000000002",
                "From": "+15550002222",
            }, {})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, recording_url)
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        log = Path(phone_line._transcript_log())
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["speech_result"], "transcript unavailable")
        self.assertEqual(rows[0]["from"], "+15550002222")
        self.assertEqual(rows[0]["sid"], "CA00000000000000000000000000000002")
        self.assertTrue(Path(rows[0]["recording"]).is_file())
        self.assertEqual(Path(rows[0]["recording"]).read_bytes(), audio)
        self.assertIn("No automatic transcript", twiml)
        self.assertNotIn("transcript: ", twiml)

    def test_config_secret_round_trip_and_no_token_in_status(self):
        raw = core.read_json(core.CONFIG_FILE, {})["phone_line"]
        self.assertNotEqual(raw["auth_token"], self.token)
        self.assertEqual(core.unprotect_secret(raw["auth_token"]), self.token)
        status = phone_line.phone_line_operation("status")
        self.assertNotIn(self.token, status)
        self.assertIn("configured=yes", status)
        self.assertIn("docs/PHONE_LINE.md", status)

    def test_voice_confirmation_gate_places_no_call_until_confirmed(self):
        def hook(text, g=None):
            confirmed = text.lower().endswith("confirm")
            core.say_lang(phone_line.phone_line_call("+15550002222", "ping", confirmed=confirmed),
                          "reply", "جواب")
            return True

        accepted = json.dumps({"sid": "CA00000000000000000000000000000003",
                               "status": "queued"}).encode("utf-8")
        with mock.patch.object(jarvis_core, "command_hook", side_effect=hook), \
                mock.patch("urllib.request.urlopen",
                           return_value=_FakeResponse(accepted, 201)) as urlopen:
            first = phone_line.voice_command_twiml(
                {"SpeechResult": "call me ping", "CallSid": "CA1"}, {})
            self.assertIn("CONFIRMATION REQUIRED", first)
            self.assertIn("confirm=1", first)
            urlopen.assert_not_called()
            action = html.unescape(re.search(r'action="([^"]+)"', first).group(1))
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(action).query)
            second = phone_line.voice_command_twiml(
                {"SpeechResult": "confirm", "CallSid": "CA1"}, query)
        self.assertIn("CA00000000000000000000000000000003", second)
        self.assertEqual(urlopen.call_count, 1)

    def test_new_tools_are_registered(self):
        names = {getattr(fn, "__name__", "") for fn in tools.TOOL_FUNCTIONS}
        self.assertTrue({"phone_line_operation", "phone_line_call", "phone_line_webhook"}
                        .issubset(names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
