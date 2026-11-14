"""Global voice dictation for Windows.

Press **Ctrl+Alt+V** anywhere (or say "start dictation") and Jarvis listens,
then types what you said straight into the app that has focus - email, Word,
Slack, a browser field, a code editor, anything.  The normal Jarvis microphone
is paused while dictation is active so the two never fight over the device.

Voice edits work while you dictate:

    "scratch that" / "woh hata do"      delete the last sentence
    "delete last word"                  delete one word
    "capitalize that"                   Capitalise the last word
    "uppercase that"                    SHOUT the last sentence
    "new paragraph" / "naya paragraph"  start a new paragraph
    "comma" / "period" / "question mark" add punctuation
    "stop dictation" / "band karo"      finish

Public API:
    dictation_operation(...)  - the tool Gemini calls
    register_hotkeys(g)       - called by jarvis_core.install
    toggle() / status()       - used by the HUD
"""
from __future__ import annotations

import re
import threading
import time

from . import core

_LOCK = threading.Lock()
_STATE = {
    "thread": None,
    "running": False,
    "buffer": "",
    "started": 0.0,
    "utterances": 0,
    "hotkey": "ctrl+alt+v",
    "error": "",
}


# --------------------------------------------------------------------------- text
def _common_prefix(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    i = 0
    while i < limit and a[i] == b[i]:
        i += 1
    return i


def _last_sentence_start(text: str) -> int:
    """Index where the last sentence/clause begins (trailing punctuation is discarded)."""
    stripped = text.rstrip()
    if not stripped:
        return 0
    i = len(stripped) - 1
    while i >= 0 and stripped[i] in ".!?":
        i -= 1
    while i >= 0 and stripped[i] not in ".!?\n":
        i -= 1
    if i >= 0:
        return i + 1
    # No punctuation: drop the last few words (max 12) as the "sentence".
    words = list(re.finditer(r"\S+", stripped))
    if len(words) <= 1:
        return 0
    return words[max(0, len(words) - 12)].start()


def _last_word_span(text: str) -> tuple[int, int]:
    m = re.search(r"(\S+)\s*$", text)
    if not m:
        return len(text), len(text)
    return m.start(1), m.end(1)


def apply_edit(buffer: str, phrase: str) -> tuple[str, str]:
    """Apply one dictated utterance to the buffer. Returns (new_buffer, mode)."""
    low = (phrase or "").strip().lower().rstrip(".!?")
    if not low:
        return buffer, "noop"
    # Edit words only count when the utterance is a short command, not part of a
    # dictation sentence such as "the period of this project was difficult".
    short = len(low.split()) <= 6
    tiny = len(low.split()) <= 4

    if short and re.search(r"\b(delete last word|remove last word|word hatao|aakhri lafz hatao)\b", low):
        start, _ = _last_word_span(buffer)
        return buffer[:start], "edit"

    if short and re.search(r"\b(scratch that|delete that|undo that|delete last|remove last|"
                           r"woh hata do|wo hata do|pichla hatao|mita do|undo)\b", low):
        start = _last_sentence_start(buffer)
        return buffer[:start].rstrip() + (" " if start else ""), "edit"

    if short and re.search(r"\b(capitalize that|capitalise that|capitalize last|bada likho|capital kar do)\b", low):
        start, end = _last_word_span(buffer)
        if start == end:
            return buffer, "noop"
        word = buffer[start:end]
        return buffer[:start] + word[:1].upper() + word[1:] + buffer[end:], "edit"

    if short and re.search(r"\b(uppercase that|all caps|poora bada likho)\b", low):
        start = _last_sentence_start(buffer)
        return buffer[:start] + buffer[start:].upper(), "edit"

    if tiny and re.search(r"\b(new paragraph|naya paragraph|naya para|paragraph)\b", low):
        return buffer.rstrip() + "\n\n", "edit"

    if tiny and re.search(r"\b(new line|nayi line|next line)\b", low):
        return buffer.rstrip() + "\n", "edit"

    punct = None
    if tiny and re.search(r"\b(question mark)\b", low):
        punct = "?"
    elif tiny and re.search(r"\b(exclamation mark|exclamation point)\b", low):
        punct = "!"
    elif tiny and re.search(r"\b(full stop|period)\b", low):
        punct = "."
    elif tiny and re.search(r"\b(comma)\b", low):
        punct = ","
    elif tiny and re.search(r"\b(colon)\b", low):
        punct = ":"
    elif tiny and re.search(r"\b(semicolon)\b", low):
        punct = ";"
    if punct:
        return buffer.rstrip() + punct + " ", "edit"

    # Normal dictated text.
    text = (phrase or "").strip()
    if not text:
        return buffer, "noop"
    joiner = "" if (not buffer or buffer.endswith((" ", "\n"))) else " "
    return buffer + joiner + text, "append"


def _keyboard():
    import keyboard  # imported lazily so tests do not need a keyboard hook
    return keyboard


def _emit(old: str, new: str):
    """Type only the difference between what is on screen and the new buffer."""
    if old == new:
        return
    prefix = _common_prefix(old, new)
    delete = len(old) - prefix
    kb = _keyboard()
    for _ in range(delete):
        kb.send("backspace")
    tail = new[prefix:]
    if not tail:
        return
    for index, chunk in enumerate(tail.split("\n")):
        if index:
            kb.send("enter")
        if chunk:
            kb.write(chunk, delay=0)


def _type_text(text: str):
    kb = _keyboard()
    for index, chunk in enumerate((text or "").split("\n")):
        if index:
            kb.send("enter")
        if chunk:
            kb.write(chunk, delay=0)


# ----------------------------------------------------------------------- session
def status() -> str:
    st = _STATE
    if st["running"]:
        seconds = int(time.time() - st["started"])
        return (f"Dictation is ON ({seconds}s, {st['utterances']} phrases, "
                f"{len(st['buffer'])} characters). Hotkey: {st['hotkey']}.")
    if st["error"]:
        return "Dictation is off. Last error: " + st["error"]
    return f"Dictation is off. Press {st['hotkey']} or say 'start dictation'."


def start() -> str:
    with _LOCK:
        if _STATE["running"]:
            return status()
        _STATE.update({"running": True, "buffer": "", "started": time.time(),
                       "utterances": 0, "error": ""})
        thread = threading.Thread(target=_worker, name="jarvis-dictation", daemon=True)
        _STATE["thread"] = thread
        thread.start()
    return "Dictation on, sir. Speak, and I will type it into the active window."


def stop(quiet: bool = False) -> str:
    was_running = _STATE["running"]
    _STATE["running"] = False
    if not quiet and was_running:
        core.say_lang("Dictation stopped, sir.", "Dictation band kar diya, sir.",
                      "ڈکٹیشن بند کر دیا، سر۔")
    return "Dictation stopped." if was_running else "Dictation was not running."


def toggle() -> str:
    return stop() if _STATE["running"] else start()


def _worker():
    g = core.G
    sr = None
    hold = g.get("mic_hold")
    try:
        import speech_recognition as sr  # noqa: F401
        if hold is not None:
            hold.set()
        idx, name = (None, None)
        resolver = g.get("_resolve_mic")
        if callable(resolver):
            try:
                idx, name = resolver()
            except Exception:
                idx, name = None, None
        mic = sr.Microphone(device_index=idx)
        rec = sr.Recognizer()
        rec.operation_timeout = 8
        rec.pause_threshold = 0.7
        rec.non_speaking_duration = 0.4
        with mic as source:
            calibrate = g.get("_calibrate")
            try:
                if callable(calibrate):
                    calibrate(source)
                else:
                    rec.adjust_for_ambient_noise(source, duration=0.4)
            except Exception:
                pass
            core.say_lang("Dictation on. I am typing what you say, sir.",
                          "Dictation on hai. Jo bolein, likh raha hoon, sir.",
                          "ڈکٹیشن آن ہے۔ جو بولیں، لکھ رہا ہوں، سر۔")
            while _STATE["running"]:
                try:
                    audio = rec.listen(source, timeout=5, phrase_time_limit=20)
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    _STATE["error"] = f"microphone: {e}"
                    core.log(f"dictation microphone error: {e}")
                    break
                recognizer = g.get("_recognize_speech")
                text = ""
                try:
                    if callable(recognizer):
                        text = recognizer(rec, audio)[0]
                    else:
                        text = rec.recognize_google(audio)
                except Exception:
                    continue
                text = (text or "").strip()
                if not text:
                    continue
                low = text.lower()
                if re.search(r"\b(stop dictation|dictation (?:band|off)|band karo dictation|"
                             r"dictation stop)\b", low):
                    break
                _handle_utterance(text)
    except Exception as e:
        _STATE["error"] = str(e)
        core.log(f"dictation failed: {e}")
        core.say_lang("Dictation could not start, sir: " + str(e)[:120],
                      "Sir, dictation start nahi ho saki: " + str(e)[:120],
                      "سر، ڈکٹیشن شروع نہیں ہو سکی۔")
    finally:
        _STATE["running"] = False
        if hold is not None:
            try:
                hold.clear()
            except Exception:
                pass
        try:
            core.say_lang("Dictation finished, sir.", "Dictation mukammal, sir.",
                          "ڈکٹیشن مکمل، سر۔")
        except Exception:
            pass


def _handle_utterance(text: str):
    old = _STATE["buffer"]
    try:
        new, mode = apply_edit(old, text)
        if mode == "noop":
            return
        _emit(old, new)
        _STATE["buffer"] = new
        _STATE["utterances"] += 1
    except Exception as e:
        _STATE["error"] = f"typing: {e}"
        core.log(f"dictation typing error: {e}")


# --------------------------------------------------------------------------- hotkeys
def register_hotkeys(g: dict | None = None) -> bool:
    """Register Ctrl+Alt+V globally. Safe to call twice."""
    try:
        import keyboard
        if getattr(register_hotkeys, "_registered", False):
            return True
        keyboard.add_hotkey(_STATE["hotkey"], lambda: threading.Thread(
            target=toggle, daemon=True).start())
        register_hotkeys._registered = True
        core.log("dictation hotkey registered: " + _STATE["hotkey"])
        return True
    except Exception as e:
        core.log(f"dictation hotkey failed: {e}")
        return False


# ----------------------------------------------------------------------------- tool
def dictation_operation(action: str = "status", text: str = "") -> str:
    """Dictate into any Windows app, or type text instantly, with voice edits.

    action:
      start   - start global dictation (also Ctrl+Alt+V). Speech is typed into the focused app.
      stop    - stop dictation
      toggle  - start if off, stop if on
      status  - is dictation running?
      type    - instantly type the given text into the focused app (text=...)
    While dictating, say "scratch that", "capitalize that", "new paragraph",
    "comma", "period" or "stop dictation" to edit the text.
    """
    a = (action or "status").strip().lower()
    if a in ("start", "on", "begin", "chalu"):
        return start()
    if a in ("stop", "off", "end", "band"):
        return stop()
    if a in ("toggle", "switch"):
        return toggle()
    if a in ("type", "write", "insert", "likho"):
        if not (text or "").strip():
            return "What should I type, sir?"
        try:
            register_hotkeys(core.G)
            _type_text(text)
            return "Typed into the active window, sir."
        except Exception as e:
            return f"Typing failed: {e}"
    if a in ("status", "state", "show"):
        return status()
    return "Dictation actions: start, stop, toggle, status, type."
