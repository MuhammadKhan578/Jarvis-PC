"""Local calendar for Jarvis: create, read, reschedule and invite.

There is no cloud account and no OAuth dance.  Events live in
``jarvis_data/calendar.json`` (git-ignored) so they stay on the user's PC.
Anything can be exported as a standard ``.ics`` file, which Outlook, Google
Calendar and Apple Calendar all understand, and an event invitation can be
emailed with the ``.ics`` attached.

Public API:
    calendar_operation(...)   - the tool Gemini calls
    upcoming(days=7)          - short list used by the HUD / MCP server
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta

from . import core

CAL_FILE = os.path.join(core.DATA_DIR, "calendar.json")


def _load() -> list[dict]:
    data = core.read_json(CAL_FILE, []) or []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("start") and item.get("title"):
            out.append(item)
    return out


def _save(events: list[dict]):
    core.write_json(CAL_FILE, events)


def _new_id(title: str, start: str) -> str:
    seed = f"{title}|{start}|{datetime.now().isoformat()}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:6]


def _parse_when(text: str) -> datetime | None:
    """Understand 'tomorrow 5 pm', 'kal 3 baje', 'in 2 hours', ISO dates."""
    raw = (text or "").strip()
    if not raw:
        return None
    t = raw.lower()
    now = datetime.now()

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[ t](\d{1,2}):(\d{2}))?", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4) or 9)
        mm = int(m.group(5) or 0)
        try:
            return datetime(y, mo, d, hh, mm)
        except ValueError:
            return None

    m = re.search(r"\b(?:in|after|baad)\s+(\d+)\s*(sec|second|seconds|min|minute|minutes|"
                  r"hour|hours|ghanta|ghante|day|days|din)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(("sec",)):
            return now + timedelta(seconds=n)
        if unit.startswith(("hour", "ghant")):
            return now + timedelta(hours=n)
        if unit.startswith(("day", "din")):
            return (now + timedelta(days=n)).replace(hour=9, minute=0, second=0, microsecond=0)
        return now + timedelta(minutes=n)

    day = None
    if re.search(r"\b(tomorrow|kal)\b", t):
        day = now + timedelta(days=1)
    elif re.search(r"\b(day after tomorrow|parson|parso)\b", t):
        day = now + timedelta(days=2)
    elif re.search(r"\b(today|aaj|tonight|aaj raat)\b", t):
        day = now

    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if not m:
        m = re.search(r"\b(\d{1,2})\s*(?::(\d{2}))?\s*(?:baje|o'?clock)\b", t)
    if not m:
        m = re.search(r"\b(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\b", t)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        ampm = (m.group(3) or "").lower() if m.lastindex and m.lastindex >= 3 else ""
        if ampm == "pm" and hh < 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0
        if not ampm and 0 <= hh <= 7:
            hh += 12  # "5" in the evening is more likely than 5 in the morning
        try:
            base = day or now
            when = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not day and when <= now:
                when += timedelta(days=1)
            return when
        except ValueError:
            return None

    if day is not None:
        return day.replace(hour=9, minute=0, second=0, microsecond=0)

    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _duration(text: str, default: int = 30) -> int:
    m = re.search(r"\b(?:for|ke\s+liye)?\s*(\d+)\s*(min|minute|minutes|minut|hour|hours|ghanta|ghante)\b",
                  (text or "").lower())
    if not m:
        return default
    n = int(m.group(1))
    return n * 60 if m.group(2).startswith(("hour", "ghant")) else n


def _attendees(text: str) -> list[str]:
    parts = re.split(r"[,;]+", text or "")
    return [p.strip() for p in parts if "@" in p and "." in p]


def _ics_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _ics(events: list[dict]) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jarvis//Local Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for ev in events:
        try:
            start = datetime.fromisoformat(ev["start"])
        except Exception:
            continue
        end = start + timedelta(minutes=int(ev.get("duration") or 30))
        def _esc(value: str) -> str:
            return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{_esc(ev.get('id') or '')}@jarvis.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_dt(start)}",
            f"DTEND:{_ics_dt(end)}",
            f"SUMMARY:{_esc(ev.get('title') or '')}",
        ])
        if ev.get("location"):
            lines.append(f"LOCATION:{_esc(ev['location'])}")
        if ev.get("notes"):
            lines.append(f"DESCRIPTION:{_esc(ev['notes'])}")
        for person in ev.get("attendees") or []:
            lines.append(f"ATTENDEE:mailto:{_esc(person)}")
        lines.extend(["END:VEVENT"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _fmt(ev: dict) -> str:
    try:
        start = datetime.fromisoformat(ev["start"])
        end = start + timedelta(minutes=int(ev.get("duration") or 30))
        when = start.strftime("%a %d %b, %I:%M %p") + " - " + end.strftime("%I:%M %p")
    except Exception:
        when = str(ev.get("start"))
    extra = []
    if ev.get("location"):
        extra.append("at " + ev["location"])
    if ev.get("attendees"):
        extra.append("with " + ", ".join(ev["attendees"]))
    note = f"  ({'; '.join(extra)})" if extra else ""
    return f"[{ev.get('id')}] {when} - {ev.get('title')}{note}"


def _find(events: list[dict], needle: str) -> dict | None:
    needle = (needle or "").strip().lower()
    if not needle:
        return None
    for ev in events:
        if ev.get("id") == needle:
            return ev
    for ev in events:
        if needle in (ev.get("title") or "").lower():
            return ev
    return None


def _range_events(events: list[dict], span: str) -> list[dict]:
    now = datetime.now()
    span = (span or "upcoming").lower()
    if span in ("today", "aaj"):
        start, end = now.replace(hour=0, minute=0, second=0, microsecond=0), now.replace(
            hour=23, minute=59, second=59, microsecond=0)
    elif span in ("week", "hafte", "7days", "7"):
        start, end = now, now + timedelta(days=7)
    elif span in ("month", "30days", "30"):
        start, end = now, now + timedelta(days=30)
    elif span in ("all", "sab"):
        start, end = datetime(1970, 1, 1), datetime(2100, 1, 1)
    else:
        start, end = now, now + timedelta(days=30)
    out = []
    for ev in events:
        try:
            when = datetime.fromisoformat(ev["start"])
        except Exception:
            continue
        if start <= when <= end:
            out.append(ev)
    out.sort(key=lambda e: e.get("start") or "")
    return out


def upcoming(days: int = 7) -> str:
    events = _range_events(_load(), f"{days}days" if days != 7 else "week")
    if not events:
        return "Calendar is clear for the next " + str(days) + " days, sir."
    return "\n".join(_fmt(e) for e in events)


def calendar_operation(action: str = "list", title: str = "", start: str = "",
                       duration_minutes: int = 30, location: str = "", notes: str = "",
                       attendees: str = "", query: str = "", range: str = "upcoming",
                       confirmed: bool = False) -> str:
    """Create, read, reschedule, delete, invite and export calendar events.

    action:
      add      - create an event (title, start, duration_minutes, location, notes, attendees)
      list     - upcoming events (range: today, week, month, all)
      update   - change an event found by query/title (new start, duration, title, notes)
      delete   - remove an event found by query/title (asks for confirmation first)
      invite   - email an .ics invitation to the attendees already on the event
      export   - write all events to an .ics file on the Desktop
      help     - how dates are understood
    start accepts 'tomorrow 5 pm', 'kal 3 baje', 'in 2 hours', '2026-11-14 09:30'.
    """
    a = (action or "list").strip().lower()
    events = _load()

    if a in ("help", "guide"):
        return (
            "Calendar actions: add, list, update, delete, invite, export.\n"
            "Times I understand: 'tomorrow 5 pm', 'kal 3 baje', 'today 18:30', "
            "'in 2 hours', '2026-11-14 09:30'. Default duration is 30 minutes.\n"
            "Events are stored locally in jarvis_data/calendar.json and can be exported as .ics."
        )

    if a == "add":
        if not (title or "").strip():
            return "What should I call the event, sir?"
        when = _parse_when(start) or _parse_when(title)
        if not when:
            return ("I could not read the date/time. Try 'tomorrow 5 pm', 'kal 3 baje', "
                    "'in 2 hours' or '2026-11-14 09:30'.")
        clean_title = re.sub(
            r"\b(?:tomorrow|today|kal|aaj|at|in|after|baad|baje|o'?clock|am|pm|\d{1,2}(?::\d{2})?)\b",
            " ", title, flags=re.I).strip(" ,-")
        clean_title = re.sub(r"\s{2,}", " ", clean_title) or title.strip()
        minutes = int(duration_minutes or 0) or _duration(title + " " + start)
        ev = {
            "id": _new_id(clean_title, when.isoformat()),
            "title": clean_title,
            "start": when.isoformat(timespec="minutes"),
            "duration": max(5, min(24 * 60, int(minutes))),
            "location": (location or "").strip(),
            "notes": (notes or "").strip(),
            "attendees": _attendees(attendees),
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        events.append(ev)
        _save(events)
        core.audit("calendar_operation", ev["title"], ev["start"])
        return "Event created, sir. " + _fmt(ev)

    if a in ("list", "today", "week", "agenda", "show", "read"):
        if a in ("today", "week"):
            range = a
        found = _range_events(events, range)
        if not found:
            return f"No events in that range, sir. ({range})"
        head = f"{len(found)} event(s):"
        return head + "\n" + "\n".join(_fmt(e) for e in found)

    if a in ("update", "reschedule", "move", "edit"):
        ev = _find(events, query or title)
        if not ev:
            return f"I could not find an event matching '{query or title}'. Use list first."
        when = _parse_when(start) if start else None
        if when:
            ev["start"] = when.isoformat(timespec="minutes")
        if duration_minutes and int(duration_minutes) > 0:
            ev["duration"] = int(duration_minutes)
        if title and title.strip().lower() not in ("", (query or "").strip().lower()):
            ev["title"] = title.strip()
        if location:
            ev["location"] = location.strip()
        if notes:
            ev["notes"] = notes.strip()
        if attendees:
            ev["attendees"] = _attendees(attendees)
        _save(events)
        core.audit("calendar_operation", "update", _fmt(ev))
        return "Event updated, sir. " + _fmt(ev)

    if a in ("delete", "remove", "cancel"):
        ev = _find(events, query or title)
        if not ev:
            return f"I could not find an event matching '{query or title}'."
        msg = core.guard("calendar_operation:delete", confirmed,
                         f"Delete calendar event: {_fmt(ev)}")
        if msg:
            return msg
        events = [e for e in events if e.get("id") != ev.get("id")]
        _save(events)
        core.audit("calendar_operation", "delete", _fmt(ev))
        return "Deleted, sir. " + _fmt(ev)

    if a == "invite":
        ev = _find(events, query or title)
        if not ev:
            return f"I could not find an event matching '{query or title}'."
        people = ev.get("attendees") or _attendees(attendees)
        if not people:
            return "That event has no attendee emails yet. Update it with attendees first."
        path = os.path.join(core.DATA_DIR, "calendar_ics", core.safe_filename(ev["title"], "invite") + ".ics")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(_ics([ev]))
        try:
            from .integrations import send_email
            body = (
                f"You are invited to: {ev['title']}\n"
                f"Time: {_fmt(ev)}\n"
                + (f"Location: {ev['location']}\n" if ev.get("location") else "")
                + (f"Notes: {ev['notes']}\n" if ev.get("notes") else "")
                + "\nThe attached .ics file opens in any calendar app."
            )
            return send_email(to=", ".join(people), subject=f"Invitation: {ev['title']}",
                              body=body, attachments=path)
        except Exception as e:
            return f"Invitation file created at {path}, but email failed: {e}"

    if a in ("export", "ics", "backup"):
        path = os.path.join(core.desktop(), "Jarvis_Calendar.ics")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(_ics(events))
        return f"Exported {len(events)} event(s) to {path}"

    return "Unknown calendar action. Use add, list, update, delete, invite, export or help."
