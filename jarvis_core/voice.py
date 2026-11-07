"""Natural voice-conversation helpers and friendly microphone selection.

The original ``jarvis.py`` already contains the real audio engine: wake word,
voice-activity detection, quiet-microphone amplification and Google speech
recognition.  This module only adds two small conveniences around it:

* ``mic phone`` / ``mobile mic`` selects a phone microphone such as WO Mic by
  name, without needing to know its list number.
* ``chalo baat karein`` / ``let's talk`` wakes Jarvis and makes it clear that
  the conversation can continue without repeating the wake word.

Nothing here touches the original audio loop, so voice behaviour stays stable.
"""
from __future__ import annotations

import re

from . import core

_MIC_WORDS = {"mic", "mike", "microphone", "microphones", "mics"}
_PHONE_WORDS = {"wo", "womic", "phone", "mobile", "cell", "cellphone",
                "android", "iphone", "smartphone"}

_CONVERSATION_PATTERNS = (
    r"^(?:chalo|acha|achha|ok|okay)?\s*baat\s+karein?$",
    r"^(?:chalo|acha|achha|ok|okay)?\s*baat\s+karni\s+hai$",
    r"^(?:mujh|mujhe|mere)\s*se\s+baat\s+karo$",
    r"^(?:tum|aap)\s*se\s+baat\s+karni\s+hai$",
    r"^(?:let'?s\s+talk|talk\s+to\s+me|conversation\s+mode|natural\s+mode)$",
    r"^i\s+want\s+to\s+talk(?:\s+to\s+you)?$",
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", (text or "").lower()))


def _phone_mics(g: dict) -> list[tuple[int, str]]:
    """Return phone/WO Mic devices first, then any other phone-like device."""
    try:
        mics = g.get("list_microphones")() or []
    except Exception:
        mics = []
    ranked = []
    for index, name in mics:
        n = (name or "").lower()
        if "wo mic" in n or "womic" in n:
            ranked.append((0, index, name))
        elif any(w in n for w in ("phone", "mobile", "android", "iphone")):
            ranked.append((1, index, name))
    ranked.sort(key=lambda row: row[0])
    return [(index, name) for _, index, name in ranked]


def phone_mic_command(text: str, g: dict) -> bool:
    """Handle 'mic phone', 'mobile mic', 'wo mic select', etc."""
    words = _words(text)
    if not (words & _MIC_WORDS):
        return False
    if not (words & _PHONE_WORDS):
        return False
    # Let the original 'mic test' do its full loudness scan instead.
    if words & {"test", "check", "testing", "jaanch"}:
        return False

    matches = _phone_mics(g)
    if matches:
        index, name = matches[0]
        setter = g.get("set_active_mic")
        if callable(setter):
            try:
                setter(index)
                core.say_lang(
                    f"Phone microphone selected, sir: {name}.",
                    f"Mobile ka microphone select ho gaya, sir: {name}.",
                    f"موبائل کا مائیکروفون منتخب ہو گیا، سر: {name}۔")
                return True
            except Exception as e:
                core.log(f"phone mic selection failed: {e}")

    try:
        printer = g.get("_print_mics")
        if callable(printer):
            printer()
        else:
            print("\n[Microphones]:")
            for number, (index, name) in enumerate(g.get("list_microphones")() or [], 1):
                print(f"  {number}. {name}")
    except Exception:
        pass
    core.say_lang(
        "I cannot see a Wo Mic or phone microphone right now, sir. Start Wo Mic on "
        "your phone and PC, then say 'mic phone' or 'mic test'.",
        "Sir, abhi Wo Mic ya mobile ka microphone nazar nahi aa raha. Phone aur PC par "
        "Wo Mic start karein, phir 'mic phone' ya 'mic test' bolein.",
        "سر، ابھی Wo Mic یا موبائل کا مائیکروفون نظر نہیں آ رہا۔ فون اور پی سی پر "
        "Wo Mic شروع کریں، پھر 'mic phone' یا 'mic test' بولیں۔")
    return True


def conversation_command(text: str, g: dict) -> bool:
    """Wake into a natural conversation without another wake word."""
    low = re.sub(r"\s+", " ", (text or "").lower()).strip(" .!?,")
    if not any(re.match(pattern, low) for pattern in _CONVERSATION_PATTERNS):
        return False
    try:
        wake = g.get("is_awake")
        if wake is not None:
            wake.set()
        asleep = g.get("user_put_to_sleep")
        if asleep is not None:
            asleep.clear()
    except Exception:
        pass
    core.say_lang(
        "I am listening, sir. Speak naturally — no need to say Hey Jarvis again.",
        "Main sun raha hoon, sir. Aaram se baat karein — Hey Jarvis dobara kehne ki "
        "zaroorat nahi.",
        "میں سن رہا ہوں، سر۔ آرام سے بات کریں — ہائے جارویس دوبارہ کہنے کی ضرورت نہیں۔")
    return True


def _install_mic_resolver(g: dict):
    """Keep a saved WO Mic working when Windows renames it slightly.

    Windows can change 'Microphone (WO Mic Device)' to
    'Microphone (2- WO Mic Device)' after a reconnect.  The original resolver
    only matches the exact saved name and then falls back to another mic.  This
    wrapper adds a safe WO Mic fuzzy match without changing the original file.
    """
    orig = g.get("_resolve_mic")
    if not orig or getattr(orig, "_jarvis_ultimate_mic", False):
        return

    def resolve_mic():
        try:
            mode = g.get("MIC_MODE")
            name = g.get("MANUAL_MIC_NAME") or ""
            if mode == "manual" and name:
                mics = g.get("list_microphones")() or []
                bad = g.get("_bad_mics") or set()
                for index, mic_name in mics:
                    if mic_name == name and index not in bad:
                        return index, mic_name
                if "wo mic" in name.lower():
                    for index, mic_name in mics:
                        if "wo mic" in (mic_name or "").lower() and index not in bad:
                            g["MANUAL_MIC_NAME"] = mic_name
                            return index, mic_name
        except Exception as e:
            core.log(f"mic fuzzy resolve failed: {e}")
        return orig()

    resolve_mic._jarvis_ultimate_mic = True
    g["_resolve_mic"] = resolve_mic


def command_hook(text: str, g: dict) -> bool:
    """Fast paths that should run before Gemini sees the command."""
    try:
        if phone_mic_command(text, g):
            return True
    except Exception as e:
        core.log(f"phone mic command failed: {e}")
    try:
        if conversation_command(text, g):
            return True
    except Exception as e:
        core.log(f"conversation command failed: {e}")
    return False
