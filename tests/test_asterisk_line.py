"""Offline tests for the free local Asterisk line.

No real sockets, no pyttsx3 voice engine, no Google/network calls: AMI, FastAGI
streams, TTS and STT are all mocked at their boundaries.
"""
from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import jarvis_core
from jarvis_core import asterisk_line, core, phone_line, tools

AMI_OK = [
    b"Asterisk Call Manager/2.1.0\r\n\r\n",
    b"Response: Success\r\nMessage: Authentication accepted\r\n\r\n",
    b"Response: Success\r\nMessage: Originate successfully queued\r\n\r\n",
]


class _FakeAmiSocket:
    """socket.create_connection() stand-in with scripted AMI blocks."""

    def __init__(self, blocks):
        self.stream = io.BytesIO(b"".join(blocks))
        self.sent: list[str] = []
        self.timeouts: list[float] = []

    def makefile(self, mode="rb", *args, **kwargs):
        return self.stream

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, data):
        self.sent.append(data.decode("utf-8", "replace"))

    def close(self):
        pass


class _FakeAgiStream:
    """Duplex binary file-like object used as both FastAGI rfile and wfile."""

    def __init__(self, env_lines=(), responses=()):
        self.incoming = list(env_lines) + [""]
        self.responses = list(responses)
        self.pending: list[str] = []
        self.written: list[str] = []

    def write(self, data):
        text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
        command = text.rstrip("\r\n")
        self.written.append(command)
        reply = self.responses.pop(0) if self.responses else []
        if callable(reply):
            reply = reply(command)
        self.pending.extend(list(reply) + [""])
        return len(data)

    def flush(self):
        pass

    def readline(self):
        if self.pending:
            return (self.pending.pop(0) + "\n").encode("utf-8")
        if self.incoming:
            return (self.incoming.pop(0) + "\n").encode("utf-8")
        return b""


class AsteriskLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-asterisk-line-")
        self.tmp = Path(self.tmp_obj.name)
        self.old = {}
        for obj, name, value in (
            (core, "CONFIG_FILE", str(self.tmp / "config.json")),
            (core, "DATA_DIR", str(self.tmp / "data")),
            (core, "AUDIT_FILE", str(self.tmp / "audit.jsonl")),
        ):
            self.old[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        self.old_server = asterisk_line._SERVER
        asterisk_line._SERVER = None
        self.secret = "test-secret-not-real"

    def tearDown(self):
        for (obj, name), value in self.old.items():
            setattr(obj, name, value)
        asterisk_line._SERVER = self.old_server
        self.tmp_obj.cleanup()

    def _configure(self, extension="1001"):
        return asterisk_line.asterisk_configure(
            host="127.0.0.1", username="jarvis", secret=self.secret,
            outbound_extension=extension)

    def _record_response(self, command):
        match = re.match(r'^RECORD FILE\s+(?:"([^"]+)"|(\S+))', command)
        self.assertIsNotNone(match, command)
        path = match.group(1) or match.group(2)
        local = asterisk_line._windows_path(path)
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(b"RIFF" + b"\0" * 60)
        self.record_path = local
        return ["200 result=1500"]

    def _run_agi(self, recognized="what time is it", stt_error=False,
                 no_recording=False, tts_error=False):
        def record(command):
            if no_recording:
                return ["200 result=-1"]
            return self._record_response(command)

        responses = [
            ["200 result=0"], ["200 result=0"], ["200 result=0"],
            record, ["200 result=0"], ["200 result=0"],
        ]
        stream = _FakeAgiStream(
            ["agi_request: agi://127.0.0.1/jarvis",
             "agi_channel: SIP/1001-00000001",
             "agi_callerid: 1001"], responses)
        engine = mock.MagicMock()
        engine.getProperty.return_value = []

        def save_to_file(text, path):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RIFF" + b"\0" * 60)

        engine.save_to_file.side_effect = save_to_file
        tts = (mock.patch.object(asterisk_line, "_tts_to_wav",
                                 side_effect=RuntimeError("no local TTS"))
               if tts_error else mock.patch("pyttsx3.init", return_value=engine))
        with tts, mock.patch("speech_recognition.AudioFile") as audio_file, \
                mock.patch("speech_recognition.Recognizer") as recognizer_cls, \
                mock.patch.object(phone_line, "_run_command",
                                  return_value="The current time is 10:10") as run:
            recognizer = recognizer_cls.return_value
            if stt_error:
                recognizer.recognize_google.side_effect = RuntimeError("Web Speech offline")
            else:
                recognizer.recognize_google.return_value = recognized
            status = asterisk_line._agi_session(stream, stream, ("127.0.0.1", 50000))
            if not no_recording:
                self.assertEqual(audio_file.call_count, 1)
        return {
            "status": status,
            "written": stream.written,
            "engine": engine,
            "recognizer": recognizer,
            "audio_file": audio_file,
            "run": run,
        }

    def _transcript(self):
        path = Path(asterisk_line._transcript_log())
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    # -- configuration ----------------------------------------------------
    def test_configure_stores_protected_secret_and_honest_summary(self):
        result = self._configure()
        self.assertIn("secret: set (protected", result)
        self.assertNotIn(self.secret, result)
        raw = core.config_get("asterisk_line", {})
        self.assertNotEqual(raw["secret"], self.secret)
        self.assertEqual(core.unprotect_secret(raw["secret"]), self.secret)
        self.assertEqual(raw["host"], "127.0.0.1")
        self.assertIn("NOT Twilio", result)
        self.assertIn("NOT a PSTN/SIM number", result)
        self.assertIn("No Asterisk settings were supplied",
                      asterisk_line.asterisk_configure())

    # -- AMI --------------------------------------------------------------
    def test_call_requires_explicit_confirmation_before_any_socket(self):
        with mock.patch("socket.create_connection") as connect:
            result = asterisk_line.asterisk_call("1001")
            result2 = asterisk_line.asterisk_operation("call", target="1001")
        self.assertIn("CONFIRMATION REQUIRED", result)
        self.assertIn("CONFIRMATION REQUIRED", result2)
        connect.assert_not_called()

    def test_confirmed_call_sends_real_ami_originate_and_reports_success(self):
        self._configure()
        fake = _FakeAmiSocket(AMI_OK)
        with mock.patch("socket.create_connection", return_value=fake) as connect:
            result = asterisk_line.asterisk_call("living room", confirmed=True)
        connect.assert_called_once_with(("127.0.0.1", 5038),
                                        timeout=asterisk_line.AMI_TIMEOUT)
        payload = "\n".join(fake.sent)
        for line in ("Action: Login", f"Username: jarvis", f"Secret: {self.secret}",
                     "Action: Originate", "Channel: Local/1001@jarvis-out",
                     "Context: jarvis-in", "Exten: 1002", "Priority: 1",
                     "Async: true", "CallerID: Jarvis <1002>", "Timeout: 30000",
                     "Variable: JARVIS_TARGET=living room"):
            self.assertIn(line, payload)
        self.assertIn("Response: Success", result)
        self.assertIn("AMI accepted the Originate", result)
        self.assertIn("Originate successfully queued", result)
        self.assertNotIn("Response: Error", result)
        self.assertIn("No PSTN/SIM number was dialed", result)

    def test_ami_rejection_is_never_reported_as_a_successful_call(self):
        self._configure()
        fake = _FakeAmiSocket([
            b"Asterisk Call Manager/2.1.0\r\n\r\n",
            b"Response: Error\r\nMessage: Authentication failed\r\n\r\n",
        ])
        with mock.patch("socket.create_connection", return_value=fake):
            result = asterisk_line.asterisk_call("1001", confirmed=True)
        self.assertIn("did not succeed", result)
        self.assertIn("Authentication failed", result)
        self.assertIn("No call is claimed", result)
        self.assertNotIn("Response: Success", result)

    def test_call_me_rings_configured_extension_without_target_variable(self):
        self._configure(extension="2001")
        fake = _FakeAmiSocket(AMI_OK)
        with mock.patch("socket.create_connection", return_value=fake):
            result = asterisk_line.asterisk_call_me(confirmed=True)
        payload = "\n".join(fake.sent)
        self.assertIn("Channel: Local/2001@jarvis-out", payload)
        self.assertNotIn("Variable:", payload)
        self.assertIn("2001", result)
        self.assertIn("Response: Success", result)

    # -- FastAGI ----------------------------------------------------------
    def test_agi_full_call_streams_records_transcribes_routes_and_logs(self):
        result = self._run_agi()
        written = result["written"]
        self.assertEqual(written[0], "ANSWER")
        self.assertIn('STREAM FILE jarvis/consent ""', written)
        self.assertIn('STREAM FILE jarvis/prompt ""', written)
        record = next(line for line in written if line.startswith("RECORD FILE "))
        expected = asterisk_line._recording_target(asterisk_line._load_cfg(),
                                                   self.record_path)
        self.assertEqual(record, f"RECORD FILE {expected} wav 15000 0 BEEP 2")
        self.assertIn(asterisk_line._wsl_path(self.record_path), record)
        # STT receives the ORIGINAL Windows path, not the /mnt/c path.
        result["audio_file"].assert_called_once_with(self.record_path)
        recognizer = result["recognizer"]
        recognizer.recognize_google.assert_called_once()
        self.assertEqual(recognizer.recognize_google.call_args.kwargs["language"], "en-US")
        result["run"].assert_called_once_with("what time is it")
        self.assertTrue(any(re.fullmatch(r'STREAM FILE jarvis/reply_\S+ ""', line)
                            for line in written))
        self.assertEqual(written[-1], "HANGUP")
        self.assertEqual(result["status"], "ok")
        rows = self._transcript()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["callerid"], "1001")
        self.assertEqual(rows[0]["recognized_text"], "what time is it")
        self.assertEqual(rows[0]["reply"], "The current time is 10:10")
        self.assertEqual(rows[0]["audio_path"], self.record_path)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(result["engine"].save_to_file.call_count, 3)

    def test_agi_stt_failure_and_missing_recording_run_no_command(self):
        failed = self._run_agi(stt_error=True)
        self.assertEqual(failed["status"], "stt_failed")
        failed["run"].assert_not_called()
        # The caller still HEARS the honest fallback, then the call ends.
        self.assertTrue(any(re.fullmatch(r'STREAM FILE jarvis/reply_\S+ ""', line)
                            for line in failed["written"]))
        self.assertIn("HANGUP", failed["written"])
        spoken = [call.args[0] for call in failed["engine"].save_to_file.call_args_list]
        self.assertIn(asterisk_line.FALLBACK_LINE, spoken)
        row = self._transcript()[0]
        self.assertEqual(row["recognized_text"], "")
        self.assertEqual(row["reply"], asterisk_line.FALLBACK_LINE)
        self.assertEqual(row["status"], "stt_failed")

        empty = self._run_agi(no_recording=True)
        self.assertEqual(empty["status"], "no_recording")
        empty["recognizer"].recognize_google.assert_not_called()
        empty["run"].assert_not_called()
        self.assertEqual(self._transcript()[1]["status"], "no_recording")

    def test_tts_failure_streams_real_beep_and_continues(self):
        result = self._run_agi(tts_error=True)
        self.assertIn('STREAM FILE beep ""', result["written"])
        result["run"].assert_called_once_with("what time is it")
        self.assertEqual(result["written"][-1], "HANGUP")

    def test_tts_only_selects_male_voices(self):
        def render(voices, filename):
            engine = mock.MagicMock()
            engine.getProperty.return_value = voices

            def save(text, path):
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"RIFF" + b"\0" * 60)

            engine.save_to_file.side_effect = save
            with mock.patch("pyttsx3.init", return_value=engine):
                asterisk_line._tts_to_wav("hello", filename, male=True)
            return engine

        female = SimpleNamespace(name="Microsoft Zira", id="zira-id")
        male = SimpleNamespace(name="Microsoft David", id="david-id")
        engine = render([female, male], "male.wav")
        engine.setProperty.assert_called_once_with("voice", "david-id")
        only_female = render([female], "no-male.wav")
        only_female.setProperty.assert_not_called()

    # -- WSL path bridge --------------------------------------------------
    def test_wsl_path_conversion_override_and_python_side_path(self):
        self.assertEqual(
            asterisk_line._wsl_path(
                r"C:\Users\Shahid\Desktop\Jarvis Github for PC\jarvis_data"
                r"\asterisk_recordings\x.wav"),
            "/mnt/c/Users/Shahid/Desktop/Jarvis Github for PC/jarvis_data/"
            "asterisk_recordings/x.wav")
        self.assertEqual(asterisk_line._wsl_path("/mnt/d/kept/x.wav"),
                         "/mnt/d/kept/x.wav")
        self.assertEqual(asterisk_line._windows_path("/mnt/c/Users/x.wav"),
                         r"C:\Users\x.wav")
        # Default: auto /mnt/<drive> conversion, quoted when the path has spaces.
        target = asterisk_line._recording_target(asterisk_line._load_cfg(),
                                                 r"C:\My Folder\x.wav")
        self.assertEqual(target, '"/mnt/c/My Folder/x.wav"')
        # Explicit override from config.json.
        core.save_config({"asterisk_line": {"wsl_recordings_dir": "/mnt/d/jarvis-recordings"}})
        target = asterisk_line._recording_target(asterisk_line._load_cfg(),
                                                 r"C:\Users\Shahid\x.wav")
        self.assertEqual(target, "/mnt/d/jarvis-recordings/x.wav")
        # A WSL path returned by Asterisk never replaces a readable Windows path.
        windows = r"C:\Users\Shahid\x.wav"
        self.assertEqual(asterisk_line._audio_path_from_response(
            ["/mnt/c/Users/Shahid/x.wav"], {}, windows), windows)

    # -- status, lifecycle and integration --------------------------------
    def test_status_and_server_lifecycle_are_honest_and_offline(self):
        self._configure()
        stopped = asterisk_line.asterisk_status()
        self.assertIn("FastAGI=stopped", stopped)
        self.assertIn("0.0.0.0:4573", stopped)
        self.assertIn("credentials set", stopped)
        self.assertIn("/mnt/", stopped)
        self.assertNotIn(self.secret, stopped)
        self.assertIn("NOT Twilio", stopped)
        self.assertIn("NOT a PSTN/SIM number", stopped)
        asterisk_line._SERVER = SimpleNamespace(server_address=("0.0.0.0", 4573))
        self.assertIn("FastAGI=running", asterisk_line.asterisk_status())
        asterisk_line._SERVER = None

        with mock.patch.object(asterisk_line, "_AgiServer") as server_cls:
            started = asterisk_line.start_agi_server(4573)
            again = asterisk_line.start_agi_server(4573)
            self.assertIn("started on 0.0.0.0:4573", started)
            self.assertIn("already running", again)
            server_cls.assert_called_once()
            server_cls.return_value.serve_forever.assert_called_once_with()
            self.assertIn("stopped", asterisk_line.stop_agi_server())
            server_cls.return_value.shutdown.assert_called_once_with()
            server_cls.return_value.server_close.assert_called_once_with()
        self.assertTrue(asterisk_line._AgiServer.allow_reuse_address)
        self.assertTrue(asterisk_line._AgiServer.daemon_threads)

    def test_tools_and_command_hooks_are_wired_with_explicit_opt_in(self):
        names = {getattr(fn, "__name__", "") for fn in tools.TOOL_FUNCTIONS}
        expected = {"asterisk_operation", "asterisk_start", "asterisk_stop",
                    "asterisk_status", "asterisk_configure", "asterisk_call",
                    "asterisk_call_me", "start_agi_server", "stop_agi_server"}
        self.assertTrue(expected.issubset(names))
        with mock.patch.object(asterisk_line, "asterisk_status",
                               return_value="STATUS") as status, \
                mock.patch.object(asterisk_line, "asterisk_start",
                                  return_value="START") as start, \
                mock.patch.object(asterisk_line, "asterisk_stop",
                                  return_value="STOP") as stop, \
                mock.patch.object(asterisk_line, "asterisk_call_me",
                                  return_value="CALLME") as call_me, \
                mock.patch.object(asterisk_line, "asterisk_call",
                                  return_value="CALL") as call, \
                mock.patch.object(asterisk_line, "asterisk_configure",
                                  return_value="CONFIG") as configure, \
                mock.patch.object(core, "say_lang") as say, \
                mock.patch.object(jarvis_core.resume, "prompt_active",
                                  return_value=False), \
                mock.patch.object(jarvis_core.mail, "looks_email_related",
                                  return_value=False), \
                mock.patch.object(jarvis_core.voice, "command_hook",
                                  return_value=False):
            for phrase in ("asterisk line status", "asterisk line start",
                           "asterisk line stop", "call me via asterisk",
                           "asterisk call me", "mujhe asterisk se call karo",
                           "asterisk call lab",
                           "asterisk setup 10.0.0.5 joe s3cret 2001",
                           "asterisk configure 10.0.0.5 joe"):
                self.assertTrue(jarvis_core.command_hook(phrase), phrase)
            status.assert_called_once_with()
            start.assert_called_once_with()
            stop.assert_called_once_with()
            self.assertEqual(call_me.call_count, 3)
            call_me.assert_called_with(confirmed=True)
            call.assert_called_once_with("lab", confirmed=True)
            configure.assert_called_once_with(host="10.0.0.5", username="joe",
                                              secret="s3cret",
                                              outbound_extension="2001")
            self.assertTrue(any("did not get all three required parts" in str(c)
                                for c in say.call_args_list))


if __name__ == "__main__":
    unittest.main(verbosity=2)
