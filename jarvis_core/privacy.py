"""Privacy centre and Windows permission guidance for Jarvis.

Windows desktop applications do not have macOS-style accessibility/calendar
permission prompts.  Microphone access is controlled by Windows; screen capture,
local calendar files and UI Automation do not expose a per-app consent dialog.
This module reports that honestly, opens the relevant Windows settings page and
lets the user disable local learning or the verbatim archive.
"""
from __future__ import annotations

import os
import platform

from . import core


def _on(value: str) -> bool:
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "on", "enable", "enabled", "chalu",
    }


def _module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def privacy_status() -> str:
    cfg = core.load_config()
    return (
        "Jarvis privacy status:\n"
        f"- Platform: {platform.system()} {platform.release()}\n"
        f"- Microphone stack: {'available' if _module('speech_recognition') else 'missing SpeechRecognition'}\n"
        f"- Local memory context: {'ON' if cfg.get('memory_enabled', True) else 'OFF'}\n"
        f"- Automatic learning: {'ON' if cfg.get('auto_learn', True) else 'OFF'}\n"
        f"- Verbatim local archive: {'ON' if cfg.get('archive_enabled', True) else 'OFF'}\n"
        f"- Safety confirmations: {'ON' if core.safe_mode() else 'OFF'}\n"
        "- Screen/UI access: used only when you invoke a screen or automation action; "
        "Windows has no separate desktop screen-recording permission prompt.\n"
        "- Calendar: local JSON/ICS files only; no cloud calendar permission is requested.\n"
        "- Network services: Gemini/STT, research pages, and only the work/MCP/email services "
        "you configure. No analytics or telemetry.\n"
        f"- Local data folder: {core.DATA_DIR}\n"
        f"- Audit log: {core.AUDIT_FILE}"
    )


def _open_windows_page(page: str) -> str:
    uri = {
        "microphone": "ms-settings:privacy-microphone",
        "speech": "ms-settings:privacy-speech",
        "notifications": "ms-settings:notifications",
        "startup": "ms-settings:startupapps",
    }.get(page, "ms-settings:privacy")
    try:
        os.startfile(uri)
        return f"Opened Windows settings: {uri}"
    except Exception as e:
        return f"Could not open Windows settings: {e}"


def privacy_operation(action: str = "status", setting: str = "", value: str = "",
                      confirmed: bool = False) -> str:
    """Inspect and control Jarvis privacy settings.

    action:
      status          - explain local data, network use and permission reality
      open_settings   - open Windows privacy settings (setting=microphone/speech)
      set             - memory_enabled/archive_enabled/auto_learn on or off
      clear_history   - erase the verbatim archive and conversation tail (confirmation required)
      data_locations  - list every main runtime data location
    """
    a = (action or "status").strip().lower()
    key = (setting or "").strip().lower()
    if a in ("status", "show", "privacy"):
        return privacy_status()
    if a in ("open_settings", "permissions", "permission"):
        return _open_windows_page(key or "microphone")
    if a in ("data_locations", "locations", "files"):
        from . import calendar_tools, memory
        return (
            "Jarvis local data locations:\n"
            f"- Config and connected-service credentials: {core.CONFIG_FILE}\n"
            f"- Structured memory: {memory.MEMORY_FILE}\n"
            f"- Verbatim archive: {memory.ARCHIVE_FILE}\n"
            f"- Local calendar: {calendar_tools.CAL_FILE}\n"
            f"- Reports: {core.REPORTS_DIR}\n"
            f"- Documents: {core.DOCS_DIR}\n"
            f"- Browser profile (logins/cookies): {core.BROWSER_PROFILE_DIR}"
        )
    if a in ("set", "configure"):
        allowed = {"memory_enabled", "archive_enabled", "auto_learn"}
        if key not in allowed:
            return "Privacy settings: memory_enabled, archive_enabled, auto_learn."
        enabled = _on(value)
        core.save_config({key: enabled})
        core.audit("privacy_operation", f"{key}={enabled}", "saved")
        note = " Existing local data is unchanged." if not enabled else ""
        return f"{key} = {enabled}.{note}"
    if a in ("clear_history", "clear_archive", "delete_history"):
        msg = core.guard(
            "privacy_operation:clear_history", confirmed,
            "Permanently erase the verbatim conversation archive and conversation tail."
        )
        if msg:
            return msg
        from . import memory
        removed = []
        for path in (memory.ARCHIVE_FILE, core.CONVERSATION_FILE):
            try:
                open(path, "w", encoding="utf-8").close()
                removed.append(path)
            except Exception as e:
                return f"Could not clear {path}: {e}"
        memory._ARCHIVE_CACHE.update({"size": -1, "mtime": 0.0, "records": []})
        memory._LAST_ARCHIVE.update({"t": 0.0, "role": "", "text": ""})
        core.audit("privacy_operation", "clear_history", "cleared", risk="high")
        return "Cleared local conversation history:\n" + "\n".join("- " + p for p in removed)
    return "Privacy actions: status, open_settings, set, data_locations, clear_history."
