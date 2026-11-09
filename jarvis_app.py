# ==========================================================
#  J.A.R.V.I.S.  -  STARK INDUSTRIES HUD (Fixed & Animated)
# ==========================================================
import os
import sys
import math
import time
import queue
import array
import random
import threading
import traceback
import webbrowser

import pyautogui
import psutil
import tkinter as tk
from tkinter import messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import jarvis_config as jcfg
except Exception:
    jcfg = None

LOG_FILE = os.path.join(APP_DIR, "jarvis_app.log")
AI_STUDIO_URL = getattr(jcfg, "AI_STUDIO_URL", "https://aistudio.google.com/app/apikey")

PREFERRED_MIC = ""
VERSION = "1.9.0"

# ---------- STARK HUD COLOR PALETTE ----------
BG = "#030712"
PANEL = "#07111e"
PANEL_BORDER = "#0f2742"
TEXT_MAIN = "#e0f2fe"
TEXT_DIM = "#476e8a"
CYAN_GLOW = "#00f0ff"
CYAN_DARK = "#003b4f"

PAL = {
    "loading":   ("#ffb703", "INITIALIZING"),
    "standby":   ("#00e5ff", "STANDBY"),
    "listening": ("#38bdf8", "LISTENING"),
    "hearing":   ("#00f59b", "RECOGNIZING"),
    "thinking":  ("#fbbf24", "PROCESSING"),
    "speaking":  ("#a5f3fc", "VOCALIZING"),
    "gaming":    ("#c084fc", "COMBAT TAKEOVER"),
    "muted":     ("#f43f5e", "SYSTEM MUTED"),
}

HINT = {
    "loading":   "Core systems online hone mein thora waqt lag raha hai...",
    "standby":   "Stark OS standby. 'Hey Jarvis' bolein ya Mic par click karein.",
    "listening": "Listening active: Boliye sir, main sun raha hoon...",
    "hearing":   "Audio received: Aap ki awaz decipher ho rahi hai...",
    "thinking":  "Neural engine thinking / performing task...",
    "speaking":  "Audio synthesizer transmitting response...",
    "gaming":    "🎮 Autonomous Game Control ACTIVE. Abort ke liye STOP dabayein.",
    "muted":     "Microphone disabled. Unmute karne ke liye Mic icon click karein.",
}

ARC_SPEED = {
    "loading":   (280, -220, 160, -110),
    "standby":   (18, -12, 8, -6),
    "listening": (65, -45, 35, -25),
    "hearing":   (110, -90, 60, -40),
    "thinking":  (280, -220, 160, -110),
    "speaking":  (85, -60, 45, -30),
    "gaming":    (220, -180, 140, -95),
    "muted":     (0, 0, 0, 0),
}

S = {"muted": False, "busy": False, "ready": False, "gaming": False,
     "mic_name": "", "mic_warn": "", "level": 0.0, "last_read": 0.0,
     "level_ok": False, "cpu": 0, "ram": 0, "selected_mic_idx": None}
ui_q = queue.Queue()


def ui_log(kind: str, text: str):
    ui_q.put((kind, text))


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


# ==========================================================
#  Tee Logging
# ==========================================================
class _Tee:
    encoding = "utf-8"

    def __init__(self, orig, is_err=False):
        self.orig, self.is_err = orig, is_err
        self.buf, self.lock = "", threading.Lock()
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
                os.remove(LOG_FILE)
            self.f = open(LOG_FILE, "a", encoding="utf-8")
        except Exception:
            self.f = None

    def write(self, s):
        try:
            if self.orig:
                self.orig.write(s)
        except Exception:
            pass
        with self.lock:
            self.buf += s
            lines = self.buf.split("\n")
            self.buf = lines.pop()
        for line in lines:
            line = line.strip()
            if line:
                self._line(line)
        return len(s)

    def _line(self, line):
        try:
            if self.f:
                self.f.write(time.strftime("%H:%M:%S ") + line + "\n")
                self.f.flush()
        except Exception:
            pass
        if line.startswith("J.A.R.V.I.S.:") or set(line) <= {"="}:
            return
        low = line.lower()
        bad = self.is_err or "error" in low or "failed" in low or "traceback" in low
        ui_log("err" if bad else "sys", line)

    def flush(self):
        pass

    def isatty(self):
        return False


# ==========================================================
#  Microphone Patches
# ==========================================================
VIRTUAL = ("cable", "voicemeeter", "vb-audio", "stereo mix", "sound mapper", "primary sound capture")


def pick_real_mic(sr):
    if S.get("selected_mic_idx") is not None:
        return S["selected_mic_idx"]

    try:
        pa = sr.Microphone.get_pyaudio().PyAudio()
    except Exception:
        return None
    found = []
    try:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                found.append((i, info.get("name", "")))
    finally:
        pa.terminate()
    ui_log("sys", "Audio Hardware: " + " | ".join(f"{i}:{n}" for i, n in found))
    pick = None
    if PREFERRED_MIC:
        pick = next(((i, n) for i, n in found if PREFERRED_MIC.lower() in n.lower()), None)
    if not pick:
        pick = next(((i, n) for i, n in found if not any(v in n.lower() for v in VIRTUAL)), None)
    if pick:
        S["mic_name"] = pick[1]
        S["selected_mic_idx"] = pick[0]
        return pick[0]
    S["mic_warn"] = "Hardware input not found. Connect mic."
    return None


def patch_speech_recognition():
    import speech_recognition as sr
    try:
        orig_read = sr.Microphone.MicrophoneStream.read

        def read(self, size):
            data = orig_read(self, size)
            try:
                a = array.array("h", data)[::8]
                if a:
                    S["level"] = (sum(x * x for x in a) / len(a)) ** 0.5
                S["last_read"] = time.time()
            except Exception:
                pass
            return data

        sr.Microphone.MicrophoneStream.read = read
        S["level_ok"] = True
    except Exception:
        S["level_ok"] = False

    orig_init = sr.Microphone.__init__

    def init(self, device_index=None, *a, **k):
        if device_index is None:
            device_index = pick_real_mic(sr)
        orig_init(self, device_index, *a, **k)

    sr.Microphone.__init__ = init

    orig_rg = sr.Recognizer.recognize_google

    def rg(self, audio_data, *a, **k):
        if S["muted"]:
            raise sr.UnknownValueError()
        return orig_rg(self, audio_data, *a, **k)

    sr.Recognizer.recognize_google = rg

    orig_listen = sr.Recognizer.listen

    def listen(self, *a, **k):
        try:
            return orig_listen(self, *a, **k)
        except sr.WaitTimeoutError:
            raise
        except Exception:
            time.sleep(1.0)
            raise

    sr.Recognizer.listen = listen


# ==========================================
#  Jarvis Hooks & Hotkeys
# ==========================================
def draw_cursor(J, img, origin, scale):
    try:
        from PIL import ImageDraw
        cx, cy = J.pyautogui.position()
        x, y = int((cx - origin[0]) * scale), int((cy - origin[1]) * scale)
        if not (0 <= x < img.width and 0 <= y < img.height):
            return img
        img = img.convert("RGB")
        d = ImageDraw.Draw(img)
        r = max(14, img.width // 100)
        red = (255, 30, 80)
        d.ellipse((x - r, y - r, x + r, y + r), outline=red, width=max(3, r // 5))
        d.line((x - 2 * r, y, x + 2 * r, y), fill=red, width=max(2, r // 6))
        d.line((x, y - 2 * r, x, y + 2 * r), fill=red, width=max(2, r // 6))
        return img
    except Exception:
        return img


def patch_jarvis(J):
    import io

    orig_speak = J.speak

    def speak(text, urdu=None):
        ui_log("jarvis", text)
        return orig_speak(text, urdu)

    J.speak = speak

    orig_ask = J.ask_gemini

    def ask(user_input):
        S["busy"] = True
        try:
            return orig_ask(user_input)
        finally:
            S["busy"] = False

    J.ask_gemini = ask

    class UIQueue(queue.Queue):
        def put(self, item, block=True, timeout=None):
            if isinstance(item, str):
                ui_log("user", item)
            super().put(item, block, timeout)

    J.command_queue = UIQueue()

    if hasattr(J, "play_game_afk"):
        orig_play = J.play_game_afk

        def wrapped_play(duration_seconds=120):
            S["gaming"] = True
            ui_log("game", f"TAKEOVER INITIALIZED ({duration_seconds}s). Press ABORT or Ctrl+Alt+S to cancel.")
            try:
                return orig_play(duration_seconds)
            finally:
                S["gaming"] = False
                ui_log("game", "TAKEOVER TERMINATED. Normal controls restored.")

        J.play_game_afk = wrapped_play

        for i, tool in enumerate(getattr(J, "TOOLS", [])):
            if getattr(tool, "__name__", "") == "play_game_afk":
                J.TOOLS[i] = J._wrap_tool(wrapped_play)

    J.LIVE_INTERVAL = 3.0

    def light_grab_frame():
        origin = J._virtual_screen()[:2]
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = J.pyautogui.screenshot()
            origin = (0, 0)
        scale = min(1.0, 1600.0 / max(img.width, img.height))
        if scale < 1.0:
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
        img = draw_cursor(J, img, origin, scale)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=65)
        return buf.getvalue()

    J._grab_frame_jpeg = light_grab_frame
    J.shortcut_listener = lambda: None


def start_hotkeys(J):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    MOD = 0x0001 | 0x0002 | 0x4000
    actions = {}

    def add(ch, fn):
        actions[ord(ch.upper())] = fn

    add("J", lambda: J.wake_up(silent=True))
    add("S", lambda: (S.update({"gaming": False}), J._stop_all()))
    add("L", J._toggle_live)
    if hasattr(J, "_debug_cursor"):
        add("D", lambda: threading.Thread(target=J._debug_cursor, daemon=True).start())
    add("T", lambda: ui_q.put(("call", "say")))

    for combo, (eng, urdu) in J.VOICE_PRESETS.items():
        key = combo.split("+")[-1]
        if len(key) == 1:
            add(key, lambda e=eng, u=urdu: J._relay_preset(e, u))

    def loop():
        ids = {}
        for n, (vk, fn) in enumerate(actions.items(), 1):
            if user32.RegisterHotKey(None, n, MOD, vk):
                ids[n] = fn
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:
                fn = ids.get(msg.wParam)
                if fn:
                    threading.Thread(target=fn, daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()


# ==========================================================
#  STARK INDUSTRIES HUD APPLICATION
# ==========================================================
class App:
    NB = 48

    def __init__(self, root):
        self.root = root
        self.J = None
        self.st = None
        self.lvl = 0.0
        self.lit = -1
        self.say = None
        self.muted_ui = None
        self.live_ui = None
        self.gaming_ui = None
        self.last_stat = 0.0
        self.K = max(1.0, root.winfo_fpixels("1i") / 96.0)
        K = self.K

        root.title(f"STARK INDUSTRIES // J.A.R.V.I.S. HUD v{VERSION}")
        root.configure(bg=BG)
        root.geometry(f"{int(1060 * K)}x{int(760 * K)}")
        root.minsize(int(920 * K), int(680 * K))
        root.protocol("WM_DELETE_WINDOW", self.quit)

        # ---------------- TOP TELEMETRY BAR ----------------
        top_bar = tk.Frame(root, bg="#050c18", height=int(32 * K), highlightthickness=1,
                           highlightbackground="#0d243a")
        top_bar.pack(side="top", fill="x")

        self.t_brand = tk.Label(top_bar, text=f"STARK INDUSTRIES // MARK VIII // J.A.R.V.I.S. v{VERSION}",
                                bg="#050c18", fg=CYAN_GLOW, font=("Consolas", 9, "bold"))
        self.t_brand.pack(side="left", padx=16, pady=4)

        self.t_stats = tk.Label(top_bar, text="CPU: --%  |  RAM: --%  |  CORE: ONLINE",
                                bg="#050c18", fg=TEXT_DIM, font=("Consolas", 9))
        self.t_stats.pack(side="right", padx=16, pady=4)

        self.b_key = tk.Button(top_bar, text="[ API KEY ]", command=self.open_api_key_dialog,
                               bg="#081422", fg=TEXT_DIM, activebackground="#0e243b",
                               activeforeground=CYAN_GLOW, relief="flat", bd=0,
                               padx=8, pady=2, font=("Consolas", 9, "bold"),
                               cursor="hand2", highlightthickness=1,
                               highlightbackground="#133654")
        self.b_key.pack(side="right", padx=(0, 8), pady=2)

        main_work = tk.Frame(root, bg=BG)
        main_work.pack(fill="both", expand=True, padx=12, pady=10)

        # ---------------- LEFT: ARC REACTOR HUD ----------------
        left = tk.Frame(main_work, bg=BG)
        left.pack(side="left", fill="y", padx=(6, 8))

        self.W = int(470 * K)
        self.c = self.W // 2
        c = self.c

        self.cv = cv = tk.Canvas(left, width=self.W, height=self.W, bg=BG, highlightthickness=0)
        cv.pack()

        cv.create_line(c - 210 * K, c, c + 210 * K, c, fill="#081827", dash=(2, 6))
        cv.create_line(c, c - 210 * K, c, c + 210 * K, fill="#081827", dash=(2, 6))

        self.outer_compass = cv.create_oval(c - 200 * K, c - 200 * K, c + 200 * K, c + 200 * K,
                                            outline="#0c2236", width=1, dash=(3, 9))
        self.rings = [cv.create_oval(0, 0, 1, 1, outline="#0d2e47", width=2) for _ in range(4)]
        self.arcs = [cv.create_arc(0, 0, 1, 1, start=0, extent=ext, style="arc", outline=CYAN_GLOW,
                                   width=max(2, int(4 * K))) for ext in (80, 55, 110, 40)]
        self.bars = [cv.create_line(c, c, c, c, fill=CYAN_GLOW, width=max(2, int(2.6 * K)), capstyle="round")
                     for _ in range(self.NB)]

        self.particles = []
        for _ in range(16):
            pt = cv.create_oval(0, 0, 1, 1, fill=CYAN_GLOW, outline="")
            self.particles.append({"id": pt, "ang": random.uniform(0, 6.28), "r": random.uniform(60, 180),
                                   "spd": random.uniform(0.015, 0.045)})

        self.glow_ring = cv.create_oval(0, 0, 1, 1, outline=CYAN_DARK, width=6)
        self.core = cv.create_oval(0, 0, 1, 1, fill="#04121d", outline=CYAN_GLOW, width=2)
        self.t_title = cv.create_text(c, c - 13 * K, text="J.A.R.V.I.S.", fill=TEXT_MAIN,
                                      font=("Segoe UI", 13, "bold"))
        self.t_sub = cv.create_text(c, c + 14 * K, text="ONLINE", fill=CYAN_GLOW,
                                    font=("Consolas", 10, "bold"))

        self.cos = [math.cos(2 * math.pi * i / self.NB - math.pi / 2) for i in range(self.NB)]
        self.sin = [math.sin(2 * math.pi * i / self.NB - math.pi / 2) for i in range(self.NB)]

        self.hint = tk.Label(left, text=HINT["loading"], bg=BG, fg=TEXT_DIM,
                             font=("Segoe UI", 9), wraplength=int(450 * K))
        self.hint.pack(pady=(4, 8))

        ctrl = tk.Frame(left, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        ctrl.pack(fill="x", padx=4, pady=(0, 10))

        self.mic_cv = tk.Canvas(ctrl, width=int(64 * K), height=int(64 * K), bg=PANEL,
                                highlightthickness=0, cursor="hand2")
        self.mic_cv.grid(row=0, column=0, rowspan=3, padx=(8, 10), pady=6)
        self.mic_circle = self.mic_cv.create_oval(4 * K, 4 * K, 60 * K, 60 * K, fill="#0d1f30",
                                                  outline=CYAN_GLOW, width=2)
        self.mic_icon = self.mic_cv.create_text(32 * K, 32 * K, text="\U0001F3A4", fill=TEXT_MAIN,
                                                font=("Segoe UI Emoji", 19))
        self.mic_cv.bind("<Button-1>", lambda e: self.toggle_listen())

        self.mw = int(340 * K)
        self.meter = tk.Canvas(ctrl, width=self.mw, height=int(16 * K), bg=PANEL, highlightthickness=0)
        self.meter.grid(row=0, column=1, sticky="w", pady=(8, 0))
        self.segs, self.seg_cols = [], []
        n, gap = 28, max(2, int(2 * K))
        sw = (self.mw - gap * (n - 1)) / n
        for i in range(n):
            col = "#00f0ff" if i < 16 else ("#38bdf8" if i < 22 else "#f43f5e")
            self.seg_cols.append(col)
            x0 = i * (sw + gap)
            self.segs.append(self.meter.create_rectangle(x0, 2, x0 + sw, 14 * K, fill="#091827", width=0))

        self.mic_lbl = tk.Label(ctrl, text="AUDIO INPUT // INITIALIZING...", bg=PANEL, fg=TEXT_DIM,
                                font=("Consolas", 10, "bold"))
        self.mic_lbl.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self.dev_lbl = tk.Label(ctrl, text="", bg=PANEL, fg="#3b6584", font=("Segoe UI", 8),
                                wraplength=int(330 * K), justify="left")
        self.dev_lbl.grid(row=2, column=1, sticky="w", pady=(0, 6))

        # ---------------- 9 CONTROL BUTTONS (3x3 GRID) ----------------
        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", padx=4)

        def mk(text, cmd, border="#133654"):
            return tk.Button(btns, text=text, command=cmd, bg="#081422", fg=TEXT_MAIN,
                             activebackground="#0e243b", activeforeground=CYAN_GLOW, relief="flat",
                             highlightthickness=1, highlightbackground=border, bd=0, padx=8, pady=7,
                             font=("Consolas", 9, "bold"), cursor="hand2")

        # Row 1
        self.b_mute = mk("[ MIC : LIVE ]", self.toggle_mute)
        self.b_mic_sel = mk("[ 🎙️ SELECT MIC ]", self.choose_mic, border="#0284c7")
        self.b_voice = mk("[ 👤 VOICE : MALE ]", self.toggle_voice, border="#0284c7")

        # Row 2
        self.b_lang = mk("[ 🌐 LANG : BOTH ]", self.toggle_lang, border="#0284c7")
        self.b_live = mk("[ VISION : OFF ]", self.toggle_live)
        self.b_team = mk("[ TEAM COMMS ]", self.open_say_box)

        # Row 3
        self.b_game = mk("[ 🎮 GAME TAKE ]", self.toggle_game, border="#6b21a8")
        self.b_stop = mk("[ 🛑 ABORT ALL ]", self.stop_all, border="#881337")
        self.b_pin = mk("[ PIN HUD ]", self.toggle_pin)

        btn_list = (self.b_mute, self.b_mic_sel, self.b_voice,
                    self.b_lang, self.b_live, self.b_team,
                    self.b_game, self.b_stop, self.b_pin)

        for i, b in enumerate(btn_list):
            b.grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")
        for i in range(3):
            btns.grid_columnconfigure(i, weight=1)
        self.pinned = False

        # ---------------- RIGHT: STREAM LOG ----------------
        right = tk.Frame(main_work, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        right.pack(side="right", fill="both", expand=True, padx=(8, 4))

        head = tk.Frame(right, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(head, text="COMMUNICATION & TELEMETRY STREAM", bg=PANEL, fg=CYAN_GLOW,
                 font=("Consolas", 10, "bold")).pack(side="left")

        self.details = tk.BooleanVar(value=False)
        tk.Checkbutton(head, text="Verbose Feed", variable=self.details, command=self.toggle_details,
                       bg=PANEL, fg=TEXT_DIM, selectcolor=BG, activebackground=PANEL,
                       activeforeground=TEXT_MAIN, font=("Segoe UI", 8)).pack(side="right")

        box = tk.Frame(right, bg="#040b14")
        box.pack(fill="both", expand=True, padx=10, pady=4)

        sb = tk.Scrollbar(box, bg="#040b14", troughcolor="#040b14")
        sb.pack(side="right", fill="y")

        self.log = tk.Text(box, bg="#040b14", fg=TEXT_MAIN, wrap="word", relief="flat", bd=0,
                           padx=12, pady=10, font=("Segoe UI", 10), state="disabled",
                           yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.config(command=self.log.yview)

        self.log.tag_configure("user", foreground="#38bdf8", font=("Segoe UI", 10, "bold"))
        self.log.tag_configure("jarvis", foreground="#4ade80")
        self.log.tag_configure("game", foreground="#c084fc", font=("Consolas", 10, "bold"))
        self.log.tag_configure("err", foreground="#fb7185")
        self.log.tag_configure("sys", foreground="#476e8a", elide=True)

        row = tk.Frame(right, bg=PANEL)
        row.pack(fill="x", padx=10, pady=(8, 10))

        self.entry = tk.Entry(row, bg="#030810", fg=TEXT_MAIN, insertbackground=CYAN_GLOW,
                              relief="flat", highlightthickness=1, highlightbackground="#0f2b48",
                              font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self.submit())

        tk.Button(row, text="TRANSMIT ❯", command=self.submit, bg="#0284c7", fg="#030712",
                  activebackground=CYAN_GLOW, activeforeground="#030712", relief="flat", bd=0,
                  padx=16, pady=7, font=("Consolas", 10, "bold"), cursor="hand2").pack(side="right")
        self.entry.focus_set()

        ui_log("sys", "Stark OS online. Core neural network initializing...")
        self.pump()
        self.tick()

    def submit(self):
        t = self.entry.get().strip()
        self.entry.delete(0, "end")
        if not t or not self.J:
            return
        self.J.is_awake.set()
        self.J.command_queue.put(t)

    def toggle_listen(self):
        J = self.J
        if not J:
            return
        if S["muted"]:
            self.toggle_mute()
            threading.Thread(target=J.wake_up, kwargs={"silent": True}, daemon=True).start()
        elif J.is_awake.is_set():
            J.is_awake.clear()
            ui_log("sys", "Standby engaged. Awaiting wake word or manual trigger.")
        else:
            threading.Thread(target=J.wake_up, kwargs={"silent": True}, daemon=True).start()

    def sync_state_labels(self):
        """Show the language / voice that were actually loaded from settings.

        The buttons used to be created with the text BOTH / MALE no matter what
        jarvis_settings.json contained, so the HUD could say BOTH while Jarvis
        was really in Roman-Urdu mode.
        """
        if not self.J:
            return
        labels = {"both": "BOTH", "en": "ENGLISH", "ur": "ROMAN URDU"}
        mode = getattr(self.J, "LANG_MODE", "both")
        gender = getattr(self.J, "VOICE_GENDER", "male")
        try:
            self.b_lang.config(text=f"[ 🌐 LANG : {labels.get(mode, 'BOTH')} ]")
            self.b_voice.config(text=f"[ 👤 VOICE : {gender.upper()} ]")
            self.b_mute.config(text="[ MIC : MUTED ]" if S.get("muted") else "[ MIC : LIVE ]")
        except Exception:
            pass

    def toggle_mute(self):
        S["muted"] = not S["muted"]
        ui_log("sys", "Microphone array MUTED." if S["muted"] else "Microphone array ONLINE.")

    def toggle_voice(self):
        if not self.J:
            return
        current = getattr(self.J, "VOICE_GENDER", "male")
        new_gender = "female" if current == "male" else "male"
        changed = self.J.set_voice_gender(new_gender)
        if not changed:
            # VOICE_LOCK is on: tell the user instead of flipping the voice by
            # accident (a stray click used to change it silently).
            ui_log("sys", "Voice is LOCKED to MALE. Say/type 'unlock voice' first to change it.")
            self.sync_state_labels()
            return
        self.b_voice.config(text=f"[ 👤 VOICE : {new_gender.upper()} ]")
        ui_log("sys", f"Voice persona set to: {new_gender.upper()}")

    def toggle_lang(self):
        if not self.J:
            return
        modes = ["both", "en", "ur"]
        labels = {"both": "BOTH", "en": "ENGLISH", "ur": "ROMAN URDU"}
        current = getattr(self.J, "LANG_MODE", "both")
        idx = (modes.index(current) + 1) % len(modes) if current in modes else 0
        new_mode = modes[idx]
        self.J.set_lang_mode(new_mode)
        self.b_lang.config(text=f"[ 🌐 LANG : {labels[new_mode]} ]")
        ui_log("sys", f"Language mode set to: {labels[new_mode]}")

    def choose_mic(self):
        import speech_recognition as sr
        try:
            pa = sr.Microphone.get_pyaudio().PyAudio()
            mics = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    mics.append((i, info.get("name", f"Microphone {i}")))
            pa.terminate()
        except Exception as e:
            messagebox.showerror("Audio Hardware Error", f"Failed to detect microphones: {e}")
            return

        if not mics:
            messagebox.showwarning("No Microphones", "No hardware audio input devices found.")
            return

        win = tk.Toplevel(self.root)
        win.title("SELECT AUDIO INPUT HARDWARE")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.geometry(f"{int(540 * self.K)}x{int(360 * self.K)}")
        win.minsize(420, 280)

        tk.Label(win, text="DETECTED AUDIO HARDWARE CHANNELS", bg=BG, fg=CYAN_GLOW,
                 font=("Consolas", 10, "bold")).pack(pady=(12, 6), padx=12, anchor="w")

        f = tk.Frame(win, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        f.pack(fill="both", expand=True, padx=12, pady=6)

        sb = tk.Scrollbar(f, bg=PANEL)
        sb.pack(side="right", fill="y")

        lb = tk.Listbox(f, bg="#040b14", fg=TEXT_MAIN, selectbackground="#0284c7",
                        selectforeground="#ffffff", font=("Segoe UI", 10),
                        relief="flat", bd=0, yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sb.config(command=lb.yview)

        active_idx = getattr(self.J, "ACTIVE_MIC_INDEX", None) if self.J else S.get("selected_mic_idx")
        sel_row = 0
        for row, (idx, name) in enumerate(mics):
            prefix = "► " if (active_idx == idx or (active_idx is None and S.get("mic_name") == name)) else "  "
            lb.insert("end", f"{prefix}[ID {idx}] {name}")
            if active_idx == idx or (active_idx is None and S.get("mic_name") == name):
                sel_row = row

        lb.selection_set(sel_row)
        lb.activate(sel_row)

        def apply_sel(_=None):
            sel = lb.curselection()
            if not sel:
                win.destroy()
                return
            chosen_idx, chosen_name = mics[sel[0]]
            S["selected_mic_idx"] = chosen_idx
            S["mic_name"] = chosen_name
            if self.J:
                self.J.set_active_mic(chosen_idx)
            self.dev_lbl.configure(text="DEV: " + chosen_name[:40], fg=CYAN_GLOW)
            ui_log("sys", f"Hardware input switched to: [{chosen_idx}] {chosen_name}")
            win.destroy()

        b_row = tk.Frame(win, bg=BG)
        b_row.pack(fill="x", padx=12, pady=10)

        tk.Button(b_row, text="CANCEL", command=win.destroy, bg="#081422", fg=TEXT_DIM,
                  relief="flat", bd=0, padx=14, pady=6, font=("Consolas", 9, "bold")).pack(side="left")

        tk.Button(b_row, text="ACTIVATE SELECTED MIC ❯", command=apply_sel, bg="#0284c7", fg="#030712",
                  activebackground=CYAN_GLOW, activeforeground="#030712", relief="flat", bd=0,
                  padx=16, pady=6, font=("Consolas", 10, "bold"), cursor="hand2").pack(side="right")

        lb.bind("<Double-Button-1>", apply_sel)
        win.bind("<Return>", apply_sel)
        win.bind("<Escape>", lambda e: win.destroy())

    def toggle_live(self):
        J = self.J
        if J:
            J._set_live(not J.live_on.is_set())

    def toggle_game(self):
        if not self.J:
            return
        if S.get("gaming"):
            self.stop_all()
        else:
            def run():
                try:
                    self.J.speak("Ji sir, main game controls sambhal raha hoon.",
                                 urdu="جی سر، میں گیم کنٹرولز سنبھال رہا ہوں۔")
                    self.J.play_game_afk(120)
                except Exception as e:
                    ui_log("err", f"Takeover fault: {e}")
            threading.Thread(target=run, daemon=True).start()

    def stop_all(self):
        S["gaming"] = False
        if self.J:
            threading.Thread(target=self.J._stop_all, daemon=True).start()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.b_pin.config(text="[ UNPIN HUD ]" if self.pinned else "[ PIN HUD ]",
                          bg="#0c2b48" if self.pinned else "#081422")

    def toggle_details(self):
        self.log.tag_configure("sys", elide=not self.details.get())

    def open_say_box(self):
        if self.say is not None:
            try:
                if self.say.winfo_exists():
                    self.say.lift()
                    return
            except Exception:
                pass
        w = tk.Toplevel(self.root)
        self.say = w
        w.title("STARK COMMS TRANSMITTER")
        w.attributes("-topmost", True)
        w.configure(bg=BG)
        w.geometry(f"{int(520 * self.K)}x{int(80 * self.K)}+420+300")
        e = tk.Entry(w, font=("Segoe UI", 13), bg="#071526", fg=TEXT_MAIN,
                     insertbackground=CYAN_GLOW, relief="flat",
                     highlightthickness=1, highlightbackground=CYAN_GLOW)
        e.pack(fill="x", padx=12, pady=16, ipady=6)

        def go(_=None):
            t = e.get().strip()
            w.destroy()
            if t and self.J:
                ui_log("sys", "Transmitting to team: " + t)
                threading.Thread(target=self.J.relay_text, args=(t,), daemon=True).start()

        e.bind("<Return>", go)
        e.bind("<Escape>", lambda ev: w.destroy())
        w.after(150, lambda: (w.lift(), w.focus_force(), e.focus_force()))

    def open_api_key_dialog(self):
        """Open the API key editor from the HUD and apply a new key live."""
        def on_saved(_key):
            J = self.J
            applied = False
            if J is not None:
                try:
                    from google import genai
                    from google.genai import types
                    opts = types.HttpOptions(timeout=15000)
                    J.client = genai.Client(http_options=opts)
                    J.client_fast = genai.Client(http_options=opts)
                    J.client_smart = genai.Client(http_options=opts)
                    applied = True
                except Exception:
                    applied = False
            if applied:
                self.add_log("sys", "Gemini API key updated live.")
            else:
                self.add_log("sys", "Gemini API key saved. Restart Jarvis to apply it.")

        api_key_dialog(self.root, first_run=False, on_saved=on_saved)

    def quit(self):
        try:
            self.root.destroy()
        finally:
            os._exit(0)

    def add_log(self, kind, text):
        prefix = {
            "user":   "❯ USER        |  ",
            "jarvis": "✦ J.A.R.V.I.S |  ",
            "game":   "🎮 OVERRIDE   |  ",
            "err":    "⚠ ALERT       |  ",
            "sys":    "⚙ SYSTEM      |  "
        }.get(kind, "")
        self.log.configure(state="normal")
        self.log.insert("end", prefix + text + "\n", kind)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 600:
            self.log.delete("1.0", f"{lines - 500}.0")
        self.log.configure(state="disabled")
        self.log.see("end")

    def pump(self):
        try:
            for _ in range(60):
                kind, text = ui_q.get_nowait()
                if kind == "call":
                    if text == "say":
                        self.open_say_box()
                    elif text == "quit":
                        self.quit()
                elif kind == "error":
                    messagebox.showerror("J.A.R.V.I.S. Error", text)
                else:
                    self.add_log(kind, text)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def tick(self):
        J = self.J
        now = time.time()
        try:
            iconic = self.root.state() == "iconic"
        except Exception:
            iconic = False

        if now - self.last_stat > 2.5:
            try:
                S["cpu"] = int(psutil.cpu_percent())
                S["ram"] = int(psutil.virtual_memory().percent)
                self.t_stats.configure(text=f"CPU: {S['cpu']}%  |  RAM: {S['ram']}%  |  CORE: ONLINE")
            except Exception:
                pass
            self.last_stat = now

        raw = S["level"] if now - S["last_read"] < 1.0 else 0.0
        target = min(1.0, (raw / 2600.0) ** 0.7) if raw > 120 else 0.0
        self.lvl += (target - self.lvl) * 0.4
        lvl = self.lvl

        awake = bool(J and J.is_awake.is_set())
        speaking = bool(J and (J.speaking.is_set() or J.relay_busy.is_set()))
        gaming = bool(S.get("gaming", False))

        if not S["ready"]:
            st = "loading"
        elif S["muted"]:
            st = "muted"
        elif gaming:
            st = "gaming"
        elif speaking:
            st = "speaking"
        elif S["busy"]:
            st = "thinking"
        elif awake:
            st = "hearing" if lvl > 0.12 else "listening"
        else:
            st = "standby"

        cv, c, K = self.cv, self.c, self.K
        col = PAL[st][0]

        if st != self.st:
            self.st = st
            dim = mix(col, BG, 0.4)
            for it in self.rings:
                cv.itemconfigure(it, outline=dim)
            for it in self.arcs:
                cv.itemconfigure(it, outline=col)
            for it in self.bars:
                cv.itemconfigure(it, fill=col)
            cv.itemconfigure(self.core, outline=col)
            cv.itemconfigure(self.glow_ring, outline=mix(col, BG, 0.6))
            cv.itemconfigure(self.t_sub, text=PAL[st][1], fill=col)
            self.hint.configure(text=HINT[st])

        quiet = st in ("standby", "muted") and lvl < 0.08
        if not iconic:
            t = now
            pulse_mod = 0.04 * math.sin(t * 8) if (speaking or gaming) else 0.0
            r0 = 74 * K * (1 + 0.03 * math.sin(t * 2.2) + 0.12 * lvl + pulse_mod)
            cv.coords(self.core, c - r0, c - r0, c + r0, c + r0)
            cv.coords(self.glow_ring, c - r0 - 6 * K, c - r0 - 6 * K, c + r0 + 6 * K, c + r0 + 6 * K)

            for i, it in enumerate(self.rings):
                base = (98 + 24 * i) * K
                r = base + (lvl * 12 * (i + 1) * K if st in ("standby", "listening", "hearing") else 0)
                if speaking or gaming:
                    r += 5 * K * math.sin(t * 5 + i)
                cv.coords(it, c - r, c - r, c + r, c + r)

            sp = ARC_SPEED.get(st, (20, -15, 10, -5))
            for i, it in enumerate(self.arcs):
                r = (90 + 24 * i) * K
                cv.coords(it, c - r, c - r, c + r, c + r)
                cv.itemconfigure(it, start=(t * sp[i % len(sp)]) % 360)

            rot = (t * 3.2) % (2 * math.pi)
            for i, it in enumerate(self.bars):
                if st == "speaking":
                    amp = 0.35 + 0.65 * abs(math.sin(t * 7 + i * 0.5)) * (0.6 + 0.4 * abs(math.sin(t * 2.5 + i * 1.8)))
                elif st == "gaming":
                    amp = 0.25 + 0.75 * abs(math.sin(t * 8 + i * 0.65))
                elif st in ("hearing", "listening", "standby"):
                    amp = 0.08 + 0.04 * math.sin(t * 1.6 + i * 0.4) + lvl * (0.45 + 0.55 * abs(math.sin(t * 10 + i * 0.8)))
                elif st in ("thinking", "loading"):
                    a = 2 * math.pi * i / self.NB - math.pi / 2
                    amp = 0.08 + 0.92 * max(0.0, math.cos(a - rot)) ** 6
                else:
                    amp = 0.05
                x0, y0 = c + self.cos[i] * 155 * K, c + self.sin[i] * 155 * K
                ln = (6 + amp * 48) * K
                cv.coords(self.bars[i], x0, y0, x0 + self.cos[i] * ln, y0 + self.sin[i] * ln)

            for p in self.particles:
                p["ang"] += p["spd"] * (2.2 if speaking or gaming else 1.0)
                pr = p["r"] * K + (lvl * 25 * K)
                px = c + pr * math.cos(p["ang"])
                py = c + pr * math.sin(p["ang"])
                sz = max(1.5, 2.8 * K)
                cv.coords(p["id"], px - sz, py - sz, px + sz, py + sz)
                cv.itemconfigure(p["id"], fill=col)

            if st == "muted":
                self.mic_cv.itemconfigure(self.mic_circle, fill="#2b0a11", outline=col)
            elif awake or st in ("speaking", "thinking", "gaming"):
                pulse = 0.5 + 0.5 * math.sin(t * 4.5)
                self.mic_cv.itemconfigure(self.mic_circle, fill=mix("#042030", col, 0.25 + 0.35 * pulse),
                                          outline=col)
            else:
                self.mic_cv.itemconfigure(self.mic_circle, fill="#081827", outline=CYAN_GLOW)

        lit = int(round(min(1.0, lvl) * len(self.segs)))
        if lit != self.lit:
            self.lit = lit
            for i, s in enumerate(self.segs):
                self.meter.itemconfigure(s, fill=self.seg_cols[i] if i < lit else "#091827")

        alive = (now - S["last_read"] < 2.0)
        if not S["ready"]:
            txt, mc = "AUDIO // INITIALIZING", TEXT_DIM
        elif S["muted"]:
            txt, mc = "AUDIO // MUTED", "#f43f5e"
        elif gaming:
            txt, mc = "OVERRIDE // COMBAT ACTIVE", "#c084fc"
        elif S["level_ok"] and not alive:
            txt, mc = "AUDIO // SIGNAL WEAK", "#fbbf24"
        elif awake:
            txt, mc = "AUDIO // RECEIVING COMMAND", "#00f59b"
        else:
            txt, mc = "AUDIO // AWAITING WAKE WORD", CYAN_GLOW
        self.mic_lbl.configure(text=txt, fg=mc)

        if S["mic_warn"]:
            self.dev_lbl.configure(text="! " + S["mic_warn"], fg="#fb7185")
        elif S["mic_name"]:
            self.dev_lbl.configure(text="DEV: " + S["mic_name"][:40], fg="#3b6584")

        if self.muted_ui != S["muted"]:
            self.muted_ui = S["muted"]
            self.b_mute.config(text="[ MIC : MUTED ]" if S["muted"] else "[ MIC : LIVE ]",
                               bg="#3b0f1a" if S["muted"] else "#081422",
                               highlightbackground="#ef4444" if S["muted"] else "#133654")

        live = bool(J and J.live_on.is_set())
        if self.live_ui != live:
            self.live_ui = live
            self.b_live.config(text="[ VISION : ON ]" if live else "[ VISION : OFF ]",
                               bg="#0b3829" if live else "#081422",
                               highlightbackground="#10b981" if live else "#133654")

        if self.gaming_ui != gaming:
            self.gaming_ui = gaming
            self.b_game.config(text="[ 🎮 COMBAT ON ]" if gaming else "[ 🎮 GAME TAKE ]",
                               bg="#4c1d95" if gaming else "#081422",
                               highlightbackground="#c084fc" if gaming else "#6b21a8")

        delay = 240 if iconic else (70 if quiet else 26)
        self.root.after(delay, self.tick)

    def boot(self):
        try:
            patch_speech_recognition()
            import jarvis as J
            patch_jarvis(J)
            self.J = J
            self.root.after(0, self.sync_state_labels)
            start_hotkeys(J)
            S["ready"] = True

            def run():
                try:
                    J.run_jarvis()
                except SystemExit:
                    ui_q.put(("call", "quit"))
                except Exception:
                    traceback.print_exc()

            threading.Thread(target=run, daemon=True).start()
        except Exception:
            ui_q.put(("error", "Jarvis start nahi hua.\n\njarvis.py isi folder mein hona chahiye.\n\n"
                      + traceback.format_exc()[-1500:]))


def _open_ai_studio():
    try:
        webbrowser.open(AI_STUDIO_URL)
    except Exception:
        pass


def api_key_dialog(root, first_run=False, on_saved=None, initial_key=""):
    """Ask for a Gemini API key and remember it in the per-user config.

    The key saved by the app is what Jarvis uses. Environment variables are
    only a fallback, so an old Windows key can never override a key saved here.
    """
    if jcfg is None:
        messagebox.showerror(
            "AUTHENTICATION ERROR",
            "jarvis_config.py not found.\n\nKeep it in the same folder as jarvis_app.py.",
            parent=root,
        )
        return False

    existing = jcfg.get_saved_api_key()
    prefill = (existing or initial_key or jcfg.get_api_key() or "").strip()
    result = {"ok": bool(existing) and jcfg.is_valid_key(existing)}

    win = tk.Toplevel(root)
    win.title("STARK SYSTEM AUTH // GEMINI API KEY")
    win.configure(bg=BG)
    win.resizable(False, False)
    try:
        win.transient(root)
        win.grab_set()
    except Exception:
        pass

    wrap = tk.Frame(win, bg=BG, padx=22, pady=18)
    wrap.pack(fill="both", expand=True)

    tk.Label(wrap, text="GEMINI API KEY", bg=BG, fg=CYAN_GLOW,
             font=("Consolas", 14, "bold")).pack(anchor="w")
    tk.Label(wrap, text="Jarvis apni Gemini API key aap ke PC par save karta hai.",
             bg=BG, fg=TEXT_MAIN, font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 10))

    steps = (
        "1.  Open Google AI Studio and sign in.\n"
        "2.  Click \"Create API key\" and copy the key.\n"
        "    New keys start with AQ. Older keys start with AIza.\n"
        "3.  Paste it below and press SAVE KEY."
    )
    tk.Label(wrap, text=steps, bg=PANEL, fg=TEXT_MAIN, justify="left",
             font=("Consolas", 9), padx=14, pady=12,
             highlightthickness=1, highlightbackground=PANEL_BORDER).pack(fill="x")

    tk.Button(wrap, text="OPEN GOOGLE AI STUDIO", command=_open_ai_studio,
              bg="#0c2b48", fg=CYAN_GLOW, activebackground="#133654",
              activeforeground="#ffffff", relief="flat", bd=0,
              padx=12, pady=7, font=("Consolas", 10, "bold"),
              cursor="hand2", highlightthickness=1,
              highlightbackground="#0284c7").pack(fill="x", pady=(12, 10))

    row = tk.Frame(wrap, bg=BG)
    row.pack(fill="x")
    entry = tk.Entry(row, show="*", bg="#040b14", fg=TEXT_MAIN,
                     insertbackground=CYAN_GLOW, relief="flat", bd=0,
                     font=("Consolas", 11), highlightthickness=1,
                     highlightbackground=PANEL_BORDER)
    entry.pack(side="left", fill="x", expand=True, ipady=7)
    if prefill:
        entry.insert(0, prefill)

    status = tk.StringVar()
    if existing:
        status.set("Saved key: " + jcfg.mask_key(existing))
    elif prefill:
        status.set("Found a Windows key: " + jcfg.mask_key(prefill)
                   + " - press SAVE KEY to keep it in the app.")
    else:
        status.set("No key saved yet.")
    tk.Label(wrap, textvariable=status, bg=BG, fg=TEXT_DIM,
             font=("Segoe UI", 9), anchor="w", justify="left",
             wraplength=520).pack(fill="x", pady=(7, 4))

    tk.Label(wrap, text="Saved at: " + jcfg.describe_location(),
             bg=BG, fg=TEXT_DIM, font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 10))

    buttons = tk.Frame(wrap, bg=BG)
    buttons.pack(fill="x")

    def do_save():
        key = entry.get().strip()
        if not jcfg.is_valid_key(key):
            status.set("Invalid key. Paste the whole key (AIza... or AQ...) with no spaces.")
            entry.focus_set()
            return
        try:
            jcfg.save_api_key(key)
        except Exception as exc:
            status.set("Could not save the key: " + str(exc))
            return
        result["ok"] = True
        status.set("Key saved. Jarvis will remember it.")
        if on_saved:
            try:
                on_saved(key)
            except Exception:
                pass
        win.after(650 if not first_run else 350, win.destroy)

    def do_reset():
        if not messagebox.askyesno(
            "RESET API KEY",
            "This completely removes the saved Gemini API key.\n\n"
            "The app config entry and the Windows GEMINI_API_KEY / "
            "GOOGLE_API_KEY variables are cleared. You can then paste a new "
            "key and press SAVE KEY.",
            parent=win,
        ):
            return
        try:
            jcfg.reset_api_key()
        except Exception:
            jcfg.clear_api_key()
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                os.environ.pop(name, None)
        entry.delete(0, "end")
        result["ok"] = False
        status.set("API key reset. Paste a new key (AIza... or AQ...) and press SAVE KEY.")
        entry.focus_set()

    def do_close():
        win.destroy()

    tk.Button(buttons, text="RESET KEY", command=do_reset,
              bg="#3b0f1a", fg="#fecdd3", activebackground="#881337",
              activeforeground="#ffffff", relief="flat", bd=0,
              padx=12, pady=7, font=("Consolas", 9, "bold"),
              cursor="hand2").pack(side="left")
    tk.Button(buttons, text="CLOSE" if not first_run else "EXIT",
              command=do_close, bg="#081422", fg=TEXT_DIM,
              activebackground="#0e243b", activeforeground=TEXT_MAIN,
              relief="flat", bd=0, padx=12, pady=7,
              font=("Consolas", 9, "bold"), cursor="hand2",
              highlightthickness=1, highlightbackground=PANEL_BORDER).pack(side="right")
    tk.Button(buttons, text="SAVE KEY", command=do_save,
              bg="#0284c7", fg="#030712", activebackground=CYAN_GLOW,
              activeforeground="#030712", relief="flat", bd=0,
              padx=16, pady=7, font=("Consolas", 10, "bold"),
              cursor="hand2").pack(side="right", padx=(0, 8))

    entry.bind("<Return>", lambda _e: do_save())
    win.bind("<Escape>", lambda _e: do_close())
    win.protocol("WM_DELETE_WINDOW", do_close)

    win.update_idletasks()
    width = max(560, win.winfo_reqwidth())
    height = win.winfo_reqheight()
    try:
        x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        pass

    try:
        win.wait_visibility()
        entry.focus_set()
    except Exception:
        pass
    try:
        win.wait_window()
    except Exception:
        pass
    return bool(result["ok"] and jcfg.get_api_key())


def ensure_api_key(root) -> bool:
    if jcfg is None:
        return False

    saved = jcfg.get_saved_api_key()
    if saved and jcfg.is_valid_key(saved):
        os.environ["GEMINI_API_KEY"] = saved
        return True

    # No usable key saved by the app yet: ask once, inside the app. If Windows
    # has an old GEMINI_API_KEY, it is used to prefill the box so the user only
    # has to press SAVE KEY. A broken saved key opens the same dialog prefilled
    # so it can be replaced (RESET KEY clears it completely).
    return api_key_dialog(
        root,
        first_run=not bool(saved),
        initial_key=saved or jcfg.get_api_key(),
    )


def main():
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr, is_err=True)
    root = tk.Tk()
    app = App(root)
    if not ensure_api_key(root):
        messagebox.showerror("AUTHENTICATION REJECTED", "GEMINI API key ke baghair Jarvis chalna mumkin nahi.")
        os._exit(1)
    threading.Thread(target=app.boot, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        try:
            messagebox.showerror("JARVIS CRITICAL FAULT", err[-1500:])
        except Exception:
            pass
        raise