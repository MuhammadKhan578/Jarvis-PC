"""The Iron-Man style HUD: a small, always-on-top arc reactor overlay.

Tkinter only.  Everything is optional: if the display is unavailable the HUD
quietly disables itself and the rest of Jarvis keeps working.
"""
from __future__ import annotations

import math
import threading
import time

from . import core

try:
    import tkinter as tk
except Exception:  # pragma: no cover
    tk = None

BG = "#010101"          # transparent colour key on Windows
CYAN = "#00e5ff"
GOLD = "#ffc107"
WHITE = "#eafcff"
MUTED = "#6f93a3"
RED = "#ff5252"

_COLORS = {
    "idle": (CYAN, "#0a2530", 1.0),
    "listening": (CYAN, "#0d3440", 1.6),
    "thinking": (GOLD, "#3a2c05", 1.9),
    "speaking": (WHITE, "#123a44", 2.3),
    "error": (RED, "#3a0808", 1.4),
}


class _HUD:
    def __init__(self):
        self.root = None
        self.canvas = None
        self.visible = True
        self.angle = 0.0
        self.pulse = 0.0
        self.state = "idle"
        self._drag = None
        self._last_state = None
        self._mission_text = ""
        self._mission_at = 0.0
        self._closing = False
        self._pending_visibility = None

    # -- window -----------------------------------------------------------
    def build(self):
        if tk is None:
            raise RuntimeError("tkinter is not available")
        root = tk.Tk()
        root.title("J.A.R.V.I.S. HUD")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-transparentcolor", BG)
        except Exception:
            pass
        root.configure(bg=BG)
        w, h = 380, 158
        sw = root.winfo_screenwidth()
        root.geometry(f"{w}x{h}+{max(0, sw - w - 28)}+36")
        canvas = tk.Canvas(root, width=w, height=h, bg=BG, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", self._drag_start)
        canvas.bind("<B1-Motion>", self._drag_move)
        canvas.bind("<Double-Button-1>", lambda e: self.toggle())
        canvas.bind("<Button-3>", lambda e: self.hide())
        self.root = root
        self.canvas = canvas
        root.after(60, self._tick)
        return root

    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event):
        if not self._drag:
            return
        x0, y0, wx, wy = self._drag
        self.root.geometry(f"+{wx + event.x_root - x0}+{wy + event.y_root - y0}")

    # -- state ------------------------------------------------------------
    def read_state(self) -> str:
        try:
            if core._event_set("stop_flag"):
                return "error"
            if core._event_set("main_busy"):
                return "thinking"
            if core._event_set("speaking"):
                return "speaking"
            if core._event_set("is_awake"):
                return "listening"
        except Exception:
            pass
        return "idle"

    def mission_line(self) -> str:
        now = time.time()
        if now - self._mission_at > 2.0:
            try:
                from . import agent
                self._mission_text = agent.active_mission_text()
            except Exception:
                self._mission_text = ""
            self._mission_at = now
        return self._mission_text

    # -- drawing ----------------------------------------------------------
    def _ring(self, cx, cy, r, color, width, start, extent):
        self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                               start=start, extent=extent, style="arc",
                               outline=color, width=width)

    def _tick(self):
        try:
            if self._closing:
                try:
                    self.root.destroy()
                except Exception:
                    pass
                return
            if self._pending_visibility is not None:
                want = self._pending_visibility
                self._pending_visibility = None
                if want:
                    self.root.deiconify()
                    self.root.attributes("-topmost", True)
                else:
                    self.root.withdraw()
                self.visible = want
            if not self.visible:
                self.root.after(200, self._tick)
                return
            self.angle = (self.angle + (3.4 if self.state != "idle" else 1.1)) % 360
            self.pulse += 0.13
            self.state = self.read_state()
            self._draw()
        except Exception as e:
            core.log(f"HUD draw error: {e}")
        try:
            self.root.after(60, self._tick)
        except Exception:
            pass

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w = int(c.winfo_width() or 380)
        h = int(c.winfo_height() or 158)
        cx, cy = 74, h // 2
        color, halo, speed = _COLORS.get(self.state, _COLORS["idle"])
        glow = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.pulse * speed))

        # outer rotating segments
        for i in range(6):
            a = self.angle * 1.0 + i * 60
            self._ring(cx, cy, 56, MUTED, 1, a, 26)
        for i in range(3):
            a = -self.angle * 1.6 + i * 120
            self._ring(cx, cy, 49, core._hex_mix(color, BG, 0.55), 2, a, 60)

        # reactor core
        r = 30 + 2.2 * math.sin(self.pulse * speed)
        for rr, cc in ((r + 9, core._hex_mix(color, BG, 0.35)),
                       (r + 4, core._hex_mix(color, BG, 0.6)),
                       (r, color)):
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          outline=cc, width=2 if rr < r else 1)
        c.create_oval(cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8,
                      fill=core._hex_mix(color, BG, 0.22), outline="")
        c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=color, outline="")
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=WHITE, outline="")

        # status text
        c.create_text(150, 38, anchor="w", text="J.A.R.V.I.S.",
                      fill=WHITE, font=("Segoe UI", 19, "bold"))
        c.create_text(152, 60, anchor="w", text="U L T I M A T E",
                      fill=MUTED, font=("Segoe UI", 7))
        state_text = {"idle": "STANDBY", "listening": "LISTENING",
                      "thinking": "PROCESSING", "speaking": "SPEAKING",
                      "error": "STOPPED"}.get(self.state, "STANDBY")
        c.create_text(152, 84, anchor="w", text="● " + state_text,
                      fill=color, font=("Consolas", 11, "bold"))
        c.create_text(152, 106, anchor="w",
                      text=time.strftime("%d %b %Y  ·  %I:%M:%S %p"),
                      fill=MUTED, font=("Consolas", 9))
        mission = self.mission_line()
        c.create_text(152, 128, anchor="w",
                      text=mission or "All systems nominal, sir.",
                      fill=GOLD if mission else core._hex_mix(CYAN, BG, 0.55),
                      font=("Consolas", 8))
        # thin baseline
        c.create_line(20, h - 8, w - 16, h - 8, fill=core._hex_mix(color, BG, 0.28))

    # -- public -----------------------------------------------------------
    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def show(self):
        self.visible = True
        self._pending_visibility = True

    def hide(self):
        self.visible = False
        self._pending_visibility = False

    def destroy(self):
        # Tk must be destroyed from its own thread; _tick does it safely.
        self._closing = True


_HUD_OBJ: _HUD | None = None
_HUD_LOCK = threading.Lock()
_HUD_STARTING = False


def _runner():
    global _HUD_OBJ, _HUD_STARTING
    try:
        hud = _HUD()
        _HUD_OBJ = hud
        root = hud.build()
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+alt+h", lambda: hud.toggle())
        except Exception:
            pass
        root.mainloop()
    except Exception as e:
        core.log(f"HUD unavailable: {e}")
        _HUD_OBJ = None
    finally:
        _HUD_STARTING = False
        _HUD_OBJ = None


def start_hud():
    """Launch the HUD in a daemon thread (idempotent)."""
    global _HUD_OBJ, _HUD_STARTING
    if not core.config_get("hud", True):
        return "HUD is disabled in config."
    if _HUD_OBJ is not None:
        return "HUD is already running."
    with _HUD_LOCK:
        if _HUD_OBJ is not None:
            return "HUD is already running."
        if _HUD_STARTING:
            return "HUD is starting."
        _HUD_STARTING = True
        threading.Thread(target=_runner, daemon=True, name="jarvis-hud").start()
    for _ in range(10):
        time.sleep(0.1)
        if _HUD_OBJ is not None:
            break
    return "HUD online. Ctrl+Alt+H toggles it." if _HUD_OBJ is not None else "HUD is starting."


def toggle_hud() -> str:
    if _HUD_OBJ is None:
        return start_hud()
    _HUD_OBJ.toggle()
    return "HUD shown." if _HUD_OBJ.visible else "HUD hidden."


def hud_operation(action: str = "toggle") -> str:
    """Control the on-screen arc-reactor HUD.

    action: show, hide, toggle, status
    """
    a = (action or "toggle").lower().strip()
    if a in ("on", "start", "show", "open"):
        if _HUD_OBJ is None:
            return start_hud()
        _HUD_OBJ.show()
        return "HUD shown."
    if a in ("off", "stop", "hide", "close"):
        if _HUD_OBJ is None:
            return "The HUD is not running."
        _HUD_OBJ.hide()
        return "HUD hidden."
    if a in ("toggle", "switch"):
        return toggle_hud()
    if a in ("status", "info"):
        return "HUD is running." if _HUD_OBJ is not None else "HUD is not running."
    return f"Unknown HUD action '{action}'."
