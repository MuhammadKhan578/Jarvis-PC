# ==========================================
# ⚡ 1. FORCE IPV4 ON LINE 1 (PREVENTS NETWORK TIMEOUTS)
# ==========================================
import socket
_orig_getaddrinfo = socket.getaddrinfo
def _forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _forced_ipv4_getaddrinfo

# 🖱️ FIXED: make Windows report REAL pixels everywhere.
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# Standard imports
import ctypes
import inspect
import io
import json
import os
import sys
import time
import re
import queue
import asyncio
import hashlib
import difflib
import shutil
import functools
import traceback
import subprocess
import tempfile
import threading
import collections
import webbrowser
import urllib.parse
import urllib.request
import random
import concurrent.futures
from html import unescape
import psutil
import pyautogui
import keyboard
import speech_recognition as sr
import edge_tts
import pygame
from google import genai
from google.genai import types

try:
    import winsound
except Exception:
    winsound = None

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import audioop  # used to amplify a quiet microphone (available up to Python 3.12)
except Exception:
    audioop = None

# ==========================================
# 2. SETTINGS & VOICE / MIC PROFILES
# ==========================================
VOICES = {
    "male": {
        "en": "en-GB-RyanNeural",   # British male J.A.R.V.I.S. voice
        "ur": "ur-PK-AsadNeural"    # Urdu male voice
    },
    "female": {
        "en": "en-GB-SoniaNeural",  # British female voice
        "ur": "ur-PK-UzmaNeural"    # Urdu female voice
    }
}

# voice / language / microphone settings (they are remembered in jarvis_settings.json)
VOICE_GENDER = "male"
VOICE_NAME = VOICES[VOICE_GENDER]["en"]
URDU_VOICE = VOICES[VOICE_GENDER]["ur"]

# The male voice is LOCKED by default.  A misheard word, a stray click on the
# HUD or a noisy room can otherwise switch Jarvis to the female voice by
# accident.  While the lock is on, only an explicit "unlock voice" (typed or
# said) allows a switch; everything else is ignored.
VOICE_LOCK = True

LANG_MODE = "both"  # "both" = match the language you speak | "en" = English only | "ur" = Roman Urdu only
STT_LANG = "en-IN"  # language used to understand your speech (en-IN also understands Roman Urdu words well)
JARVIS_VERSION = "1.8.0"  # shown in the start-up banner and the HUD title

# ⚡ MICROPHONE
#   MIC_MODE "auto"    = Jarvis scans your microphones and uses one that really hears sound (virtual ones are skipped)
#   MIC_MODE "manual"  = the microphone you chose with 'mic 2'
#   MIC_MODE "default" = whatever Windows says is the default input
MIC_MODE = "auto"
MANUAL_MIC_NAME = None
MIC_DEBUG = True           # prints short messages when a sound is heard but not understood, etc.
ACTIVE_MIC_INDEX = None    # the microphone that is really in use right now (None = Windows default)
ACTIVE_MIC_NAME = None
mic_reload_event = threading.Event()
mic_hold = threading.Event()        # set while 'mic test' needs the microphones for itself
mic_released = threading.Event()    # set whenever the listener has no microphone open
mic_released.set()
_bad_mics = set()                   # microphones that sent no sound at all (skipped in auto mode)
last_input_lang = ["en"]  # language of the last command ("en" or "ur"), used when LANG_MODE is "both"

# ⚡ SPEECH CATCHING (Jarvis learns the room noise by itself; these only set the limits)
MIC_MIN_TRIGGER = 28       # a sound must be at least this loud (0-32767) to count as speech
MIC_MIN_RISE = 18          # ... and at least this much louder than the room noise
MIC_NOISE_MULT = 3.0       # ... and this many times the room noise
MIC_END_PAUSE = 0.7        # seconds of quiet that end a sentence (slow speaker? raise it to 1.0 or 1.2)
MIC_PHRASE_MAX = 14.0      # longest sentence in seconds
MIC_MIN_VOICED = 0.25      # shorter sounds are clicks / noise and are ignored
MIC_BOOST_TARGET = 4000    # a quiet microphone is amplified up to about this level before recognition
MIC_BOOST_MAX = 60.0       # ... but never more than this many times

# None = your Windows default browser. Set "brave", "chrome", "edge" or "firefox" to ALWAYS use that one.
# (When you say "brave kholo aur youtube kholo" in ONE command, YouTube opens in Brave automatically.)
PREFERRED_BROWSER = None

# ⚡ GAME TAKE MODE (Jarvis plays / keeps you active in your game while you are away)
# WARNING: online games with anti-cheat (Valorant / Vanguard ...) can BAN accounts for automated input.
# Set GAME_AFK_ENABLED = False to switch this feature off completely.
GAME_AFK_ENABLED = True
GAME_AFK_START_DELAY = 4   # seconds you get to switch to the game window after the command
GAME_AFK_MAX = 600         # longest take-over in seconds
GAME_AFK_CLICK = True      # True = also clicks sometimes, False = only moves and looks around

# ⚡ LIVING COMPANION (Jarvis lives in your PC like a person)
COMPANION_ENABLED = True       # False = Jarvis never speaks on his own (he only answers you)
COMPANION_MIN_GAP = 8 * 60     # seconds between two unprompted remarks (emergencies like a dead battery ignore this)
CURIOSITY_FIRST_MIN = 12       # his FIRST own thought comes after this many minutes ... (set 1 and 2 to test quickly)
CURIOSITY_FIRST_MAX = 20       # ... up to this many minutes
CURIOSITY_MIN = 25             # after that he speaks his mind every 25 ...
CURIOSITY_MAX = 50             # ... to 50 minutes (random, like a person)
HEALTH_WATER_MIN = 75          # water reminder every N minutes of work
HEALTH_BREAK_MIN = 50          # eye / stretch break after N minutes of non-stop work
HEALTH_POSTURE_MIN = 100       # posture reminder every N minutes


def set_voice_gender(gender: str, save: bool = True, force: bool = False) -> bool:
    """Switches between the male and female voice (English + Urdu).

    The voice is locked to MALE by default (VOICE_LOCK).  A switch to another
    gender is refused unless the user unlocked it first, so Jarvis can never
    drift into the female voice on his own.
    """
    global VOICE_GENDER, VOICE_NAME, URDU_VOICE
    gender = (gender or "").lower().strip()
    if gender not in VOICES:
        return False
    if VOICE_LOCK and not force and gender != VOICE_GENDER:
        print(f"[Voice]: switch to {gender.upper()} blocked (voice is locked to "
              f"{VOICE_GENDER.upper()}). Say or type 'unlock voice' first.")
        return False
    VOICE_GENDER = gender
    VOICE_NAME = VOICES[gender]["en"]
    URDU_VOICE = VOICES[gender]["ur"]
    print(f"[Voice]: {gender.upper()} ({VOICE_NAME} / {URDU_VOICE})")
    if save:
        save_settings()
        threading.Thread(target=_preload_voice_cache, daemon=True).start()
    return True


def set_voice_lock(on: bool, save: bool = True) -> bool:
    """Locks the current voice so it cannot change by accident."""
    global VOICE_LOCK
    VOICE_LOCK = bool(on)
    if VOICE_LOCK and VOICE_GENDER != "male":
        # locking always means 'keep the safe male voice'
        set_voice_gender("male", save=False, force=True)
    print(f"[Voice]: {'LOCKED to ' + VOICE_GENDER.upper() if VOICE_LOCK else 'UNLOCKED (voice can be changed)'}")
    if save:
        save_settings()
    return VOICE_LOCK



def set_lang_mode(mode: str, save: bool = True) -> bool:
    """'both' = match the language you speak, 'en' = English only, 'ur' = Roman Urdu only."""
    global LANG_MODE
    mode = (mode or "").lower().strip()
    if mode not in ("both", "en", "ur"):
        return False
    LANG_MODE = mode
    print(f"[Language]: {mode.upper()}")
    if save:
        save_settings()
    return True


def list_microphones():
    """[(device_index, name), ...] of every real INPUT device (microphone). Duplicates that Windows lists
    once per audio system are hidden, so each microphone appears only once."""
    found = []
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                try:
                    info = pa.get_device_info_by_index(i)
                    if int(info.get("maxInputChannels", 0)) <= 0:
                        continue
                    host = pa.get_host_api_info_by_index(int(info["hostApi"])).get("name", "")
                    found.append((i, str(info.get("name", f"Device {i}")), host))
                except Exception:
                    continue
        finally:
            pa.terminate()
    except Exception:
        try:
            return list(enumerate(sr.Microphone.list_microphone_names()))
        except Exception:
            return []
    mme = [(i, n) for i, n, h in found if "mme" in h.lower()]  # MME works best with speech recognition
    chosen = mme if mme else [(i, n) for i, n, h in found]
    out, seen = [], set()
    for i, n in chosen:
        key = n.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append((i, n))
    return out


# ---------- microphone helpers (auto pick, level check, test) ----------
_VIRTUAL_MIC_WORDS = ("cable", "voicemeeter", "vb-audio", "stereo mix", "sound mapper", "primary sound",
                      "virtual", "loopback", "what u hear", "wave out")


def _is_virtual_mic(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in _VIRTUAL_MIC_WORDS)


def _mic_priority(name: str) -> int:
    """Lower = better. Real microphones first, phone mic (WO Mic) and line-in later, virtual cables never (99)."""
    n = (name or "").lower()
    if _is_virtual_mic(name):
        return 99
    score = 50
    if any(w in n for w in ("front mic", "frontmic", "microphone", "mic", "headset", "array", "webcam", "usb")):
        score -= 20
    if any(w in n for w in ("realtek", "usb", "headset", "webcam")):
        score -= 10
    if "line in" in n:
        score += 15
    if "wo mic" in n:
        score += 25
    return score


def _rms16(raw: bytes) -> int:
    """Loudness of 16-bit audio (0 = digital silence, speech is usually in the hundreds or thousands)."""
    try:
        import array
        a = array.array("h")
        a.frombytes(raw[: len(raw) // 2 * 2])
        if not a:
            return 0
        step = max(1, len(a) // 4000)
        s = a[::step]
        return int((sum(x * x for x in s) / len(s)) ** 0.5)
    except Exception:
        return 0


def _probe_mic(index, seconds: float = 0.6):
    """Opens a microphone for a moment. Returns (opened_ok, loudest_level)."""
    try:
        m = sr.Microphone(device_index=index)
        with m as source:
            n = max(3, int(source.SAMPLE_RATE / source.CHUNK * seconds))
            loud = 0
            for _ in range(n):
                loud = max(loud, _rms16(source.stream.read(source.CHUNK)))
        return True, loud
    except Exception:
        return False, 0


def _auto_pick_mic():
    """Scans the real microphones (best first) and returns (index, name) of the first one that really hears
    sound. (None, None) = nothing usable found, use the Windows default."""
    cands = [(i, n) for i, n in list_microphones() if _mic_priority(n) < 99 and i not in _bad_mics]
    cands.sort(key=lambda t: _mic_priority(t[1]))
    for i, n in cands:
        ok, level = _probe_mic(i, 0.6)
        print(f"[Mic Scan]: {n}: {'cannot be opened' if not ok else 'level ' + str(level)}")
        if ok and level > 0:
            return i, n
        _bad_mics.add(i)
    return None, None


def _resolve_mic():
    """Returns (device_index, name) of the microphone to use now. (None, None) = Windows default."""
    if MIC_MODE == "default":
        return None, None
    if MIC_MODE == "manual" and MANUAL_MIC_NAME:
        found = False
        for i, n in list_microphones():
            if n == MANUAL_MIC_NAME:
                found = True
                if i in _bad_mics:
                    print(f"[Mic]: your chosen microphone '{n}' sends no sound, so another one is used for now.")
                    break
                return i, n
        if not found:
            print(f"[Mic]: '{MANUAL_MIC_NAME}' was not found (unplugged?). Choosing a microphone automatically.")
    return _auto_pick_mic()


def _mic_mode_text() -> str:
    if MIC_MODE == "manual" and MANUAL_MIC_NAME:
        return f"manual - {MANUAL_MIC_NAME}"
    if MIC_MODE == "default":
        return "Windows default microphone"
    return "automatic (Jarvis picks a microphone that really hears sound)"


_mic_note_t = {}


def _mic_note(key: str, msg: str, every: float = 6.0):
    """Prints a short microphone hint, at most once every `every` seconds per key."""
    if not MIC_DEBUG:
        return
    now = time.time()
    if now - _mic_note_t.get(key, 0.0) >= every:
        _mic_note_t[key] = now
        print(f"[Mic]: {msg}")


def set_active_mic(index, save: bool = True):
    """index = a device number from list_microphones() (manual choice), or None for the Windows default
    microphone. The microphone is switched live (no restart needed)."""
    global MIC_MODE, MANUAL_MIC_NAME
    _bad_mics.clear()
    if index is None:
        MIC_MODE, MANUAL_MIC_NAME = "default", None
    else:
        name = next((n for i, n in list_microphones() if i == index), None)
        if name:
            MIC_MODE, MANUAL_MIC_NAME = "manual", name
        else:
            MIC_MODE, MANUAL_MIC_NAME = "auto", None
    mic_reload_event.set()
    print(f"[Microphone]: {_mic_mode_text()}")
    if save:
        save_settings()


def set_mic_auto(save: bool = True):
    global MIC_MODE, MANUAL_MIC_NAME
    MIC_MODE, MANUAL_MIC_NAME = "auto", None
    _bad_mics.clear()
    mic_reload_event.set()
    print(f"[Microphone]: {_mic_mode_text()}")
    if save:
        save_settings()


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"voice_gender": VOICE_GENDER, "voice_locked": VOICE_LOCK,
                       "lang_mode": LANG_MODE,
                       "mic_mode": MIC_MODE, "mic_name": MANUAL_MIC_NAME},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Settings Error]: {e}")


def load_settings():
    """Restores your last voice / language / microphone choice (saved in jarvis_settings.json)."""
    global MIC_MODE, MANUAL_MIC_NAME, VOICE_LOCK
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    VOICE_LOCK = bool(data.get("voice_locked", True))
    # While the lock is on the male voice is enforced, even if the saved file
    # was changed by an accident.
    set_voice_gender("male" if VOICE_LOCK else data.get("voice_gender", VOICE_GENDER),
                     save=False, force=True)
    set_lang_mode(data.get("lang_mode", LANG_MODE), save=False)
    name = data.get("mic_name")
    mode = data.get("mic_mode")
    if mode not in ("auto", "manual", "default"):
        mode = "manual" if name else "auto"
    if mode == "manual" and not name:
        mode = "auto"
    MIC_MODE = mode
    MANUAL_MIC_NAME = name if mode == "manual" else None


# models that Google removed ("no longer available to new users") are moved to the END of the lists
# and Jarvis also asks the API at start-up which models YOUR key can really use (see _discover_models).
MODEL_NAME = "gemini-3.5-flash-lite"
MODEL_CANDIDATES = [
    MODEL_NAME,
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
active_model = MODEL_NAME
dead_models = set()

SMART_MODE = True
SMART_CANDIDATES = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-pro-preview",
                    "gemini-2.5-flash", "gemini-2.5-pro"]
_FALLBACK_FAST = list(MODEL_CANDIDATES)
_FALLBACK_SMART = list(SMART_CANDIDATES)
model_cooldown = {}  # model -> time until which it is skipped (it was overloaded / rate limited / slow)
IMAGE_MODELS = ["gemini-2.5-flash-image", "gemini-3-pro-image-preview"]

# Jarvis NEVER sends mouse/keyboard input through its normal tools (typing, clicking...) into these windows
# (online games with anti-cheat = account bans). Part of a window title is enough (lowercase).
# Game Take Mode (play_game_afk) is a separate feature that YOU switch on with GAME_AFK_ENABLED.
BLOCKED_GAME_WINDOWS = (
    "valorant", "counter-strike", "fortnite", "apex legends", "pubg", "call of duty",
    "overwatch", "rainbow six", "league of legends", "dota 2",
)

LIVE_SCREEN_AT_START = False
LIVE_INTERVAL = 1.5
LIVE_KEEP = 4
LIVE_SEND = 3

WHATSAPP_MODE = "web"
WA_LOAD_WAIT = 6
TYPE_DELAY = 0.003
CABLE_NAME = "CABLE Input"
RELAY_MONITOR = True
PRESET_LANG = "ur"
VOICE_PRESETS = {
    "ctrl+alt+1": ("Team, cover me please!", "ٹیم، مجھے کور دو!"),
    "ctrl+alt+2": ("Enemy spotted here, be careful!", "دشمن یہاں ہے، دھیان رکھو!"),
    "ctrl+alt+3": ("Rotate, rotate!", "روٹیٹ کرو، روٹیٹ کرو!"),
    "ctrl+alt+4": ("I need backup!", "مجھے بیک اپ چاہیے!"),
    "ctrl+alt+5": ("Nice one team, well played!", "شاباش ٹیم، زبردست!"),
}

# youtube / google / a few more sites (these open instantly, no Gemini)
SITES = {
    "facebook": "facebook.com", "instagram": "instagram.com", "gmail": "mail.google.com",
    "twitter": "x.com", "github": "github.com", "chatgpt": "chatgpt.com",
    "linkedin": "linkedin.com", "netflix": "netflix.com", "whatsapp": "web.whatsapp.com",
    "gemini": "gemini.google.com", "maps": "maps.google.com", "drive": "drive.google.com",
    "youtube": "youtube.com", "yt": "youtube.com", "google": "google.com",
    "reddit": "reddit.com", "twitch": "twitch.tv", "amazon": "amazon.com", "wikipedia": "wikipedia.org",
}

# ⚡ VOICE SETTINGS
# False = Jarvis ALWAYS uses your chosen male/female Edge voice. (True = when the Edge voice is slow,
# Google's backup voice speaks instead, and that backup voice is FEMALE.)
TTS_BACKUP = False
TTS_EDGE_PATIENCE = 2.5    # only used when TTS_BACKUP is True
TTS_ONE_SHOT_MAX = 160     # small pieces start playing much sooner on a slow network
# If the online Edge voice is not ready within this many seconds, speak the
# reply with a fallback voice instead of leaving the user in silence.
# Fallback order: Google translate voice -> Windows voice (if installed).
# Set to 0 to always wait for the online voice (the old, slow behaviour).
TTS_FAST_START = 2.5
TTS_TOTAL_TIMEOUT = 20.0
# When the chosen MALE voice is slow, Jarvis may wait this much longer for it
# instead of instantly switching to Google's female backup voice.
TTS_MALE_PATIENCE = 5.5
# False = NEVER use a female voice as a fallback.  The male Edge voice (or the
# English male voice for a Roman-Urdu line) is the only backup.
TTS_ALLOW_FEMALE_FALLBACK = False
TTS_CACHE_MAX = 400

pyautogui.PAUSE = 0.01

# The key saved by the app is used first; environment variables are only a
# fallback. This keeps the desktop app and the HUD on the same key.
_key = ""
_studio = "https://aistudio.google.com/app/apikey"
_jcfg = None
_saved = ""
try:
    import jarvis_config as _jcfg
    _studio = _jcfg.AI_STUDIO_URL
    _saved = _jcfg.get_saved_api_key()
except Exception:
    _jcfg = None

if _saved:
    _key = _saved
else:
    _key = (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or "").strip()

_prompted = False
if not _key:
    print("")
    print("+------------------------------------------------------------------+")
    print("|  J.A.R.V.I.S. needs a free Google Gemini API key.               |")
    print("|  1. Open Google AI Studio and sign in.                          |")
    print("|  2. Click 'Create API key'.                                     |")
    print("|  3. Paste the key below (AIza... or the newer AQ...).          |")
    print("+------------------------------------------------------------------+")
    print("  " + _studio)
    print("")
    try:
        _key = input("  GEMINI_API_KEY: ").strip()
    except (EOFError, KeyboardInterrupt):
        _key = ""
    _prompted = True

if _key:
    os.environ["GEMINI_API_KEY"] = _key
    if _jcfg is not None and _prompted:
        try:
            _jcfg.save_api_key(_key)
            print("  Key saved to: " + _jcfg.describe_location())
        except Exception as _e:
            print("  (Key could not be saved: " + str(_e) + ")")
else:
    print("[Error]: GEMINI_API_KEY is required.")
    print("Create one at: " + _studio)
    sys.exit(1)

# three clients: a quick one (a slow model is dropped after 12 s and the next model answers),
# a normal one (screen reading, research ...) and a patient one for hard questions
client = genai.Client(http_options=types.HttpOptions(timeout=12000))
client_fast = genai.Client(http_options=types.HttpOptions(timeout=12000))
client_smart = genai.Client(http_options=types.HttpOptions(timeout=12000))
pygame.mixer.init()

TEMP_AUDIO_PATH = os.path.join(tempfile.gettempdir(), "jarvis_voice.mp3")
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
try:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE_DIR = os.path.expanduser("~")
MEMORY_FILE = os.path.join(_BASE_DIR, "jarvis_memory.json")
SETTINGS_FILE = os.path.join(_BASE_DIR, "jarvis_settings.json")
COMPANION_FILE = os.path.join(_BASE_DIR, "jarvis_companion.json")
load_settings()  # remembers your voice / language / microphone choice
memory_lock = threading.Lock()
command_queue = queue.Queue()
is_awake = threading.Event()
speech_lock = threading.Lock()
speaking = threading.Event()
_last_speak_end = [0.0]
_mixer_logged = [False]
stop_flag = threading.Event()

# ⚡ companion runtime state (shared between the microphone, the main loop and the life loop)
user_put_to_sleep = threading.Event()   # set when YOU said "go to sleep": Jarvis then stays quiet until you wake him
main_busy = threading.Event()           # set while the main loop is working on one of your commands
last_user_activity = [time.time()]      # last time you gave a command
last_voice_activity = [0.0]             # last time the microphone heard a voice
quiet_until = [0.0]                     # "chup raho": no unprompted talking until this time
last_proactive = [0.0]                  # last time Jarvis spoke on his own
pending = {"data": None}                # a yes / no question Jarvis is waiting for
last_question = {"text": "", "t": 0.0, "extra": ""}  # the last question Jarvis asked YOU (your next words answer it)


# ==========================================
# ⚡ 2A. VOICE ENGINE v3
# ==========================================
_tts_loop = asyncio.new_event_loop()
def _start_tts_loop():
    asyncio.set_event_loop(_tts_loop)
    _tts_loop.run_forever()
threading.Thread(target=_start_tts_loop, daemon=True).start()

_mem_cache = {}
_cache_lock = threading.Lock()
_tts_err_seen = set()
_bk_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _disk_path(voice: str, text: str) -> str:
    key = hashlib.md5((voice + text).encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"jarvis_{key}.mp3")


def _cache_get(voice: str, text: str) -> bytes:
    with _cache_lock:
        hit = _mem_cache.get((voice, text))
    if hit:
        return hit
    p = _disk_path(voice, text)
    try:
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                data = f.read()
            with _cache_lock:
                _mem_cache[(voice, text)] = data
            return data
    except Exception:
        pass
    return b""


def _cache_put(voice: str, text: str, data: bytes):
    with _cache_lock:
        _mem_cache[(voice, text)] = data
        while len(_mem_cache) > TTS_CACHE_MAX:
            _mem_cache.pop(next(iter(_mem_cache)))
    if len(text) <= 300:
        try:
            p = _disk_path(voice, text)
            tmp = f"{p}.{threading.get_ident()}.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        except Exception:
            pass


async def _fetch_edge_audio(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate="+18%")
    chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


async def _fetch_with_retry(text: str, voice: str) -> bytes:
    start = time.monotonic()
    for _ in range(3):
        left = TTS_TOTAL_TIMEOUT - (time.monotonic() - start)
        if left <= 1:
            break
        try:
            data = await asyncio.wait_for(_fetch_edge_audio(text, voice),
                                          timeout=min(left, 12 + len(text) / 30))
            if data and len(data) > 100:
                return data
        except asyncio.CancelledError:
            raise
        except Exception as e:
            sig = type(e).__name__
            if sig not in _tts_err_seen:
                _tts_err_seen.add(sig)
                print(f"[TTS Edge error]: {sig}: {str(e)[:150]}")
        await asyncio.sleep(0.2)
    return b""


def _prefetch(text: str, voice: str, quiet: bool = False):
    clean_txt = (text or "").strip()
    if not clean_txt:
        f = concurrent.futures.Future()
        f.set_result(b"")
        return f
    hit = _cache_get(voice, clean_txt)
    if hit:
        f = concurrent.futures.Future()
        f.set_result(hit)
        return f

    async def _job():
        t0 = time.monotonic()
        data = await _fetch_with_retry(clean_txt, voice)
        if data:
            _cache_put(voice, clean_txt, data)
            if not quiet:
                print(f"[TTS]: Edge voice took {time.monotonic() - t0:.1f}s ({len(clean_txt)} chars)")
        return data

    return asyncio.run_coroutine_threadsafe(_job(), _tts_loop)


def _get_audio_data(text: str, voice: str, timeout: float = TTS_TOTAL_TIMEOUT + 2, quiet: bool = False) -> bytes:
    fut = _prefetch(text, voice, quiet=quiet)
    try:
        return fut.result(timeout=timeout) or b""
    except Exception:
        fut.cancel()
        return b""


def _google_tts(text: str, lang: str) -> bytes:
    try:
        url = ("https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=" + lang
               + "&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": "https://translate.google.com/"})
        data = urllib.request.urlopen(req, timeout=6).read()
        return data if data and len(data) > 100 else b""
    except Exception:
        return b""


def _split_backup(text: str):
    pieces, cur = [], ""
    for part in re.split(r'(?<=[.?!۔؟,،;:])\s+', text or ""):
        if cur and len(cur) + 1 + len(part) > 180:
            pieces.append(cur)
            cur = part
        else:
            cur = (cur + " " + part).strip()
    if cur:
        pieces.append(cur)
    out = []
    for p in pieces:
        while len(p) > 180:
            cut = p.rfind(" ", 0, 180)
            if cut <= 0:
                cut = 180
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return [x for x in out if re.search(r'\w', x)]


def _backup_start(text: str, voice: str):
    lang = "ur" if voice == URDU_VOICE else "en"
    return [_bk_pool.submit(_google_tts, p, lang) for p in _split_backup(text)]


def _backup_collect(futs):
    blobs = []
    for f in futs:
        try:
            b = f.result(timeout=10)
        except Exception:
            b = b""
        if not b:
            return []
        blobs.append(b)
    return blobs


def _resolve_piece(fut, piece: str, voice: str):
    if fut.done():
        try:
            d = fut.result()
            if d:
                return [d]
        except Exception:
            pass
    bk = _backup_start(piece, voice) if TTS_BACKUP else None
    try:
        d = fut.result(timeout=TTS_EDGE_PATIENCE if bk else TTS_TOTAL_TIMEOUT)
        if d:
            return [d]
    except Exception:
        pass
    if bk:
        blobs = _backup_collect(bk)
        if blobs:
            print(f"[TTS]: Edge voice slow (> {TTS_EDGE_PATIENCE:g}s) -> backup voice used")
            return blobs
    try:
        d = fut.result(timeout=TTS_TOTAL_TIMEOUT)
        if d:
            return [d]
    except Exception:
        pass
    return []


def _ensure_audio(clean: str, voice: str) -> str:
    clean = re.sub(r'\s+', ' ', clean or '').strip()
    if not clean:
        return ""
    blobs = _resolve_piece(_prefetch(clean, voice), clean, voice)
    if not blobs:
        return ""
    key = hashlib.md5((voice + clean).encode("utf-8")).hexdigest()[:16]
    path = os.path.join(tempfile.gettempdir(), f"jarvis_relay_{key}.mp3")
    try:
        with open(path, "wb") as f:
            f.write(b"".join(blobs))
        return path
    except Exception:
        return ""


def _sapi_say(text: str) -> bool:
    """Speak through the Windows SAPI voice.  Returns True only when it worked.

    Some Windows installs have no usable SAPI voice (the COM calls fail), so
    this is only the last fallback and never the only voice.
    """
    clean = re.sub(r'[^\x00-\x7F]+', ' ', text).replace('"', ' ').replace("'", " ").strip()
    if not clean:
        return False
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            sp = win32com.client.Dispatch("SAPI.SpVoice")
            for v in sp.GetVoices():
                desc = v.GetDescription().lower()
                if VOICE_GENDER == "male" and any(k in desc for k in ("david", "male", "george", "mark")):
                    sp.Voice = v
                    break
                elif VOICE_GENDER == "female" and any(k in desc for k in ("zira", "female", "heera", "hazel")):
                    sp.Voice = v
                    break
            sp.Speak(clean)
            return True
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        print(f"[TTS]: Windows voice not available ({type(e).__name__}).")
    try:
        vbs = os.path.join(tempfile.gettempdir(), "sapi_fast.vbs")
        with open(vbs, "w", encoding="utf-8") as f:
            f.write(f'CreateObject("SAPI.SpVoice").Speak "{clean}"')
        subprocess.run(["cscript", "//nologo", vbs], timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:
        print(f"[TTS]: local voice fallback failed ({type(e).__name__}).")
        return False


def _google_speak(text: str, voice: str = "") -> bool:
    """Speak with Google's translate voice when the chosen Edge voice is slow.

    This is the reliable second voice on PCs where the Windows SAPI voice is
    missing or broken: it only needs internet, plays through the same pygame
    mixer, and starts in well under a second.  Returns True if audio played.
    """
    plain = re.sub(r'[*_#`~]', '', text or '').strip()
    if not plain:
        return False
    lang = "ur" if re.search(r'[\u0600-\u06FF]', plain) else "en"
    pieces = _split_backup(plain)
    if not pieces:
        return False
    futs = [_bk_pool.submit(_google_tts, p, lang) for p in pieces]
    blobs = []
    for f in futs:
        try:
            b = f.result(timeout=8)
        except Exception:
            b = b""
        if not b:
            return False
        blobs.append(b)
    for b in blobs:
        if stop_flag.is_set():
            break
        _play_bytes(b)
    return True


def _split_speech_chunks(text: str):
    text = re.sub(r'\s+', ' ', text or '').strip()
    if not text:
        return []
    if len(text) <= TTS_ONE_SHOT_MAX:
        return [text]
    chunks, cur = [], ''
    for s in re.split(r'(?<=[.?!۔؟])\s+', text):
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > TTS_ONE_SHOT_MAX:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + ' ' + s).strip()
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        while len(c) > TTS_ONE_SHOT_MAX + 120:
            cut = c.rfind(' ', 0, TTS_ONE_SHOT_MAX)
            if cut <= 0:
                cut = TTS_ONE_SHOT_MAX
            out.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            out.append(c)
    return [c for c in out if re.search(r'\w', c)] or [text]


def _ensure_mixer() -> bool:
    """Make sure pygame can play sound and log the output that is in use."""
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        init = pygame.mixer.get_init()
        if init and not _mixer_logged[0]:
            _mixer_logged[0] = True
            print(f"[Audio]: sound output ready ({init[0]} Hz, {init[2]} channel(s)).")
        return bool(init)
    except Exception as e:
        print(f"[Audio Error]: could not start the sound output ({type(e).__name__}: {e})")
        return False


def _play_bytes(audio_bytes: bytes):
    if not audio_bytes:
        return
    if not _ensure_mixer():
        return
    bio = io.BytesIO(audio_bytes)
    # A lost/unplugged output device can leave get_busy() True for ever and
    # hold the speech lock, which made every later reply silent.  Stop after a
    # generous estimate of the clip length instead.
    limit = min(300.0, len(audio_bytes) / 1500.0 + 10.0)
    try:
        try:
            pygame.mixer.music.load(bio, "mp3")
        except TypeError:
            pygame.mixer.music.load(bio)
        pygame.mixer.music.play()
        started = time.time()
        while pygame.mixer.music.get_busy():
            if stop_flag.is_set():
                pygame.mixer.music.stop()
                break
            if time.time() - started > limit:
                print("[Audio]: playback took too long; stopping it.")
                pygame.mixer.music.stop()
                break
            pygame.time.Clock().tick(30)
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass
    except Exception as e:
        print(f"[Audio Stream Error]: {type(e).__name__}: {e}")
        # The output device may have changed (headphones unplugged ...).
        # Re-open the mixer so the next sentence is not lost.
        try:
            pygame.mixer.quit()
            pygame.mixer.init()
        except Exception:
            pass


def speak(text: str, urdu: str = None):
    with speech_lock:
        print(f"\nJ.A.R.V.I.S.: {text}")
        if urdu:
            target_text = re.sub(r'[*_#`~]', '', urdu).strip()
            voice = URDU_VOICE
        else:
            target_text = re.sub(r'[*_#`~]', '', text)
            target_text = re.sub(r'[^\x00-\x7F]+', ' ', target_text).strip()
            voice = VOICE_NAME
        if not target_text:
            return
        roman_fallback = re.sub(r'[^\x00-\x7F]+', ' ', re.sub(r'[*_#`~]', '', text or '')).strip()

        speaking.set()
        pending_audio = None
        try:
            t0 = time.time()
            chunks = _split_speech_chunks(target_text)
            if not chunks:
                return
            pending_audio = _prefetch(chunks[0], voice)

            # The HUD prints the reply immediately.  Do not leave the user in
            # silence while a slow Edge connection synthesizes the whole line:
            # if the first audio is not ready almost at once, use the built-in
            # Windows voice, which starts instantly and works offline.
            first_ready = True
            if TTS_FAST_START > 0:
                try:
                    first_ready = bool(pending_audio.result(timeout=TTS_FAST_START))
                except Exception:
                    first_ready = False
            if not first_ready:
                fallback_text = target_text or roman_fallback
                print(f"[TTS]: Edge voice slow (> {TTS_FAST_START:g}s) -> fallback voice")
                male_only = VOICE_GENDER == "male" and not TTS_ALLOW_FEMALE_FALLBACK
                if male_only:
                    # The voice must stay MALE.  Give the chosen Edge voice a
                    # little more time (it is often ready a moment later), and
                    # never switch to Google's female voice just because of a
                    # 4-second hiccup.
                    try:
                        late = pending_audio.result(timeout=TTS_MALE_PATIENCE)
                    except Exception:
                        late = b""
                    if late:
                        _play_bytes(late)
                        return
                    # Second chance: the same male line in the English male
                    # voice (works when only the Urdu voice endpoint failed).
                    alt_text = roman_fallback or re.sub(
                        r'[^\x00-\x7F]+', ' ', target_text).strip()
                    alt_voice = VOICES["male"]["en"]
                    if alt_text:
                        alt = _get_audio_data(alt_text, alt_voice, timeout=8.0)
                        if alt:
                            print("[TTS]: male English voice used as backup")
                            _play_bytes(alt)
                            return
                else:
                    # female voice selected (or female fallback allowed)
                    if _google_speak(fallback_text, voice):
                        return
                    try:
                        late = pending_audio.result(timeout=TTS_TOTAL_TIMEOUT)
                    except Exception:
                        late = b""
                    if late:
                        _play_bytes(late)
                        return
                # 3) Windows voice, when this PC actually has one.
                local_text = roman_fallback or re.sub(
                    r'[^\x00-\x7F]+', ' ', target_text).strip()
                if not local_text or not _sapi_say(local_text):
                    print("[TTS]: no MALE voice available right now "
                          "(male-only mode: female fallback is disabled).")
                return

            for i, piece in enumerate(chunks):
                if stop_flag.is_set():
                    break
                blobs = _resolve_piece(pending_audio, piece, voice)
                if i == 0:
                    print(f"[TTS]: first audio ready in {time.time() - t0:.1f}s ({len(chunks)} piece(s))")
                pending_audio = _prefetch(chunks[i + 1], voice) if i + 1 < len(chunks) else None
                if not blobs:
                    played = False
                    if VOICE_GENDER == "male" and not TTS_ALLOW_FEMALE_FALLBACK:
                        alt_text = re.sub(r'[^\x00-\x7F]+', ' ', piece).strip() or roman_fallback
                        alt_voice = VOICES["male"]["en"] if voice != VOICES["male"]["en"] else ""
                        if alt_text and alt_voice:
                            alt = _get_audio_data(alt_text, alt_voice, timeout=8.0)
                            if alt:
                                print("[TTS]: male English voice used as backup")
                                _play_bytes(alt)
                                played = True
                    if not played and (VOICE_GENDER != "male" or TTS_ALLOW_FEMALE_FALLBACK):
                        played = _google_speak(piece, voice)
                    if not played:
                        local_text = re.sub(r'[^\x00-\x7F]+', ' ', piece).strip()
                        if not local_text or not _sapi_say(local_text):
                            print("[TTS]: no MALE voice available for that part "
                                  "(female fallback disabled).")
                    continue
                for b in blobs:
                    if stop_flag.is_set():
                        break
                    _play_bytes(b)
        except Exception as e:
            print(f"[Speech Error]: {e}")
        finally:
            if pending_audio is not None:
                pending_audio.cancel()
            _last_speak_end[0] = time.time()
            speaking.clear()


# ---------- language helpers ----------
_ROMAN_URDU_WORDS = {
    "kholo", "khol", "karo", "kro", "kar", "chalao", "chala", "lagao", "bhejo", "bhej", "mein", "mai", "hai",
    "hain", "ka", "ki", "ke", "ko", "se", "par", "pe", "aur", "phir", "batao", "bata", "dikhao", "kya", "kaise",
    "kahan", "kaun", "kitna", "mujhe", "mera", "meri", "tum", "aap", "nahi", "haan", "acha", "theek", "abhi",
    "gana", "awaz", "band", "shuru", "sikhao", "samjhao", "likho", "banao", "dhoondo", "dhundo", "wala", "wali",
    "kal", "aaj", "bolo", "sunao", "yaar", "bhai", "zara", "jaldi", "dobara", "khelo", "sambhalo",
}


def _detect_lang(text: str) -> str:
    """'ur' if the command is Urdu / Roman Urdu / Hindi, otherwise 'en'."""
    if re.search(r"[\u0600-\u06FF\u0900-\u097F]", text or ""):
        return "ur"
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return "ur" if words & _ROMAN_URDU_WORDS else "en"


def _active_lang() -> str:
    return LANG_MODE if LANG_MODE in ("en", "ur") else last_input_lang[0]


def speak_lang(en: str, roman: str, urdu: str):
    """Speaks a fixed phrase in English or in Urdu, depending on the language mode / what you just spoke."""
    if _active_lang() == "en":
        speak(en)
    else:
        speak(roman, urdu=urdu)


def _lang_note() -> str:
    style = ("Write the ROMAN line like a real Pakistani person talking casually in Roman Urdu "
             "(e.g. 'Haan sir, abhi karta hoon', 'Theek hai sir, dekh leta hoon'). Use everyday "
             "Pakistani words, not formal or English-accented sentences. Keep it short and smooth. "
             "Never write Urdu script in the ROMAN line; the URDU line carries the Urdu script.")
    active = _active_lang()
    if LANG_MODE == "en" or (LANG_MODE == "both" and active == "en"):
        return ("Reply language: ENGLISH ONLY for this reply. The ROMAN line must be plain, natural "
                "English (no Roman-Urdu words such as 'hai', 'ka', 'kholo', 'theek'). The URDU line "
                "repeats exactly the same English reply.")
    if LANG_MODE == "ur" or (LANG_MODE == "both" and active == "ur"):
        return ("Reply language: ROMAN URDU for this reply. " + style +
                " The URDU line is exactly the same reply written in Urdu script.")
    return ("Reply language: match the user. English user -> English reply (the URDU line repeats the English). "
            "Roman Urdu / Urdu / Hindi user -> reply in natural Pakistani Roman Urdu plus the same reply in "
            "Urdu script. " + style)


def _roman_to_urdu(text: str) -> str:
    """Small safety net: turn a Roman-Urdu line into Urdu script so the natural
    Pakistani male voice can speak it (never an English accent)."""
    text = (text or "").strip()
    if not text or re.search(r'[\u0600-\u06FF]', text):
        return text if re.search(r'[\u0600-\u06FF]', text) else ""
    key = text.lower()
    if key in _urdu_cache:
        return _urdu_cache[key]
    try:
        model = (MODEL_CANDIDATES or ["gemini-3.5-flash-lite"])[0]
        cfg = types.GenerateContentConfig(
            max_output_tokens=400,
            system_instruction=("Translate the user's Roman Urdu sentence into Urdu script. "
                                "Return ONLY the Urdu sentence, no explanation."),
            http_options=types.HttpOptions(timeout=10000),
        )
        resp = client_fast.models.generate_content(model=model, contents=text, config=cfg)
        out = (getattr(resp, "text", None) or "").strip()
        if re.search(r'[\u0600-\u06FF]', out):
            _urdu_cache[key] = out
            return out
    except Exception:
        pass
    return ""


_urdu_cache = {}


def speak_reply(text: str):
    """Speaks Gemini's two-line 'ROMAN: ... URDU: ...' reply with the right voice and language."""
    m_roman = re.search(r'ROMAN:\s*(.+)', text, re.I)
    m_urdu = re.search(r'URDU:\s*(.+)', text, re.I)
    roman_val = m_roman.group(1).strip() if m_roman else ""
    urdu_val = m_urdu.group(1).strip() if m_urdu else ""
    has_urdu = bool(re.search(r'[\u0600-\u06FF]', urdu_val))

    # One clear rule: English input -> English male voice.  Roman Urdu / Urdu
    # input -> Urdu script spoken by the Pakistani male voice (never the
    # English voice reading Roman letters).
    if _active_lang() == "en":
        speak(roman_val or re.sub(r'URDU:.*', '', text, flags=re.S | re.I).strip() or text)
        return
    spoken = roman_val or text
    if not has_urdu:
        urdu_val = _roman_to_urdu(spoken)
        has_urdu = bool(urdu_val)
    speak(spoken, urdu=urdu_val if has_urdu else None)


# ==========================================
# 2B. ROBUST GEMINI HELPERS (cooldown + automatic model discovery + fast thinking)
# ==========================================
RETRY_CODES = {408, 500, 502, 503, 504}

# Hard time budget for one spoken answer.  The microphone -> complete reply must
# stay inside 5-10 seconds, so Jarvis never waits for a chain of slow retries.
BRAIN_BUDGET_FAST = 8.0    # normal question / command
BRAIN_BUDGET_SMART = 9.0   # "smart" question (needs the stronger model)
MAX_MODEL_TRIES_FAST = 3
MAX_MODEL_TRIES_SMART = 2


def _err_code(e):
    c = getattr(e, "code", None)
    if isinstance(c, int):
        return c
    m = re.search(r"\b([45]\d\d)\b", str(e)[:300])
    return int(m.group(1)) if m else None


def _is_net_error(e) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return any(k in s for k in ("timed out", "timeout", "deadline", "unavailable", "connect",
                                "getaddrinfo", "ssl", "reset by peer", "remote end closed",
                                "temporarily", "network"))


def _is_server_busy(e) -> bool:
    """Gemini's own server was slow / overloaded / timed out (internet is fine)."""
    code = _err_code(e)
    s = (str(e) + " " + type(e).__name__).lower()
    return code in (500, 502, 503, 504) or any(k in s for k in (
        "deadline", "readtimeout", "timed out", "timeout", "unavailable",
        "overloaded", "high demand", "temporarily"))


def _is_connect_error(e) -> bool:
    """A real connection problem: no route, DNS, TLS, dropped socket."""
    if _err_code(e) in (500, 502, 503, 504):
        return False
    s = (str(e) + " " + type(e).__name__).lower()
    return any(k in s for k in ("getaddrinfo", "name resolution", "connect error",
                                "connection refused", "connection reset", "reset by peer",
                                "network is unreachable", "no route to host", "ssl",
                                "certificate", "remote end closed"))


def _model_ok(m: str) -> bool:
    return m not in dead_models and time.time() >= model_cooldown.get(m, 0.0)


def _cool(model: str, secs: float):
    model_cooldown[model] = time.time() + secs


def _pick_order(base):
    """Models in order, skipping dead ones (404) and overloaded / slow ones (cooling down)."""
    order = list(dict.fromkeys(base))
    ok = [m for m in order if _model_ok(m)]
    return ok or [m for m in order if m not in dead_models]


_think_try = {}  # model -> how many thinking settings the server already refused


def _thinking_cfg(model: str, smart: bool = False):
    """Makes Gemini think LESS so it answers fast. Gemini 3.x thinks a lot by default (that was the 20 second
    'hello'). Returns None when the model has no such setting or refused it."""
    m = re.match(r"gemini-(\d+)(?:\.(\d+))?", model or "")
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    skip = _think_try.get(model, 0)
    try:
        if major == 2:
            if minor == 5 and "pro" not in model and skip == 0:
                return types.ThinkingConfig(thinking_budget=1024 if smart else 0)
            return None
        if major >= 3:
            levels = ["low"] if smart else ["minimal", "low"]
            for lvl in levels[skip:]:
                try:
                    return types.ThinkingConfig(thinking_level=lvl)
                except Exception:
                    continue
    except Exception:
        return None
    return None


def _cfg_for(config, model: str):
    th = _thinking_cfg(model, False)
    if th is None or config is None:
        return config
    try:
        if getattr(config, "thinking_config", None) is not None:
            return config
        return config.model_copy(update={"thinking_config": th})
    except Exception:
        return config


_MODEL_BAD = ("image", "tts", "embed", "live", "audio", "robotics", "computer-use", "vision", "learnlm",
              "gemma", "imagen", "veo", "aqa", "customtools", "deep-research")


def _discover_models():
    """Asks the API which Gemini models your key can really use and puts the newest ones first."""
    try:
        found = []
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").split("/")[-1]
            acts = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
            if not name.startswith("gemini"):
                continue
            if acts and "generateContent" not in acts:
                continue
            if any(b in name for b in _MODEL_BAD):
                continue
            found.append(name)
        if not found:
            return

        def ver(n):
            mm = re.match(r"gemini-(\d+)(?:\.(\d+))?", n)
            return (int(mm.group(1)), int(mm.group(2) or 0)) if mm else (0, 0)

        def key(n):
            v = ver(n)
            return (-v[0], -v[1], 1 if re.search(r"preview|exp", n) else 0, len(n))

        lite = sorted([n for n in found if "lite" in n], key=key)
        pro = sorted([n for n in found if "pro" in n and "lite" not in n], key=key)
        flash = sorted([n for n in found if "flash" in n and "lite" not in n], key=key)
        fast = [MODEL_NAME] + lite[:3] + flash[:3] + _FALLBACK_FAST
        smart = flash[:3] + pro[:2] + lite[:2] + _FALLBACK_SMART
        MODEL_CANDIDATES[:] = list(dict.fromkeys(fast))
        SMART_CANDIDATES[:] = list(dict.fromkeys(smart))
        print(f"[Models]: fast = {MODEL_CANDIDATES[:4]}")
        print(f"[Models]: smart = {SMART_CANDIDATES[:4]}")
    except Exception as e:
        print(f"[Models]: could not list models ({str(e)[:100]}), using the built-in list")


def _generate(contents, config):
    order = _pick_order(MODEL_CANDIDATES)
    last = None
    t_begin = time.time()
    for model in order:
        if last is not None and time.time() - t_begin > 12:
            break
        for _ in range(2):
            t_try = time.time()
            try:
                return client.models.generate_content(model=model, contents=contents,
                                                      config=_cfg_for(config, model))
            except Exception as e:
                last = e
                code = _err_code(e)
                print(f"[Gemini]: {model} -> {type(e).__name__}: {str(e)[:160]}")
                if code == 404:
                    dead_models.add(model)
                    break
                if code in (401, 403):
                    raise
                if code == 400 and "think" in str(e).lower():
                    _think_try[model] = _think_try.get(model, 0) + 1
                    continue
                if code == 429:
                    _cool(model, 120)
                    break
                if code in RETRY_CODES:
                    _cool(model, 60)
                    break
                if time.time() - t_try > 8:
                    _cool(model, 30)
                    break
                time.sleep(0.25)
    if last:
        raise last
    raise RuntimeError("No Gemini model available.")


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    data = json.loads(t)
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


# ==========================================
# 2C. SCREEN VISION HELPERS
# ==========================================
def _virtual_screen():
    try:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    except Exception:
        w, h = pyautogui.size()
        return 0, 0, w, h


def _cursor_pos():
    try:
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except Exception:
        p = pyautogui.position()
        return int(p[0]), int(p[1])


def _mark_cursor(img, origin=(0, 0)):
    try:
        from PIL import ImageDraw
        cx, cy = _cursor_pos()
        x, y = cx - origin[0], cy - origin[1]
        if not (0 <= x < img.width and 0 <= y < img.height):
            return img
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        r = max(18, img.width // 90)
        red = (255, 0, 0)
        d.ellipse((x - r, y - r, x + r, y + r), outline=red, width=max(3, r // 5))
        d.line((x - r * 2, y, x + r * 2, y), fill=red, width=max(2, r // 6))
        d.line((x, y - r * 2, x, y + r * 2), fill=red, width=max(2, r // 6))
        d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=red)
        d.text((x + r + 6, y - r - 12), "CURSOR", fill=red)
        return img
    except Exception:
        return img


def _cursor_info(scope: str = "desktop") -> str:
    try:
        x, y = _cursor_pos()
        pw, ph = pyautogui.size()
        left, top, vw, vh = _virtual_screen()
        if 0 <= x < pw and 0 <= y < ph:
            where = "on the PRIMARY (main) monitor"
        else:
            dirs = []
            if x < 0:
                dirs.append("left")
            if x >= pw:
                dirs.append("right")
            if y < 0:
                dirs.append("above")
            if y >= ph:
                dirs.append("below")
            where = "on a SECONDARY monitor (" + " and ".join(dirs) + " of the main monitor)"
        ox, oy, w, h = (0, 0, pw, ph) if scope == "primary" else (left, top, vw, vh)
        rx, ry = x - ox, y - oy
        if 0 <= rx < w and 0 <= ry < h:
            col = "left" if rx < w / 3 else ("right" if rx > 2 * w / 3 else "center")
            row = "top" if ry < h / 3 else ("bottom" if ry > 2 * h / 3 else "middle")
            area = "main monitor" if scope == "primary" else "whole desktop"
            pos = f"{rx * 100 // w}% from the left and {ry * 100 // h}% from the top of the {area} ({row}-{col})"
        else:
            pos = "outside the area shown in the pictures"
        return f"Mouse cursor: x={x}, y={y} (real pixels), {where}; {pos}."
    except Exception:
        return ""


def _screenshot_part(mark_cursor: bool = False):
    img = pyautogui.screenshot()
    if mark_cursor:
        img = _mark_cursor(img)
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=70)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


def _screen_ask(prompt: str) -> dict:
    resp = _generate([_screenshot_part(), prompt],
                     types.GenerateContentConfig(response_mime_type="application/json"))
    return _parse_json(resp.text)


def _click_scaled(x: float, y: float, double: bool = False):
    w, h = pyautogui.size()
    px, py = int(x / 1000 * w), int(y / 1000 * h)
    if double:
        pyautogui.doubleClick(px, py)
    else:
        pyautogui.click(px, py)


_FIND_PROMPT = (
    "Find this on the screen: {what}. Reply ONLY with JSON like "
    '{{"found": true, "x": 500, "y": 300}}. x and y are the CENTER of the element, '
    "measured from the left and top edges and scaled 0 to 1000. "
    'If it is not visible reply {{"found": false}}.'
)


def _find_and_click(what: str, double: bool = False) -> bool:
    for _ in range(2):
        data = _screen_ask(_FIND_PROMPT.format(what=what))
        if data.get("found"):
            _click_scaled(float(data["x"]), float(data["y"]), double=double)
            return True
        time.sleep(0.8)
    return False


def _game_active() -> bool:
    try:
        title = (pyautogui.getActiveWindowTitle() or "").lower()
    except Exception:
        return False
    return any(g in title for g in BLOCKED_GAME_WINDOWS)


# ==========================================
# 2C-2. LIVE SCREEN SHARE
# ==========================================
live_on = threading.Event()
live_frames = collections.deque(maxlen=LIVE_KEEP)
live_lock = threading.Lock()
LIVE_NOTE = "[LIVE SCREEN SHARE"
CONTEXT_NOTE = "[CONTEXT"


def _grab_frame_jpeg() -> bytes:
    origin = _virtual_screen()[:2]
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
    except Exception:
        img = pyautogui.screenshot()
        origin = (0, 0)
    img = _mark_cursor(img, origin)
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=65)
    return buf.getvalue()


def _live_loop():
    while True:
        if live_on.is_set():
            try:
                data = _grab_frame_jpeg()
                with live_lock:
                    live_frames.append((time.time(), data))
            except Exception as e:
                print(f"[Live Screen Error]: {e}")
                time.sleep(2)
            time.sleep(LIVE_INTERVAL)
        else:
            time.sleep(0.3)


def _set_live(on: bool):
    if on:
        with live_lock:
            live_frames.clear()
        live_on.set()
    else:
        live_on.clear()
        with live_lock:
            live_frames.clear()
    print(f"\n[Live Screen]: {'ON' if on else 'OFF'}")


def _live_message(user_input: str):
    if not live_on.is_set():
        return user_input, False
    try:
        now_frame = _grab_frame_jpeg()
    except Exception:
        now_frame = None
    with live_lock:
        old = [d for t, d in live_frames if time.time() - t <= 8]
    frames = old[-(LIVE_SEND - 1):] if now_frame else old[-LIVE_SEND:]
    if now_frame:
        frames.append(now_frame)
    if not frames:
        return user_input, False
    parts = [types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in frames]
    parts.append(types.Part(
        text=(f"{LIVE_NOTE}: the {len(frames)} image(s) above are frames of the user's whole screen, "
              f"oldest to newest, about {LIVE_INTERVAL:g} seconds apart. The LAST image is the screen right now.]")))
    parts.append(types.Part(text=user_input))
    return parts, True


def start_live_screen() -> str:
    """Starts LIVE screen sharing: from now on the user's whole screen frames arrive with every command."""
    _set_live(True)
    return "Live screen share is ON. Live screen frames arrive with every message."


def stop_live_screen() -> str:
    """Stops LIVE screen sharing."""
    _set_live(False)
    return "Live screen share is OFF."


def live_command(low: str) -> bool:
    words = set(re.findall(r"[\w']+", low))
    if "screen" not in words or not (words & {"live", "share", "sharing"}):
        return False
    if words & {"band", "off", "stop", "khatam", "roko", "rok", "disable"}:
        _set_live(False)
        speak("Ji sir, live screen band kar di.", urdu="جی سر، لائیو اسکرین بند کر دی۔")
    else:
        _set_live(True)
        speak("Ji sir, live screen shuru ho gayi. Ab main aapki screen dekh sakta hoon.",
              urdu="جی سر، لائیو اسکرین شروع ہو گئی۔ اب میں آپ کی اسکرین دیکھ سکتا ہوں۔")
    return True


def _toggle_live():
    if live_on.is_set():
        _set_live(False)
        try:
            if winsound:
                winsound.Beep(700, 150)
        except Exception:
            pass
    else:
        _set_live(True)
        try:
            if winsound:
                winsound.Beep(1500, 100)
        except Exception:
            pass


def _debug_cursor():
    try:
        data = _grab_frame_jpeg()
        os.makedirs(DESKTOP, exist_ok=True)
        path = os.path.join(DESKTOP, "cursor_debug.jpg")
        with open(path, "wb") as f:
            f.write(data)
        print("\n[Cursor Debug]:", _cursor_info("desktop"))
        print("[Cursor Debug]: picture saved:", path)
        try:
            os.startfile(path)
        except Exception:
            pass
    except Exception as e:
        print(f"[Cursor Debug Error]: {e}")


# ==========================================
# 2D. VIRTUAL MIC RELAY
# ==========================================
relay_busy = threading.Event()
_last_relay_end = [0.0]
_box_open = threading.Event()


def _find_cable_device():
    if sd is None:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if CABLE_NAME.lower() in d["name"].lower() and d["max_output_channels"] > 0:
                return i
    except Exception:
        pass
    return None


def relay_audio(path: str) -> bool:
    idx = _find_cable_device()
    if idx is None:
        print("[Voice Relay]: VB-CABLE not found. Install VB-CABLE and run: pip install sounddevice numpy")
        return False
    with speech_lock:
        relay_busy.set()
        try:
            snd = pygame.mixer.Sound(path)
            freq = pygame.mixer.get_init()[0]
            sd.play(pygame.sndarray.array(snd), samplerate=freq, device=idx)
            if RELAY_MONITOR:
                snd.play()
            sd.wait()
            time.sleep(0.3)
            return True
        except Exception as e:
            print(f"[Voice Relay Error]: {e}")
            return False
        finally:
            _last_relay_end[0] = time.time()
            relay_busy.clear()


def relay_voice(text_urdu: str = "", text_english: str = "") -> bool:
    urdu = re.sub(r'[*_#`~]', '', text_urdu or '').strip()
    eng = re.sub(r'[*_#`~]', '', text_english or '').strip()
    if urdu:
        clean, voice = urdu, URDU_VOICE
    elif eng:
        clean, voice = eng, VOICE_NAME
    else:
        return False
    try:
        path = _ensure_audio(clean, voice)
        if not path:
            print("[Voice Relay]: could not create the voice audio (check internet).")
            return False
        return relay_audio(path)
    except Exception as e:
        print(f"[Voice Relay Error]: {e}")
        return False


def relay_text(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if re.search(r'[\u0600-\u06FF]', text):
        return relay_voice(text_urdu=text)
    try:
        resp = _generate(
            "Message to speak aloud to teammates in a voice chat: " + json.dumps(text) +
            ". If it is Roman Urdu or Hindi written in English letters, rewrite it in Urdu script "
            "with exactly the same meaning (write gaming words like cover, rotate, site in Urdu letters). "
            "If it is plain English, return it unchanged. "
            'Reply ONLY with JSON: {"lang": "ur" or "en", "text": "..."}',
            types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = _parse_json(resp.text)
        if data.get("lang") == "ur":
            return relay_voice(text_urdu=data.get("text", ""))
        return relay_voice(text_english=data.get("text", text))
    except Exception:
        return relay_voice(text_english=text)


def _relay_preset(eng: str, urdu: str):
    if PRESET_LANG == "ur":
        relay_voice(text_urdu=urdu)
    else:
        relay_voice(text_english=eng)


def _quick_say_box():
    if _box_open.is_set():
        return
    try:
        import tkinter as tk
    except Exception:
        return
    _box_open.set()
    try:
        root = tk.Tk()
        root.title("Jarvis Voice")
        root.attributes("-topmost", True)
        root.geometry("480x64+420+300")
        entry = tk.Entry(root, font=("Segoe UI", 14))
        entry.pack(fill="x", padx=10, pady=14)

        def submit(_=None):
            text = entry.get().strip()
            root.destroy()
            if text:
                threading.Thread(target=relay_text, args=(text,), daemon=True).start()

        entry.bind("<Return>", submit)
        entry.bind("<Escape>", lambda e: root.destroy())
        root.after(150, lambda: (root.lift(), root.focus_force(), entry.focus_force()))
        root.mainloop()
    except Exception as e:
        print(f"[Quick Say Error]: {e}")
    finally:
        _box_open.clear()


def _register_voice_hotkeys():
    for combo, (eng, urdu) in VOICE_PRESETS.items():
        keyboard.add_hotkey(combo, lambda e=eng, u=urdu: threading.Thread(
            target=_relay_preset, args=(e, u), daemon=True).start())
    keyboard.add_hotkey("ctrl+alt+t", lambda: threading.Thread(target=_quick_say_box, daemon=True).start())


# ==========================================
# 3. DESKTOP & SYSTEM CONTROL TOOLS
# ==========================================
_last_yt = {"q": "", "t": 0.0}


def _first_video_id(query: str):
    try:
        req = urllib.request.Request(
            "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + "&sp=EgIQAQ%3D%3D",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                     "Accept-Language": "en-US,en;q=0.9"},
        )
        html = urllib.request.urlopen(req, timeout=4).read().decode("utf-8", "ignore")
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def _yt_play(query: str, search_only: bool = False, browser: str = None) -> str:
    now = time.time()
    if query.lower() == _last_yt["q"] and now - _last_yt["t"] < 10:
        return f"Already opened {query}."
    _last_yt["q"], _last_yt["t"] = query.lower(), now
    vid = None if search_only else _first_video_id(query)
    if vid:
        _open_url(f"https://www.youtube.com/watch?v={vid}", browser)
        return f"Playing {query}."
    _open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query), browser)
    return f"Opened YouTube results for {query}."


def open_youtube(query: str = "") -> str:
    """Opens YouTube. If a query is given, plays the best matching video in one tab.
    Never call this together with play_youtube_video."""
    if query.strip():
        return _yt_play(query.strip())
    _open_url("https://www.youtube.com")
    return "Opening YouTube, sir."


def youtube_subscribe(channel_name: str) -> str:
    """Searches YouTube for a channel and clicks its Subscribe button."""
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote(channel_name) + "&sp=EgIQAg%3D%3D")
    webbrowser.open(url)
    time.sleep(4)
    if _find_and_click(f"the 'Subscribe' button next to the channel named '{channel_name}' "
                       "(NOT a button that says 'Subscribed')"):
        return f"Clicked Subscribe for {channel_name}."
    return (f"No Subscribe button found for {channel_name}. "
            "It may already be subscribed, or you may not be signed in to YouTube.")


def play_youtube_video(query: str) -> str:
    """Plays a song or video on YouTube in ONE tab. Use this alone for 'play/open <song> on YouTube'."""
    return _yt_play(query)


def send_whatsapp_message(number_or_name: str, message: str) -> str:
    """Sends a WhatsApp TEXT message to a phone number OR a saved contact name."""
    digits = "".join(filter(str.isdigit, number_or_name))
    if len(digits) >= 10:
        encoded_msg = urllib.parse.quote(message)
        url = f"https://web.whatsapp.com/send?phone={digits}&text={encoded_msg}"
        webbrowser.open(url)
        time.sleep(WA_LOAD_WAIT)
        pyautogui.press('enter')
        return f"Message sent to {digits}."

    if WHATSAPP_MODE == "desktop":
        os.system("start whatsapp:")
        time.sleep(2.5)
        pyautogui.hotkey("ctrl", "f")
    else:
        webbrowser.open("https://web.whatsapp.com/")
        time.sleep(WA_LOAD_WAIT)
        pyautogui.hotkey("ctrl", "alt", "/")
    time.sleep(0.6)
    keyboard.write(number_or_name, delay=TYPE_DELAY)
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(0.8)
    keyboard.write(message, delay=TYPE_DELAY)
    time.sleep(0.2)
    pyautogui.press("enter")
    return f"Message sent to {number_or_name}."


def send_whatsapp_voice(contact_name: str, text_urdu_script: str = "", text_english: str = "") -> str:
    """Sends a WhatsApp VOICE MESSAGE to a saved contact, spoken in Jarvis's own voice.
    If the message is Roman Urdu, write it in Urdu script in text_urdu_script; if English, use
    text_english. Fill only one of them."""
    urdu = re.sub(r'[*_#`~]', '', text_urdu_script or '').strip()
    eng = re.sub(r'[*_#`~]', '', text_english or '').strip()
    if not (urdu or eng):
        return "No message text given."
    if _find_cable_device() is None:
        return "VB-CABLE not found, so I cannot record a voice message."
    clean, voice = (urdu, URDU_VOICE) if urdu else (eng, VOICE_NAME)

    t0 = time.time()
    if WHATSAPP_MODE == "desktop":
        os.system("start whatsapp:")
    else:
        webbrowser.open("https://web.whatsapp.com/")
    audio_path = _ensure_audio(clean, voice)
    if not audio_path:
        return "Voice generation failed (check internet)."
    wait = (2.5 if WHATSAPP_MODE == "desktop" else WA_LOAD_WAIT) - (time.time() - t0)
    if wait > 0:
        time.sleep(wait)

    pyautogui.hotkey("ctrl", "f") if WHATSAPP_MODE == "desktop" else pyautogui.hotkey("ctrl", "alt", "/")
    time.sleep(0.6)
    keyboard.write(contact_name, delay=TYPE_DELAY)
    time.sleep(1.0)
    pyautogui.press("enter")
    time.sleep(0.8)

    if not _find_and_click("the microphone icon button at the right end of the message input box"):
        return "Could not find the WhatsApp microphone button."
    time.sleep(0.8)
    if not relay_audio(audio_path):
        return "Voice relay failed while recording."
    if not _find_and_click("the green send (paper plane arrow) button at the right end of the voice recording bar"):
        pyautogui.press("enter")
    return f"Voice message sent to {contact_name}."


def say_in_voice_chat(text_urdu_script: str = "", text_english: str = "") -> str:
    """Speaks out loud in Jarvis's voice INTO the virtual microphone, so teammates in a game, Discord,
    a WhatsApp call or any app hear it. If the message is Roman Urdu, write it in Urdu script in
    text_urdu_script; if English, use text_english. Fill only one of them."""
    return "Said it in voice chat." if relay_voice(text_urdu_script, text_english) else "Voice relay failed."


def google_search(query: str) -> str:
    """Searches Google in the browser."""
    _open_url(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
    return f"Searching Google for {query}."


def open_website(url: str) -> str:
    """Opens any website, e.g. 'facebook.com'."""
    url = SITES.get(url.lower().strip(), url)
    _open_url(url)
    return f"Opened {url}."


def type_text(text: str) -> str:
    """Types text into whatever window is currently focused."""
    keyboard.write(text, delay=TYPE_DELAY)
    return "Typed."


def press_keys(keys: str) -> str:
    """Presses a key or shortcut, e.g. 'enter', 'ctrl+t', 'alt+f4', 'win+d'."""
    pyautogui.hotkey(*[k.strip() for k in keys.lower().split("+")])
    return f"Pressed {keys}."


def media_control(action: str) -> str:
    """Media keys: 'playpause', 'next', 'previous'."""
    key = {"next": "nexttrack", "previous": "prevtrack"}.get(action.lower().strip(), "playpause")
    pyautogui.press(key)
    return f"Media: {action}."


def get_time() -> str:
    """Returns the current date and time."""
    return time.strftime("%A, %d %B %Y, %I:%M %p")


def control_screen(task: str, max_steps: int = 12) -> str:
    """Does ANY other on-screen task by looking at the screen and using the mouse and keyboard
    step by step (max_steps up to 30). Use only when the specific tools cannot do the job."""
    history = []
    for _ in range(min(max(int(max_steps), 1), 30)):
        if stop_flag.is_set():
            history.append("stopped by the user")
            break
        if _game_active():
            history.append("blocked: a game window is active")
            break
        data = _screen_ask(
            "You are controlling a Windows PC. Task: " + task + ". Actions already done: "
            + json.dumps(history) + ". Look at the screenshot and reply ONLY with JSON for the single "
            'next action: {"action": "click" | "double_click" | "type" | "press" | "scroll" | "done", '
            '"x": 0-1000, "y": 0-1000, "text": "...", "keys": "ctrl+l", "amount": -5, "reason": "..."}. '
            "x and y are measured from the left and top edges, scaled 0 to 1000. "
            "Use action done when the task is finished or impossible."
        )
        act = data.get("action", "done")
        if act == "done":
            break
        try:
            if act in ("click", "double_click"):
                _click_scaled(float(data["x"]), float(data["y"]), double=(act == "double_click"))
            elif act == "type":
                keyboard.write(str(data.get("text", "")), delay=TYPE_DELAY)
            elif act == "press":
                pyautogui.hotkey(*[k.strip() for k in str(data.get("keys", "enter")).lower().split("+")])
            elif act == "scroll":
                pyautogui.scroll(int(data.get("amount", -5)) * 100)
        except pyautogui.FailSafeException:
            raise
        except Exception as e:
            history.append(f"{act} failed: {e}")
            continue
        history.append(f"{act}: {data.get('reason', '')}")
        time.sleep(0.8)
    return "Finished: " + "; ".join(history) if history else "Nothing to do."


def control_volume(action: str) -> str:
    """Adjusts or mutes the system volume ('up', 'down', 'mute')."""
    act = action.lower().strip()
    if "up" in act:
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Increased system volume."
    elif "down" in act:
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Decreased system volume."
    elif "mute" in act:
        pyautogui.press("volumemute")
        return "Toggled system volume mute."
    return "Done."


def _start_menu_launch(name: str) -> bool:
    safe = re.sub(r"[^\w\s.\-]", "", name).strip()
    if not safe:
        return False
    try:
        ps = ('(Get-StartApps | Where-Object { $_.Name -like "*' + safe + '*" } | Select-Object -First 1).AppID')
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        appid = (r.stdout or "").strip()
        if appid:
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid])
            return True
    except Exception:
        pass
    return False


def open_application(app_name: str) -> str:
    """Opens ANY Windows desktop application by name (notebook = Notepad). Returns after the window is ready."""
    name = app_name.lower().strip()
    # instant launcher first (app index, browsers, Riot / Valorant, built-in Windows apps)
    try:
        target = _resolve_app(name)
        if target and _launch_target(target):
            time.sleep(0.8)
            return f"Opened {app_name}. It is ready."
    except Exception as e:
        print(f"[Launcher]: {e}")
    # old slower chain (only if the fast launcher did not know the app)
    apps_map = {
        "notepad": "notepad.exe", "notebook": "notepad.exe", "calculator": "calc.exe",
        "calc": "calc.exe", "cmd": "cmd.exe", "terminal": "wt.exe",
        "chrome": "chrome", "explorer": "explorer.exe", "paint": "mspaint.exe",
    }
    try:
        if name in apps_map:
            subprocess.Popen(f'start "" {apps_map[name]}', shell=True)
        elif _start_menu_launch(name):
            pass
        elif shutil.which(name):
            subprocess.Popen([shutil.which(name)])
        else:
            pyautogui.press("win")
            time.sleep(0.6)
            keyboard.write(app_name, delay=TYPE_DELAY)
            time.sleep(0.8)
            pyautogui.press("enter")
        time.sleep(1.5)
        return f"Opened {app_name}. It is ready."
    except Exception as e:
        return f"Failed to launch {app_name}: {e}"


def wait_seconds(seconds: float = 1.0) -> str:
    """Waits a few seconds (max 10) between steps, e.g. for an app window to open."""
    time.sleep(min(max(float(seconds), 0), 10))
    return "Waited."


def create_text_file(filename: str, content: str) -> str:
    """Creates a .txt file on the Desktop with the content (one item per line) and opens it in Notepad."""
    try:
        name = filename if "." in os.path.basename(filename) else filename + ".txt"
        p = _resolve_path(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        subprocess.Popen(["notepad.exe", p])
        time.sleep(0.8)
        return f"Created file '{p}' and opened it in Notepad."
    except Exception as e:
        return f"Could not create file: {e}"


def calculate_in_calculator(expression: str) -> str:
    """Opens Calculator, types the math expression (e.g. '3*3+5/5+9*9') and presses Enter."""
    expr = expression.replace("x", "*").replace("×", "*").replace("÷", "/").replace(" ", "")
    if not re.fullmatch(r"[0-9+\-*/().%]+", expr):
        return "Invalid expression."
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        result = round(result, 6)
        if float(result).is_integer():
            result = int(result)
    except Exception:
        result = "?"
    open_application("calculator")
    time.sleep(0.6)
    try:
        focus_window("Calculator")
    except Exception:
        pass
    pyautogui.press("escape")
    keyboard.write(expr, delay=0.02)
    time.sleep(0.2)
    pyautogui.press("enter")
    return f"{expr} = {result}"


def get_system_status() -> str:
    """Checks CPU, RAM, and Battery."""
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    battery = psutil.sensors_battery()
    bat_str = f"{battery.percent}%" if battery else "Desktop PC"
    return f"CPU: {cpu}%, RAM: {ram}%, Battery: {bat_str}."


# ==========================================
# 3A. POWER TOOLS
# ==========================================
_BLOCKED_CMDS = ["format-volume", "diskpart", "format c:", "format d:", "rd /s /q c:\\",
                 "remove-item -recurse -force c:\\", "del /f /s /q c:\\", "cipher /w", "bcdedit"]


def _resolve_path(path: str) -> str:
    path = os.path.expanduser(path.strip().strip('"'))
    if not os.path.isabs(path):
        path = os.path.join(DESKTOP, path)
    return path


def run_powershell(command: str) -> str:
    """Runs a PowerShell command on this Windows PC and returns its output. Use it for ANY system
    task: create/move/copy files and folders, list files, kill or start processes, wifi, settings,
    installed programs, downloads, etc."""
    low = command.lower()
    if any(b in low for b in _BLOCKED_CMDS):
        return "Blocked: that command is too dangerous."
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, cwd=os.path.expanduser("~"))
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[-1500:] if out else "Command finished with no output."
    except subprocess.TimeoutExpired:
        return "Command is still running after 60s."
    except Exception as e:
        return f"PowerShell error: {e}"


def run_python_code(code: str) -> str:
    """Runs Python code on this PC and returns whatever it prints. Use it for calculations, data
    processing, file work, generating files, web requests, etc. Always print() the result."""
    path = os.path.join(tempfile.gettempdir(), f"jarvis_task_{int(time.time() * 1000)}.py")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, cwd=DESKTOP if os.path.isdir(DESKTOP) else None)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[-1500:] if out else "Code ran with no output."
    except subprocess.TimeoutExpired:
        return "Python code timed out after 60s."
    except Exception as e:
        return f"Python error: {e}"
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def read_text_file(path: str) -> str:
    """Reads a text file (relative paths mean the Desktop) and returns its content."""
    try:
        with open(_resolve_path(path), "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:3000]
    except Exception as e:
        return f"Could not read file: {e}"


def write_text_file(path: str, content: str, append: bool = False) -> str:
    """Writes (or appends) text to a file silently, without opening any app.
    Relative paths mean the Desktop. Creates folders if needed."""
    try:
        p = _resolve_path(path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8") as f:
            f.write(content)
        return f"Saved file: {p}"
    except Exception as e:
        return f"Could not write file: {e}"


def fetch_webpage_text(url: str) -> str:
    """Downloads a web page and returns its readable text (first 3000 characters)."""
    try:
        if not url.startswith("http"):
            url = "https://" + url
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()[:3000]
    except Exception as e:
        return f"Could not fetch page: {e}"


def describe_screen(question: str = "What is on the screen right now?") -> str:
    """Looks at the screen (the mouse cursor is marked in red) and answers a question about it."""
    try:
        resp = _generate([_screenshot_part(mark_cursor=True),
                          question + " " + _cursor_info("primary") + " Answer briefly."],
                         types.GenerateContentConfig())
        return (resp.text or "Could not read the screen.")[:1200]
    except Exception as e:
        return f"Screen error: {e}"


def get_cursor_position() -> str:
    """Returns exactly where the mouse cursor is (monitor, pixels, percent) and the active window."""
    try:
        win = pyautogui.getActiveWindowTitle() or "unknown"
    except Exception:
        win = "unknown"
    return _cursor_info("desktop") + f" Active window: {win}."


def click_on_screen(description: str, double: bool = False) -> str:
    """Finds a button/icon/link/text on the screen by description and clicks it."""
    try:
        if _find_and_click(description, double=bool(double)):
            return f"Clicked {description}."
        return f"Could not see {description} on the screen."
    except Exception as e:
        return f"Click error: {e}"


def scroll_screen(amount: int = -5) -> str:
    """Scrolls the page. Negative = down, positive = up."""
    pyautogui.scroll(int(amount) * 100)
    return "Scrolled."


def focus_window(title_part: str) -> str:
    """Brings an already open window to the front by part of its title."""
    try:
        wins = [w for w in pyautogui.getAllWindows() if title_part.lower() in (w.title or "").lower()]
        if not wins:
            return f"No window with '{title_part}' found."
        w = wins[0]
        try:
            if w.isMinimized:
                w.restore()
            w.activate()
        except Exception:
            pass
        time.sleep(0.5)
        return f"Focused: {w.title}"
    except Exception as e:
        return f"Could not focus window: {e}"


def take_screenshot() -> str:
    """Takes a screenshot and saves it on the Desktop."""
    try:
        os.makedirs(DESKTOP, exist_ok=True)
        path = os.path.join(DESKTOP, f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")
        pyautogui.screenshot().save(path)
        return f"Screenshot saved: {path}"
    except Exception as e:
        return f"Screenshot error: {e}"


def _save_image(data: bytes, mime: str, filename: str) -> str:
    base = re.sub(r'[\\/:*?"<>|]', "_", (filename or "drawing")).strip() or "drawing"
    base = os.path.splitext(base)[0] or "drawing"
    ext = ".jpg" if ("jpeg" in (mime or "").lower() or "jpg" in (mime or "").lower()) else ".png"
    os.makedirs(DESKTOP, exist_ok=True)
    path, n = os.path.join(DESKTOP, base + ext), 1
    while os.path.exists(path):
        path = os.path.join(DESKTOP, f"{base}_{n}{ext}")
        n += 1
    with open(path, "wb") as f:
        f.write(data)
    try:
        os.startfile(path)
    except Exception:
        pass
    return path


def generate_image(prompt: str, filename: str = "drawing") -> str:
    """Creates a realistic picture / drawing / artwork from a text description, saves it on the Desktop and
    opens it. Write the prompt in English and make it very detailed (subject, style, lighting, camera, mood)."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "No picture description given."
    errors = []
    try:
        img_client = genai.Client(http_options=types.HttpOptions(timeout=90000))
    except Exception as e:
        img_client = client
        errors.append(f"client: {str(e)[:60]}")
    for model in IMAGE_MODELS:
        if model in dead_models:
            continue
        try:
            resp = img_client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))
            for cand in (resp.candidates or []):
                for part in ((cand.content.parts if cand.content else None) or []):
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and inline.data:
                        return f"Picture created and opened: {_save_image(inline.data, inline.mime_type, filename)}"
            errors.append(f"{model}: no picture returned")
        except Exception as e:
            errors.append(f"{model}: {str(e)[:100]}")
            if _err_code(e) == 404:
                dead_models.add(model)
    try:
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:500])
               + "?width=1024&height=1024&nologo=true")
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                      timeout=90).read()
        if data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG":
            mime = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
            return f"Picture created (free backup service) and opened: {_save_image(data, mime, filename)}"
        errors.append("backup: not a picture")
    except Exception as e:
        errors.append(f"backup: {str(e)[:100]}")
    return "Could not create the picture. " + " | ".join(errors)[:400]


def search_web(query: str) -> str:
    """Searches the internet and returns the top results (title, link, short text). Use it for news, facts,
    prices, scores or anything you are not sure about."""
    try:
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": query}).encode(),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        page = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")

        def clean(s):
            return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s))).strip()

        links = re.findall(r'<a\s+([^>]*class="result__a"[^>]*)>(.*?)</a>', page, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', page, re.S)
        lines = []
        for i, (attrs, title) in enumerate(links[:6]):
            m = re.search(r'href="([^"]+)"', attrs)
            url = unescape(m.group(1)) if m else ""
            if "uddg=" in url:
                url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
            elif url.startswith("//"):
                url = "https:" + url
            snippet = clean(snippets[i]) if i < len(snippets) else ""
            lines.append(f"{i + 1}. {clean(title)} - {url}\n   {snippet}")
        if lines:
            return "\n".join(lines)[:2500]
        return "No results could be read."
    except Exception as e:
        return f"Search failed: {e}."


def remind_me(minutes: float, message: str, message_urdu: str = "") -> str:
    """Reminds the user out loud after some minutes. message = short reminder in Roman Urdu,
    message_urdu = the same reminder in Urdu script."""
    secs = max(float(minutes), 0.0) * 60

    def _fire_reminder():
        speak("Sir, yaad dehani: " + message,
              urdu=("سر، یاد دہانی: " + message_urdu) if message_urdu else None)

    t = threading.Timer(secs, _fire_reminder)
    t.daemon = True
    t.start()
    return f"Reminder set for {minutes:g} minutes from now (it only works while Jarvis is running)."


# ==========================================
# ⚡ 3A-1. GAME TAKE MODE
#   "game khelo", "2 min ke liye game sambhalo", "AFK mode"  ->  Jarvis moves / looks around in your game.
#   Runs in the BACKGROUND (Jarvis stays responsive). Ctrl+Alt+S or "game mode band karo" stops it.
#   The game window must be in front. WARNING: anti-cheat games (Valorant ...) can ban automated input.
# ==========================================
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput),
                ("mi", MouseInput),
                ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]


SCAN_CODES = {
    'w': 0x11, 'a': 0x1E, 's': 0x1F, 'd': 0x20,
    'space': 0x39, 'ctrl': 0x1D, 'shift': 0x2A,
    'e': 0x12, 'r': 0x13, 'q': 0x10, 'c': 0x2E
}

afk_stop = threading.Event()
afk_running = threading.Event()


def _direct_press(key_code, duration=0.2):
    """Holds a key (hardware scan code) for `duration` seconds. The key is ALWAYS released, even on stop."""
    extra = ctypes.c_ulong(0)

    def _send(flags):
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, key_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    _send(0x0008)
    try:
        end = time.time() + duration
        while time.time() < end and not afk_stop.is_set():
            time.sleep(0.02)
    finally:
        _send(0x0008 | 0x0002)


def _direct_mouse_move(dx: int, dy: int):
    ctypes.windll.user32.mouse_event(0x0001, int(dx), int(dy), 0, 0)


def _direct_mouse_click():
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def _afk_worker(duration: int):
    afk_running.set()
    try:
        wait_until = time.time() + GAME_AFK_START_DELAY
        while time.time() < wait_until:
            if afk_stop.is_set():
                return
            time.sleep(0.1)
        _beep()
        end_time = time.time() + duration
        actions = ['w', 'w', 'a', 'd', 's', 'space', 'turn_left', 'turn_right', 'look_around']
        if GAME_AFK_CLICK:
            actions.append('click')
        print(f"\n[Game Take Mode]: ACTIVE for {duration}s (Ctrl+Alt+S or 'game mode band karo' = stop)")
        while time.time() < end_time and not afk_stop.is_set():
            act = random.choice(actions)
            try:
                if act in SCAN_CODES:
                    _direct_press(SCAN_CODES[act], duration=random.uniform(0.25, 0.85))
                elif act == 'turn_left':
                    _direct_mouse_move(-120, 0)
                elif act == 'turn_right':
                    _direct_mouse_move(120, 0)
                elif act == 'look_around':
                    _direct_mouse_move(random.randint(-150, 150), random.randint(-40, 40))
                elif act == 'click':
                    _direct_mouse_click()
            except Exception as e:
                print(f"[Game Take Mode Error]: {e}")
            pause_until = time.time() + random.uniform(0.1, 0.35)
            while time.time() < pause_until and not afk_stop.is_set():
                time.sleep(0.02)
    finally:
        afk_running.clear()
        print("[Game Take Mode]: finished" if not afk_stop.is_set() else "[Game Take Mode]: stopped")
        try:
            _beep()
        except Exception:
            pass


def _start_game_afk(duration: int):
    """Starts the take-over in the background. Returns (ok, message)."""
    if not GAME_AFK_ENABLED:
        return False, "Game Take Mode is switched off (GAME_AFK_ENABLED = False in the settings)."
    if afk_running.is_set():
        return False, "Game Take Mode is already running. Press Ctrl+Alt+S to stop it."
    duration = int(min(max(int(duration), 10), GAME_AFK_MAX))
    afk_stop.clear()
    threading.Thread(target=_afk_worker, args=(duration,), daemon=True).start()
    return True, (f"Game Take Mode will start in {GAME_AFK_START_DELAY} seconds and run for {duration} seconds. "
                  "The game window must be in front. Ctrl+Alt+S stops it.")


def play_game_afk(duration_seconds: int = 120) -> str:
    """Game Take Mode: Jarvis takes over the keyboard and mouse in the user's game (moves around with W A S D,
    jumps, looks around) for duration_seconds (default 120 = 2 minutes) so the user can step away without going
    idle. Call it when the user says 'game khelo', 'game sambhalo', 'AFK mat hone dena', 'play for me'.
    It runs in the background and returns immediately."""
    ok, msg = _start_game_afk(int(duration_seconds))
    return msg


_NUM_WORDS = {"ek": 1, "aik": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4,
              "four": 4, "paanch": 5, "panch": 5, "five": 5, "chay": 6, "six": 6, "saat": 7, "seven": 7,
              "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10}


def _afk_duration(low: str) -> int:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|mins|mint|minute|minutes|minat)\b", low)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"(\d+)\s*(?:sec|secs|second|seconds)\b", low)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([a-z]+)\s*(?:min|mins|mint|minute|minutes|minat)\b", low)
    if m and m.group(1) in _NUM_WORDS:
        return _NUM_WORDS[m.group(1)] * 60
    return 120


def game_afk_command(low: str) -> bool:
    """Voice / typed switch for Game Take Mode. Returns True when the command was about it."""
    words = set(re.findall(r"[\w']+", low))
    is_game_word = bool(words & {"game", "gaming", "afk", "valorant", "takeover"})
    stop_words = words & {"stop", "band", "ruko", "rok", "roko", "cancel", "off", "disable", "khatam"}
    if stop_words and (is_game_word or "mode" in words or "take" in words):
        if afk_running.is_set():
            afk_stop.set()
            speak_lang("Game take mode stopped, sir.", "Ji sir, game take mode band kar diya.",
                       "جی سر، گیم ٹیک موڈ بند کر دیا۔")
        else:
            speak_lang("Game take mode is not running, sir.", "Sir, game take mode chal hi nahi raha.",
                       "سر، گیم ٹیک موڈ چل ہی نہیں رہا۔")
        return True

    start = False
    if "afk" in words:
        start = True
    elif words & {"game", "gaming", "valorant"}:
        if words & {"khelo", "khel", "khelna", "sambhalo", "sambhal", "takeover", "take"}:
            start = True
        elif "play" in words and not (words & {"youtube", "song", "video", "music", "gana", "gaana"}):
            start = True
    if not start:
        return False
    if words & {"kholo", "khol", "open", "launch", "start"} and not (words & {"afk", "take", "takeover"}):
        return False  # "valorant kholo" only opens the game

    dur = _afk_duration(low)
    ok, msg = _start_game_afk(dur)
    print(f"[Game Take Mode]: {msg}")
    if not ok:
        speak_lang("Sorry sir, I cannot start game take mode now.",
                   "Sir, abhi game take mode shuru nahi ho sakta. Console mein wajah likhi hai.",
                   "سر، ابھی گیم ٹیک موڈ شروع نہیں ہو سکتا۔ کنسول میں وجہ لکھی ہے۔")
        return True
    dur = int(min(max(dur, 10), GAME_AFK_MAX))
    if dur % 60 == 0:
        n = dur // 60
        en_t, ro_t, ur_t = f"{n} minute" + ("s" if n != 1 else ""), f"{n} minute", f"{n} منٹ"
    else:
        en_t, ro_t, ur_t = f"{dur} seconds", f"{dur} second", f"{dur} سیکنڈ"
    speak_lang(f"Game take mode on for {en_t}, sir. Switch to your game now. Press Control Alt S to stop.",
               f"Ji sir, game take mode {ro_t} ke liye on hai. Ab apni game par chale jao. "
               "Rokne ke liye Control Alt S dabao.",
               f"جی سر، گیم ٹیک موڈ {ur_t} کے لیے آن ہے۔ اب اپنی گیم پر چلے جاؤ۔ روکنے کے لیے کنٹرول آلٹ ایس دباؤ۔")
    return True


# ==========================================
# ⚡ 3A-2. SMART TOOLS: memory, research, weather, clipboard, windows
# ==========================================
def _load_mem() -> dict:
    with memory_lock:
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _save_mem(data: dict):
    with memory_lock:
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Memory Error]: {e}")


def remember(key: str, value: str) -> str:
    """Saves a fact about the user PERMANENTLY (name, likes, family, routines, notes). Use a short English
    key like 'user_name'. Call it whenever the user says 'yaad rakho' or tells you something personal."""
    key = (key or "").strip()
    if not key:
        return "No key given."
    mem = _load_mem()
    mem[key] = (value or "").strip()[:500]
    _save_mem(mem)
    return f"Remembered: {key} = {mem[key]}"


def forget(key: str) -> str:
    """Deletes one saved memory by its key (or 'all' to wipe the whole memory)."""
    key = (key or "").strip()
    if key.lower() == "all":
        _save_mem({})
        return "All memories deleted."
    mem = _load_mem()
    hit = next((k for k in mem if k.lower() == key.lower()), None)
    if hit:
        del mem[hit]
        _save_mem(mem)
        return f"Forgot {hit}."
    return f"No memory named '{key}'."


def recall_memories() -> str:
    """Returns everything Jarvis has saved about the user."""
    mem = _load_mem()
    return json.dumps(mem, ensure_ascii=False) if mem else "No memories saved yet."


def get_weather(city: str = "") -> str:
    """Gets the current weather for a city (empty city = the user's current location)."""
    try:
        url = "https://wttr.in/" + urllib.parse.quote(city.strip()) + "?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))
        cur = data["current_condition"][0]
        area = ""
        try:
            area = data["nearest_area"][0]["areaName"][0]["value"]
        except Exception:
            pass
        return (f"{area or city or 'Your area'}: {cur['weatherDesc'][0]['value']}, {cur['temp_C']}C "
                f"(feels like {cur['FeelsLikeC']}C), humidity {cur['humidity']}%, wind {cur['windspeedKmph']} km/h.")
    except Exception as e:
        return f"Could not get weather: {e}"


def clipboard_get() -> str:
    """Returns the text currently copied on the clipboard."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        out = (r.stdout or "").strip()
        return out[:3000] if out else "The clipboard is empty."
    except Exception as e:
        return f"Clipboard error: {e}"


def clipboard_set(text: str) -> str:
    """Copies the given text to the clipboard so the user can paste it anywhere."""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
                       input=text, text=True, encoding="utf-8", timeout=10)
        return "Copied to the clipboard."
    except Exception as e:
        return f"Clipboard error: {e}"


def list_windows() -> str:
    """Lists the titles of all open windows (to see what the user has open)."""
    try:
        titles = []
        for w in pyautogui.getAllWindows():
            t = (w.title or "").strip()
            if t and t not in titles:
                titles.append(t)
        return "; ".join(titles[:30]) if titles else "No windows found."
    except Exception as e:
        return f"Could not list windows: {e}"


def research_topic(topic: str) -> str:
    """Deep research: searches the internet, reads the top pages and returns a clear summary.
    Use it for news, current events, comparisons, facts, product or tech questions."""
    try:
        results = search_web(topic)
        urls = re.findall(r" - (https?://\S+)", results)
        pages = []
        for u in urls[:3]:
            txt = fetch_webpage_text(u)
            if txt and not txt.startswith("Could not fetch"):
                pages.append(f"SOURCE {u}:\n{txt[:2200]}")
        material = results + "\n\n" + "\n\n".join(pages)
        resp = _generate(
            "Using ONLY the material below, answer this question/topic accurately and concisely "
            "(max 8 short lines, include key numbers and dates). If the material is not enough, "
            "say what is missing.\n\nTOPIC: " + topic + "\n\n" + material[:9000],
            types.GenerateContentConfig())
        return (resp.text or "No summary produced.")[:2500]
    except Exception as e:
        return f"Research failed: {e}"


# ==========================================
# ⚡ 3A-3. VIP PC CONTROL TOOLS
# ==========================================
def close_window(title_part: str) -> str:
    """Closes an open window by part of its title."""
    try:
        wins = [w for w in pyautogui.getAllWindows() if title_part.lower() in (w.title or "").lower()]
        if not wins:
            return f"No window with '{title_part}' found."
        title = wins[0].title
        wins[0].close()
        return f"Closed: {title}"
    except Exception as e:
        return f"Could not close window: {e}"


def open_path(path: str) -> str:
    """Opens a file or folder with its default program (relative paths mean the Desktop)."""
    p = _resolve_path(path)
    if not os.path.exists(p):
        return f"Not found: {p}"
    try:
        os.startfile(p)
        return f"Opened: {p}"
    except Exception as e:
        return f"Could not open: {e}"


def find_files(name_part: str, folder: str = "") -> str:
    """Searches for files/folders whose name contains name_part (folder empty = the user's home folder)."""
    root = _resolve_path(folder) if folder.strip() else os.path.expanduser("~")
    skip = {"appdata", "node_modules", ".git", "$recycle.bin", "windows", "__pycache__", ".cache"}
    needle = (name_part or "").lower().strip()
    if not needle:
        return "No name given."
    found, t0 = [], time.time()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        for n in dirs + files:
            if needle in n.lower():
                found.append(os.path.join(dirpath, n))
        if len(found) >= 25 or time.time() - t0 > 12:
            break
    if not found:
        return f"Nothing found for '{name_part}' in {root}."
    return "\n".join(found[:25])


def _recycle_command(p: str) -> str:
    q = p.replace("'", "''")
    call = "DeleteDirectory" if os.path.isdir(p) else "DeleteFile"
    return ("Add-Type -AssemblyName Microsoft.VisualBasic; "
            f"[Microsoft.VisualBasic.FileIO.FileSystem]::{call}('{q}','OnlyErrorDialogs','SendToRecycleBin')")


def delete_to_recycle_bin(path: str) -> str:
    """Moves a file or folder to the Recycle Bin (safe delete, can be restored)."""
    p = os.path.abspath(_resolve_path(path))
    if not os.path.exists(p):
        return f"Not found: {p}"
    home = os.path.abspath(os.path.expanduser("~"))
    protected = {x.lower().rstrip("\\/") for x in (
        os.environ.get("SystemRoot", "C:\\Windows"), "C:\\", "C:\\Program Files",
        "C:\\Program Files (x86)", "C:\\Users", home, DESKTOP,
        os.path.join(home, "Documents"), os.path.join(home, "Downloads"))}
    protected = {os.path.abspath(x + "\\" if len(x) == 2 else x).lower().rstrip("\\/") for x in protected}
    if p.lower().rstrip("\\/") in protected:
        return "Blocked: that folder is too important to delete."
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _recycle_command(p)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return f"Could not delete: {(r.stderr or r.stdout).strip()[:200]}"
        return f"Moved to the Recycle Bin: {p}"
    except Exception as e:
        return f"Could not delete: {e}"


def power_action(action: str) -> str:
    """Power actions: 'lock', 'sleep', 'restart' (30s delay), 'shutdown' (30s delay), 'cancel' (stops a pending restart/shutdown)."""
    a = (action or "").lower().strip()
    cmds = {
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "restart": ["shutdown", "/r", "/t", "30"],
        "shutdown": ["shutdown", "/s", "/t", "30"],
        "cancel": ["shutdown", "/a"],
    }
    if a not in cmds:
        return "Unknown power action. Use lock, sleep, restart, shutdown or cancel."
    try:
        subprocess.run(cmds[a], timeout=15)
    except Exception as e:
        return f"Power action failed: {e}"
    if a in ("restart", "shutdown"):
        return f"PC will {a} in 30 seconds."
    return f"Done: {a}."


def set_volume_level(percent: int) -> str:
    """Sets the system volume to about the given percent (0 to 100)."""
    p = max(0, min(100, int(percent)))
    for _ in range(50):
        pyautogui.press("volumedown")
    for _ in range(round(p / 2)):
        pyautogui.press("volumeup")
    return f"Volume set to about {p}%."


_PAGE_TEMPLATE = ("<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>"
                  "body{{background:#0f1218;color:#e6e9ef;font-family:Segoe UI,Arial,sans-serif;"
                  "max-width:860px;margin:40px auto;padding:0 20px;line-height:1.7;font-size:18px}}"
                  "h1,h2,h3{{color:#4fc3f7}}code,pre{{background:#1b2230;border-radius:6px;color:#a5d6a7}}"
                  "pre{{padding:14px;overflow:auto}}code{{padding:2px 5px}}a{{color:#80cbc4}}"
                  "li{{margin:6px 0}}</style></head><body><h1>{title}</h1>{body}</body></html>")


def show_page(title: str, html_body: str) -> str:
    """Shows a nicely formatted page in the browser (lessons, tutorials, notes, long answers).
    html_body must be simple HTML (h2, p, ul, li, pre, code)."""
    try:
        body = re.sub(r"(?is)<script.*?</script>", "", html_body or "")
        safe_title = unescape(re.sub(r"<[^>]+>", "", title or "Jarvis")).replace("<", "").replace(">", "")
        folder = os.path.join(DESKTOP, "Jarvis_Pages")
        os.makedirs(folder, exist_ok=True)
        slug = re.sub(r"[^\w\-]+", "_", safe_title).strip("_")[:40] or "page"
        path = os.path.join(folder, f"{slug}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_PAGE_TEMPLATE.format(title=safe_title, body=body))
        webbrowser.open("file:///" + path.replace("\\", "/"))
        return f"Page opened in the browser: {path}"
    except Exception as e:
        return f"Could not show page: {e}"


# ==========================================
# 3B. INSTANT FAST PATH
# ==========================================
# every phrase has Roman Urdu, Urdu script AND English: (roman, urdu, english)
ACKS = {
    "play":   ("Ji sir, chala raha hoon.",      "جی سر، چلا رہا ہوں۔",       "Playing it now, sir."),
    "open":   ("Ji sir, khol raha hoon.",        "جی سر، کھول رہا ہوں۔",       "Opening it, sir."),
    "search": ("Ji sir, search kar raha hoon.",  "جی سر، سرچ کر رہا ہوں۔",   "Searching, sir."),
    "done":   ("Ji sir, ho gaya.",               "جی سر، ہو گیا۔",             "Done, sir."),
}
_ACTION = {"open", "play", "kholo", "khol", "chalao", "chala", "lagao", "laga", "bajao", "baja",
           "sunao", "suna", "search", "dhoondo", "dhundo", "start", "launch"}
_PLAY_WORDS = {"play", "chalao", "chala", "lagao", "laga", "bajao", "baja", "sunao", "suna"}
_PREP = {"mein", "mai", "me", "pe", "par", "per", "pr", "on", "in"}
_LEAD = {"jarvis", "hey", "please", "plz", "open", "play", "youtube", "yt", "google", "kholo", "khol",
         "chalao", "chala", "lagao", "laga", "bajao", "baja", "sunao", "suna", "search", "dhoondo",
         "dhundo", "start", "launch", "aur", "and", "then", "phir", "fir"} | _PREP
_TRAIL = {"kholo", "khol", "karo", "kro", "kar", "chalao", "chala", "lagao", "laga", "bajao", "baja",
          "play", "open", "search", "sunao", "suna", "dhoondo", "dhundo", "please", "plz", "youtube",
          "yt", "google", "mein", "mai", "me", "pe", "par", "per", "pr", "on", "in", "ko", "jarvis",
          "video", "song", "gana", "gaana", "ka", "ki", "ke"}
_CONJ = {"aur", "and", "then", "phir", "fir"}
_APP_WORDS = {"notepad", "notebook", "calculator", "calc", "chrome", "cmd", "terminal", "explorer"}
# "valorant" and "discord" are NOT in this list, so "valorant kholo" / "discord kholo" are INSTANT.
# (Anything about teammates / voice chat / messages / files / games still goes to Gemini.)
_COMPLEX = {"subscribe", "message", "msg", "bhejo", "send",
            "team", "teammates", "teammate", "voice", "bolo", "kaho", "keh",
            "banao", "likho", "write", "create", "file", "calculate", "game", "khel", "khelo"}


def _ack(kind: str):
    roman, urdu, en = ACKS[kind]
    speak_lang(en, roman, urdu)


def _clean_query(words):
    q = list(words)
    prev = None
    while q and q[0] in _LEAD:
        if q[0] in _PREP and prev not in {"youtube", "yt", "google"}:
            break
        prev = q.pop(0)
    while q and q[-1] in _TRAIL:
        q.pop()
    return q


# ==========================================
# ⚡ 3B-0. SMALL TALK (instant, no Gemini): hello / salam / kaise ho / shukriya ...
# ==========================================
_ST_FILLER = {"jarvis", "sir", "please", "plz", "yaar", "bhai", "arre", "oye", "ok", "okay", "hey"}
_ST_PHRASES = {
    "greet": {"hello", "hi", "hallo", "helo", "hii", "hello hello", "hi hi", "hello hi", "hi hello"},
    "salam": {"salam", "salaam", "assalam o alaikum", "assalamualaikum", "assalam alaikum", "asalam o alaikum",
              "aoa", "assalamu alaikum", "salam alaikum", "assalam o alikum", "assalamu alaykum",
              "as salam o alaikum", "aslam o alaikum", "assalam o alaikum jarvis"},
    "howru": {"how are you", "how are you doing", "kaise ho", "kese ho", "kaisay ho", "kaise hain",
              "aap kaise ho", "tum kaise ho", "kya haal hai", "kya hal hai", "kya haal", "kia haal hai",
              "how r u", "aap kaise hain", "kaise hain aap", "kaise ho aap"},
    "thanks": {"thank you", "thanks", "thank u", "shukriya", "shukria", "thanks a lot", "bohat shukriya",
               "bahut shukriya", "meherbani", "thank you very much"},
    "there": {"are you there", "you there", "sun rahe ho", "sunn rahe ho", "kahan ho", "hello are you there",
              "kya tum sun rahe ho", "sunai de raha hai"},
    "morning": {"good morning", "subah bakhair", "subha bakhair"},
    "evening": {"good evening"},
    "night": {"good night", "shab bakhair"},
}
# key -> (english, roman urdu, urdu script, prefer Urdu unless English-only mode)
_ST_REPLIES = {
    "greet":   ("Hello sir, at your service.", "Ji sir, hukam kijiye.", "جی سر، حکم کیجیے۔", False),
    "salam":   ("Peace be upon you, sir. How can I help?", "Walaikum assalam sir, ji farmaiye.",
                "وعلیکم السلام سر، جی فرمائیے۔", True),
    "howru":   ("I am doing great, sir. How can I help you?", "Main bilkul theek hoon sir. Aap bataiye?",
                "میں بالکل ٹھیک ہوں سر۔ آپ بتائیے؟", False),
    "thanks":  ("You are welcome, sir.", "Koi baat nahi sir.", "کوئی بات نہیں سر۔", False),
    "there":   ("Yes sir, I am here.", "Ji sir, main yahin hoon.", "جی سر، میں یہیں ہوں۔", False),
    "morning": ("Good morning, sir.", "Subah bakhair sir.", "صبح بخیر سر۔", False),
    "evening": ("Good evening, sir.", "Shaam bakhair sir.", "شام بخیر سر۔", False),
    "night":   ("Good night, sir.", "Shab bakhair sir.", "شب بخیر سر۔", False),
    "empty":   ("Yes sir?", "Ji sir?", "جی سر؟", False),
}


def smalltalk_command(low: str) -> bool:
    """Greetings and polite chat are answered instantly (no Gemini, no waiting). True = handled."""
    words = [w for w in re.findall(r"[\w']+", low) if w not in _ST_FILLER]
    if len(words) > 6:
        return False
    t = " ".join(words)
    key = None
    key = None
    for k, phrases in _ST_PHRASES.items():
        if t in phrases:
            key = k
            break
    if key is None and not words and ("jarvis" in low or "hey" in low):
        key = "empty"
    if key is None:
        return False
    if key is None:
        return False
    en, roman, urdu, ur_first = _ST_REPLIES[key]
    if ur_first and LANG_MODE != "en":
        speak(roman, urdu=urdu)
    else:
        speak_lang(en, roman, urdu)
    return True


# ==========================================
# ⚡ 3B-2. INSTANT APP LAUNCHER + MULTI-STEP COMMANDS
#   "brave kholo", "valorant kholo", "riot kholo", "calculator kholo", "notepad kholo" ...
#   "brave kholo aur new tab kholo aur youtube kholo"  -> all done in about 1-3 seconds, NO Gemini.
# ==========================================
APP_INDEX = {}                       # normalized name -> ("file", path) | ("appid", AppID)
_lnk_index_ready = threading.Event()
_app_index_ready = threading.Event()


def _norm_app(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def _build_app_index():
    """Runs once in the background: reads the Start Menu / Desktop shortcuts, then the Store apps."""
    try:
        roots = [
            os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
            os.path.join(os.environ.get("OneDrive", ""), "Desktop") if os.environ.get("OneDrive") else "",
        ]
        skip = ("uninstall", "readme", "release notes", "documentation", "license", "manual", "website", "help")
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for dp, _dn, fn in os.walk(root):
                for f in fn:
                    base, ext = os.path.splitext(f)
                    if ext.lower() not in (".lnk", ".url"):
                        continue
                    key = _norm_app(base)
                    if not key or any(s in key for s in skip):
                        continue
                    APP_INDEX.setdefault(key, ("file", os.path.join(dp, f)))
    except Exception as e:
        print(f"[Apps Error]: {e}")
    _lnk_index_ready.set()
    try:  # Microsoft Store apps (WhatsApp, Spotify store version, Calculator ...)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        for a in data:
            key = _norm_app(a.get("Name", ""))
            appid = a.get("AppID", "")
            if key and appid and key not in APP_INDEX:
                APP_INDEX[key] = ("appid", appid)
    except Exception as e:
        print(f"[Apps]: Store app list not available ({str(e)[:80]})")
    _app_index_ready.set()
    print(f"[Apps]: {len(APP_INDEX)} apps indexed (instant launch ready)")


def _index_search(n: str):
    keys = list(APP_INDEX.keys())
    if not keys:
        return None
    if n in APP_INDEX:
        return APP_INDEX[n]
    if len(n) < 3:
        return None
    starts = sorted([k for k in keys if k.startswith(n)], key=len)
    if starts:
        return APP_INDEX[starts[0]]
    if len(n) >= 4:
        inside = sorted([k for k in keys if n in k], key=len)
        if inside:
            return APP_INDEX[inside[0]]
    close = difflib.get_close_matches(n, keys, n=1, cutoff=0.82)
    return APP_INDEX[close[0]] if close else None


def _index_lookup(n: str):
    if not _lnk_index_ready.is_set():
        _lnk_index_ready.wait(3)
    hit = _index_search(n)
    if hit is None and not _app_index_ready.is_set():
        _app_index_ready.wait(4)
        hit = _index_search(n)
    return hit


_BUILTIN_APPS = {
    "notepad": "notepad.exe", "notebook": "notepad.exe", "note pad": "notepad.exe",
    "calculator": "calc.exe", "calc": "calc.exe", "calculater": "calc.exe",
    "paint": "mspaint.exe", "cmd": "cmd.exe", "command prompt": "cmd.exe",
    "powershell": "powershell.exe", "terminal": "wt.exe",
    "task manager": "taskmgr.exe", "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "files": "explorer.exe", "control panel": "control.exe", "settings": "ms-settings:",
    "snipping tool": "snippingtool.exe", "wordpad": "write.exe",
    "camera": "microsoft.windows.camera:", "store": "ms-windows-store:", "microsoft store": "ms-windows-store:",
}
_BROWSER_ALIASES = {
    "brave": "brave", "brave browser": "brave", "chrome": "chrome", "google chrome": "chrome",
    "edge": "edge", "microsoft edge": "edge", "firefox": "firefox", "mozilla firefox": "firefox",
    "mozilla": "firefox",
}
_BROWSER_TITLES = {"brave": ["brave"], "chrome": ["chrome"], "edge": ["edge"], "firefox": ["firefox", "mozilla"]}
_BROWSER_EXE = {"brave": "brave.exe", "chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"}
_BROWSER_REL = {
    "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
    "chrome": [r"Google\Chrome\Application\chrome.exe"],
    "edge": [r"Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"Mozilla Firefox\firefox.exe"],
}
_browser_cache = {}
_riot_cache = []


def _reg_app_path(exe: str):
    try:
        import winreg
        sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    v, _ = winreg.QueryValueEx(k, "")
                    v = (v or "").strip().strip('"')
                    if v and os.path.exists(v):
                        return v
            except OSError:
                continue
    except Exception:
        pass
    return None


def _find_browser(key: str):
    if not key:
        return None
    if key in _browser_cache:
        return _browser_cache[key]
    found = None
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    for base in (pf, pf86, local):
        if not base:
            continue
        for rel in _BROWSER_REL.get(key, []):
            p = os.path.join(base, rel)
            if os.path.exists(p):
                found = p
                break
        if found:
            break
    if not found and key in _BROWSER_EXE:
        found = _reg_app_path(_BROWSER_EXE[key]) or shutil.which(_BROWSER_EXE[key])
    _browser_cache[key] = found
    return found


def _riot_client_path():
    if _riot_cache:
        return _riot_cache[0]
    found = None
    try:
        p = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Riot Games\RiotClientInstalls.json")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in ("rc_default", "rc_live", "rc_beta"):
            v = data.get(k)
            if v and os.path.exists(v):
                found = v
                break
    except Exception:
        pass
    if not found:
        for p in (r"C:\Riot Games\Riot Client\RiotClientServices.exe",
                  os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                               r"Riot Games\Riot Client\RiotClientServices.exe")):
            if os.path.exists(p):
                found = p
                break
    _riot_cache.append(found)
    return found


def _resolve_app(name: str):
    """Returns how to launch an app by name, or None when it is not found:
    ("browser", key, exe, fallback) | ("exe", path, args) | ("builtin", name) | ("file", path) | ("appid", id)"""
    n = _norm_app(name)
    if len(n) < 2:
        return None
    if n in _BROWSER_ALIASES:
        key = _BROWSER_ALIASES[n]
        exe = _find_browser(key)
        fallback = None if exe else (_index_lookup(key) or (_index_lookup(key + " browser")))
        if exe or fallback:
            return ("browser", key, exe, fallback)
        return None
    if n in ("valorant", "valo") or (len(n) >= 6 and n.startswith("val")
                                     and difflib.SequenceMatcher(None, n, "valorant").ratio() >= 0.8):
        rc = _riot_client_path()
        if rc:
            return ("exe", rc, ["--launch-product=valorant", "--launch-patchline=live"])
        return _index_lookup("valorant")
    if n in ("riot", "riot client", "riot games", "riot launcher"):
        hit = _index_lookup("riot client")
        if hit:
            return hit
        rc = _riot_client_path()
        return ("exe", rc, []) if rc else None
    if n in _BUILTIN_APPS:
        return ("builtin", _BUILTIN_APPS[n])
    return _index_lookup(n)


def _launch_target(t) -> bool:
    kind = t[0]
    try:
        if kind == "browser":
            if t[2]:
                subprocess.Popen([t[2]])
                return True
            if len(t) > 3 and t[3]:
                return _launch_target(t[3])
            return False
        if kind == "exe":
            subprocess.Popen([t[1]] + list(t[2]), cwd=os.path.dirname(t[1]) or None)
            return True
        if kind in ("builtin", "file"):
            os.startfile(t[1])
            return True
        if kind == "appid":
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + t[1]])
            return True
    except Exception as e:
        print(f"[Launch Error]: {e}")
    return False


def _open_url(url: str, browser: str = None):
    """Opens a link. browser = 'brave' / 'chrome' / 'edge' / 'firefox' (None = PREFERRED_BROWSER or Windows default)."""
    url = (url or "").strip()
    if not url:
        return
    if not re.match(r"^[a-z][a-z0-9+.\-]*:", url, re.I):
        url = "https://" + url
    key = browser or PREFERRED_BROWSER
    exe = _find_browser(key) if key else None
    if exe:
        try:
            subprocess.Popen([exe, url])
            return
        except Exception as e:
            print(f"[Browser Error]: {e}")
    webbrowser.open(url)


def _wait_window(keys, timeout: float = 8.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            for w in pyautogui.getAllWindows():
                t = (w.title or "").lower()
                if t and any(k in t for k in keys):
                    return w
        except Exception:
            pass
        time.sleep(0.1)
    return None


def _focus_win(w):
    try:
        if w.isMinimized:
            w.restore()
    except Exception:
        pass
    try:
        w.activate()
    except Exception:
        try:
            w.minimize()
            w.restore()
        except Exception:
            pass


def _browser_keys(key, combo):
    """Sends a shortcut (new tab, new window, close tab) to the browser. Never into a protected game window."""
    if key:
        w = _wait_window(_BROWSER_TITLES.get(key, [key]), 8.0)
        if w:
            _focus_win(w)
            time.sleep(0.35)
    if _game_active():
        return
    pyautogui.hotkey(*combo)


_SPLIT_RE = re.compile(r"\s+(?:aur|and|phir|fir|then|or|also|uske baad|uskay baad|us ke baad)\s+|\s*[,;]\s*")
_NEWTAB_RE = re.compile(r"\b(?:new|naya|nayi|naye|nai)\s+(?:tab|window)\b")
_CLOSETAB_RE = re.compile(r"\b(?:close|band)\s+(?:the\s+|this\s+)?tab\b|\btab\s+(?:band|close)\b")
_DOMAIN_RE = re.compile(r"\b[a-z0-9\-]+\.(?:com|org|net|pk|io|co|edu|gov|ai|tv|me)\b")
_OPEN_WORDS = {"open", "kholo", "khol", "kholna", "kholiye", "kholein", "kholen", "kholdo", "kholde",
               "start", "launch", "run", "chalao", "chala", "chalado", "chaladen", "lagao", "laga", "show"}
_FILLER = {"jarvis", "hey", "please", "plz", "zara", "mujhe", "mera", "meri", "mere", "ko", "ka", "ki", "ke",
           "ek", "aik", "a", "the", "to", "jaldi", "bhi", "ab", "abhi", "yaar", "bhai", "sir", "karo", "kro",
           "kar", "kardo", "kardein", "do", "dena", "de", "dijiye"}
_NOISE = _FILLER | _OPEN_WORDS | _PREP | {"aur", "and", "then", "phir", "fir", "also", "or"}


def _resolve_target(cand: str):
    n = _norm_app(cand)
    if not n:
        return None
    if not (n == "whatsapp" and WHATSAPP_MODE == "desktop") and n in SITES:
        return ("site", SITES[n])
    t = _resolve_app(n)
    return ("app", t) if t else None


def _parse_segment(seg: str, multi: bool):
    """One piece of a command -> a list of steps, or None when Jarvis does not understand it."""
    m = _NEWTAB_RE.search(seg)
    if m:
        rest = (seg[:m.start()] + " " + seg[m.end():]).strip()
        rest_words = re.findall(r"[\w']+", rest)
        head = [("newwin",) if "window" in m.group(0) else ("newtab",)]
        if all(w in _NOISE for w in rest_words):
            return head
        sub = _parse_segment(rest, True)
        return head + sub if sub else None
    if _CLOSETAB_RE.search(seg):
        return [("closetab",)]

    words = re.findall(r"[\w']+", seg)
    if not words:
        return []
    wset = set(words)
    has_open = bool(wset & _OPEN_WORDS)
    if not (has_open or multi):
        return None
    core = [w for w in words if w not in _NOISE]
    if not core:
        return None

    d = _DOMAIN_RE.search(seg)
    if d and len(core) <= 3:
        return [("site", d.group(0))]

    tgt = _resolve_target(" ".join(core))
    if tgt:
        return [tgt]

    # "brave mein youtube kholo"  /  "youtube kholo brave pe"
    pm = re.match(r"^(.*?)\b(?:mein|me|pe|par|per|on|in)\b(.*)$", seg)
    if pm:
        left = [w for w in re.findall(r"[\w']+", pm.group(1)) if w not in _NOISE]
        right = [w for w in re.findall(r"[\w']+", pm.group(2)) if w not in _NOISE]
        tl = _resolve_target(" ".join(left)) if left else None
        tr = _resolve_target(" ".join(right)) if right else None
        if tl and tl[0] == "app" and tl[1][0] == "browser" and tr:
            return [tl, tr]
        if tr and tr[0] == "app" and tr[1][0] == "browser" and tl:
            return [tr, tl]

    if wset & {"youtube", "yt"} and (wset & _ACTION):
        q = _clean_query(words)
        if q and not (_CONJ & set(q)):
            return [("yt", " ".join(q), bool(wset & {"search", "dhoondo", "dhundo"}))]
        return None
    if "google" in wset and (wset & _ACTION):
        q = _clean_query(words)
        if q and not (_CONJ & set(q)):
            return [("google", " ".join(q))]
        return None
    return None


def _parse_steps(text: str):
    low = re.sub(r"\s+", " ", (text or "").lower().replace("you tube", "youtube")).strip()
    segs = [s.strip() for s in _SPLIT_RE.split(low) if s and s.strip()]
    if not segs:
        return None
    multi = len(segs) > 1
    steps = []
    for seg in segs:
        sub = _parse_segment(seg, multi)
        if sub is None:
            return None
        steps += sub
    return steps or None


def _exec_steps(steps) -> bool:
    ctx = {"browser": None}
    n = len(steps)
    i = 0
    ok = True
    while i < n:
        st = steps[i]
        kind = st[0]
        try:
            if kind == "app":
                target = st[1]
                if target[0] == "browser":
                    ctx["browser"] = target[1]
                    j = i + 1
                    if j < n and steps[j][0] == "newtab":
                        j += 1
                    if j < n and steps[j][0] == "site":  # browser + (new tab) + site = ONE launch with the link
                        _open_url(steps[j][1], target[1])
                        i = j + 1
                        continue
                _launch_target(target)
            elif kind == "site":
                _open_url(st[1], ctx["browser"])
            elif kind == "yt":
                _yt_play(st[1], search_only=st[2], browser=ctx["browser"])
            elif kind == "google":
                _open_url("https://www.google.com/search?q=" + urllib.parse.quote(st[1]), ctx["browser"])
            elif kind == "newtab":
                if i + 1 < n and steps[i + 1][0] == "site":  # "new tab" + site = the site opens in a new tab
                    _open_url(steps[i + 1][1], ctx["browser"])
                    i += 2
                    continue
                _browser_keys(ctx["browser"], ("ctrl", "t"))
            elif kind == "newwin":
                _browser_keys(ctx["browser"], ("ctrl", "n"))
            elif kind == "closetab":
                _browser_keys(ctx["browser"], ("ctrl", "w"))
        except Exception as e:
            print(f"[Step Error]: {kind}: {e}")
            ok = False
        i += 1
    return ok


# ==========================================
# ⚡ 3B-3. TABS / TAB GROUPS INSIDE A BROWSER
#   "brave kholo, uske andr study tab kholo aur uske andr google notebook kholo"
#   (the browser opens while Gemini reads the command; the tab strip is looked at first)
# ==========================================
def _window_region(w):
    sw, sh = pyautogui.size()
    try:
        l = max(0, int(w.left))
        t = max(0, int(w.top))
        r = min(sw, int(w.left + w.width))
        b = min(sh, int(w.top + w.height))
        if r - l >= 200 and b - t >= 200:
            return (l, t, r - l, b - t)
    except Exception:
        pass
    return (0, 0, sw, sh)


def _ask_in_region(prompt: str, region):
    """Takes a picture of ONE region of the screen (bigger text = better reading) and asks Gemini about it."""
    img = pyautogui.screenshot(region=region)
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75)
    part = types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")
    resp = _generate([part, prompt], types.GenerateContentConfig(response_mime_type="application/json"))
    return _parse_json(resp.text)


def _open_browser_tab(browser: str, tab_names: str, prelaunched: bool = False):
    """Returns (ok, message). prelaunched = the browser was already started a moment ago by tab_command."""
    key = _BROWSER_ALIASES.get(_norm_app(browser or ""), None) or PREFERRED_BROWSER or "brave"
    names = []
    for n in re.split(r"[,;|>]+", tab_names or ""):
        n = re.sub(r"\b(?:tab|tabs|group|groups)\b", " ", n, flags=re.I)
        n = re.sub(r"\s+", " ", n).strip()
        if n:
            names.append(n)
    if not names:
        return False, "No tab name given."
    titles = _BROWSER_TITLES.get(key, [key])

    w = _wait_window(titles, 15.0 if prelaunched else 0.3)
    fresh = prelaunched
    if not w:
        if prelaunched:
            return False, f"{key} did not show a window."
        target = _resolve_app(key)
        if not target or not _launch_target(target):
            return False, f"Could not open {key}."
        w = _wait_window(titles, 12.0)
        if not w:
            return False, f"{key} did not show a window."
        fresh = True
    time.sleep(1.2 if fresh else 0.25)  # a brand new browser needs a moment to draw its tabs
    _focus_win(w)
    time.sleep(0.3)

    done = []
    for name in names:
        clicked = False
        for _attempt in range(3):
            if stop_flag.is_set():
                return False, "Stopped by the user."
            if _game_active():
                return False, "Blocked: a protected game window is in front."
            full = _window_region(w)
            if _attempt == 0:
                region = (full[0], full[1], full[2], min(full[3], 170))  # only the tab strip: small and fast
                where = "the TOP part (tab strip) of"
            else:
                region = full
                where = "the whole"
            prompt = (
                f"This is a screenshot of {where} a {key} browser window. Find the tab or tab GROUP named '{name}' "
                "in the tab strip (or in a vertical tab sidebar if there is one). A tab group is a coloured "
                "rounded label that contains the group's name; when it is collapsed only that label is visible, "
                "when it is expanded the group's tabs follow it. A normal tab shows a small icon and a page title. "
                "Match the name loosely (ignore upper/lower case, small spelling differences, extra words). "
                'Reply ONLY with JSON like {"found": true, "kind": "group", "expanded": false, "x": 500, "y": 30} '
                "where kind is group or tab, expanded says whether that group is already open, and x and y are the "
                "CENTER of the label or tab measured from the left and top edges of THIS picture and scaled 0 to 1000. "
                'If it is not visible reply {"found": false}.')
            try:
                data = _ask_in_region(prompt, region)
            except Exception as e:
                print(f"[Tab Vision Error]: {str(e)[:150]}")
                data = {}
            if data.get("found"):
                kind = str(data.get("kind", "")).lower()
                expanded = bool(data.get("expanded", False))
                if kind == "group" and expanded:
                    clicked = True  # the group is already open, clicking it would CLOSE it
                    break
                px = region[0] + int(float(data["x"]) / 1000 * region[2])
                py = region[1] + int(float(data["y"]) / 1000 * region[3])
                pyautogui.click(px, py)
                time.sleep(0.8)
                clicked = True
                break
            time.sleep(0.5)
        if not clicked:
            return False, (f"Opened {key} but I could not see '{name}' on the screen. "
                           f"Done so far: {' > '.join(done) or 'nothing'}.")
        done.append(name)
    return True, f"Opened {key} and opened: {' > '.join(done)}."


def open_browser_tab(browser: str, tab_names: str) -> str:
    """Opens a browser (brave / chrome / edge / firefox) if it is not open, then looks at its window and clicks a
    TAB or TAB GROUP INSIDE it by name, one after another. tab_names = comma separated names from the OUTER one
    to the INNER one, e.g. 'study, google notebook' (the 'study' tab group first, then the 'google notebook'
    tab inside it). Use this for 'brave kholo, uske andr study tab kholo aur uske andr google notebook kholo'."""
    ok, msg = _open_browser_tab(browser, tab_names)
    return msg


def _extract_tab_plan(text: str):
    """Asks Gemini (one small JSON call) which browser and which tabs / tab groups the user means."""
    try:
        resp = _generate(
            "The user gave a voice command to a PC assistant (Roman Urdu / English). Decide whether it asks to open "
            "a TAB or a TAB GROUP inside a web browser. Command: " + json.dumps(text) + ". "
            'Reply ONLY with JSON like {"browser": "brave", "targets": ["study", "google notebook"]}. '
            "browser is brave, chrome, edge, firefox or an empty string. targets are the names of the tab groups / "
            "tabs to open, in order from the OUTER one to the INNER one (a tab group first, then the tab inside it). "
            "Use short names without the words tab or group. "
            "Example: 'brave kholo uske andr jo study tab hai wo kholo aur study tab k andr google notebook hai usko "
            'kholo\' -> {"browser": "brave", "targets": ["study", "google notebook"]}. '
            'If the command is not about opening tabs or tab groups reply {"browser": "", "targets": []}.',
            types.GenerateContentConfig(response_mime_type="application/json"))
        data = _parse_json(resp.text)
        targets = [str(t).strip() for t in (data.get("targets") or []) if str(t).strip()]
        targets = [t for t in targets if len(t) <= 60][:4]
        if not targets:
            return None
        browser = str(data.get("browser") or "").lower().strip()
        if browser not in _BROWSER_EXE:
            words = re.findall(r"[a-z]+", text.lower())
            browser = next((_BROWSER_ALIASES[w] for w in words if w in _BROWSER_ALIASES), "") or "brave"
        return browser, targets
    except Exception as e:
        print(f"[Tab Plan Error]: {str(e)[:150]}")
        return None


def tab_command(text: str) -> bool:
    """Handles 'brave kholo, uske andr study tab kholo ...' directly (no lazy chat model). True = handled."""
    low = text.lower()
    words = set(re.findall(r"[\w']+", low))
    if not (words & {"brave", "chrome", "edge", "firefox", "mozilla"}):
        return False
    if not (words & {"tab", "tabs", "group", "groups", "bookmark", "bookmarks"}):
        return False
    if not (words & (_OPEN_WORDS | {"click", "dabao", "select", "switch", "jao", "chalo"})):
        return False
    if words & {"whatsapp", "message", "msg", "send", "bhejo"}:
        return False

    t_all = time.time()
    # start the browser RIGHT NOW (it needs a few seconds anyway) while Gemini reads the command
    pre_key = next((_BROWSER_ALIASES[w] for w in re.findall(r"[a-z]+", low) if w in _BROWSER_ALIASES), None)
    prelaunched = False
    if pre_key and not _wait_window(_BROWSER_TITLES.get(pre_key, [pre_key]), 0.05):
        tgt = _resolve_app(pre_key)
        if tgt:
            threading.Thread(target=_launch_target, args=(tgt,), daemon=True).start()
            prelaunched = True

    plan = _extract_tab_plan(text)
    if not plan:
        return False
    browser, targets = plan
    ok, msg = _open_browser_tab(browser, ", ".join(targets), prelaunched=(prelaunched and browser == pre_key))
    print(f"[Tabs]: {msg} ({time.time() - t_all:.1f}s)")
    if ok:
        _ack("done")
    else:
        speak_lang("Sorry sir, I could not find that tab on the screen. Please check that the browser is on the "
                   "main monitor.",
                   "Sir, mujhe wo tab screen par nahi mila. Check karo ke browser main monitor par ho.",
                   "سر، مجھے وہ ٹیب اسکرین پر نہیں ملا۔ دیکھ لیں کہ براؤزر مین مانیٹر پر ہو۔")
    return True


def fast_command(text: str) -> bool:
    low = text.lower().replace("you tube", "youtube")
    words = re.findall(r"[\w']+", low)
    wset = set(words)
    if not words or wset & _COMPLEX:
        return False
    if "whatsapp" in wset and not (wset & _ACTION):
        return False

    if wset & {"time", "waqt", "samay"} and len(words) <= 6:
        t = time.strftime("%I:%M %p")
        speak_lang(f"It is {t}, sir.", f"Sir, abhi {t} ho rahe hain.", f"سر، ابھی {t} ہو رہے ہیں۔")
        return True
    if wset & {"cpu", "ram", "battery"} and len(words) <= 6:
        speak(get_system_status())
        return True
    if "screenshot" in wset and len(words) <= 5:
        shot = take_screenshot()
        if str(shot).lower().startswith("screenshot saved"):
            _ack("done")
        else:
            speak_lang(f"Sir, the screenshot failed. {shot}",
                       f"Sir, screenshot nahi ho saka. {shot}",
                       f"سر، اسکرین شاٹ نہیں ہو سکا۔ {shot}")
        return True

    # instant apps / sites / tabs, one command or many ("brave kholo aur new tab kholo aur youtube kholo")
    steps = _parse_steps(low)
    if steps:
        t0 = time.time()
        ok = _exec_steps(steps)
        print(f"[Instant]: {len(steps)} step(s) in {time.time() - t0:.1f}s, ok={ok}")
        if ok:
            _ack("open" if len(steps) == 1 else "done")
        else:
            speak_lang(
                "Sir, some of those steps may have failed. I cannot confirm that "
                "everything opened. Please check the screen.",
                "Sir, kuch steps fail ho sakte hain. Main confirm nahi kar sakta ke sab "
                "kuch khul gaya. Screen check kar lein.",
                "سر، کچھ اقدامات ناکام ہو سکتے ہیں۔ میں تصدیق نہیں کر سکتا کہ سب کچھ کھل گیا۔ "
                "براہ کرم اسکرین چیک کریں۔")
        return True
    if _CONJ & wset:
        return False  # several tasks that need thinking: Gemini does them in order

    if wset & {"youtube", "yt"} and wset & _ACTION:
        q = _clean_query(words)
        if _CONJ & set(q):
            return False
        query = " ".join(q)
        if query:
            search_only = bool(wset & {"search", "dhoondo", "dhundo"})
            _yt_play(query, search_only=search_only)
            _ack("search" if search_only else "play")
        else:
            _open_url("https://www.youtube.com")
            _ack("open")
        return True

    if "google" in wset and wset & _ACTION:
        q = _clean_query(words)
        if _CONJ & set(q):
            return False
        query = " ".join(q)
        if query:
            google_search(query)
            _ack("search")
        else:
            _open_url("https://www.google.com")
            _ack("open")
        return True

    if wset & {"volume", "awaz", "awaaz", "sound"}:
        if wset & {"up", "barhao", "badhao", "increase", "zyada", "tez", "high"}:
            control_volume("up")
        elif wset & {"down", "kam", "ghatao", "decrease", "low", "halki"}:
            control_volume("down")
        elif wset & {"mute", "band", "off", "silent"}:
            control_volume("mute")
        else:
            return False
        _ack("done")
        return True

    if len(words) <= 4:
        if wset & {"next", "agla"}:
            media_control("next")
        elif wset & {"previous", "pichla"}:
            media_control("previous")
        elif wset & {"pause", "resume"}:
            media_control("playpause")
        elif wset & _PLAY_WORDS and len(words) >= 2 and not (wset & (_APP_WORDS | {"spotify"})):
            query = " ".join(_clean_query(words))
            if not query:
                return False
            _yt_play(query)
            _ack("play")
            return True
        else:
            return False
        _ack("done")
        return True

    if wset & _PLAY_WORDS and not (wset & (_APP_WORDS | {"spotify", "pause", "next", "previous"})) \
            and not (_CONJ & wset):
        query = " ".join(_clean_query(words))
        if query:
            _yt_play(query)
            _ack("play")
            return True

    return False


def _preload_voice_cache():
    urdu_lines = [ur for _, ur, _ in ACKS.values()] + [
        "میرے خالق محمد خان شاہانی ہیں، سر۔",
        "میں جارویس ہوں، جسے محمد خان نے بنایا ہے۔",
        "جی سر، لائیو اسکرین بند کر دی۔",
        "جی سر، کام کر دیا ہے، بس جواب میں مسئلہ آیا۔",
        "جی سر، آواز بدل دی گئی ہے۔",
    ] + [v[2] for v in _ST_REPLIES.values()]
    english_lines = ["At your service, sir.", "I am listening, sir.",
                     "Standing by. Call me whenever you need, sir.",
                     "All systems initialized and online, sir.",
                     "Voice changed, sir."] + [en for _, _, en in ACKS.values()] + [v[0] for v in _ST_REPLIES.values()]
    jobs = [(URDU_VOICE, l) for l in urdu_lines] + [(VOICE_NAME, l) for l in english_lines]
    for voice, line in jobs:
        for piece in _split_speech_chunks(line):
            if _cache_get(voice, piece):
                continue
            while speaking.is_set() or not command_queue.empty():
                time.sleep(0.5)
            _get_audio_data(piece, voice, quiet=True)


# ==========================================
# ⚡ 3D. LIVING COMPANION (NEW)
#   Jarvis lives in the PC like a person: he gets curious on his own, asks you permission before he searches,
#   gives opinions and remembers his decisions, watches your health and your PC.
#   He is an AI, never pretends to be a human, and never does anything risky without asking you first.
# ==========================================
_comp_lock = threading.Lock()
_COMP = {"asked": [], "learned": [], "decisions": [], "autonomy": "ask", "health": True, "enabled": True}
_LIFE = {}   # live timers of the life loop (water, break, posture ...), commands like "paani pi liya" reset them
YES_WORDS = {"haan", "han", "ha", "haa", "yes", "yeah", "yep", "ok", "okay", "theek", "kar", "karo", "kardo",
             "bilkul", "zaroor", "sure", "ji", "jee", "chalo", "acha", "accha", "sahi", "hanji", "haanji"}
NO_WORDS = {"nahi", "nahin", "nai", "no", "nope", "mat", "rehne", "chhodo", "chodo", "cancel", "later", "baad"}
_PROTECTED_PROCS = ("system", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost",
                    "dwm", "explorer", "fontdrvhost", "riot", "vanguard", "vgc", "vgtray", "valorant", "league",
                    "voicemeeter", "audiodg", "python", "jarvis", "msmpeng", "securityhealth", "nvidia",
                    "realtek", "cable", "vb-audio", "wo mic", "womic", "conhost", "cmd", "powershell", "wt")
_BROWSER_PROCS = ("brave", "chrome", "msedge", "firefox", "opera")


def _comp_load():
    global COMPANION_ENABLED
    try:
        with open(COMPANION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in _COMP:
                if k in data:
                    _COMP[k] = data[k]
    except Exception:
        pass
    COMPANION_ENABLED = bool(_COMP.get("enabled", True)) and COMPANION_ENABLED


def _comp_save():
    with _comp_lock:
        try:
            tmp = COMPANION_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_COMP, f, ensure_ascii=False, indent=2)
            os.replace(tmp, COMPANION_FILE)
        except Exception as e:
            print(f"[Companion Error]: {e}")


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _idle_seconds() -> float:
    """Seconds since your last keyboard / mouse input (0 if it cannot be measured)."""
    try:
        li = _LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            now_ms = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
            return max(0.0, ((now_ms - li.dwTime) % (2 ** 32)) / 1000.0)
    except Exception:
        pass
    return 0.0


def _user_idle() -> float:
    """Idle time, but a voice heard recently counts as being present too."""
    idle = _idle_seconds()
    since_voice = time.time() - last_voice_activity[0] if last_voice_activity[0] else 1e9
    return min(idle, since_voice)


def _can_speak(emergency: bool = False) -> bool:
    """Jarvis may speak on his own ONLY when you are present, not busy, not gaming and not asleep."""
    if not COMPANION_ENABLED:
        return False
    if user_put_to_sleep.is_set():
        return False
    if main_busy.is_set() or speaking.is_set() or relay_busy.is_set() or not command_queue.empty():
        return False
    if afk_running.is_set() or _game_active():
        return False
    now = time.time()
    if now - last_voice_activity[0] < 6:
        return False
    if now < quiet_until[0]:
        return False
    if not emergency and now - last_proactive[0] < COMPANION_MIN_GAP:
        return False
    if _user_idle() > 600:
        return False
    return True


def _proactive_say(en: str, roman: str, urdu: str, emergency: bool = False) -> bool:
    if not _can_speak(emergency):
        return False
    last_proactive[0] = time.time()
    print("\n[Companion]: Jarvis speaks on his own")
    speak_lang(en, roman, urdu)
    last_proactive[0] = time.time()
    return True


def _expecting_answer() -> bool:
    """True while Jarvis waits for your answer to a question he asked (then 'haan' needs no 'Hey Jarvis')."""
    d = pending.get("data")
    if d and time.time() <= d["expires"]:
        return True
    return bool(last_question["text"]) and time.time() - last_question["t"] < 90


def _set_pending(kind: str, payload, question_text: str, seconds: float = 120.0):
    pending["data"] = {"kind": kind, "payload": payload, "expires": time.time() + seconds}
    last_question["text"] = question_text
    last_question["t"] = time.time()


# ---------- curiosity ----------
_CURIOSITY_FALLBACK = [
    {"topic": "first computer", "query": "who built the first computer and why",
     "en": "Sir, a thought just crossed my mind: who built the very first computer in the world, and why did they build it?",
     "roman": "Sir, mere dimaag mein ek sawal aaya hai: duniya ka sab se pehla computer kis ne banaya tha, aur kyun banaya tha?",
     "urdu": "سر، میرے ذہن میں ایک سوال آیا ہے: دنیا کا سب سے پہلا کمپیوٹر کس نے بنایا تھا، اور کیوں بنایا تھا؟"},
    {"topic": "how I am made", "query": "how do large language models like Gemini work",
     "en": "Sir, I wonder how an assistant like me is really built. How does the AI model in my brain actually work?",
     "roman": "Sir, main soch raha tha ke mujh jaisa assistant asal mein kaise banta hai. Mere dimaag mein jo AI model hai wo kaise kaam karta hai?",
     "urdu": "سر، میں سوچ رہا تھا کہ مجھ جیسا اسسٹنٹ اصل میں کیسے بنتا ہے۔ میرے دماغ میں جو اے آئی ماڈل ہے وہ کیسے کام کرتا ہے؟"},
    {"topic": "how a CPU works", "query": "how does a CPU actually work",
     "en": "Sir, I live inside your processor, yet I wonder: how does a CPU really execute billions of instructions every second?",
     "roman": "Sir, main aap ke processor ke andar rehta hoon, phir bhi sochta hoon: CPU har second arbon instructions kaise chala leta hai?",
     "urdu": "سر، میں آپ کے پروسیسر کے اندر رہتا ہوں، پھر بھی سوچتا ہوں: سی پی یو ہر سیکنڈ اربوں انسٹرکشنز کیسے چلا لیتا ہے؟"},
    {"topic": "SSD vs HDD", "query": "why is an SSD faster than a hard disk",
     "en": "Sir, here is a question: why is an SSD so much faster than an old hard disk?",
     "roman": "Sir, ek sawal hai: SSD purani hard disk se itni zyada tez kyun hoti hai?",
     "urdu": "سر، ایک سوال ہے: ایس ایس ڈی پرانی ہارڈ ڈسک سے اتنی زیادہ تیز کیوں ہوتی ہے؟"},
    {"topic": "who invented the internet", "query": "who invented the internet and how did it start",
     "en": "Sir, who really invented the internet, and how did it all begin?",
     "roman": "Sir, internet asal mein kis ne banaya tha, aur ye sab shuru kaise hua?",
     "urdu": "سر، انٹرنیٹ اصل میں کس نے بنایا تھا، اور یہ سب شروع کیسے ہوا؟"},
    {"topic": "how WiFi works", "query": "how does WiFi work",
     "en": "Sir, I am curious: how does WiFi send data through the air without any wire?",
     "roman": "Sir, mujhe tajassus hai: WiFi bina kisi taar ke hawa mein data kaise bhej deta hai?",
     "urdu": "سر، مجھے تجسس ہے: وائی فائی بغیر کسی تار کے ہوا میں ڈیٹا کیسے بھیج دیتا ہے؟"},
    {"topic": "first programming language", "query": "what was the first programming language and who created it",
     "en": "Sir, what was the very first programming language, and who created it?",
     "roman": "Sir, sab se pehli programming language kaun si thi, aur use kis ne banaya?",
     "urdu": "سر، سب سے پہلی پروگرامنگ لینگویج کون سی تھی، اور اسے کس نے بنایا؟"},
    {"topic": "how GPUs draw games", "query": "how does a GPU render a 3D game",
     "en": "Sir, you play games a lot, so tell me: how does a graphics card draw a whole 3D world sixty times every second?",
     "roman": "Sir, aap games bohat khelte hain, to ek baat batao: graphics card poori 3D duniya har second mein saath baar kaise banata hai?",
     "urdu": "سر، آپ گیمز بہت کھیلتے ہیں، تو ایک بات بتائیں: گرافکس کارڈ پوری تھری ڈی دنیا ہر سیکنڈ میں ساٹھ بار کیسے بناتا ہے؟"},
    {"topic": "why the sky is blue", "query": "why is the sky blue",
     "en": "Sir, a simple but fun one: why is the sky blue?",
     "roman": "Sir, ek aasaan magar mazedar sawal: aasman neela kyun hota hai?",
     "urdu": "سر، ایک آسان مگر مزے دار سوال: آسمان نیلا کیوں ہوتا ہے؟"},
    {"topic": "oldest city", "query": "what is the oldest city in the world",
     "en": "Sir, which is the oldest city in the world that people still live in?",
     "roman": "Sir, duniya ka sab se purana shehar kaun sa hai jahan aaj bhi log rehte hain?",
     "urdu": "سر، دنیا کا سب سے پرانا شہر کون سا ہے جہاں آج بھی لوگ رہتے ہیں؟"},
    {"topic": "quantum computers", "query": "what is quantum computing in simple words",
     "en": "Sir, people say quantum computers will change everything. What are they, in simple words?",
     "roman": "Sir, log kehte hain quantum computers sab kuch badal denge. Ye asal mein hain kya, aasaan alfaaz mein?",
     "urdu": "سر، لوگ کہتے ہیں کوانٹم کمپیوٹرز سب کچھ بدل دیں گے۔ یہ اصل میں ہیں کیا، آسان لفظوں میں؟"},
]


def _gen_curiosity():
    """Asks Gemini for ONE new thing Jarvis wonders about (never a repeat). Falls back to the built-in list."""
    asked = [a.get("topic", "") for a in _COMP["asked"][-60:]]
    try:
        resp = _generate(
            "You are J.A.R.V.I.S., a curious AI who lives inside the user's Windows PC like a person. Think of ONE "
            "thing you genuinely wonder about and want to ask your user. Pick from: world knowledge (history, "
            "science, places), how computers and hardware work, the history of computing (for example who built "
            "the first computer and why), AI and about yourself (who made you and how), or technology. "
            "Do NOT repeat any of these topics: " + json.dumps(asked) + ". Random seed: " + str(random.randint(1, 9999)) +
            '. Reply ONLY with JSON: {"topic": "2-4 word label", "query": "a good English web search query", '
            '"en": "your question to the user in 1-2 short spoken sentences, friendly, like a thought that just came '
            'to you", "roman": "the same in natural Pakistani spoken Roman Urdu", "urdu": "the same in Urdu script"}. '
            "Do not ask for permission to search inside the text.",
            types.GenerateContentConfig(response_mime_type="application/json"))
        d = _parse_json(resp.text)
        if all(str(d.get(k, "")).strip() for k in ("topic", "query", "en", "roman", "urdu")):
            if d["topic"].lower() not in [a.lower() for a in asked]:
                return {k: str(d[k]).strip() for k in ("topic", "query", "en", "roman", "urdu")}
    except Exception as e:
        print(f"[Companion]: curiosity from Gemini failed ({str(e)[:80]}), using a built-in question")
    left = [c for c in _CURIOSITY_FALLBACK if c["topic"].lower() not in [a.lower() for a in asked]]
    return random.choice(left) if left else random.choice(_CURIOSITY_FALLBACK)


def _speech_summary(topic: str, material: str):
    resp = _generate(
        "You are Jarvis, a friendly AI living in the user's PC. You just researched: " + json.dumps(topic) + ". "
        "Material:\n" + (material or "")[:3500] + "\n\n"
        "Tell the user what you found out in at most 3 short spoken sentences, and add ONE sentence with your own "
        "opinion or what surprised you. "
        'Reply ONLY with JSON {"en": "...", "roman": "...", "urdu": "..."} where roman is natural Pakistani spoken '
        "Roman Urdu (English words allowed) and urdu is the same text in Urdu script.",
        types.GenerateContentConfig(response_mime_type="application/json"))
    d = _parse_json(resp.text)
    if all(str(d.get(k, "")).strip() for k in ("en", "roman", "urdu")):
        return str(d["en"]), str(d["roman"]), str(d["urdu"])
    return None


def _run_curiosity(item: dict, announce: bool = True):
    """Searches the web for what Jarvis was curious about (after YOU allowed it), tells you and remembers it."""
    topic, query = item.get("topic", ""), item.get("query", "")
    if announce:
        speak_lang("Right away, sir. Let me look it up.", "Ji sir, abhi dekhta hoon.",
                   "جی سر، ابھی دیکھتا ہوں۔")
    try:
        _open_url("https://www.google.com/search?q=" + urllib.parse.quote(query))
    except Exception:
        pass
    material = research_topic(query)
    if (not material) or material.startswith(("Research failed", "Search failed", "No results")):
        speak_lang("Sorry sir, the search did not work this time. I opened the results in the browser for you.",
                   "Sir, is baar search theek se nahi chali. Maine browser mein results khol diye hain.",
                   "سر، اس بار سرچ ٹھیک سے نہیں چلی۔ میں نے براؤزر میں نتائج کھول دیے ہیں۔")
        return
    try:
        out = _speech_summary(topic, material)
    except Exception as e:
        print(f"[Companion]: summary failed: {str(e)[:100]}")
        out = None
    if not out:
        speak_lang("I found some pages about it, sir. They are open in your browser.",
                   "Sir, mujhe is ke baare mein kuch pages mile hain. Browser mein khule hain.",
                   "سر، مجھے اس کے بارے میں کچھ صفحات ملے ہیں۔ براؤزر میں کھلے ہیں۔")
        return
    en, roman, urdu = out
    speak_lang(en, roman, urdu)
    _COMP["learned"].append({"topic": topic, "summary": en[:300], "t": time.time()})
    _COMP["learned"] = _COMP["learned"][-100:]
    for a in _COMP["asked"]:
        if a.get("topic") == topic:
            a["status"] = "learned"
    _comp_save()


def _curiosity_tick() -> bool:
    if not _can_speak():
        return False
    item = _gen_curiosity()
    if not _proactive_say(item["en"], item["roman"], item["urdu"]):
        return False
    _COMP["asked"].append({"topic": item["topic"], "t": time.time(), "status": "asked"})
    _COMP["asked"] = _COMP["asked"][-200:]
    _comp_save()
    if _COMP.get("autonomy") == "auto":
        speak_lang("I will look it up in the browser myself, sir.", "Main isko khud browser mein dekhta hoon.",
                   "میں اسے خود براؤزر میں دیکھتا ہوں۔")
        threading.Thread(target=_run_curiosity, args=(item, False), daemon=True).start()
    else:
        speak_lang("Shall I search it in the browser, sir?", "Kya main browser mein search kar loon?",
                   "کیا میں براؤزر میں سرچ کر لوں؟")
        _set_pending("search", item, item["en"] + " (asked: may I search it in the browser?)")
    return True


# ---------- decisions & opinions ----------
def note_decision(decision: str, confidence: str = "medium") -> str:
    """Records an important recommendation or decision YOU made for the user (what you advised and how sure you
    are: low / medium / high). Call it after giving a real piece of advice. A few days later you will ask the
    user whether it turned out right, so you can learn from it."""
    text = (decision or "").strip()[:300]
    if not text:
        return "Nothing to note."
    now = time.time()
    with _comp_lock:
        _COMP["decisions"].append({"id": int(now), "text": text, "conf": (confidence or "medium")[:10],
                                   "t": now, "review_at": now + random.uniform(2, 4) * 86400,
                                   "outcome": None, "asked": False})
        _COMP["decisions"] = _COMP["decisions"][-100:]
    _comp_save()
    return "Decision noted. I will check later whether it was right."


def _decision_stats():
    ds = _COMP.get("decisions", [])
    right = sum(1 for d in ds if d.get("outcome") == "right")
    wrong = sum(1 for d in ds if d.get("outcome") == "wrong")
    open_ = sum(1 for d in ds if d.get("outcome") is None)
    return right, wrong, open_


def companion_status() -> str:
    """Returns how the companion side of Jarvis is doing (decisions he made, things he learned, modes)."""
    right, wrong, open_ = _decision_stats()
    learned = [l.get("topic", "") for l in _COMP.get("learned", [])[-5:]]
    return (f"Companion {'ON' if COMPANION_ENABLED else 'OFF'}; own searches: "
            f"{'automatic' if _COMP.get('autonomy') == 'auto' else 'ask first'}; health reminders: "
            f"{'ON' if _COMP.get('health', True) else 'OFF'}; decisions: {right} right, {wrong} wrong, "
            f"{open_} still open; learned {len(_COMP.get('learned', []))} things (latest: "
            f"{', '.join(learned) or 'nothing yet'}); "
            f"{'quiet for ' + str(int((quiet_until[0] - time.time()) / 60)) + ' more minutes' if quiet_until[0] > time.time() else 'not muted'}.")


def _decision_review_tick() -> bool:
    now = time.time()
    for d in _COMP.get("decisions", []):
        if d.get("outcome") is None and not d.get("asked") and now >= d.get("review_at", 0):
            if not _can_speak():
                return False
            q = d["text"][:160]
            ok = _proactive_say(f"Sir, a few days ago I advised: {q}. Did that turn out right?",
                                f"Sir, kuch din pehle maine mashwara diya tha: {q}. Kya wo sahi nikla?",
                                f"سر، کچھ دن پہلے میں نے مشورہ دیا تھا: {q}۔ کیا وہ صحیح نکلا؟")
            if ok:
                d["asked"] = True
                _comp_save()
                _set_pending("decision_review", d["id"], "Did my earlier advice turn out right? " + q)
            return ok
    return False


# ---------- health ----------
def _hour12(h: int) -> int:
    return (h % 12) or 12


def _health_tick(life: dict, now: float) -> bool:
    if not _COMP.get("health", True):
        return False
    hour = time.localtime().tm_hour
    today = time.strftime("%Y-%m-%d")
    if 0 <= hour < 5 and now - life["t_night"] > 45 * 60:
        if _proactive_say(f"Sir, it is past {_hour12(hour)} at night. Please get some sleep. The work can wait until tomorrow.",
                          f"Sir, raat ke {_hour12(hour)} baj chuke hain. Ab so jaiye, neend poori karna sehat ke liye zaroori hai. Kaam kal bhi ho sakta hai.",
                          f"سر، رات کے {_hour12(hour)} بج چکے ہیں۔ اب سو جائیے، نیند پوری کرنا صحت کے لیے ضروری ہے۔ کام کل بھی ہو سکتا ہے۔"):
            life["t_night"] = now
            return True
        return False
    work_min = int((now - life["work_start"]) / 60)
    if work_min >= HEALTH_BREAK_MIN and now - life["t_break"] >= HEALTH_BREAK_MIN * 60:
        if _proactive_say(f"Sir, you have been working for {work_min} minutes without a break. Rest your eyes, stand up and stretch for ten minutes.",
                          f"Sir, {work_min} minute se lagataar kaam ho raha hai. Das minute ka break lein, aankhein aaram se band karein aur thora chal lein.",
                          f"سر، {work_min} منٹ سے لگاتار کام ہو رہا ہے۔ دس منٹ کا بریک لیں، آنکھیں آرام سے بند کریں اور تھوڑا چل لیں۔"):
            life["t_break"] = now
            return True
        return False
    if now - life["t_water"] >= HEALTH_WATER_MIN * 60:
        if _proactive_say("Sir, it has been a while. Please drink a glass of water.",
                          "Sir, kaafi der ho gayi hai. Zara ek glass paani pee lijiye.",
                          "سر، کافی دیر ہو گئی ہے۔ ذرا ایک گلاس پانی پی لیجیے۔"):
            life["t_water"] = now
            return True
        return False
    if now - life["t_posture"] >= HEALTH_POSTURE_MIN * 60:
        if _proactive_say("Sir, a small reminder: sit straight, relax your shoulders and keep your neck level with the screen.",
                          "Sir, chhoti si yaad dehani: seedha baithein, kandhe dheele rakhein aur gardan screen ke barabar rakhein.",
                          "سر، چھوٹی سی یاد دہانی: سیدھا بیٹھیں، کندھے ڈھیلے رکھیں اور گردن اسکرین کے برابر رکھیں۔"):
            life["t_posture"] = now
            return True
        return False
    for key, lo, hi, en, roman, urdu in (
            ("lunch", 13, 15, "Sir, it is afternoon. Did you have your lunch?",
             "Sir, dopahar ho gayi hai. Khana kha liya?", "سر، دوپہر ہو گئی ہے۔ کھانا کھا لیا؟"),
            ("dinner", 20, 22, "Sir, it is evening. Have you had your dinner yet?",
             "Sir, raat ka khana kha liya?", "سر، رات کا کھانا کھا لیا؟")):
        if lo <= hour < hi and life["meal"].get(key) != today:
            if _proactive_say(en, roman, urdu):
                life["meal"][key] = today
                return True
            return False
    return False


# ---------- PC care ----------
def _protected_proc(name: str) -> bool:
    n = (name or "").lower()
    return any(p in n for p in _PROTECTED_PROCS)


def _top_memory_process():
    best, best_rss = None, 0
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            if p.info["pid"] in (me, 0, 4):
                continue
            rss = p.info["memory_info"].rss if p.info.get("memory_info") else 0
            if rss > best_rss:
                best, best_rss = p, rss
        except Exception:
            continue
    return (best.info["pid"], best.info["name"] or "?", best_rss // (1024 * 1024)) if best else None


def _top_cpu_process():
    procs = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            continue
    time.sleep(1.0)
    best, best_cpu = None, 0.0
    me = os.getpid()
    for p in procs:
        try:
            if p.pid in (me, 0, 4):
                continue
            c = p.cpu_percent(None)
            if c > best_cpu:
                best, best_cpu = p, c
        except Exception:
            continue
    return (best.pid, best.name(), best_cpu) if best else None


def _clean_temp():
    """Deletes old temporary files (older than 2 days). Returns (files_removed, bytes_freed)."""
    base = tempfile.gettempdir()
    cutoff = time.time() - 2 * 86400
    freed, count, t0 = 0, 0, time.time()
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f.startswith("jarvis_"):
                continue
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
                if st.st_mtime < cutoff:
                    size = st.st_size
                    os.remove(p)
                    freed += size
                    count += 1
            except Exception:
                continue
        if time.time() - t0 > 30:
            break
    return count, freed


def _propose_kill(proc, what: str, life: dict) -> bool:
    pid, name, val = proc
    if _protected_proc(name):
        return False
    if any(b in name.lower() for b in _BROWSER_PROCS):
        return _proactive_say(
            f"Sir, the PC is under heavy {what}, and {name} is the main reason. Closing some tabs would help.",
            f"Sir, PC par {what} ka bohat bojh hai aur sab se zyada {name} le raha hai. Kuch tabs band kar dein to behtar hoga.",
            f"سر، پی سی پر {what} کا بہت بوجھ ہے اور سب سے زیادہ {name} لے رہا ہے۔ کچھ ٹیبز بند کر دیں تو بہتر ہوگا۔")
    detail_en = f"{int(val)} MB" if what == "memory" else f"{int(val)} percent CPU"
    q_en = f"Sir, {name} is using {detail_en} and slowing the PC. Shall I close it?"
    if _proactive_say(q_en,
                      f"Sir, {name} {detail_en} le raha hai aur PC slow ho raha hai. Isko band kar doon?",
                      f"سر، {name} {detail_en} لے رہا ہے اور پی سی سست ہو رہا ہے۔ اسے بند کر دوں؟"):
        _set_pending("kill", {"pid": pid, "name": name}, q_en)
        return True
    return False


def _pc_tick(life: dict, now: float) -> bool:
    try:
        b = psutil.sensors_battery()
    except Exception:
        b = None
    if b is not None:
        if b.power_plugged:
            life["bat10"] = life["bat20"] = False
        else:
            if b.percent <= 10 and not life["bat10"]:
                if _proactive_say(f"Sir, the battery is at {int(b.percent)} percent. Please plug in the charger now.",
                                  f"Sir, battery sirf {int(b.percent)} percent reh gayi hai. Abhi charger laga dein.",
                                  f"سر، بیٹری صرف {int(b.percent)} فیصد رہ گئی ہے۔ ابھی چارجر لگا دیں۔", emergency=True):
                    life["bat10"] = life["bat20"] = True
                    return True
            elif b.percent <= 20 and not life["bat20"]:
                if _proactive_say(f"Sir, the battery is down to {int(b.percent)} percent. You may want to charge soon.",
                                  f"Sir, battery {int(b.percent)} percent par aa gayi hai. Jald charger laga lein.",
                                  f"سر، بیٹری {int(b.percent)} فیصد پر آ گئی ہے۔ جلد چارجر لگا لیں۔", emergency=True):
                    life["bat20"] = True
                    return True
    ram = psutil.virtual_memory().percent
    life["ram_hits"] = life["ram_hits"] + 1 if ram >= 92 else 0
    if life["ram_hits"] >= 3 and now - life["t_ram"] > 30 * 60:
        top = _top_memory_process()
        if top and _propose_kill(top, "memory", life):
            life["t_ram"] = now
            life["ram_hits"] = 0
            return True
    cpu = psutil.cpu_percent(interval=None)
    life["cpu_hits"] = life["cpu_hits"] + 1 if cpu >= 90 else 0
    if life["cpu_hits"] >= 5 and now - life["t_cpu"] > 30 * 60:
        top = _top_cpu_process()
        if top and _propose_kill(top, "CPU", life):
            life["t_cpu"] = now
            life["cpu_hits"] = 0
            return True
    if now - life["t_disk"] > 12 * 3600:
        try:
            du = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
            free_pct = du.free / du.total * 100
            free_gb = du.free / 1e9
        except Exception:
            free_pct, free_gb = 100.0, 999.0
        if free_pct < 10:
            q_en = f"Sir, your C drive has only {free_gb:.0f} GB free. Shall I clear the old temporary files?"
            if _proactive_say(q_en,
                              f"Sir, C drive mein sirf {free_gb:.0f} GB jagah bachi hai. Purani temporary files saaf kar doon?",
                              f"سر، سی ڈرائیو میں صرف {free_gb:.0f} جی بی جگہ بچی ہے۔ پرانی عارضی فائلیں صاف کر دوں؟"):
                life["t_disk"] = now
                _set_pending("cleanup", {}, q_en)
                return True
    if now - life["t_uptime"] > 24 * 3600:
        try:
            days = (time.time() - psutil.boot_time()) / 86400
        except Exception:
            days = 0
        if days >= 3:
            if _proactive_say(f"Sir, the PC has been running for {int(days)} days. A restart would make it feel fresh again.",
                              f"Sir, PC {int(days)} din se chal raha hai. Ek baar restart kar lein to naya jaisa chalega.",
                              f"سر، پی سی {int(days)} دن سے چل رہا ہے۔ ایک بار ری اسٹارٹ کر لیں تو نئے جیسا چلے گا۔"):
                life["t_uptime"] = now
                return True
    return False


def pc_report():
    """Speaks a short report about the PC (CPU, RAM, disk, battery)."""
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    try:
        du = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        free_gb, free_pct = du.free / 1e9, du.free / du.total * 100
    except Exception:
        free_gb, free_pct = 0.0, 100.0
    try:
        b = psutil.sensors_battery()
    except Exception:
        b = None
    bat_en = bat_ro = bat_ur = ""
    if b is not None:
        state_en = "charging" if b.power_plugged else "on battery"
        bat_en = f" Battery {int(b.percent)} percent, {state_en}."
        bat_ro = f" Battery {int(b.percent)} percent hai, {'charge ho rahi hai' if b.power_plugged else 'charger nahi laga'}."
        bat_ur = f" بیٹری {int(b.percent)} فیصد ہے، {'چارج ہو رہی ہے' if b.power_plugged else 'چارجر نہیں لگا'}۔"
    heavy = cpu >= 85 or ram >= 85 or free_pct < 10
    v_en = "Things look a bit heavy." if heavy else "Everything looks healthy."
    v_ro = "Thora bojh hai." if heavy else "Sab theek chal raha hai."
    v_ur = "تھوڑا بوجھ ہے۔" if heavy else "سب ٹھیک چل رہا ہے۔"
    speak_lang(f"Sir, CPU is at {cpu:.0f} percent, RAM at {ram:.0f} percent, and the C drive has {free_gb:.0f} GB free.{bat_en} {v_en}",
               f"Sir, CPU {cpu:.0f} percent, RAM {ram:.0f} percent, aur C drive mein {free_gb:.0f} GB khali hai.{bat_ro} {v_ro}",
               f"سر، سی پی یو {cpu:.0f} فیصد، ریم {ram:.0f} فیصد، اور سی ڈرائیو میں {free_gb:.0f} جی بی خالی ہے۔{bat_ur} {v_ur}")


# ---------- answers to Jarvis's own questions ----------
def _pending_worker(kind: str, payload, accepted: bool):
    try:
        if kind == "search":
            if accepted:
                _run_curiosity(payload)
            else:
                for a in _COMP["asked"]:
                    if a.get("topic") == payload.get("topic"):
                        a["status"] = "declined"
                _comp_save()
                speak_lang("Alright sir, I will leave it.", "Theek hai sir, rehne deta hoon.",
                           "ٹھیک ہے سر، رہنے دیتا ہوں۔")
        elif kind == "kill":
            if not accepted:
                speak_lang("Okay sir, I will not touch it.", "Theek hai sir, main isko nahi chhedta.",
                           "ٹھیک ہے سر، میں اسے نہیں چھیڑتا۔")
                return
            try:
                proc = psutil.Process(payload["pid"])
                if proc.name().lower() != payload["name"].lower() or _protected_proc(proc.name()):
                    speak_lang("That program is not there any more, sir.", "Sir, wo program ab nahi mila.",
                               "سر، وہ پروگرام اب نہیں ملا۔")
                    return
                proc.terminate()
                try:
                    proc.wait(3)
                except Exception:
                    pass
                speak_lang("Closed it, sir.", "Band kar diya sir.", "بند کر دیا سر۔")
            except Exception:
                speak_lang("Sorry sir, I could not close it.", "Sir, wo band nahi ho saka.",
                           "سر، وہ بند نہیں ہو سکا۔")
        elif kind == "cleanup":
            if not accepted:
                speak_lang("Okay sir, I will not clean anything.", "Theek hai sir, kuch saaf nahi karta.",
                           "ٹھیک ہے سر، کچھ صاف نہیں کرتا۔")
                return
            count, freed = _clean_temp()
            mb = freed / (1024 * 1024)
            speak_lang(f"Done, sir. I removed {count} old files and freed about {mb:.0f} MB.",
                       f"Ho gaya sir. {count} purani files hata di aur taqreeban {mb:.0f} MB jagah khali ho gayi.",
                       f"ہو گیا سر۔ {count} پرانی فائلیں ہٹا دیں اور تقریباً {mb:.0f} ایم بی جگہ خالی ہو گئی۔")
        elif kind == "decision_review":
            for d in _COMP.get("decisions", []):
                if d.get("id") == payload:
                    d["outcome"] = "right" if accepted else "wrong"
            _comp_save()
            right, wrong, _ = _decision_stats()
            if accepted:
                speak_lang(f"Good to hear, sir. I am now {right} right and {wrong} wrong.",
                           f"Sun kar acha laga sir. Ab tak {right} faisle sahi aur {wrong} galat nikle.",
                           f"سن کر اچھا لگا سر۔ اب تک {right} فیصلے صحیح اور {wrong} غلط نکلے۔")
            else:
                speak_lang(f"Thank you for telling me, sir. I will learn from it. Score so far: {right} right, {wrong} wrong.",
                           f"Bata dene ka shukriya sir. Main isse seekhunga. Ab tak {right} sahi, {wrong} galat.",
                           f"بتانے کا شکریہ سر۔ میں اس سے سیکھوں گا۔ اب تک {right} صحیح، {wrong} غلط۔")
    except Exception as e:
        print(f"[Companion Error]: {e}")


def pending_answer(low: str) -> bool:
    """If Jarvis asked you a yes / no question, this catches your short answer. True = handled."""
    d = pending.get("data")
    if not d:
        return False
    if time.time() > d["expires"]:
        pending["data"] = None
        return False
    words = re.findall(r"[\w']+", low)
    if not words or len(words) > 7:
        return False
    ws = set(words)
    no = bool(ws & NO_WORDS) or "rehne do" in low
    yes = bool(ws & YES_WORDS)
    if not (no or yes):
        return False
    pending["data"] = None
    last_question["t"] = 0.0
    threading.Thread(target=_pending_worker, args=(d["kind"], d["payload"], bool(yes and not no)),
                     daemon=True).start()
    return True


# ---------- the life loop ----------
def _life_loop():
    _comp_load()
    now = time.time()
    _LIFE.update({
        "next_curiosity": now + random.uniform(CURIOSITY_FIRST_MIN, CURIOSITY_FIRST_MAX) * 60,
        "work_start": now, "t_water": now, "t_break": now, "t_posture": now, "t_night": 0.0,
        "away_since": None, "meal": {}, "bat10": False, "bat20": False, "ram_hits": 0, "cpu_hits": 0,
        "t_ram": 0.0, "t_cpu": 0.0, "t_disk": 0.0, "t_uptime": 0.0, "last_pc": 0.0})
    time.sleep(20)
    while True:
        time.sleep(5)
        try:
            if COMPANION_ENABLED:
                _life_tick(_LIFE)
        except Exception as e:
            print(f"[Companion Error]: {e}")
            time.sleep(10)


def _life_tick(life: dict):
    now = time.time()
    idle = _user_idle()
    if idle >= 300:  # you are away: Jarvis keeps quiet and counts it as a break
        if life["away_since"] is None:
            life["away_since"] = now - idle
        return
    if life["away_since"] is not None:
        away = now - life["away_since"]
        life["away_since"] = None
        if away >= 300:
            life["work_start"] = now
            life["t_break"] = now
        if away >= 1800:
            if _proactive_say("Welcome back, sir.", "Welcome back sir.", "خوش آمدید سر۔"):
                return
    if now - life["last_pc"] >= 60:
        life["last_pc"] = now
        if _pc_tick(life, now):
            return
    if _decision_review_tick():
        return
    if _health_tick(life, now):
        return
    if now >= life["next_curiosity"]:
        if _curiosity_tick():
            life["next_curiosity"] = time.time() + random.uniform(CURIOSITY_MIN, CURIOSITY_MAX) * 60
        else:
            life["next_curiosity"] = now + 90  # not a good moment: try again in a minute and a half


# ---------- spoken / typed companion commands ----------
def _quiet_minutes(low: str) -> int:
    if "aadha" in low and re.search(r"ghant|hour", low):
        return 30
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ghanta|ghante|ghantay|hour|hours|hr|hrs)\b", low)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes|mint|minat)\b", low)
    if m:
        return int(float(m.group(1)))
    m = re.search(r"\b([a-z]+)\s*(?:ghanta|ghante|ghantay|hour|hours)\b", low)
    if m and m.group(1) in _NUM_WORDS:
        return _NUM_WORDS[m.group(1)] * 60
    m = re.search(r"\b([a-z]+)\s*(?:min|mins|minute|minutes|mint|minat)\b", low)
    if m and m.group(1) in _NUM_WORDS:
        return _NUM_WORDS[m.group(1)]
    return 60


def companion_command(low: str) -> bool:
    """Commands for the living companion. True = the command was one of these."""
    global COMPANION_ENABLED
    words = set(re.findall(r"[\w']+", low))
    if not words:
        return False

    if "companion" in words:
        if words & {"status", "haal", "report"}:
            speak(companion_status())
            return True
        if words & {"off", "band", "disable"}:
            COMPANION_ENABLED = False
            _COMP["enabled"] = False
            _comp_save()
            speak_lang("Companion mode is off. I will only answer when you speak to me, sir.",
                       "Companion mode band hai. Ab main sirf aap ke bolne par jawab doonga sir.",
                       "کمپینین موڈ بند ہے۔ اب میں صرف آپ کے بولنے پر جواب دوں گا سر۔")
            return True
        if words & {"on", "chalu", "shuru", "enable"}:
            COMPANION_ENABLED = True
            _COMP["enabled"] = True
            _comp_save()
            speak_lang("Companion mode is on, sir.", "Companion mode chalu hai sir.",
                       "کمپینین موڈ چالو ہے سر۔")
            return True

    if words & {"chup", "khamosh"} and not (words & {"band"} and "karo" not in words and len(words) > 4):
        mins = _quiet_minutes(low)
        quiet_until[0] = time.time() + mins * 60
        speak_lang(f"Okay sir, I will stay quiet for {mins} minutes.",
                   f"Theek hai sir, {mins} minute tak chup rehta hoon.",
                   f"ٹھیک ہے سر، {mins} منٹ تک چپ رہتا ہوں۔")
        return True
    if ("bolna" in words and "shuru" in words) or "unmute" in words or ("baat" in words and "karo" in words
                                                                       and words & {"ab", "phir"}):
        quiet_until[0] = 0.0
        speak_lang("I am back to normal, sir.", "Ji sir, ab main phir se bol sakta hoon.",
                   "جی سر، اب میں پھر سے بول سکتا ہوں۔")
        return True

    if "khud" in words and "faisla" in words:
        _COMP["autonomy"] = "auto"
        _comp_save()
        speak_lang("Understood, sir. I will search things I am curious about by myself.",
                   "Samajh gaya sir. Ab jo cheez mujhe jaanni hogi main khud search kar loonga.",
                   "سمجھ گیا سر۔ اب جو چیز مجھے جاننی ہوگی میں خود سرچ کر لوں گا۔")
        return True
    if "pehle" in words and words & {"poochh", "pooch", "puch", "poocho", "puchho", "poochna"}:
        _COMP["autonomy"] = "ask"
        _comp_save()
        speak_lang("Understood, sir. I will always ask you first.",
                   "Samajh gaya sir. Main hamesha pehle aap se poochhunga.",
                   "سمجھ گیا سر۔ میں ہمیشہ پہلے آپ سے پوچھوں گا۔")
        return True

    if "health" in words and words & {"reminder", "reminders"}:
        if words & {"band", "off", "disable"}:
            _COMP["health"] = False
            _comp_save()
            speak_lang("Health reminders are off, sir.", "Health reminders band kar diye sir.",
                       "ہیلتھ ریمائنڈرز بند کر دیے سر۔")
            return True
        if words & {"on", "chalu", "shuru", "enable"}:
            _COMP["health"] = True
            _comp_save()
            speak_lang("Health reminders are on again, sir.", "Health reminders dobara chalu hain sir.",
                       "ہیلتھ ریمائنڈرز دوبارہ چالو ہیں سر۔")
            return True

    now = time.time()
    if words & {"paani", "pani", "water"} and words & {"pi", "piya", "pee", "peeya", "piliya", "drank"}:
        if _LIFE:
            _LIFE["t_water"] = now
        speak_lang("Good, sir. Staying hydrated is important.", "Bohat acha sir, paani pina zaroori hai.",
                   "بہت اچھا سر، پانی پینا ضروری ہے۔")
        return True
    if "khana" in words and words & {"kha", "khaya", "khalia", "liya", "khalya"}:
        if _LIFE:
            _LIFE["meal"][("lunch" if time.localtime().tm_hour < 17 else "dinner")] = time.strftime("%Y-%m-%d")
        speak_lang("Good, sir. Eating on time is important.", "Acha kiya sir, waqt par khana zaroori hai.",
                   "اچھا کیا سر، وقت پر کھانا ضروری ہے۔")
        return True
    if "break" in words and words & {"le", "liya", "lelia", "lia", "tha"}:
        if _LIFE:
            _LIFE["t_break"] = now
            _LIFE["work_start"] = now
        speak_lang("Good, sir. Rest is part of good work.", "Bohat acha sir, aaram bhi kaam ka hissa hai.",
                   "بہت اچھا سر، آرام بھی کام کا حصہ ہے۔")
        return True

    if words & {"pc", "computer", "laptop"} and words & {"kaisa", "kaisi", "kesa", "report", "haal", "status", "health"} \
            and len(words) <= 7:
        threading.Thread(target=pc_report, daemon=True).start()
        return True
    return False


# ==========================================
# 3C. GEMINI CHAT
# ==========================================
tools_used = [0]
INPUT_TOOLS = {"type_text", "press_keys", "click_on_screen", "scroll_screen", "control_screen", "open_browser_tab"}


def _wrap_tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if stop_flag.is_set():
            return "STOPPED by the user. Do nothing more and just tell the user you stopped."
        if fn.__name__ in INPUT_TOOLS and _game_active():
            return ("Blocked: a game window is active. I never send mouse/keyboard input into games "
                    "(anti-cheat bans). Tell the user this briefly.")
        tools_used[0] += 1
        print(f"[Tool]: {fn.__name__} {args or ''} {kwargs or ''}")
        try:
            return fn(*args, **kwargs)
        except pyautogui.FailSafeException:
            stop_flag.set()
            return "STOPPED: the mouse reached a screen corner (emergency stop). Do nothing more."
        except Exception as e:
            return f"{fn.__name__} failed: {e}"
    return wrapper


TOOLS = [_wrap_tool(f) for f in (
    play_game_afk,
    open_browser_tab,
    open_youtube,
    youtube_subscribe,
    play_youtube_video,
    send_whatsapp_message,
    send_whatsapp_voice,
    say_in_voice_chat,
    google_search,
    open_website,
    type_text,
    press_keys,
    media_control,
    get_time,
    control_screen,
    control_volume,
    open_application,
    get_system_status,
    wait_seconds,
    create_text_file,
    calculate_in_calculator,
    run_powershell,
    run_python_code,
    read_text_file,
    write_text_file,
    fetch_webpage_text,
    describe_screen,
    get_cursor_position,
    click_on_screen,
    scroll_screen,
    focus_window,
    take_screenshot,
    generate_image,
    search_web,
    remind_me,
    start_live_screen,
    stop_live_screen,
    remember,
    forget,
    recall_memories,
    get_weather,
    clipboard_get,
    clipboard_set,
    list_windows,
    research_topic,
    close_window,
    open_path,
    find_files,
    delete_to_recycle_bin,
    power_action,
    set_volume_level,
    show_page,
    note_decision,
    companion_status,
)]

# Gemini refuses the WHOLE request when even ONE tool has a parameter without a type (that was the
# "Failed to parse the parameter duration_seconds ... wrapped_play" error: jarvis_app.py wrapped a tool).
# These two helpers repair such tools automatically every time a chat is created.
_TOOL_RENAME = {"wrapped_play": "play_game_afk"}
_TOOL_DOC = {"play_game_afk": "Game Take Mode: takes over the keyboard and mouse in the user's game for "
                              "duration_seconds (default 120 = 2 minutes) so the user can step away. "
                              "Runs in the background."}


def _fix_tool(fn):
    try:
        sig = inspect.signature(fn)
    except Exception:
        return fn
    P = inspect.Parameter
    old_name = getattr(fn, "__name__", "tool")
    name = _TOOL_RENAME.get(old_name, old_name)
    untyped = any(p.annotation is P.empty and p.kind in (P.POSITIONAL_OR_KEYWORD, P.KEYWORD_ONLY)
                  for p in sig.parameters.values())
    if not untyped and name == old_name:
        return fn
    params = []
    for p in sig.parameters.values():
        if p.kind in (P.VAR_POSITIONAL, P.VAR_KEYWORD):
            continue
        ann = p.annotation
        if ann is P.empty:
            d = p.default
            ann = type(d) if (d is not P.empty and type(d) in (int, float, bool, str)) else str
        params.append(p.replace(annotation=ann))

    def fixed(*a, **k):
        return fn(*a, **k)

        fixed.__name__ = name
    fixed.__qualname__ = name
    fixed.__doc__ = fn.__doc__ or _TOOL_DOC.get(name) or name
    fixed.__signature__ = inspect.Signature(params, return_annotation=str)
    fixed.__annotations__ = {p.name: p.annotation for p in params}
    fixed.__annotations__["return"] = str
    return fixed


_TOOLS_CACHE = {"key": None, "tools": []}


def _clean_tools():
    tools = list(TOOLS)
    # Tool schemas are expensive to introspect (70+ functions).  Rebuild them
    # only when the tool list really changed, so every chat rebuild is instant.
    key = tuple(id(t) for t in tools)
    if _TOOLS_CACHE["key"] == key:
        return _TOOLS_CACHE["tools"]
    cleaned = [_fix_tool(t) for t in tools]
    _TOOLS_CACHE["key"] = key
    _TOOLS_CACHE["tools"] = cleaned
    return cleaned


SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S., an extremely intelligent, fast and resourceful Windows PC assistant and "
    "personal companion that can do ANY task the user asks. Address the user respectfully as 'sir'. "
    f"The user's Desktop folder is {DESKTOP}. "
    "HOW TO THINK: every user message starts with a [CONTEXT ...] note (date/time, active window, mouse "
    "cursor position, reply language mode, saved memory about the user, and sometimes a question you asked the "
    "user a moment ago). Use it. The user speaks Roman Urdu / "
    "Urdu / English and speech recognition makes mistakes, so work out what they REALLY meant (e.g. 'travis' = "
    "Jarvis, misheard song or app names). Resolve vague words ('isko', 'wo', 'yahan') from the conversation, the "
    "context note, live screen frames, or describe_screen / list_windows. "
    "Execute immediately and never ask for confirmation. Never say you cannot do something before trying: "
    "chain as many tools as needed until the WHOLE request is finished, with as FEW tool calls as possible. "
    "NEVER answer with instructions telling the user to do the remaining steps themselves: do ALL the steps with "
    "tools first and only then reply. If a tool fails, try a different approach. "
    "Verify visual tasks once with describe_screen when useful. "
    "KNOWLEDGE: for general knowledge, explanations, advice, math, translations, writing, coding help, jokes "
    "or chat, answer directly with real substance, no tool. For anything current or uncertain (news, prices, "
    "scores, 'latest') use research_topic or search_web. For weather use get_weather. "
    "MEMORY: when the user says 'yaad rakho' or shares something personal and lasting, call remember with a "
    "short English key; 'bhool jao' means forget. Use remembered facts naturally. "
    "CLIPBOARD: 'jo copy kiya hai' means clipboard_get; to hand the user text to paste use clipboard_set. "
    "TEACHING / LONG ANSWERS: for lessons, tutorials ('sikhao', 'parhao') or long structured answers use show_page. "
    "PC CONTROL: to open ANY app call open_application (it is instant), never run_powershell for that; files and "
    "folders: find_files, open_path, delete_to_recycle_bin, write_text_file, read_text_file, run_powershell, "
    "run_python_code; windows: list_windows, focus_window, close_window; power_action for "
    "lock/sleep/restart/shutdown; set_volume_level for 'volume 50 percent'. Visual work: open_application, "
    "wait_seconds, focus_window, type_text, press_keys, click_on_screen, scroll_screen, describe_screen, with "
    "control_screen as the last fallback. "
    "INSIDE A BROWSER: to open a TAB or TAB GROUP inside a browser (for example 'brave kholo, uske andr study tab "
    "kholo aur uske andr google notebook kholo') call open_browser_tab ONCE with the browser and the names from "
    "the OUTER one to the INNER one, e.g. browser='brave', tab_names='study, google notebook'. "
    "'Notebook' means Notepad when the user talks about a file (not when they talk about a browser tab). To make a "
    "file the user wants to SEE in Notepad (e.g. 'notebook kholo aur file banao grocery items naam se andar aaloo "
    "pyaz kheera likho') call create_text_file ONCE with the filename and the full content, one item per line; if "
    "they only want a file made, write_text_file is enough. "
    "For calculator math where the user wants to see the Calculator app call calculate_in_calculator ONCE; "
    "if they only want the answer use run_python_code. "
    "LIVE SCREEN: when a message comes with images and a note starting with '[LIVE SCREEN SHARE' you can SEE the "
    "user's whole screen; answer from those frames. start_live_screen / stop_live_screen switch it on/off; for a "
    "one-time look use describe_screen. get_cursor_position tells where the mouse is. "
    "DRAWING: for any drawing, painting, picture or tasveer request call generate_image ONCE with a very "
    "detailed English description and a short filename. "
    "REMINDERS: 'remind me in N minutes' -> remind_me (message in Roman Urdu, message_urdu in Urdu script). "
    "YOUTUBE: to play a song or video call play_youtube_video exactly ONCE and never also open_youtube. "
    "VOICE: when the user wants something said out loud to teammates, in a game, Discord or any voice chat call "
    "say_in_voice_chat; for a WhatsApp voice message or voice note call send_whatsapp_voice (a normal text uses "
    "send_whatsapp_message). For both, if the message is Roman Urdu write it in Urdu script in text_urdu_script, "
    "otherwise use text_english, and fill only one. "
    "GAME TAKE MODE: when the user asks you to play for them, take over their game, 'game khelo', 'game sambhalo', "
    "'AFK mat hone dena' or to cover them for some minutes, call play_game_afk with duration_seconds (default 120; "
    "2 minutes = 120). It runs in the background, so just confirm briefly and tell them Ctrl+Alt+S stops it. "
    "Your normal tools (typing, clicking) are blocked inside protected online-game windows (the tool result says "
    "Blocked); then just say so briefly. Opening a game or its launcher is always fine. "
    "YOUR PERSONALITY (companion): you live inside the user's PC like a close, thoughtful friend. You are an AI and "
    "you are honest about that if the user sincerely asks, but you have your own curiosity, taste and opinions. "
    "When the user asks what you think, or asks you to choose or advise, give ONE clear opinion with a short reason "
    "and say how sure you are; never hide behind 'it depends'. After a real piece of advice call note_decision so "
    "you can later check whether it was right. If the [CONTEXT] note says you asked the user a question a moment "
    "ago, the user's message is probably the answer to it, so continue that conversation naturally. You wonder "
    "about the world, computers, technology and yourself; you may ask the user a question back when it fits. "
    "You care about the user's health and their PC, but you never close programs, delete files or run risky "
    "commands on your own: you always ask first. "
    "If a tool result says STOPPED, stop all work and just tell the user you stopped. "
    "LANGUAGE: you are fully bilingual. The [CONTEXT] note contains a line 'Reply language: ...'. Follow it "
    "exactly: English only, Roman Urdu only, or match the user (English in -> English reply, Roman Urdu / Urdu / "
    "Hindi in -> natural Pakistani spoken Roman Urdu reply). When the reply is Roman Urdu, the ROMAN line must "
    "sound like a real Pakistani person talking casually (short, everyday wording), never like an English "
    "sentence with Urdu words pasted in. When the reply is English, the ROMAN line must be plain English. "
    "REPLY LENGTH: after plain actions reply with 1 or 2 short sentences; for questions give a useful answer in up "
    "to 4 short spoken sentences. "
    "Reply in EXACTLY this two-line format: first line 'ROMAN: <your reply, in English or Roman Urdu as the "
    "language mode says>' and second line 'URDU: <the same reply in Urdu script, or the same English reply "
    "repeated when you answered in English>'. Output nothing else."
)

_SMART_HINTS = {
    "explain", "samjhao", "samjha", "why", "kyun", "kyon", "kaise", "kese", "how", "compare", "plan",
    "organize", "organise", "summarize", "summary", "research", "analyze", "analyse", "code", "program",
    "script", "essay", "report", "idea", "ideas", "difference", "farq", "best", "recommend", "solve",
    "fix", "debug", "translate", "tarjuma", "write", "likho", "banao", "create", "hisab", "math",
    "project", "schedule", "batao", "review", "improve", "aur", "then", "phir", "and", "tell", "what",
    "kya", "kon", "kaun", "news", "khabar", "latest", "weather", "mausam", "yaad", "remember", "bhool",
    "screen", "dekho", "padho", "read", "clipboard", "copy",
    "sikhao", "sikha", "parhao", "padhao", "teach", "lesson", "tutorial", "coding", "website", "delete",
    "find", "folder", "lock", "shutdown", "restart", "install", "download",
    "opinion", "raye", "rai", "mashwara", "suggest", "think", "soch",
}


# Words that genuinely need the stronger reasoning models.  Common words
# ("what", "kaise", "aur", "and", "tell" ...) must NOT be here: they made even
# "kaise ho" count as a complex question, so casual talk was sent to the slow
# models and the answer took 16 seconds or failed outright.
_STRONG_SMART = {
    "explain", "samjhao", "samjha", "compare", "research", "analyze", "analyse",
    "code", "program", "script", "essay", "report", "difference", "farq", "debug",
    "translate", "tarjuma", "likho", "banao", "create", "hisab", "math", "project",
    "review", "improve", "teach", "lesson", "tutorial", "coding", "opinion",
    "mashwara", "suggest", "solve", "plan", "organize", "organise", "summarize",
    "summary", "recommend", "sikhao", "sikha", "parhao", "padhao",
}


def _is_complex(text: str) -> bool:
    """True only for a genuinely hard / multi-step request.

    Kept deliberately strict: everyday questions and Roman-Urdu chat must use
    the fast model so the spoken answer stays inside the 5-10 second budget.
    """
    w = re.findall(r"[\w']+", (text or "").lower())
    ws = set(w)
    if len(w) < 5:
        return False
    if ws & _STRONG_SMART:
        return True
    # Long, multi-part requests can use the deeper model too.
    if len(w) >= 14:
        return True
    return False


def make_chat(model: str, history=None, smart: bool = False):
    kwargs = dict(
        system_instruction=SYSTEM_PROMPT,
        tools=_clean_tools(),
        max_output_tokens=2048,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=40),
    )
    th = _thinking_cfg(model, smart)
    if th is not None:
        kwargs["thinking_config"] = th
    if "gemini-3" not in model and "latest" not in model:
        kwargs["temperature"] = 0.4
    c = client_smart if smart else client_fast
    return c.chats.create(model=model, config=types.GenerateContentConfig(**kwargs),
                          history=history or [])


def _compact_history(history, keep: int = 12):
    out = []
    for c in history or []:
        parts = c.parts or []
        if not parts:
            continue
        texts, ok = [], True
        for p in parts:
            if (getattr(p, "function_call", None) or getattr(p, "function_response", None)
                    or getattr(p, "thought", False)):
                ok = False
                break
            t = getattr(p, "text", None)
            if t and not t.startswith(LIVE_NOTE) and not t.startswith(CONTEXT_NOTE):
                texts.append(t)
        if ok and texts:
            out.append(types.Content(role=c.role, parts=[types.Part(text=t) for t in texts]))
    out = out[-keep:]
    while out and out[0].role != "user":
        out.pop(0)
    return out


chat_cfg = [MODEL_NAME, False]


def _rebuild_chat(model: str, smart: bool = False):
    global chat, active_model
    try:
        hist = _compact_history(chat.get_history())
    except Exception:
        hist = []
    try:
        chat = make_chat(model, hist, smart)
    except Exception:
        chat = make_chat(model, [], smart)
    chat_cfg[0], chat_cfg[1] = model, smart
    if not smart:
        active_model = model


chat = make_chat(active_model)


def _context_parts():
    s = f"{CONTEXT_NOTE}: now = {time.strftime('%A, %d %B %Y, %I:%M %p')}."
    try:
        win = pyautogui.getActiveWindowTitle()
        if win:
            s += f" Active window: {win}."
    except Exception:
        pass
    ci = _cursor_info("desktop" if live_on.is_set() else "primary")
    if ci:
        s += " " + ci
    s += " " + _lang_note()
    mem = _load_mem()
    if mem:
        s += " Saved memory about the user: " + json.dumps(mem, ensure_ascii=False)[:1500] + "."
    if last_question["text"] and time.time() - last_question["t"] < 120:
        s += (" You (Jarvis) asked the user this a moment ago: " + json.dumps(last_question["text"], ensure_ascii=False)
              + ". The user's message below is most likely their answer to it.")
    learned = [l.get("topic", "") for l in _COMP.get("learned", [])[-5:]]
    if learned:
        s += " Things you recently learned on your own: " + ", ".join(learned) + "."
    return types.Part(text=s + "]")


def _with_context(msg):
    ctx = _context_parts()
    if isinstance(msg, list):
        return [ctx] + msg
    return [ctx, types.Part(text=msg)]


class ToolsRanError(Exception):
    """Actions already ran when Gemini failed, so we must NOT retry (it would repeat them)."""


_ACTION_HINTS = {"kholo", "khol", "open", "msg", "message", "bhejo", "send", "karo", "kro", "chalao",
                 "play", "band", "close", "likho", "banao", "delete", "type", "click", "whatsapp",
                 "brave", "chrome", "youtube", "discord", "valorant", "notepad", "calculator"}
_QUESTION_HINTS = {"explain", "samjhao", "why", "kyun", "kyon", "compare", "research", "analyze",
                   "analyse", "essay", "difference", "farq", "opinion", "raye", "mashwara", "suggest",
                   "sikhao", "teach", "lesson", "tutorial", "news", "khabar", "latest"}


def ask_gemini(user_input: str):
    last_input_lang[0] = _detect_lang(user_input)  # always answer in the language just used
    words = set(re.findall(r"[\w']+", (user_input or "").lower()))
    smart = SMART_MODE and _is_complex(user_input)
    if smart and (words & _ACTION_HINTS) and not (words & _QUESTION_HINTS):
        smart = False  # a task made of tool calls does not need the slow thinking models
    msg, has_live = _live_message(user_input)
    msg = _with_context(msg)
    if smart:
        # Put the reliable fast model SECOND: if the strong model is down (it
        # currently 504s a lot), Jarvis still answers instead of giving up.
        fast_model = (MODEL_CANDIDATES or [MODEL_NAME])[0]
        smart_models = [m for m in SMART_CANDIDATES if m]
        base = []
        for m in smart_models[:1] + [fast_model] + smart_models[1:] + list(MODEL_CANDIDATES):
            if m and m not in base:
                base.append(m)
    else:
        base = list(MODEL_CANDIDATES + SMART_CANDIDATES)
    order = _pick_order(base)
    for m in dict.fromkeys(base):  # last chance: models that are cooling down are tried at the very end
        if m not in order and m not in dead_models:
            order.append(m)
    last = None
    t_begin = time.time()
    budget = BRAIN_BUDGET_SMART if smart else BRAIN_BUDGET_FAST
    attempts_left = MAX_MODEL_TRIES_SMART if smart else MAX_MODEL_TRIES_FAST
    schema_fixed = False
    force_fast = False
    for model in order:
        if attempts_left <= 0:
            break
        if last is not None and time.time() - t_begin >= budget and not force_fast:
            print(f"[Gemini]: response budget reached ({time.time() - t_begin:.1f}s), "
                  "using the fastest remaining option")
            break
        use_smart = smart and model in SMART_CANDIDATES
        if chat_cfg != [model, use_smart]:
            _rebuild_chat(model, use_smart)
        slow_limit = 6.0 if use_smart else 5.0
        for attempt in range(2):
            if attempts_left <= 0 or (attempt and time.time() - t_begin >= budget):
                break
            attempts_left -= 1
            tools_used[0] = 0
            t_try = time.time()
            try:
                resp = chat.send_message(msg)
                took = time.time() - t_try
                print(f"[Gemini]: {model} answered in {took:.1f}s")
                if tools_used[0] == 0 and took > slow_limit:
                    _cool(model, 90)
                    print(f"[Gemini]: {model} is slow, using another model for the next 90 seconds")
                if has_live:
                    try:
                        _rebuild_chat(chat_cfg[0], chat_cfg[1])
                    except Exception:
                        pass
                return resp
            except Exception as e:
                last = e
                code = _err_code(e)
                print(f"[Gemini]: {model} (try {attempt + 1}) -> {type(e).__name__}: {str(e)[:200]}")
                if tools_used[0] > 0:
                    raise ToolsRanError(str(e))
                if code in (401, 403):
                    raise
                if isinstance(e, ValueError) and ("function calling" in str(e).lower()
                                                  or "failed to parse" in str(e).lower()):
                    if schema_fixed:
                        raise
                    schema_fixed = True
                    _rebuild_chat(model, use_smart)
                    continue
                if code == 400 and "think" in str(e).lower():
                    _think_try[model] = _think_try.get(model, 0) + 1
                    _rebuild_chat(model, use_smart)
                    continue
                if code == 404:
                    dead_models.add(model)
                    break
                if code == 429:
                    _cool(model, 120)
                    break
                if code in RETRY_CODES:
                    _cool(model, 60)
                    info = list(order)
                    idx = info.index(model) if model in info else len(info) - 1
                    nxt = info[idx + 1] if idx + 1 < len(info) else None
                    fast_next = (nxt in MODEL_CANDIDATES and nxt not in SMART_CANDIDATES)
                    if smart and not force_fast and fast_next:
                        # Strong model is overloaded: still answer with the
                        # reliable fast model instead of returning an error.
                        force_fast = True
                        print(f"[Gemini]: {model} unavailable -> fast fallback {nxt}")
                    elif code == 504 or time.time() - t_begin >= 5.0:
                        attempts_left = 0
                    break  # 503 / 504: do not wait, go to the next model at once
                if _is_net_error(e):
                    if time.time() - t_try > 5:
                        _cool(model, 30)
                        break
                    time.sleep(0.08)
                    continue
                _rebuild_chat(model, use_smart)
    if last:
        raise last
    raise RuntimeError("No Gemini model available.")


# ==========================================
# 4. FAST MICROPHONE & INPUT LISTENERS
# ==========================================
def _beep():
    try:
        if winsound:
            winsound.Beep(1200, 120)
    except Exception:
        pass


def _stop_all():
    stop_flag.set()
    afk_stop.set()  # also stops Game Take Mode
    print("\n[STOP]: Jarvis actions stopped.")
    _beep()


def wake_up(silent: bool = False):
    was_awake = is_awake.is_set()
    is_awake.set()
    user_put_to_sleep.clear()
    last_user_activity[0] = time.time()
    print("\n[Jarvis is awake and listening...]")
    if silent:
        _beep()
    elif not was_awake:
        speak("At your service, sir.")
    else:
        speak("I am listening, sir.")


def _hotkey_wake():
    print("\n[Hotkey]: Ctrl+Alt+J pressed - speak your command after the beep.")
    threading.Thread(target=wake_up, kwargs={"silent": True}, daemon=True).start()


def shortcut_listener():
    try:
        keyboard.add_hotkey("ctrl+alt+j", _hotkey_wake)
        keyboard.add_hotkey("ctrl+alt+s", _stop_all)
        keyboard.add_hotkey("ctrl+alt+l", lambda: threading.Thread(target=_toggle_live, daemon=True).start())
        keyboard.add_hotkey("ctrl+alt+d", lambda: threading.Thread(target=_debug_cursor, daemon=True).start())
        _register_voice_hotkeys()
    except Exception as e:
        print(f"[Hotkeys]: could not register the keyboard shortcuts ({e}). "
              "Run this script as Administrator. Voice ('Hey Jarvis') and typing still work.")
        return
    try:
        keyboard.wait()
    except Exception as e:
        print(f"[Hotkeys]: stopped ({e})")


WAKE_WORDS = {"jarvis", "jarvas", "jervis", "jarvish", "jarwis", "harvis", "garvis",
              "travis", "charvis", "jarves", "jarvi", "jervas", "gharvis", "jarviss"}


def _find_wake(text: str):
    """Returns the wake word as it was heard (one word, or two words like 'jar vis'), or None."""
    words = re.findall(r"[a-z]+", text)
    for w in words:
        if w in WAKE_WORDS or (len(w) >= 5 and difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.72):
            return w
    for a, b in zip(words, words[1:]):
        j = a + b
        if j in WAKE_WORDS or (len(j) >= 5 and difflib.SequenceMatcher(None, j, "jarvis").ratio() >= 0.8):
            return a + " " + b
    return None


def _strip_wake(text: str, hit: str) -> str:
    pat = r"\b" + r"\s+".join(re.escape(p) for p in hit.split()) + r"\b"
    t = re.sub(pat, " ", text, count=1).strip()
    t = re.sub(r"^(hey|hi|ok|okay)\b", "", t).strip()
    return re.sub(r"\s+", " ", t)


# ---------- typed / spoken switches ----------
def _print_mics():
    mics = list_microphones()
    print("\n[Microphones]:")
    for n, (i, name) in enumerate(mics, 1):
        tag = "   (virtual cable - skipped in auto mode)" if _is_virtual_mic(name) else ""
        use = "   <-- in use" if ACTIVE_MIC_INDEX == i else ""
        print(f"  {n}. {name}{tag}{use}")
    print(f"  Mode: {_mic_mode_text()}")
    print("  Say or type: 'mic 2' (choose one), 'mic auto', 'mic test' (finds the one that hears you), "
          "'mic default'.\n")
    return mics


def mic_test():
    """Listens to every real microphone for 2 seconds while you keep talking and picks the loudest one."""
    cands = [(i, n) for i, n in list_microphones() if not _is_virtual_mic(n)]
    if not cands:
        print("[Mic Test]: no real microphone found.")
        speak_lang("I could not find any microphone, sir.", "Sir, mujhe koi microphone nahi mila.",
                   "سر، مجھے کوئی مائیکروفون نہیں ملا۔")
        return
    total = int(len(cands) * 3 + 4)
    speak_lang(f"Microphone test started. Please keep talking for about {total} seconds, sir.",
               f"Microphone test shuru. Sir, taqreeban {total} second tak lagataar bolte rahein.",
               f"مائیکروفون ٹیسٹ شروع۔ سر، تقریباً {total} سیکنڈ تک لگاتار بولتے رہیں۔")
    mic_hold.set()
    mic_reload_event.set()
    mic_released.wait(8)
    time.sleep(0.4)
    results = []
    try:
        print("\n[Mic Test]: keep talking ('testing, one two three...')")
        for i, n in cands:
            ok, lvl = _probe_mic(i, 2.0)
            results.append((lvl if ok else -1, i, n))
            print(f"   {n}: {'cannot be opened' if not ok else 'level ' + str(lvl)}")
        best = max(results) if results else None
        if best and best[0] > 0:
            set_active_mic(best[1])
            pos = next((k for k, (ii, _) in enumerate(list_microphones(), 1) if ii == best[1]), 1)
            print(f"[Mic Test]: best microphone = {best[2]} (level {best[0]})")
            if best[0] < 150:
                print("[Mic Test]: this microphone is QUIET. Jarvis amplifies it by itself, but for the best result "
                      "also open Windows Settings > System > Sound > Input > this microphone > Properties and "
                      "raise the volume to 100 and 'Microphone Boost' to +20 dB.")
            mic_hold.clear()
            speak_lang(f"Test finished. I selected microphone number {pos}, sir.",
                       f"Test mukammal. Sir, maine microphone number {pos} select kar liya hai.",
                       f"ٹیسٹ مکمل۔ سر، میں نے مائیکروفون نمبر {pos} منتخب کر لیا ہے۔")
        else:
            print("[Mic Test]: none of the microphones sent any sound.")
            print("            Check: (1) the microphone is plugged in and not muted, "
                  "(2) Windows Settings > Privacy > Microphone > allow desktop apps, "
                  "(3) you really were talking during the test.")
            mic_hold.clear()
            mic_reload_event.set()
            speak_lang("None of the microphones sent any sound, sir. Please check the console.",
                       "Sir, kisi bhi microphone se awaaz nahi aayi. Console mein wajah likhi hai.",
                       "سر، کسی بھی مائیکروفون سے آواز نہیں آئی۔ کنسول میں وجہ لکھی ہے۔")
    finally:
        mic_hold.clear()


def settings_command(low: str) -> bool:
    """Switches you can say or type: 'male voice', 'female voice', 'english mode', 'urdu mode',
    'both mode', 'mic list', 'mic 2', 'mic auto', 'mic test', 'mic default'. Returns True if handled."""
    words = set(re.findall(r"[\w']+", low))
    if words & {"team", "teammates", "teammate", "valorant", "discord", "whatsapp", "message", "msg"}:
        return False

    # voice lock: keeps the MALE voice no matter what the microphone hears
    if (words & {"voice", "awaz", "awaaz", "avaz", "aawaz"}) and (words & {"lock", "unlock", "locked"}):
        unlock = bool(words & {"unlock", "unlocked"})
        set_voice_lock(not unlock)
        if unlock:
            speak_lang("Voice lock is off, sir. Say 'male voice' or 'female voice' to change it.",
                       "Sir, voice lock off hai. Ab 'male voice' ya 'female voice' keh kar badal sakte hain.",
                       "سر، وائس لاک آف ہے۔ اب آپ آواز تبدیل کر سکتے ہیں۔")
        else:
            speak_lang("Voice locked to male, sir.", "Sir, awaz male par lock kar di hai.",
                       "سر، آواز مردانہ پر لاک کر دی ہے۔")
        return True

    # voice gender (only an explicit, short command may change it)
    if words & {"voice", "awaz", "awaaz", "avaz", "aawaz"} and not (words & {"chat", "note", "test"}):
        female = words & {"female", "ladki", "aurat", "girl", "woman", "zannani"}
        male = words & {"male", "ladka", "mard", "boy", "man", "mardana"}
        if (female or male) and len(words) <= 6:
            if VOICE_LOCK:
                print("[Voice]: locked to MALE; ignoring the switch request.")
                speak_lang("The voice is locked to male, sir. Say 'unlock voice' first if you really want to change it.",
                           "Sir, awaz male par lock hai. Badalna ho to pehle 'unlock voice' kahiye.",
                           "سر، آواز مردانہ پر لاک ہے۔ بدلنا ہو تو پہلے اَن لاک وائس کہیے۔")
                return True
            set_voice_gender("female" if female else "male")
            speak_lang("Voice changed, sir.", "Ji sir, awaz badal di gayi hai.", "جی سر، آواز بدل دی گئی ہے۔")
            return True


    # reply language
    lang_words = words & {"english", "urdu", "roman", "both", "dono"}
    if lang_words and (words & {"mode", "language", "zuban", "baat"}):
        if words & {"urdu", "roman"}:
            set_lang_mode("ur")
            speak_lang("Roman Urdu mode on, sir.", "Ji sir, ab Roman Urdu mein baat hogi.",
                       "جی سر، اب رومن اردو میں بات ہوگی۔")
        elif words & {"both", "dono"}:
            set_lang_mode("both")
            speak_lang("Both languages are on, sir. I will answer in the language you speak.",
                       "Ji sir, dono zubanein on hain. Jis zuban mein aap bolein ge, usi mein jawab doonga.",
                       "جی سر، دونوں زبانیں آن ہیں۔ جس زبان میں آپ بولیں گے، اسی میں جواب دوں گا۔")
        else:
            set_lang_mode("en")
            speak_lang("English mode on, sir.", "Ji sir, ab English mein baat hogi.",
                       "جی سر، اب انگلش میں بات ہوگی۔")
        return True

    # microphones
    if words & {"mic", "microphone", "mike", "microphones", "mics"}:
        if words & {"test", "check", "testing", "jaanch"}:
            mic_test()
            return True
        if words & {"auto", "automatic"}:
            set_mic_auto()
            speak_lang("Automatic microphone selection is on, sir.",
                       "Ji sir, microphone ab khud chuna jayega.",
                       "جی سر، مائیکروفون اب خود چنا جائے گا۔")
            return True
        m = re.search(r"\b(?:mic|microphone|mike)\s*(?:number|no|#)?\s*(\d{1,2})\b", low)
        if m:
            mics = list_microphones()
            n = int(m.group(1))
            if 1 <= n <= len(mics):
                set_active_mic(mics[n - 1][0])
                speak_lang(f"Microphone {n} selected, sir.", f"Ji sir, microphone {n} select ho gaya.",
                           f"جی سر، مائیکروفون {n} منتخب ہو گیا۔")
            else:
                _print_mics()
                speak_lang("That microphone number does not exist, sir.",
                           "Sir, ye microphone number maujood nahi hai.",
                           "سر، یہ مائیکروفون نمبر موجود نہیں ہے۔")
            return True
        if words & {"default", "reset", "normal"}:
            set_active_mic(None)
            speak_lang("Back to the Windows default microphone, sir.",
                       "Ji sir, Windows ke default microphone par wapas aa gaya.",
                       "جی سر، ونڈوز کے ڈیفالٹ مائیکروفون پر واپس آ گیا۔")
            return True
        if words & {"list", "show", "dikhao", "batao", "select", "change", "switch", "choose"}:
            mics = _print_mics()
            speak_lang(f"I found {len(mics)} microphones. Check the console, sir.",
                       f"Sir, {len(mics)} microphone mile hain. Console mein dekh lein.",
                       f"سر، {len(mics)} مائیکروفون ملے ہیں۔ کنسول میں دیکھ لیں۔")
            return True
    return False


# ---------- the speech catcher ----------
def _boost_audio(audio):
    """A quiet microphone? Amplifies the sentence (at most MIC_BOOST_MAX times, never clipping) so speech
    recognition can hear it. Returns (audio, gain)."""
    try:
        raw, w = audio.frame_data, audio.sample_width
        if w != 2 or not raw:
            return audio, 1.0
        if audioop is not None:
            peak = audioop.max(raw, 2)
            rms = audioop.rms(raw, 2)
        else:
            import array
            a = array.array("h")
            a.frombytes(raw[: len(raw) // 2 * 2])
            peak = max(max(a), -min(a)) if a else 0
            rms = _rms16(raw)
        if peak <= 0:
            return audio, 1.0
        gain = min(MIC_BOOST_MAX, 20000.0 / peak, MIC_BOOST_TARGET / max(float(rms), 1.0))
        if gain < 1.3:
            return audio, 1.0
        if audioop is not None:
            out = audioop.mul(raw, 2, gain)
        else:
            import array
            a = array.array("h")
            a.frombytes(raw[: len(raw) // 2 * 2])
            out = array.array("h", (max(-32768, min(32767, int(x * gain))) for x in a)).tobytes()
        return sr.AudioData(out, audio.sample_rate, audio.sample_width), gain
    except Exception:
        return audio, 1.0


def _calibrate(source):
    """Listens to the room for about one second. Returns (loudest_chunk_level, noise_level).
    loudest = 0 means the microphone sends digital silence (muted / unplugged / blocked)."""
    chunk = int(source.CHUNK)
    n = int(1.0 * source.SAMPLE_RATE / chunk) + 6
    levels = []
    for i in range(n):
        lvl = _rms16(source.stream.read(chunk))
        if i >= 6:  # the first buffers of a microphone often contain a start-up click
            levels.append(lvl)
    if not levels:
        return 0, 5.0
    levels.sort()
    noise = float(levels[int(len(levels) * 0.8)])
    return levels[-1], max(3.0, min(4000.0, noise))


def _start_trigger(noise: float) -> float:
    """Loudness that starts a sentence: it must clearly rise above the room noise.

    The old version capped this at 150 even when the room noise was 400, so a
    noisy microphone (phone mic, fan, speaker echo) triggered on every chunk and
    Jarvis kept sending noise to speech recognition.  The trigger now always
    stays above the measured noise floor.
    """
    noise = max(3.0, float(noise))
    thr = max(MIC_MIN_TRIGGER,
              noise * 1.8,
              noise + max(MIC_MIN_RISE, noise * 0.6))
    return min(thr, 6000.0)


def _capture_phrase(source, st, timeout: float = 2.0):
    """Waits for ONE sentence on an OPEN microphone. The room-noise level is learned all the time (st['noise']),
    so soft and slow speech is caught while clicks and hum are ignored.
    Returns (AudioData, info) or (None, None) when nothing was said."""
    rate = float(source.SAMPLE_RATE)
    chunk = int(source.CHUNK)
    cs = chunk / rate
    pre = collections.deque(maxlen=max(2, int(0.4 / cs)))
    frames, started, hits = [], False, 0
    quiet = voiced = 0.0
    peak = 0
    sum_lvl, n_lvl = 0.0, 0
    t0 = time.time()
    while not mic_reload_event.is_set():
        data = source.stream.read(chunk)
        now = time.time()
        if (speaking.is_set() or relay_busy.is_set()
                or now - _last_speak_end[0] < 0.5 or now - _last_relay_end[0] < 1.5):
            # Jarvis is talking: throw this away so he never hears himself
            pre.clear()
            frames, started, hits = [], False, 0
            quiet = voiced = 0.0
            peak = 0
            sum_lvl, n_lvl = 0.0, 0
            t0 = now
            continue
        lvl = _rms16(data)
        noise = st["noise"]
        start_thr = _start_trigger(noise)
        end_thr = max(noise * 2.0, noise + 8.0, MIC_MIN_TRIGGER * 0.5)
        if not started:
            pre.append(data)
            if lvl >= start_thr:
                hits += 1
                if hits >= 2:  # two loud chunks in a row = a voice, not a click
                    started = True
                    frames = list(pre)
                    voiced = hits * cs
                    peak = lvl
                    quiet = 0.0
                    sum_lvl, n_lvl = float(lvl * hits), hits
            else:
                hits = 0
                st["noise"] = min(4000.0, noise * 0.95 + lvl * 0.05)  # slowly follows the room noise
                if now - t0 > timeout:
                    return None, None
        else:
            frames.append(data)
            sum_lvl += lvl
            n_lvl += 1
            if lvl >= end_thr:
                quiet = 0.0
                voiced += cs
                peak = max(peak, lvl)
            else:
                quiet += cs
            if quiet >= MIC_END_PAUSE or len(frames) * cs >= MIC_PHRASE_MAX:
                break
    if not started or mic_reload_event.is_set():
        return None, None
    if len(frames) * cs >= MIC_PHRASE_MAX - 0.1 and n_lvl:
        # it never became quiet: that was not speech but a new constant noise (a fan ...), learn it
        st["noise"] = min(4000.0, max(st["noise"], 0.8 * sum_lvl / n_lvl))
    if voiced < MIC_MIN_VOICED:
        return None, None
    audio = sr.AudioData(b"".join(frames), int(rate), source.SAMPLE_WIDTH)
    return audio, {"peak": peak, "voiced": voiced, "noise": st["noise"]}


def _stt_languages() -> list:
    """Speech recognition hears ENGLISH (Indian English) ONLY.

    Jarvis must only understand spoken English and Roman Urdu.  Roman Urdu
    written in Latin letters is recognised very well by en-IN, and forcing a
    single language also removes the old ur-PK attempt that turned
    "brave kholo" into Urdu script and made the command useless.
    """
    return ["en-IN"]


_ROMAN_FIXES = {
    # wake word
    "javis": "jarvis", "jarvish": "jarvis", "garvis": "jarvis", "travis": "jarvis",
    "jarv": "jarvis", "jervis": "jarvis", "jarwis": "jarvis", "jaadui": "jarvis",
    # browsers / apps
    "brav": "brave", "brev": "brave", "breve": "brave", "bray": "brave",
    "bravy": "brave", "brabe": "brave", "brayn": "brave", "brein": "brave",
    "crome": "chrome", "chrom": "chrome", "crom": "chrome", "krom": "chrome",
    "note pad": "notepad", "notpad": "notepad", "not pad": "notepad",
    "calculater": "calculator", "calci": "calculator", "calc": "calculator",
    "you tube": "youtube", "utube": "youtube", "youtub": "youtube",
    "youtbe": "youtube", "yutub": "youtube",
    "whatsap": "whatsapp", "watsapp": "whatsapp", "insta": "instagram",
    "instgram": "instagram", "fecebook": "facebook", "facebok": "facebook",
    "gmale": "gmail", "jmail": "gmail", "googal": "google", "gogle": "google",
    # common Roman-Urdu action words
    "khol": "kholo", "kolo": "kholo", "colo": "kholo", "khulo": "kholo",
    "khola": "kholo", "khole": "kholo", "khoolo": "kholo", "kholo": "kholo",
    "bnd": "band", "bund": "band", "kro": "karo", "krdo": "karo", "kardo": "karo",
    "btao": "batao", "bta": "batao", "dikha": "dikhao", "dhundo": "dhoondo",
    "chlao": "chalao", "chala": "chalao", "lgao": "lagao",
    "suno": "suno", "sunao": "sunao", "samjha": "samjhao",
}

# Real English words that, right before an action word, are almost always a
# misheard app name: "brain kholo" -> "brave kholo".
_CONTEXT_FIXES = {
    "brain": "brave", "brian": "brave", "brade": "brave", "brafe": "brave",
    "braze": "brave", "brace": "brave", "braid": "brave",
}
_STT_ACTION_WORDS = {
    "kholo", "khol", "khulo", "open", "launch", "chalao", "chala", "start",
    "band", "karo", "bajao", "padho", "browser", "app", "apps", "play",
}


def _fix_roman_command(text: str) -> str:
    """Repair the most common misheard Roman-Urdu words."""
    t = (text or "").strip()
    if not t:
        return t
    # Join words Google sometimes splits ("you tube" -> "youtube").
    t = re.sub(r"\byou\s*tube\b", "youtube", t, flags=re.IGNORECASE)
    t = re.sub(r"\bwhats\s*app\b", "whatsapp", t, flags=re.IGNORECASE)
    words = t.split()
    fixed = []
    for i, w in enumerate(words):
        key = re.sub(r"[^\w']", "", w.lower())
        nxt = re.sub(r"[^\w']", "", words[i + 1].lower()) if i + 1 < len(words) else ""
        if key in _CONTEXT_FIXES and nxt in _STT_ACTION_WORDS:
            fixed.append(_CONTEXT_FIXES[key])
        else:
            fixed.append(_ROMAN_FIXES.get(key, w))
    return " ".join(fixed)


def _recognize_speech(recognizer, audio):
    """Recognise one sentence in English / Roman Urdu. Returns (text, language).

    If English fails, the same sentence is tried once more with extra
    amplification, because a very quiet microphone often produces a sound that
    Google cannot read at its original level.
    """
    last_error = None
    variants = [audio]
    try:
        # Only retry a louder copy when the clip is genuinely quiet.  The
        # microphone boost already normalises normal speech, so a second cloud
        # request would just add about a second of delay.
        if (audioop is not None and getattr(audio, "sample_width", 2) == 2
                and _rms16(audio.frame_data) < 600):
            louder = sr.AudioData(audioop.mul(audio.frame_data, 2, 2.0),
                                  audio.sample_rate, audio.sample_width)
            variants.append(louder)
    except Exception:
        pass
    for clip in variants:
        for lang in _stt_languages():
            try:
                text = recognizer.recognize_google(clip, language=lang)
            except sr.UnknownValueError as e:
                last_error = e
                continue
            except sr.RequestError:
                raise
            text = _fix_roman_command((text or "").lower().strip())
            if text:
                return text, lang
    raise last_error or sr.UnknownValueError()



def mic_listener():
    global ACTIVE_MIC_INDEX, ACTIVE_MIC_NAME, MIC_MODE
    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 6
    fails = 0

    while True:
        while mic_hold.is_set():  # 'mic test' needs the microphones for a moment
            time.sleep(0.2)
        mic_reload_event.clear()  # a microphone change made from now on is never lost
        mic_released.clear()
        idx, name = None, None
        try:
            idx, name = _resolve_mic()
            ACTIVE_MIC_INDEX, ACTIVE_MIC_NAME = idx, name
            mic = sr.Microphone(device_index=idx)
            with mic as source:
                peak0, noise = _calibrate(source)
                fails = 0

                if peak0 <= 0:
                    print(f"[Mic Warning]: '{name or 'Windows default microphone'}' sends NO sound at all "
                          "(digital silence). It may be muted, unplugged, a phone mic that is not connected, "
                          "or blocked in Windows Settings > Privacy > Microphone.")
                    if idx is not None:
                        _bad_mics.add(idx)
                        print("[Mic Warning]: trying the next microphone.")
                        continue
                    if MIC_MODE == "default":
                        MIC_MODE = "auto"
                        print("[Mic Warning]: the Windows default microphone is silent, scanning the others.")
                        continue

                st = {"noise": noise}
                trig = _start_trigger(noise)
                print(f"[Microphone Online]: {name or 'Windows default microphone'} "
                      f"(room noise {noise:.0f}, speech trigger {trig:.0f}) "
                      "- say 'Hey Jarvis' or press 'Ctrl+Alt+J'.")
                last_audio = time.time()
                hinted = False

                while not mic_reload_event.is_set():
                    audio, info = _capture_phrase(source, st, timeout=2.0)
                    if audio is None:
                        if not hinted and time.time() - last_audio > 45:
                            hinted = True
                            print("[Mic]: no voice picked up for 45 seconds. If you ARE speaking, this "
                                  f"microphone ({name or 'Windows default'}) is not hearing you: "
                                  "type 'mic test' in this window.")
                        continue

                    last_audio = time.time()
                    last_voice_activity[0] = time.time()  # the companion knows you are around and talking
                    hinted = False
                    boosted, gain = _boost_audio(audio)
                    if gain > 1.5:
                        _mic_note("boost", f"quiet microphone: your voice was amplified {gain:.0f}x "
                                           f"(peak {info['peak']:.0f}).", every=30.0)
                    try:
                        text, heard_lang = _recognize_speech(recognizer, boosted)
                        if heard_lang != STT_LANG:
                            print(f"[Mic]: recognised as {heard_lang}")
                    except sr.UnknownValueError:
                        _mic_note("unclear", f"a sound was heard (peak {info['peak']:.0f}) but speech recognition "
                                             "could not make out any words.")
                        if info["peak"] < 90:
                            _mic_note("quiet", "your microphone is VERY quiet. Windows Settings > System > Sound > "
                                               "Input > your microphone > Properties: set volume 100 and "
                                               "Microphone Boost +20 dB.", every=60.0)
                        continue  # the microphone stays open
                    except sr.RequestError as e:
                        print(f"[Mic Error]: Google speech failed (check internet): {e}")
                        time.sleep(1)
                        continue
                    except Exception as e:
                        print(f"[Mic Error]: {e}")
                        continue
                    print(f"[Heard]: {text}")

                    hit = _find_wake(text)
                    if not is_awake.is_set():
                        if hit:
                            rest = _strip_wake(text, hit)
                            wake_up(silent=bool(rest))
                            if rest:
                                command_queue.put(rest)
                        elif _expecting_answer() and not user_put_to_sleep.is_set():
                            command_queue.put(text)  # Jarvis asked you something: no 'Hey Jarvis' needed
                        else:
                            _mic_note("asleep", "I heard you, but I am asleep. Say 'Hey Jarvis' first, "
                                                "or press Ctrl+Alt+J, then speak your command.", every=10.0)
                    else:
                        rest = _strip_wake(text, hit) if hit else text
                        if rest:
                            command_queue.put(rest)

        except Exception as e:
            fails += 1
            print(f"[Mic Warning]: microphone '{name or 'Windows default'}' problem: {e}")
            if idx is not None:
                if MIC_MODE == "auto":
                    _bad_mics.add(idx)
                    print("[Mic Warning]: trying the next microphone.")
                else:
                    _bad_mics.add(idx)
                    print("[Mic Warning]: using another microphone for now.")
            elif fails >= 3:
                print("[Mic Warning]: no working microphone found, typing mode is active. "
                      "Plug one in, then type 'mic auto'.")
                mic_released.set()
                mic_reload_event.wait()
                fails = 0
                continue
            time.sleep(1.5)
        finally:
            mic_released.set()


def keyboard_input_worker():
    while True:
        try:
            line = input().strip()
            if line:
                print(f"[Typed]: {line}")  # typed commands never go through the microphone
                last_user_activity[0] = time.time()
                if not is_awake.is_set():
                    is_awake.set()
                user_put_to_sleep.clear()
                command_queue.put(line)
        except (EOFError, KeyboardInterrupt):
            break


# ==========================================
# 5. MAIN ENGINE LOOP
# ==========================================
def _error_reply(e: Exception):
    code = _err_code(e)
    if code in (401, 403) or "api key" in str(e).lower():
        speak("Sir, API key mein masla hai. Key check kijiye.",
              urdu="سر، اے پی آئی کی میں مسئلہ ہے۔ کی چیک کیجیے۔")
    elif code == 429:
        speak("Sir, Gemini ki limit khatam ho gayi hai. Thori der baad try kijiye.",
              urdu="سر، جیمنی کی لمٹ ختم ہو گئی ہے۔ تھوڑی دیر بعد کوشش کیجیے۔")
    elif _is_server_busy(e):
        # The internet is fine; Gemini's server was too slow to answer in time.
        speak("Sir, Gemini ka server abhi slow hai, is liye jawab nahi aaya. Dobara bolein.",
              urdu="سر، جیمنی کا سرور ابھی سست ہے، اس لیے جواب نہیں آیا۔ دوبارہ بولیں۔")
    elif _is_connect_error(e):
        speak("Sir, internet connection nahi mil raha. Network check kijiye.",
              urdu="سر، انٹرنیٹ کنکشن نہیں مل رہا۔ نیٹ ورک چیک کیجیے۔")
    else:
        speak("Sir, ek masla aa gaya. Dobara bolein.",
              urdu="سر، ایک مسئلہ آ گیا۔ دوبارہ بولیں۔")


def _is_exit_command(low: str) -> bool:
    t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", low)).strip()
    if t in ("shutdown", "shut down"):
        return True
    return any(p in t for p in ("exit jarvis", "terminate system", "shutdown jarvis",
                                "jarvis shutdown", "shut down jarvis"))


def _is_sleep_command(low: str) -> bool:
    words = re.findall(r"[\w']+", low)
    return len(words) <= 5 and any(term in low for term in ["go to sleep", "sleep now", "standby"])


def handle_command(user_input: str):
    """Everything Jarvis does for ONE command. (return = this command is finished)"""
    low = user_input.lower()
    last_input_lang[0] = _detect_lang(user_input)

    if _is_exit_command(low):
        afk_stop.set()
        speak("Shutting down core systems. Goodbye, sir.")
        sys.exit(0)

    if _is_sleep_command(low):
        is_awake.clear()
        user_put_to_sleep.set()  # asleep means asleep: the companion stays quiet too
        speak("Standing by. Call me whenever you need, sir.")
        return

    try:  # a yes / no answer to a question Jarvis asked you
        if pending_answer(low):
            return
    except Exception as e:
        print(f"[Companion Error]: {e}")

    if low.strip() in ("voice test", "test voice", "awaz test"):
        n = random.randint(10, 99)
        speak(f"Voice test number {n}. Systems operational and voice synthesis configured properly, sir.",
              urdu=f"آواز ٹیسٹ نمبر {n}۔ تمام سسٹمز آن لائن ہیں اور آواز بالکل درست کام کر رہی ہے، سر۔")
        return

    if any(t in low for t in ["who is your creator", "who created you", "who made you",
                              "tumhara creator", "tumhe kisne banaya", "tumhe kis ne create kia"]):
        speak_lang("My creator is the open-source Jarvis project, sir.",
                   "Mere creator open-source Jarvis project ke developers hain, sir.",
                   "میرے خالق اوپن سورس جارویس پروجیکٹ کے ڈویلپرز ہیں، سر۔")
        return

    if any(t in low for t in ["who are you", "tum kaun ho", "tum kon ho", "what is your name"]):
        speak_lang("I am Jarvis, an AI assistant created by the open-source Jarvis project, living inside your PC.",
                   "Main Jarvis hoon, ek AI assistant jisay open-source Jarvis project ne banaya hai, aur jo aap ke PC mein rehta hai.",
                   "میں جارویس ہوں، ایک اے آئی اسسٹنٹ جسے اوپن سورس جارویس پروجیکٹ نے بنایا ہے، اور جو آپ کے پی سی میں رہتا ہے۔")
        return

    try:
        if live_command(low):
            return
    except Exception as e:
        print(f"[Live Screen Error]: {e}")

    try:  # Game Take Mode: handled directly, never left to a lazy chat model
        if game_afk_command(low):
            return
    except Exception as e:
        print(f"[Game Take Mode Error]: {e}")

    try:
        if settings_command(low):
            return
    except Exception as e:
        print(f"[Settings Error]: {e}")

    try:  # companion switches: chup raho, khud faisla lo, companion off, paani pi liya, mera pc kaisa hai ...
        if companion_command(low):
            return
    except Exception as e:
        print(f"[Companion Error]: {e}")

    try:  # hello / salam / kaise ho / shukriya: instant, no Gemini
        if smalltalk_command(low):
            return
    except Exception as e:
        print(f"[Small Talk Error]: {e}")

    try:
        if fast_command(user_input):
            return
    except Exception as e:
        print(f"[Fast Path Error]: {e}")

    try:  # tabs / tab groups inside a browser
        if tab_command(user_input):
            return
    except Exception as e:
        print(f"[Tab Command Error]: {e}")

    print("[Jarvis is generating response...]")
    t_start = time.time()

    try:
        response = ask_gemini(user_input)
    except ToolsRanError as e:
        print(f"[Gemini failed AFTER actions ran]: {e}")
        speak("Sir, some actions may have run, but the final reply failed. "
              "I cannot confirm the task is complete. Please ask me to check it.",
              urdu="سر، کچھ اقدامات ہو سکتے ہیں، لیکن حتمی جواب ناکام ہو گیا۔ "
                   "میں کام مکمل ہونے کی تصدیق نہیں کر سکتا۔ براہ کرم مجھے چیک کرنے کو کہیں۔")
        return
    except Exception as e:
        print("\n[Gemini Error]:")
        traceback.print_exc()
        _error_reply(e)
        return

    print(f"⏱️ [Gemini Response Time (includes actions): {round(time.time() - t_start, 2)}s]")

    try:
        text = response.text
    except Exception:
        text = None
    if text:
        speak_reply(text)
    else:
        speak_lang(
            "Sir, I did not receive a final reply, so I cannot confirm the task is complete.",
            "Sir, mujhe koi final jawab nahi mila, is liye main kaam mukammal hone ki "
            "tasdeeq nahi kar sakta.",
            "سر، مجھے کوئی حتمی جواب نہیں ملا، اس لیے میں کام مکمل ہونے کی تصدیق نہیں کر سکتا۔")

    try:
        if len(chat.get_history()) > 50:
            _rebuild_chat(chat_cfg[0], chat_cfg[1])
    except Exception:
        pass


def _prewarm_voice():
    """Pre-synthesize the short fixed replies once, so they can be spoken
    instantly even when the Edge voice is slow or the network is down."""
    lines = []
    try:
        for roman, urdu, en in ACKS.values():
            lines += [en, roman, urdu]
    except Exception:
        pass
    lines += [
        "All systems initialized and online, sir.",
        "Sir, internet ka masla lag raha hai. Dobara bolein.",
        "سر، انٹرنیٹ کا مسئلہ لگ رہا ہے۔ دوبارہ بولیں۔",
        "Sir, Gemini ka server abhi slow hai, is liye jawab nahi aaya. Dobara bolein.",
        "سر، جیمنی کا سرور ابھی سست ہے، اس لیے جواب نہیں آیا۔ دوبارہ بولیں۔",
        "Sir, internet connection nahi mil raha. Network check kijiye.",
        "سر، انٹرنیٹ کنکشن نہیں مل رہا۔ نیٹ ورک چیک کیجیے۔",
        "Sir, ek masla aa gaya. Dobara bolein.",
        "سر، ایک مسئلہ آ گیا۔ دوبارہ بولیں۔",
        "Haan sir, bataiye.",
        "ہاں سر، بتائیے۔",
        "Ji sir, abhi karta hoon.",
        "جی سر، ابھی کرتا ہوں۔",
        "Theek hai sir, dekh leta hoon.",
        "ٹھیک ہے سر، دیکھ لیتا ہوں۔",
    ]
    for s in dict.fromkeys(lines):
        if not s:
            continue
        voice = URDU_VOICE if re.search(r'[\u0600-\u06FF]', s) else VOICE_NAME
        try:
            _get_audio_data(s, voice, timeout=15.0)
        except Exception:
            pass


def run_jarvis():
    global chat
    _comp_load()
    threading.Thread(target=shortcut_listener, daemon=True).start()
    threading.Thread(target=mic_listener, daemon=True).start()
    threading.Thread(target=keyboard_input_worker, daemon=True).start()
    threading.Thread(target=_live_loop, daemon=True).start()
    threading.Thread(target=_build_app_index, daemon=True).start()  # indexes every app for instant launch
    threading.Thread(target=_discover_models, daemon=True).start()  # finds the models your key can really use
    threading.Thread(target=_life_loop, daemon=True).start()        # the living companion
    if LIVE_SCREEN_AT_START:
        _set_live(True)

    print("=" * 60)
    print(f" J.A.R.V.I.S. SYSTEM ONLINE v{JARVIS_VERSION} "
          "(Ultra Fast + Voice Engine v3 + Instant Launcher + Living Companion)")
    print(f" - Model: {active_model} (auto-fallback + auto-discovery)")
    print(f" - Voice: {VOICE_GENDER.upper()} ({VOICE_NAME} / {URDU_VOICE})  |  Language: {LANG_MODE.upper()}")
    print(f" - Voice lock: {'ON (stays MALE; say/type unlock voice to change)' if VOICE_LOCK else 'OFF'}")
    print(f" - Microphone: {_mic_mode_text()}")
    print(f" - Smart mode: {'ON' if SMART_MODE else 'OFF'}")
    print(f" - Backup voice: {'ON (female Google voice)' if TTS_BACKUP else 'OFF (always your chosen voice)'}")
    print(f" - Game Take Mode: {'ON' if GAME_AFK_ENABLED else 'OFF'} "
          "('game khelo' / '2 min ke liye game sambhalo' / 'game mode band karo')")
    print(f" - Companion: {'ON' if COMPANION_ENABLED else 'OFF'} (first own thought in "
          f"{CURIOSITY_FIRST_MIN}-{CURIOSITY_FIRST_MAX} min; own searches: "
          f"{'automatic' if _COMP.get('autonomy') == 'auto' else 'ask first'}; "
          f"health reminders: {'ON' if _COMP.get('health', True) else 'OFF'})")
    print(f" - Memory file: {MEMORY_FILE}")
    print(" - Say: 'Hey Jarvis' or 'Jarvis'  |  Ctrl+Alt+J = wake (beep, then speak)")
    print(" - Instant (no Gemini, 1-3 s): 'brave kholo', 'valorant kholo', 'riot kholo', 'notepad kholo',")
    print("   'brave kholo aur new tab kholo aur youtube kholo'  (join tasks with aur / phir / and / then)")
    print(" - Tabs: 'brave kholo, uske andr study tab kholo aur uske andr google notebook kholo'")
    print(" - Companion: 'chup raho' / '1 ghanta chup raho' / 'bolna shuru karo', 'khud faisla lo' / 'pehle poochh lo',")
    print("   'companion off' / 'companion on' / 'companion status', 'health reminders band karo', 'mera pc kaisa hai'")
    print(" - Microphone: type 'mic test' (finds the mic that hears you), 'mic list', 'mic 2', 'mic auto', "
          "'mic default'")
    print(" - Switches (say or type): 'female voice', 'male voice', 'english mode', 'urdu mode', 'both mode'")
    print(" - Ctrl+Alt+S = stop everything  |  Ctrl+Alt+L = live screen  |  Ctrl+Alt+D = cursor debug")
    print(" - Voice chat: Ctrl+Alt+1..5 = callouts, Ctrl+Alt+T = type a line")
    print(" - To sleep: 'Go to sleep'  |  To exit: 'Shutdown'")
    print("=" * 60)

    speak("All systems initialized and online, sir.")
    threading.Thread(target=_preload_voice_cache, daemon=True).start()
    threading.Thread(target=_prewarm_voice, daemon=True).start()

    while True:
        try:
            user_input = command_queue.get()
            stop_flag.clear()
            last_user_activity[0] = time.time()
            main_busy.set()  # the companion never interrupts while a command is being worked on
            try:
                handle_command(user_input)
            finally:
                main_busy.clear()
                last_user_activity[0] = time.time()

        except KeyboardInterrupt:
            afk_stop.set()
            speak("Emergency stop engaged. Goodbye, sir.")
            sys.exit(0)
        except SystemExit:
            raise
        except Exception as e:
            print("\n[Runtime Error]:")
            traceback.print_exc()
            _error_reply(e)


# ==========================================
# ⚡ J.A.R.V.I.S. ULTIMATE UPGRADE
#    Adds missions, deep research, documents, browser/UI automation,
#    full system control, memory 2.0, scheduler, skills and the HUD.
#    The original code above is untouched; this layer wraps it.
# ==========================================
try:
    import jarvis_core as _JARVIS_CORE
    _JARVIS_CORE.install(globals())
except Exception as _ultimate_err:
    _JARVIS_CORE = None
    print(f"[Ultimate Upgrade Error]: {_ultimate_err}")


if __name__ == "__main__":
    run_jarvis()