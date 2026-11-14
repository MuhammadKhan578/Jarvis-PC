"""The new Jarvis tools, in the exact shape Gemini's function calling expects.

Every function here has fully typed parameters and a useful docstring.  They are
appended to the original ``TOOLS`` list by ``jarvis_core.install``.
"""
from __future__ import annotations

import os
import time

from . import calendar_tools, core, dictation, mcp, news, persona, smarthome, workspace
from .agent import mission_operation, schedule_operation, skill_operation
from .brain import brain_operation
from .browser import browser_operation
from .computer import file_operation, network_operation, system_operation, ui_operation
from .diagnostics import diagnostics_operation
from .documents import document_operation
from .hud import hud_operation
from .integrations import email_operation, integration_operation
from .memory import archive_stats, memory_operation
from .research import research_operation


def config_operation(key: str = "", value: str = "", confirmed: bool = False) -> str:
    """Read or change Jarvis settings.

    key (leave empty to show everything):
      safe_mode     - true/false: ask before destructive actions (default true)
      hud           - true/false: the arc-reactor overlay
      auto_learn    - true/false: learn durable facts from conversations
      research_depth- quick, standard or deep
      safe_mode off turns off confirmation prompts; only do this when the user explicitly asks
    """
    cfg = core.load_config()
    k = (key or "").strip().lower()
    if not k:
        shown = {x: cfg.get(x) for x in ("safe_mode", "hud", "auto_learn", "research_depth")}
        return "Current settings:\n" + "\n".join(f"- {x}: {v}" for x, v in shown.items())
    if k not in ("safe_mode", "hud", "auto_learn", "research_depth", "auto_repair"):
        return f"Unknown setting '{key}'."
    if value == "":
        return f"{k} = {cfg.get(k)}"
    if k == "research_depth":
        v = value.strip().lower()
        if v not in ("quick", "standard", "deep"):
            return "research_depth must be quick, standard or deep."
        core.save_config({k: v})
        return f"{k} = {v}"
    v = value.strip().lower() in ("1", "true", "yes", "on", "enable", "enabled", "chalu")
    if k == "safe_mode" and not v:
        msg = core.guard("config_operation:safe_mode", confirmed,
                         "Turn OFF the safety confirmations for destructive actions.")
        if msg:
            return msg
    core.set_safe_mode(v) if k == "safe_mode" else core.save_config({k: v})
    return f"{k} = {v}"


def _calendar_line() -> str:
    try:
        events = calendar_tools._range_events(calendar_tools._load(), "week")
        if not events:
            return "calendar clear for 7 days"
        nxt = calendar_tools._fmt(events[0])
        return f"calendar: {len(events)} event(s) this week, next {nxt}"
    except Exception:
        return "calendar unavailable"


def _workspace_line() -> str:
    try:
        from . import workspace as ws_mod
        connected = [name for name in ws_mod._SERVICES if ws_mod._cfg(name).get("token")]
        return (", ".join(connected) if connected else "none connected")
    except Exception:
        return "unavailable"


def _mcp_line() -> str:
    try:
        return str(len(mcp._servers())) + " configured (" + mcp.SERVER_NAME + " server ready)"
    except Exception:
        return "unknown"


def ultimate_status() -> str:
    """Show a full status line for the upgraded Jarvis: memory, missions, schedule, safety, HUD."""
    from . import agent as agent_mod
    from . import hud as hud_mod
    cfg = core.load_config()
    try:
        from .memory import _load_raw
        mem = _load_raw()
        facts = len(mem.get("facts", {}))
        eps = len(mem.get("episodes", []))
        pins = len(mem.get("pins", []))
        try:
            arch = archive_stats().splitlines()[0]
        except Exception:
            arch = "archive unavailable"
    except Exception:
        facts, eps, pins, arch = 0, 0, 0, "archive unavailable"
    try:
        missions = agent_mod._load_missions()
        running = sum(1 for m in missions.values() if m.get("status") in ("running", "planning"))
        done = sum(1 for m in missions.values() if m.get("status") == "done")
    except Exception:
        running = done = 0
    try:
        jobs = sum(1 for j in agent_mod._load_schedule().values() if j.get("enabled", True))
    except Exception:
        jobs = 0
    try:
        from . import browser as browser_mod
        browser_state = "automation browser running" if browser_mod._running() else "browser idle"
    except Exception:
        browser_state = "browser unknown"
    return (
        "J.A.R.V.I.S. ULTIMATE status:\n"
        f"- Model: {core.G.get('active_model') or '?'}\n"
        f"- Language: {core.G.get('LANG_MODE') or '?'}  |  Voice: {core.G.get('VOICE_GENDER') or '?'}\n"
        f"- Safety mode: {'ON (destructive actions need confirmation)' if core.safe_mode() else 'OFF'}\n"
        f"- HUD: {'running' if hud_mod._HUD_OBJ else 'stopped'}  |  {browser_state}\n"
        f"- Memory: {facts} facts, {pins} pinned, {eps} episodes\n"
        f"- {arch}\n"
        f"- Missions: {running} running, {done} completed  |  Scheduled jobs: {jobs}\n"
        f"- Dictation: {dictation.status()}\n"
        f"- Persona: {persona.style_line()}  |  {_calendar_line()}\n"
        f"- Work tools: {_workspace_line()}  |  MCP servers: {_mcp_line()}\n"
        f"- Brain: Ultimate Reasoning Core online (deep/max multi-pass)\n"
        f"- Capabilities: research, missions, files, documents, browser, UI automation, "
        "system/network control, email, calendar, dictation, work apps (GitHub/Slack/Notion/"
        "Linear/Jira), MCP server+client, personality and writing-voice learning, "
        "translation, skills, diagnostics, scheduler, deep reasoning.\n"
        f"- Data folder: {core.DATA_DIR}\n"
        f"- Audit log: {core.AUDIT_FILE}"
    )


def audit_operation(action: str = "tail", limit: int = 30, search: str = "") -> str:
    """Inspect what Jarvis has done lately (privacy/transparency).

    action: tail (latest entries), search (find a tool/word), clear (delete the audit log)
    """
    a = (action or "tail").lower().strip()
    if a in ("clear", "wipe"):
        try:
            open(core.AUDIT_FILE, "w", encoding="utf-8").close()
            return "Audit log cleared."
        except Exception as e:
            return f"Could not clear the audit log: {e}"
    if a in ("search", "find"):
        try:
            hits = []
            with open(core.AUDIT_FILE, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if search.lower() in line.lower():
                        hits.append(line.strip())
            return "\n".join(hits[-max(1, int(limit)):]) if hits else f"Nothing matching '{search}'."
        except Exception as e:
            return f"Could not search the audit log: {e}"
    return core.audit_tail(limit)


def memory_report() -> str:
    """Open a readable report of everything Jarvis remembers about the user."""
    return memory_operation("export")


TOOL_FUNCTIONS = [
    research_operation,
    memory_operation,
    brain_operation,
    file_operation,
    system_operation,
    network_operation,
    ui_operation,
    browser_operation,
    document_operation,
    mission_operation,
    schedule_operation,
    skill_operation,
    diagnostics_operation,
    integration_operation,
    email_operation,
    calendar_tools.calendar_operation,
    dictation.dictation_operation,
    workspace.workspace_operation,
    mcp.mcp_operation,
    persona.persona_operation,
    hud_operation,
    config_operation,
    ultimate_status,
    audit_operation,
    smarthome.smart_home,
    smarthome.smart_scene,
    smarthome.smart_home_setup,
    smarthome.smart_home_help,
    news.news_brief,
]
