"""Regression tests for the optional, local-only single-speaker check."""

import math
import tempfile
import unittest
from pathlib import Path

from jarvis_core.voice_id import VoiceID


def _tone(seed: float, seconds: float = 1.2, rate: int = 16000):
    values = []
    for i in range(int(seconds * rate)):
        t = i / float(rate)
        values.append(int(9000 * math.sin(2 * math.pi * (120 + seed * 35) * t)))
    return b"".join(int(v).to_bytes(2, "little", signed=True) for v in values)


class VoiceIDTests(unittest.TestCase):
    def test_enroll_then_verify_same_local_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            vid = VoiceID(Path(tmp) / "voiceprint.json")
            pcm = _tone(1)
            self.assertTrue(vid.enroll(pcm, 16000))
            self.assertTrue(vid.has_enrollment())
            self.assertTrue(vid.enabled)
            self.assertTrue(vid.verify(pcm, 16000))
            self.assertGreaterEqual(vid.score, 0.80)

    def test_clear_removes_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voiceprint.json"
            vid = VoiceID(path)
            self.assertTrue(vid.enroll(_tone(2), 16000))
            vid.clear()
            self.assertFalse(vid.has_enrollment())
            self.assertFalse(vid.enabled)
            self.assertFalse(path.exists())

    def test_skip_is_persisted_and_does_not_enroll(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voiceprint.json"
            vid = VoiceID(path)
            self.assertFalse(vid.setup_done())
            vid.mark_skipped()
            self.assertTrue(vid.setup_done())
            self.assertFalse(VoiceID(path).has_enrollment())

    def test_lock_requires_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            vid = VoiceID(Path(tmp) / "voiceprint.json")
            self.assertFalse(vid.set_enabled(True))
            self.assertTrue(vid.enroll(_tone(3), 16000))
            self.assertTrue(vid.set_enabled(True))
            self.assertTrue(vid.enabled)

    def test_no_audio_is_uploaded_by_module(self):
        source = Path(__file__).resolve().parents[1] / "jarvis_core" / "voice_id.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("urllib", text)
        self.assertNotIn("requests", text)
        self.assertNotIn("socket", text)


if __name__ == "__main__":
    unittest.main()
