"""Regression tests for natural conversational greetings on PC.

"Hello Jarvis, kaise ho" must be answered locally and instantly with the
"Kya hua sir" opener, not handed to Gemini. These tests patch speech output so
nothing is spoken and no live API is used.
"""

import unittest
from unittest.mock import patch

import jarvis


class GreetingTests(unittest.TestCase):
    def _run(self, text):
        with patch.object(jarvis, "speak") as speak, patch.object(jarvis, "speak_lang") as speak_lang:
            handled = jarvis.smalltalk_command(text)
        call = speak_lang.call_args if speak_lang.called else speak.call_args
        spoken = "" if call is None else " ".join(str(a) for a in call.args)
        return handled, spoken

    def test_hello_jarvis_kaise_ho_is_local(self):
        handled, spoken = self._run("hello jarvis, kaise ho")
        self.assertTrue(handled)
        self.assertIn("Kya hua sir", spoken)

    def test_hello_kaise_ho_without_wake_word(self):
        handled, spoken = self._run("hello kaise ho")
        self.assertTrue(handled)
        self.assertIn("Kya hua sir", spoken)

    def test_plain_kaise_ho_still_answered(self):
        handled, spoken = self._run("kaise ho")
        self.assertTrue(handled)
        self.assertIn("Kya hua sir", spoken)

    def test_unrelated_command_not_swallowed(self):
        handled, _ = self._run("youtube pe gana chalao")
        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()
