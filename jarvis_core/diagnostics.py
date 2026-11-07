"""Self-diagnostics: Jarvis checks its own body and the PC, then repairs what it can."""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

from . import core

REQUIRED = [
    ("google.genai", "google-genai"),
    ("pyautogui", "pyautogui"),
    ("keyboard", "keyboard"),
    ("speech_recognition", "SpeechRecognition"),
    ("edge_tts", "edge-tts"),
    ("pygame", "pygame"),
    ("psutil", "psutil"),
    ("pyaudio", "PyAudio"),
    ("PIL", "Pillow"),
]
OPTIONAL = [
    ("pywinauto", "pywinauto"),
    ("docx", "python-docx"),
    ("openpyxl", "openpyxl"),
    ("pptx", "python-pptx"),
    ("pypdf", "pypdf"),
    ("reportlab", "reportlab"),
    ("pycaw", "pycaw"),
    ("screen_brightness_control", "screen-brightness-control"),
    ("websocket", "websocket-client"),
    ("requests", "requests"),
    ("bs4", "beautifulsoup4"),
    ("pyperclip", "pyperclip"),
]


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _internet() -> tuple[bool, str]:
    for host, port in (("8.8.8.8", 53), ("1.1.1.1", 53), ("www.google.com", 443)):
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.close()
            return True, f"reachable via {host}:{port}"
        except Exception:
            continue
    return False, "no outbound connection"


def _audio() -> dict:
    out = {"microphones": [], "speakers": [], "ok": False}
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        for d in devs:
            try:
                name = str(d.get("name", "?"))
                if int(d.get("max_input_channels") or 0) > 0 and name not in out["microphones"]:
                    out["microphones"].append(name)
                if int(d.get("max_output_channels") or 0) > 0 and name not in out["speakers"]:
                    out["speakers"].append(name)
            except Exception:
                continue
        out["ok"] = bool(out["microphones"])
    except Exception:
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if int(info.get("maxInputChannels") or 0) > 0:
                    out["microphones"].append(info.get("name", "?"))
                if int(info.get("maxOutputChannels") or 0) > 0:
                    out["speakers"].append(info.get("name", "?"))
            p.terminate()
            out["ok"] = bool(out["microphones"])
        except Exception:
            pass
    return out


def _gemini() -> tuple[bool, str]:
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return False, "no GEMINI_API_KEY in the environment"
    client = core.G.get("client_fast") or core.G.get("client")
    model = core.G.get("active_model") or core.G.get("MODEL_NAME")
    if client is None:
        return False, "the Gemini client is not initialised"
    try:
        resp = client.models.generate_content(model=model, contents="Reply with the single word: OK")
        text = (getattr(resp, "text", "") or "").strip()
        return (True, f"{model} answered '{core.truncate(text, 40)}'") if text else (False, "empty answer")
    except Exception as e:
        return False, f"{model} failed: {core.truncate(str(e), 160)}"


def _browser() -> str:
    from . import browser as browser_mod
    try:
        if browser_mod._running():
            return "automation browser running"
        exe = browser_mod._find_exe("chrome") or browser_mod._find_exe("edge") or browser_mod._find_exe("brave")
        return f"available ({os.path.basename(exe)})" if exe else "Chrome/Edge/Brave not found"
    except Exception as e:
        return f"could not check: {e}"


def _disk() -> str:
    try:
        import psutil
        rows = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                rows.append(f"{part.device} {core.human_bytes(u.free)} free ({u.percent}% used)")
            except Exception:
                continue
        return "; ".join(rows) or "no drives"
    except Exception:
        return "psutil unavailable"


def run_checks(full: bool = True) -> dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    add("Python", sys.version_info >= (3, 9), platform.python_version())
    add("Windows", os.name == "nt", platform.platform())
    missing_req = [pkg for mod, pkg in REQUIRED if not _has(mod)]
    add("Core packages", not missing_req, "all present" if not missing_req else "missing: " + ", ".join(missing_req))
    missing_opt = [pkg for mod, pkg in OPTIONAL if not _has(mod)]
    add("Optional packages", True, "all present" if not missing_opt else "missing: " + ", ".join(missing_opt))

    net_ok, net_detail = _internet()
    add("Internet", net_ok, net_detail)
    if full:
        try:
            g_ok, g_detail = _gemini()
        except Exception as e:
            g_ok, g_detail = False, str(e)
        add("Gemini", g_ok, g_detail)
    else:
        add("Gemini key", bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
            "set" if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") else "missing")

    audio = _audio()
    add("Microphone", audio["ok"], f"{len(audio['microphones'])} input device(s)")
    add("Speakers", bool(audio["speakers"]), f"{len(audio['speakers'])} output device(s)")
    add("Browser automation", "not found" not in _browser(), _browser())
    add("Disk", True, _disk())
    try:
        import psutil
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.2)
        add("Memory", vm.percent < 92, f"{vm.percent}% used ({core.human_bytes(vm.available)} free)")
        add("CPU", cpu < 95, f"{cpu}% now")
        bt = psutil.boot_time()
        add("Uptime", True, f"{int((time.time() - bt) // 3600)} hours")
        b = psutil.sensors_battery()
        if b:
            add("Battery", b.percent > 10 or b.power_plugged,
                f"{int(b.percent)}% {'charging' if b.power_plugged else 'on battery'}")
    except Exception as e:
        add("System metrics", False, str(e))
    try:
        from . import memory as memory_mod
        facts = core.read_json(memory_mod.MEMORY_FILE, {}) or {}
        n = len(facts.get("facts", {})) if isinstance(facts, dict) else 0
        add("Memory 2.0", True, f"{n} facts stored")
    except Exception as e:
        add("Memory 2.0", False, str(e))
    try:
        from . import agent as agent_mod
        jobs = agent_mod._load_schedule()
        missions = agent_mod._load_missions()
        add("Scheduler", True, f"{len(jobs)} jobs; {len(missions)} missions")
    except Exception as e:
        add("Scheduler", False, str(e))
    return {
        "checks": checks,
        "ok": all(c["ok"] for c in checks if c["name"] not in ("Optional packages", "Battery", "Browser automation")),
        "time": time.time(),
    }


def _report_markdown(result: dict) -> str:
    lines = ["# J.A.R.V.I.S. Diagnostic Report", "",
             f"**Overall:** {'all critical systems nominal' if result['ok'] else 'attention needed'}",
             f"**Time:** {core.now_str()}", "",
             "| System | Status | Details |", "|---|---|---|"]
    for c in result["checks"]:
        mark = "OK" if c["ok"] else "FAIL"
        lines.append(f"| {c['name']} | {mark} | {c['detail'].replace('|', '/')} |")
    failures = [c for c in result["checks"] if not c["ok"]]
    if failures:
        lines += ["", "## Recommended fixes"]
        for c in failures:
            name = c["name"]
            if name == "Core packages":
                lines.append(f"- Install missing packages: `pip install {c['detail'].replace('missing: ', '')}`")
            elif name == "Gemini":
                lines.append("- Check the API key and internet connection, then restart Jarvis.")
            elif name == "Microphone":
                lines.append("- Run `mic list` and `mic test`, or set the default input device in Windows.")
            elif name == "Internet":
                lines.append("- Check Wi-Fi/Ethernet; try `network_operation(action='ping')`.")
            else:
                lines.append(f"- Investigate {name}: {c['detail']}")
    else:
        lines += ["", "No action required, sir. Everything I can test is working."]
    return "\n".join(lines)


def diagnostics_operation(action: str = "full") -> str:
    """Check Jarvis and the PC for problems.

    action:
      full / quick  - run all checks and open a report
      packages      - only check installed libraries
      internet      - only check connectivity
      audio         - only check microphone and speakers
      speak         - run checks and read the result aloud
      fix           - install missing core packages and flush DNS
    """
    a = (action or "full").lower().strip()
    if a in ("packages", "libs", "deps"):
        missing = [pkg for mod, pkg in REQUIRED if not _has(mod)]
        missing_opt = [pkg for mod, pkg in OPTIONAL if not _has(mod)]
        out = []
        out.append("Core: " + ("all present" if not missing else "MISSING " + ", ".join(missing)))
        out.append("Optional: " + ("all present" if not missing_opt else "missing " + ", ".join(missing_opt)))
        return "\n".join(out)
    if a == "internet":
        ok, detail = _internet()
        return ("Internet is working — " if ok else "No internet — ") + detail
    if a in ("audio", "mic", "sound"):
        data = _audio()
        return (f"Microphones ({len(data['microphones'])}): " + ", ".join(data["microphones"][:8]) +
                f"\nSpeakers ({len(data['speakers'])}): " + ", ".join(data["speakers"][:8]))
    if a in ("fix", "repair"):
        return self_repair()
    result = run_checks(full=(a not in ("quick", "fast")))
    md = _report_markdown(result)
    md_path, html_path = core.save_report("Diagnostics", md, open_it=True)
    failed = [c["name"] for c in result["checks"] if not c["ok"]]
    spoken = ("All critical systems are nominal, sir." if not failed
              else "I found issues with: " + ", ".join(failed[:4]) + ". The report is open.")
    if a in ("speak", "voice", "read"):
        core.say_async(spoken)
    return spoken + f"\nReport: {html_path or md_path}\n\n" + md


def self_repair() -> str:
    """Try to fix common problems: missing packages, DNS cache, temp files."""
    actions = []
    missing = [pkg for mod, pkg in REQUIRED + OPTIONAL if not _has(mod)]
    if missing:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                            "--disable-pip-version-check"] + missing,
                           capture_output=True, text=True, timeout=300)
            still = [pkg for mod, pkg in REQUIRED + OPTIONAL if not _has(mod)]
            actions.append("installed packages: " + (", ".join(missing) if not still else
                                                     "partial, still missing: " + ", ".join(still)))
        except Exception as e:
            actions.append(f"package install failed: {e}")
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, timeout=20)
        actions.append("DNS cache flushed")
    except Exception:
        pass
    try:
        fn = core.G.get("_clean_temp")
        if fn:
            count, freed = fn()
            actions.append(f"removed {count} temp files ({core.human_bytes(freed)})")
    except Exception:
        pass
    return "Repairs attempted:\n- " + "\n- ".join(actions) if actions else "Nothing needed repair."
