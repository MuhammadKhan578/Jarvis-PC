"""Mission engine, persistent scheduler and the skills loader.

The mission engine turns a big goal ("build me a portfolio website and a report
on the market") into a plan, then executes it step by step with the full Jarvis
tool set.  Progress survives restarts.  The scheduler lets Jarvis run commands
later or on a repeating basis.  Skills are small user-authored extensions.
"""
from __future__ import annotations

import contextvars
import importlib.util
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta

from . import core

MISSIONS_FILE = os.path.join(core.DATA_DIR, "missions.json")
SCHEDULE_FILE = os.path.join(core.DATA_DIR, "schedule.json")

_MISSIONS_LOCK = threading.RLock()
_SCHEDULE_LOCK = threading.RLock()
_ACTIVE_MISSIONS: dict[str, threading.Thread] = {}
_CURRENT_MISSION = contextvars.ContextVar("current_mission", default="")
_RUNNING = threading.Event()
_STOP = threading.Event()


# --------------------------------------------------------------------------
# Mission persistence
# --------------------------------------------------------------------------
def _load_missions() -> dict:
    data = core.read_json(MISSIONS_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_missions(data: dict):
    core.write_json(MISSIONS_FILE, data)


def _new_mission(goal: str) -> dict:
    mid = "M" + time.strftime("%y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    return {
        "id": mid,
        "goal": (goal or "").strip(),
        "status": "planning",
        "created": time.time(),
        "updated": time.time(),
        "plan": [],
        "results": [],
        "report": "",
        "error": "",
    }


def _mission_summary(m: dict) -> str:
    steps = m.get("plan") or []
    done = sum(1 for s in steps if s.get("status") == "done")
    return (f"{m.get('id')}  [{m.get('status','?')}]  {done}/{len(steps)} steps — "
            f"{core.truncate(m.get('goal',''), 120)}")


# --------------------------------------------------------------------------
# Planning and step execution
# --------------------------------------------------------------------------
_MISSION_SYSTEM = (
    "You are J.A.R.V.I.S. running a multi-step mission for your user. You have the full "
    "tool set: files, documents, research, browser automation, UI automation, system control, "
    "memory, scheduling and skills. Work autonomously. Never tell the user to do a step "
    "themselves when a tool can do it. Prefer a few well-chosen tool calls over many tiny ones. "
    "Address the user as 'sir'. If a step fails, try a different approach before reporting failure. "
    "The user speaks Roman Urdu / Urdu / English; final reports are written in clear English "
    "unless the goal asks otherwise."
)


def plan_mission(goal: str, max_steps: int = 8) -> list[dict]:
    """Ask Gemini for an ordered plan. Falls back to a single-step plan."""
    prompt = (
        f"MISSION GOAL: {goal}\n\n"
        f"Break this into at most {max_steps} concrete execution steps. Each step must be "
        "something an autonomous Windows assistant can actually do with tools (research, "
        "browse, create files/documents, run commands, inspect the screen, send messages). "
        "Each step needs: title (short), detail (exactly what to do and what 'done' looks like), "
        "and tools (likely tool names). Do not include steps like 'ask the user'.\n\n"
        'Return ONLY JSON: {"title":"short mission title","steps":['
        '{"title":"...","detail":"...","tools":["..."]}]}'
    )
    data = core.llm_json(prompt, system="You are a meticulous mission planner. Return JSON only.",
                         smart=True, fallback=None)
    if not isinstance(data, dict) or not data.get("steps"):
        # Premium models are often overloaded.  The fast model still plans well.
        data = core.llm_json(prompt, system="You are a meticulous mission planner. Return JSON only.",
                             smart=False, fallback=None)
    steps = []
    title = goal[:80]
    if isinstance(data, dict):
        title = str(data.get("title") or title)[:120]
        raw_steps = data.get("steps") or []
        for i, s in enumerate(raw_steps[:max_steps], 1):
            if isinstance(s, dict):
                steps.append({
                    "n": i,
                    "title": core.truncate(s.get("title", f"Step {i}"), 120),
                    "detail": core.truncate(s.get("detail", ""), 900),
                    "tools": [str(t) for t in (s.get("tools") or [])][:8],
                    "status": "pending",
                    "result": "",
                })
            elif isinstance(s, str) and s.strip():
                steps.append({"n": i, "title": core.truncate(s, 120), "detail": s.strip(),
                              "tools": [], "status": "pending", "result": ""})
    if not steps:
        steps = [{"n": 1, "title": "Complete the mission", "detail": goal,
                  "tools": [], "status": "pending", "result": ""}]
    return steps


def _mission_tools():
    base = list(core.G.get("_clean_tools", lambda: core.G.get("TOOLS") or [])())
    internal = [mission_update, mission_complete]
    try:
        import typing
        for fn in internal:
            fn.__annotations__ = typing.get_type_hints(fn)
    except Exception:
        pass
    return base + internal


def _mission_chat(mission: dict):
    t = core.gen_types()
    if t is None:
        raise RuntimeError("google-genai types are not available")
    client = core.G.get("client_fast") or core.G.get("client_smart")
    if client is None:
        raise RuntimeError("Gemini client is not ready")
    model = core.G.get("MODEL_NAME") or ""
    dead = core.G.get("dead_models") or set()
    if not model or model in dead:
        for m in (core.G.get("MODEL_CANDIDATES") or []):
            if m and m not in dead:
                model = m
                break
    model = model or "gemini-3.5-flash-lite"
    kwargs = dict(
        system_instruction=_MISSION_SYSTEM,
        tools=_mission_tools(),
        max_output_tokens=2048,
        automatic_function_calling=t.AutomaticFunctionCallingConfig(maximum_remote_calls=60),
    )
    if "gemini-3" not in model and "latest" not in model:
        kwargs["temperature"] = 0.3
    return client.chats.create(model=model, config=t.GenerateContentConfig(**kwargs))


def mission_update(progress: str, note: str = "") -> str:
    """Record progress on the current mission step.

    Call this after finishing meaningful work inside a step, so progress is not lost.

    Args:
        progress: One short sentence describing what was just completed.
        note: Optional detail, file path, or result worth keeping.
    """
    mid = _CURRENT_MISSION.get()
    if not mid:
        return "No active mission."
    with _MISSIONS_LOCK:
        data = _load_missions()
        m = data.get(mid)
        if not m:
            return "Mission not found."
        m.setdefault("progress", []).append({"t": time.time(), "text": core.truncate(progress, 400),
                                             "note": core.truncate(note, 800)})
        m["progress"] = m["progress"][-80:]
        m["updated"] = time.time()
        _save_missions(data)
    return "Progress recorded."


def mission_complete(summary: str) -> str:
    """Mark the whole mission as finished.

    Call this exactly once, at the very end, after every step is done.

    Args:
        summary: What was delivered, including any file paths.
    """
    mid = _CURRENT_MISSION.get()
    if not mid:
        return "No active mission."
    with _MISSIONS_LOCK:
        data = _load_missions()
        m = data.get(mid)
        if not m:
            return "Mission not found."
        m["final_summary"] = core.truncate(summary, 2000)
        m["updated"] = time.time()
        _save_missions(data)
    _MISSION_RESULT[mid] = core.truncate(summary, 2000)
    return "Mission completion recorded."


_MISSION_RESULT: dict[str, str] = {}


def _retryable_step_error(e: Exception) -> bool:
    text = f"{type(e).__name__}: {e}".lower()
    return any(k in text for k in (
        "429", "500", "502", "503", "504", "deadline", "timeout", "timed out",
        "unavailable", "resource_exhausted", "internal", "connection"))


def _run_mission(mid: str):
    _RUNNING.set()
    try:
        with _MISSIONS_LOCK:
            data = _load_missions()
            m = data.get(mid)
            if not m:
                return
            if not m.get("plan"):
                m["status"] = "planning"
                m["plan"] = plan_mission(m["goal"])
            m["status"] = "running"
            m["updated"] = time.time()
            _save_missions(data)

        core.say_async(f"Mission accepted, sir. I am starting work on "
                       f"{core.truncate(m['goal'], 90)}.")
        _CURRENT_MISSION.set(mid)

        chat = _mission_chat(m)
        for step in m["plan"]:
            if _STOP.is_set():
                break
            with _MISSIONS_LOCK:
                live = _load_missions().get(mid) or {}
                status_now = live.get("status")
                if live.get("final_summary"):
                    break  # mission_complete already fired; do not run extra steps
            if status_now == "cancelled":
                break
            with _MISSIONS_LOCK:
                data = _load_missions()
                m = data.get(mid) or m
                live_step = next((s for s in m.get("plan", []) if s.get("n") == step.get("n")), step)
                if live_step.get("status") == "done":
                    continue
                live_step["status"] = "running"
                m["status"] = "running"
                m["updated"] = time.time()
                _save_missions(data)

            done_lines = "\n".join(
                f"- {s['title']}: {core.truncate(s.get('result',''), 240)}"
                for s in m["plan"] if s.get("status") == "done")
            prompt = (
                f"MISSION: {m['goal']}\n\n"
                f"PLAN:\n" + "\n".join(
                    f"{s['n']}. [{s.get('status','pending')}] {s['title']} — {s['detail']}"
                    for s in m["plan"]) + "\n\n"
                f"COMPLETED SO FAR:\n{done_lines or '(none yet)'}\n\n"
                f"NOW EXECUTE STEP {step['n']}: {step['title']}\n"
                f"{step['detail']}\n\n"
                "Use tools to actually do it. When the step is genuinely finished, reply with "
                "a short factual result (files created, findings, numbers). Do not start later steps. "
                "If the whole mission is now complete, call mission_complete with the final summary."
            )
            text = ""
            send_prompt = prompt
            for attempt in (1, 2):
                try:
                    resp = chat.send_message(send_prompt)
                    text = getattr(resp, "text", None) or ""
                    break
                except Exception as e:
                    core.log(f"mission step {step['n']} attempt {attempt} failed: {e}")
                    text = f"Step failed: {e}"
                    if attempt == 1 and _retryable_step_error(e) and not _STOP.is_set():
                        time.sleep(3)
                        # A timeout can happen after a tool already ran.  Never repeat
                        # side effects blindly: check the current state first.
                        send_prompt = (
                            "RETRY AFTER A CONNECTION FAILURE. The previous attempt at this step "
                            "may already have executed some tools. Do NOT repeat any action with "
                            "side effects. First inspect the current state (files, apps, pages, "
                            "results), then finish only the missing work. If the step is already "
                            "complete, just report the factual result.\n\n" + prompt
                        )
                        continue
                    break

            with _MISSIONS_LOCK:
                data = _load_missions()
                m = data.get(mid) or m
                for s in m.get("plan", []):
                    if s.get("n") == step.get("n"):
                        s["status"] = "done" if not text.startswith("Step failed:") else "failed"
                        s["result"] = core.truncate(text, 2000)
                m["updated"] = time.time()
                _save_missions(data)
            core.log(f"Mission {mid} step {step['n']} done: {core.truncate(text, 200)}")

        with _MISSIONS_LOCK:
            data = _load_missions()
            m = data.get(mid) or m
            results = "\n\n".join(f"### {s['n']}. {s['title']}\n{s.get('result','')}"
                                  for s in m.get("plan", []))
            final = m.get("final_summary") or _MISSION_RESULT.get(mid) or ""
            if m.get("status") not in ("cancelled", "failed"):
                finished = bool(m.get("final_summary")) or all(
                    s.get("status") == "done" for s in m.get("plan", []))
                m["status"] = "done" if finished else "partial"
            m["updated"] = time.time()
            _save_missions(data)

        report_md = (
            f"# Mission Report: {m['goal']}\n\n"
            f"**Status:** {m['status']}  \n**Mission ID:** {mid}\n\n"
            f"## Plan and Results\n\n{results}\n\n"
            + (f"## Final Summary\n\n{final}\n" if final else "")
        )
        md_path, html_path = core.save_report("Mission - " + m["goal"][:60], report_md,
                                              open_it=True,
                                              subtitle=f"Mission {mid} · {m['status']}")
        with _MISSIONS_LOCK:
            data = _load_missions()
            if mid in data:
                data[mid]["report"] = html_path or md_path
                _save_missions(data)

        spoken = core.truncate(final or "All planned steps are complete.", 600)
        core.say_async("Mission complete, sir. " + spoken)
        core.audit("mission", m["goal"], f"{mid} {m['status']} report={html_path}", risk="normal")
    except Exception as e:
        core.log(f"mission {mid} failed: {e}")
        try:
            with _MISSIONS_LOCK:
                data = _load_missions()
                if mid in data:
                    data[mid]["status"] = "failed"
                    data[mid]["error"] = str(e)
                    _save_missions(data)
            core.say_async(f"Sir, the mission failed: {core.truncate(str(e), 200)}")
        except Exception:
            pass
    finally:
        _CURRENT_MISSION.set("")
        _ACTIVE_MISSIONS.pop(mid, None)
        _RUNNING.clear()


def start_mission(goal: str, background: bool = True) -> str:
    """Start a multi-step autonomous mission towards a goal."""
    goal = (goal or "").strip()
    if not goal:
        return "No mission goal given."
    m = _new_mission(goal)
    with _MISSIONS_LOCK:
        data = _load_missions()
        data[m["id"]] = m
        _save_missions(data)
    if background:
        t = threading.Thread(target=_run_mission, args=(m["id"],), daemon=True, name=f"mission-{m['id']}")
        _ACTIVE_MISSIONS[m["id"]] = t
        t.start()
        return (f"Mission {m['id']} started in the background: {core.truncate(goal, 140)}. "
                "I will speak and open a report when it is finished.")
    _run_mission(m["id"])
    return f"Mission {m['id']} finished. " + core.truncate(_MISSION_RESULT.get(m["id"], ""), 800)


def cancel_mission(mid: str = "") -> str:
    with _MISSIONS_LOCK:
        data = _load_missions()
        targets = [mid] if mid else [k for k, v in data.items() if v.get("status") in ("running", "planning")]
        changed = []
        for k in targets:
            if k in data and data[k].get("status") in ("running", "planning"):
                data[k]["status"] = "cancelled"
                data[k]["updated"] = time.time()
                changed.append(k)
        _save_missions(data)
    return ("Cancelled: " + ", ".join(changed)) if changed else "No running mission to cancel."


def unfinished_missions(include_paused: bool = False) -> list[dict]:
    """Missions that were still running when the previous session ended."""
    wanted = {"running", "planning"}
    if include_paused:
        wanted.add("paused")
    data = _load_missions()
    rows = [m for m in data.values()
            if isinstance(m, dict) and m.get("status") in wanted]
    return sorted(rows, key=lambda m: -float(m.get("updated") or m.get("created") or 0))


def defer_mission(mid: str) -> str:
    """Keep a mission for later without offering it on every startup."""
    with _MISSIONS_LOCK:
        data = _load_missions()
        m = data.get(mid)
        if not m:
            return f"No mission '{mid}'."
        if m.get("status") in ("running", "planning"):
            m["status"] = "paused"
            m["updated"] = time.time()
            _save_missions(data)
            return f"Mission {mid} paused."
        return f"Mission {mid} is {m.get('status')}."


def resume_mission(mid: str) -> str:
    """Continue a saved mission from its first unfinished step."""
    mid = (mid or "").strip()
    with _MISSIONS_LOCK:
        data = _load_missions()
        m = data.get(mid)
        if not m:
            return f"No mission '{mid}'."
        if m.get("status") in ("done", "cancelled"):
            return f"Mission {mid} is already {m.get('status')}."
        running = _ACTIVE_MISSIONS.get(mid)
        if running is not None and running.is_alive():
            return f"Mission {mid} is already running."
        m["status"] = "running"
        m["updated"] = time.time()
        _save_missions(data)
    t = threading.Thread(target=_run_mission, args=(mid,), daemon=True,
                         name=f"mission-{mid}")
    _ACTIVE_MISSIONS[mid] = t
    t.start()
    return f"Resumed mission {mid}: {core.truncate(m.get('goal', ''), 140)}"


def mission_operation(action: str = "start", goal: str = "", mission_id: str = "",
                      wait: bool = False) -> str:
    """Run and manage long multi-step missions.

    action:
      start   - plan and execute a big goal autonomously (goal required)
      list    - show all missions and their progress
      status  - detailed status of one mission (mission_id)
      cancel  - stop a running mission (mission_id optional)
      report  - reopen the saved report for a mission
    """
    a = (action or "start").lower().strip()
    if a in ("start", "run", "do"):
        return start_mission(goal or mission_id, background=not wait)
    if a in ("list", "all"):
        data = _load_missions()
        if not data:
            return "No missions have been started yet."
        rows = sorted(data.values(), key=lambda m: -m.get("created", 0))
        return "\n".join(_mission_summary(m) for m in rows[:30])
    if a in ("status", "show"):
        data = _load_missions()
        m = data.get(mission_id) or next(
            (v for v in data.values() if mission_id and mission_id.lower() in v.get("goal", "").lower()), None)
        if not m:
            return f"No mission '{mission_id}'."
        lines = [_mission_summary(m), "", "Plan:"]
        for s in m.get("plan", []):
            lines.append(f"  {s['n']}. [{s.get('status','?')}] {s['title']}")
            if s.get("result"):
                lines.append(f"     -> {core.truncate(s['result'], 300)}")
        for p in (m.get("progress") or [])[-6:]:
            lines.append(f"  · {p.get('text','')}")
        if m.get("report"):
            lines.append(f"Report: {m['report']}")
        return "\n".join(lines)
    if a in ("cancel", "stop"):
        return cancel_mission(mission_id)
    if a in ("report", "open"):
        data = _load_missions()
        m = data.get(mission_id)
        if not m:
            return f"No mission '{mission_id}'."
        if m.get("report") and os.path.exists(m["report"]):
            return core.open_path(m["report"])
        return "That mission has no saved report yet."
    return f"Unknown mission action '{action}'."


# --------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------
def _load_schedule() -> dict:
    data = core.read_json(SCHEDULE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_schedule(data: dict):
    core.write_json(SCHEDULE_FILE, data)


def _next_run(job: dict, now: float | None = None) -> float:
    now = now or time.time()
    kind = job.get("kind", "once")
    if kind == "once":
        return float(job.get("when") or 0)
    if kind == "interval":
        base = float(job.get("last_run") or now)
        return max(now, base + float(job.get("interval") or 3600))
    if kind == "daily":
        hh, mm = [int(x) for x in (job.get("time") or "09:00").split(":")[:2]]
        d = datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if d.timestamp() <= now:
            d += timedelta(days=1)
        return d.timestamp()
    if kind == "weekly":
        hh, mm = [int(x) for x in (job.get("time") or "09:00").split(":")[:2]]
        wd = int(job.get("weekday") or 0)  # Monday=0
        d = datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta = (wd - d.weekday()) % 7
        d += timedelta(days=delta)
        if d.timestamp() <= now:
            d += timedelta(days=7)
        return d.timestamp()
    return now + 3600


def add_schedule(when: float, prompt: str, kind: str = "once", time_str: str = "",
                 interval: int = 0, weekday: int = 0, label: str = "") -> dict:
    job = {
        "id": "S" + uuid.uuid4().hex[:8],
        "kind": kind,
        "prompt": prompt,
        "when": when,
        "time": time_str,
        "interval": int(interval or 0),
        "weekday": int(weekday or 0),
        "label": label or core.truncate(prompt, 80),
        "enabled": True,
        "created": time.time(),
        "last_run": 0,
        "runs": 0,
        "next": when,
    }
    with _SCHEDULE_LOCK:
        data = _load_schedule()
        data[job["id"]] = job
        _save_schedule(data)
    return job


def parse_schedule_text(text: str) -> dict | None:
    """Understand 'in 10 minutes', 'at 17:30', 'daily at 9 am', 'every 2 hours'."""
    t = (text or "").lower().strip()
    if not t:
        return None
    now = time.time()
    m = re.search(r"\bin\s+(\d+)\s*(sec|second|seconds|min|minute|minutes|hour|hours|ghanta|ghante)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = 1 if unit.startswith("sec") else 60 if unit.startswith(("min", "minute")) else 3600
        return {"kind": "once", "when": now + n * mult, "label": f"in {n} {unit}"}
    m = re.search(r"\b(?:every|har)\s+(\d+)\s*(sec|second|seconds|min|minute|minutes|hour|hours|ghanta|ghante)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = 1 if unit.startswith("sec") else 60 if unit.startswith(("min", "minute")) else 3600
        return {"kind": "interval", "interval": n * mult, "when": now + n * mult,
                "label": f"every {n} {unit}"}
    m = re.search(r"\b(?:daily|roz|every day|har roz)\b.*?\b(?:at|se|ko)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        hh = int(m.group(1)) % 24
        mm = int(m.group(2) or 0) % 60
        ap = m.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        hh %= 24
        time_str = f"{hh:02d}:{mm:02d}"
        tmp = {"kind": "daily", "time": time_str}
        return {"kind": "daily", "time": time_str, "when": _next_run(tmp, now),
                "label": f"daily at {time_str}"}
    m = re.search(r"\b(?:at|ko)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if m:
        hh = int(m.group(1)) % 24
        mm = int(m.group(2) or 0) % 60
        ap = m.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        d = datetime.now().replace(hour=hh % 24, minute=mm, second=0, microsecond=0)
        if d.timestamp() <= now:
            d += timedelta(days=1)
        return {"kind": "once", "when": d.timestamp(), "time": f"{hh % 24:02d}:{mm:02d}",
                "label": d.strftime("%d %b %H:%M")}
    return None


_TIME_REMOVERS = [
    r"\bin\s+\d+\s*(?:sec|second|seconds|min|minute|minutes|hour|hours|ghanta|ghante)\b",
    r"\b(?:daily|roz|every\s+day|har\s+roz)\b(?:\s+(?:at|se|ko))?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?",
    r"\bevery\s+\d+\s*(?:sec|second|seconds|min|minute|minutes|hour|hours|ghanta|ghante)\b",
    r"\b(?:at|ko)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
]


def _extract_prompt(text: str) -> str:
    """Strip the scheduling phrase from a natural request, keep the task."""
    t = (text or "").strip()
    for pattern in _TIME_REMOVERS:
        t = re.sub(pattern, " ", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,:-")
    return t


def schedule_operation(action: str = "add", text: str = "", prompt: str = "",
                       job_id: str = "", confirmed: bool = False) -> str:
    """Create and manage scheduled commands.

    action:
      add      - schedule something. Put the natural language request in text
                 ('in 20 minutes remind me to drink water', 'daily at 9 am give me the news').
      list     - show every scheduled job
      remove   - delete a job (job_id, confirmed=true)
      pause / resume - disable or enable a job (job_id)
      clear    - delete all jobs (confirmed=true)
    """
    a = (action or "add").lower().strip()
    if a in ("add", "create", "set"):
        parsed = parse_schedule_text(text)
        if not parsed:
            return ("I could not understand the time. Say it like 'in 20 minutes ...', "
                    "'at 6:30 pm ...' or 'daily at 9 am ...'.")
        task = (prompt or _extract_prompt(text)).strip()
        if not task:
            return "What should I do at that time?"
        job = add_schedule(parsed["when"], task, kind=parsed.get("kind", "once"),
                           time_str=parsed.get("time", ""), interval=parsed.get("interval", 0),
                           label=parsed.get("label", ""))
        when_txt = time.strftime("%A %d %b at %I:%M %p", time.localtime(job["when"]))
        return (f"Scheduled ({job['id']}): {core.truncate(task, 160)} — {parsed.get('label','')}, "
                f"next run {when_txt}.")
    if a in ("list", "all", "show"):
        data = _load_schedule()
        if not data:
            return "Nothing is scheduled."
        rows = []
        for job in sorted(data.values(), key=lambda j: j.get("next") or 0):
            state = "on" if job.get("enabled", True) else "paused"
            rows.append(f"- {job['id']} [{state}, {job.get('kind')}] {core.truncate(job.get('prompt',''), 120)} "
                        f"→ {time.strftime('%d %b %I:%M %p', time.localtime(job.get('next') or 0))}")
        return "\n".join(rows)
    if a in ("remove", "delete"):
        msg = core.guard("schedule_operation:remove", confirmed, f"Delete scheduled job {job_id}.")
        if msg:
            return msg
        with _SCHEDULE_LOCK:
            data = _load_schedule()
            job = data.pop(job_id, None)
            _save_schedule(data)
        return f"Removed {job_id}: {core.truncate(job.get('prompt',''), 100)}" if job else f"No job {job_id}."
    if a in ("pause", "resume", "enable", "disable"):
        with _SCHEDULE_LOCK:
            data = _load_schedule()
            job = data.get(job_id)
            if not job:
                return f"No job {job_id}."
            job["enabled"] = a in ("resume", "enable")
            job["next"] = _next_run(job) if job["enabled"] else job.get("next")
            _save_schedule(data)
        return f"{job_id} is now {'enabled' if job['enabled'] else 'paused'}."
    if a in ("clear", "wipe"):
        msg = core.guard("schedule_operation:clear", confirmed, "Delete every scheduled job.")
        if msg:
            return msg
        with _SCHEDULE_LOCK:
            _save_schedule({})
        return "All scheduled jobs deleted."
    return f"Unknown schedule action '{action}'."


def _scheduler_loop():
    last_save = 0.0
    while not _STOP.is_set():
        try:
            now = time.time()
            due = []
            with _SCHEDULE_LOCK:
                data = _load_schedule()
                dirty = False
                for job in list(data.values()):
                    if not job.get("enabled", True):
                        continue
                    nxt = float(job.get("next") or job.get("when") or 0)
                    if nxt and nxt <= now:
                        due.append(dict(job))
                        job["last_run"] = now
                        job["runs"] = int(job.get("runs", 0)) + 1
                        if job.get("kind") == "once":
                            job["enabled"] = False
                        else:
                            job["next"] = _next_run(job, now)
                        dirty = True
                if dirty:
                    _save_schedule(data)
            for job in due:
                prompt = (job.get("prompt") or "").strip()
                if not prompt:
                    continue
                core.log(f"Scheduler firing {job['id']}: {core.truncate(prompt, 120)}")
                core.say_async("Sir, a scheduled task is due.")
                q = core.G.get("command_queue")
                if q is not None:
                    try:
                        q.put(prompt)
                        continue
                    except Exception:
                        pass
                fn = core.G.get("handle_command")
                if fn:
                    try:
                        fn(prompt)
                    except Exception as e:
                        core.log(f"scheduled command failed: {e}")
            if now - last_save > 60:
                last_save = now
        except Exception as e:
            core.log(f"scheduler error: {e}")
        time.sleep(15)


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
_SKILL_CACHE: dict[str, dict] = {}
_SKILL_MTIMES: dict[str, float] = {}


def _skill_dirs() -> list[str]:
    dirs = [core.SKILLS_DIR]
    extra = core.load_config().get("skill_dirs") or []
    if isinstance(extra, list):
        dirs += [str(d) for d in extra if d]
    return dirs


def discover_skills(force: bool = False) -> dict[str, dict]:
    global _SKILL_CACHE
    found: dict[str, dict] = {}
    for folder in _skill_dirs():
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            if name.lower().startswith(("readme", "license", "_")):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".md", ".py", ".json"):
                continue
            try:
                mt = os.path.getmtime(path)
                key = os.path.abspath(path)
                if not force and _SKILL_MTIMES.get(key) == mt and key in _SKILL_CACHE:
                    found[_SKILL_CACHE[key]["name"]] = _SKILL_CACHE[key]
                    continue
                if ext == ".md":
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), name)
                    skill = {"name": os.path.splitext(name)[0], "title": first[:100],
                             "description": first[:200], "kind": "prompt", "instructions": text[:12000],
                             "path": path}
                elif ext == ".json":
                    data = core.read_json(path, {}) or {}
                    skill = {"name": str(data.get("name") or os.path.splitext(name)[0]),
                             "title": str(data.get("title") or data.get("name") or name),
                             "description": str(data.get("description") or ""),
                             "kind": "prompt",
                             "instructions": str(data.get("instructions") or data.get("prompt") or ""),
                             "path": path}
                else:
                    skill = {"name": os.path.splitext(name)[0], "title": name,
                             "description": "", "kind": "python", "path": path}
                    mod = _load_python_skill(path)
                    if mod is None:
                        continue
                    skill["title"] = str(getattr(mod, "NAME", skill["name"]))
                    skill["description"] = str(getattr(mod, "DESCRIPTION", ""))
                    skill["module"] = mod
                skill["name"] = re.sub(r"[^a-zA-Z0-9_\- ]+", "", skill["name"]).strip() or os.path.splitext(name)[0]
                found[skill["name"].lower()] = skill
                _SKILL_CACHE[skill["name"].lower()] = skill
                _SKILL_MTIMES[key] = mt
            except Exception as e:
                core.log(f"skill {name} failed to load: {e}")
    return found


def _load_python_skill(path: str):
    try:
        modname = "jarvis_skill_" + re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0])
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[modname] = mod
        return mod
    except Exception as e:
        core.log(f"python skill load failed ({path}): {e}")
        return None


def _skill_hint_block() -> str:
    skills = discover_skills()
    if not skills:
        return ""
    lines = []
    for s in list(skills.values())[:20]:
        lines.append(f"- {s['name']}: {core.truncate(s.get('description') or s.get('title') or '', 120)}")
    return "[AVAILABLE SKILLS — use skill_operation(action='run', name=...)]\n" + "\n".join(lines)


def skill_operation(action: str = "list", name: str = "", args: str = "") -> str:
    """List and run user-authored skills from the jarvis_skills folder.

    action:
      list  - show available skills
      read  - show a skill's instructions
      run   - execute a skill (name required, args optional)
    """
    a = (action or "list").lower().strip()
    skills = discover_skills(force=True)
    if a in ("list", "all", "show"):
        if not skills:
            return f"No skills found. Add .md or .py files to {core.SKILLS_DIR}."
        return "\n".join(
            f"- {s['name']} [{s['kind']}]: {core.truncate(s.get('description') or s.get('title') or '', 160)}"
            for s in skills.values())
    key = (name or "").strip().lower()
    skill = skills.get(key)
    if not skill:
        key2 = re.sub(r"[\s\-]+", "_", key)
        skill = skills.get(key2)
    if not skill:
        key2 = re.sub(r"[\s_\-]+", "", key)
        matches = [s for k, s in skills.items() if key2 and key2 in re.sub(r"[\s_\-]+", "", k)]
        skill = matches[0] if matches else None
    if not skill:
        return f"No skill named '{name}'."
    if a == "read":
        if skill["kind"] == "python":
            return f"{skill['title']}\n{skill.get('description','')}\nPath: {skill['path']}"
        return skill.get("instructions", "")[:12000]
    if a in ("run", "execute", "do"):
        if skill["kind"] == "python":
            mod = skill.get("module") or _load_python_skill(skill["path"])
            if mod is None:
                return "The skill could not be loaded."
            fn = getattr(mod, "run", None)
            if not callable(fn):
                return "That Python skill has no run() function."
            try:
                import inspect
                sig = inspect.signature(fn)
                if len(sig.parameters) == 0:
                    result = fn()
                elif len(sig.parameters) == 1:
                    result = fn(args or core.G)
                else:
                    result = fn(core.G, args or "")
                return str(result)[:8000]
            except Exception as e:
                return f"Skill '{skill['name']}' failed: {e}"
        prompt = (
            "Execute this user-defined skill for the user.\n\n"
            f"SKILL: {skill.get('title')}\n{skill.get('instructions','')}\n\n"
            f"USER REQUEST / ARGUMENTS: {args or '(none — just run the skill normally)'}\n\n"
            "Use the available tools to complete it, then report the result briefly."
        )
        try:
            chat = _mission_chat({"goal": skill.get("title", "skill")})
            resp = chat.send_message(prompt)
            return (getattr(resp, "text", None) or "Skill finished.")[:8000]
        except Exception as e:
            return f"Skill '{skill['name']}' failed: {e}"
    return f"Unknown skill action '{action}'."


# --------------------------------------------------------------------------
# Daily briefing helper
# --------------------------------------------------------------------------
def active_mission_text() -> str:
    """Short status line for the HUD."""
    try:
        data = _load_missions()
        running = [m for m in data.values() if m.get("status") in ("running", "planning")]
        if not running:
            return ""
        m = sorted(running, key=lambda x: -x.get("updated", 0))[0]
        plan = m.get("plan") or []
        done = sum(1 for s in plan if s.get("status") == "done")
        step = next((s for s in plan if s.get("status") == "running"), None)
        title = (step or {}).get("title") or m.get("goal", "")
        return f"MISSION {done}/{len(plan)} · {core.truncate(title, 44)}"
    except Exception:
        return ""


def start_background():
    """Start the scheduler thread once (called from run_jarvis)."""
    if getattr(sys, "_jarvis_scheduler_started", False):
        return
    sys._jarvis_scheduler_started = True
    threading.Thread(target=_scheduler_loop, daemon=True, name="jarvis-scheduler").start()
    core.log("Scheduler online.")
