"""Unfinished-work journal and the startup resume prompt.

Every command is written to disk as *running* before it starts and marked
*done* when it ends.  If Windows or Jarvis stops in the middle, the next start
asks the user whether to finish the interrupted work.  A prepared email draft
is saved separately, so a shutdown between "draft ready" and "yes" never loses
it.

The journal is deliberately small and boring: a list of tasks in
``jarvis_data/pending_tasks.json``.  It never stores passwords.
"""
from __future__ import annotations

import os
import re
import threading
import time

from . import agent, core, mail

TASKS_FILE = os.path.join(core.DATA_DIR, "pending_tasks.json")
_LOCK = threading.RLock()
_TTL = 7 * 24 * 3600       # ignore journals older than a week
_RESUME_TTL = 24 * 3600    # how long a spoken yes/no prompt stays valid
_MAX_TASKS = 40
_STATE = {"active": False, "queue": [], "asked_at": 0.0, "summary": ""}
# Never offer to "resume" a power/exit command after a reboot.  The command
# either completed or the PC is already off; asking again would be dangerous.
_NEVER_RESUME = re.compile(
    r"^\s*(?:shutdown|shut\s*down|restart|reboot|sleep|lock|exit|quit|"
    r"band\s+karo|band\s+kar\s+do|so\s+jao|go\s+to\s+sleep|"
    r"shutdown\s+jarvis|exit\s+jarvis)\b", re.I)


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------
def _load() -> list:
    data = core.read_json(TASKS_FILE, [])
    return data if isinstance(data, list) else []


def _save(tasks: list):
    tasks = [t for t in tasks if isinstance(t, dict)][-_MAX_TASKS:]
    core.write_json(TASKS_FILE, tasks)


def _new_id() -> str:
    return "T" + str(int(time.time() * 1000)) + "-" + str(abs(hash(threading.get_ident())) % 10000)


def begin(text: str) -> str:
    """Record a command as running.  Returns its journal id."""
    # Never let an App Password reach the on-disk journal.
    text = mail.redact_secrets((text or "").strip())
    if not text:
        return ""
    # A question *about* unfinished work is not itself unfinished work.  The
    # journal is written before command_hook runs, so without this check the
    # pending-work question would still be "running" when it scans the journal
    # and would offer to resume itself.
    if _is_status_query(text.lower()):
        return ""
    task = {"id": _new_id(), "text": text, "status": "running",
            "started": time.time(), "updated": time.time(), "error": ""}
    with _LOCK:
        tasks = _load()
        tasks.append(task)
        _save(tasks)
    return task["id"]


def complete(task_id: str, status: str = "done", error: str = ""):
    """Mark a running command finished.  Never overwrites a failure."""
    if not task_id:
        return
    with _LOCK:
        tasks = _load()
        for task in tasks:
            if task.get("id") == task_id and task.get("status") == "running":
                task["status"] = status
                task["updated"] = time.time()
                if error:
                    task["error"] = str(error)[:500]
        _save(tasks)


def fail(task_id: str, error):
    complete(task_id, "failed", error)


def _mark(task_id: str, status: str):
    with _LOCK:
        tasks = _load()
        for task in tasks:
            if task.get("id") == task_id:
                task["status"] = status
                task["updated"] = time.time()
        _save(tasks)


def unfinished(include_deferred: bool = False) -> list:
    """Commands that were still running when the previous session ended."""
    now = time.time()
    wanted = {"running", "deferred"} if include_deferred else {"running"}
    out = []
    for task in _load():
        if task.get("status") not in wanted:
            continue
        if now - float(task.get("updated") or task.get("started") or 0) > _TTL:
            continue
        text = (task.get("text") or "").strip()
        if not text or text.upper() == "[REDACTED APP PASSWORD]":
            continue
        if _NEVER_RESUME.match(text):
            continue
        # Questions about pending work are answered from the journal; they are
        # never resumable work, even if an old journal entry was left running.
        if _is_status_query(text.lower()):
            continue
        # A bare yes/no or a send confirmation belongs to the email state,
        # not to a resumable task.
        try:
            if (mail._is_yes(text) or mail._is_no(text)
                    or mail._is_send_confirmation(text)):
                continue
        except Exception:
            pass
        out.append(task)
    return sorted(out, key=lambda t: -float(t.get("started") or 0))


# --------------------------------------------------------------------------
# Startup queue
# --------------------------------------------------------------------------
def _email_label(state: dict) -> str:
    stage = state.get("stage")
    to = state.get("to") or (state.get("draft") or {}).get("to") or "recipient"
    subject = (state.get("draft") or {}).get("subject") or ""
    if stage == "sending":
        return f"email to {to} — the last send was interrupted"
    if stage == "resend_confirm":
        return f"email to {to} — waiting to retry an interrupted send"
    if stage == "draft":
        return f"email draft to {to}" + (f" — {core.truncate(subject, 60)}" if subject else "")
    if stage == "content":
        return f"email to {to} — waiting for the message"
    if stage == "to":
        return "email — waiting for the recipient address"
    return "email draft"


def _build_queue(include_deferred: bool = False, exclude_text: str = "") -> list:
    items = []
    skip = re.sub(r"\s+", " ", (exclude_text or "").strip().lower())
    try:
        pending = mail.restore_pending(include_deferred=include_deferred)
        if pending:
            items.append({"kind": "email", "label": _email_label(pending)})
    except Exception as e:
        core.log(f"resume: email restore failed: {e}")
    try:
        for mission in agent.unfinished_missions(include_paused=include_deferred)[:3]:
            items.append({
                "kind": "mission",
                "id": mission.get("id", ""),
                "label": "mission: " + core.truncate(mission.get("goal", ""), 100),
            })
    except Exception as e:
        core.log(f"resume: mission scan failed: {e}")
    try:
        has_email = any(item.get("kind") == "email" for item in items)
        for task in unfinished(include_deferred=include_deferred)[:5]:
            text = task.get("text", "")
            # The pending-work question itself is never a task.
            if skip and re.sub(r"\s+", " ", text.strip().lower()) == skip:
                continue
            # The saved email draft already represents an interrupted email
            # command; do not ask about the same work twice.
            if has_email and re.search(r"\b(?:email|mail|gmail)\b", text, re.I):
                continue
            items.append({
                "kind": "task",
                "id": task.get("id", ""),
                "text": text,
                "label": core.truncate(text, 120),
            })
    except Exception as e:
        core.log(f"resume: task scan failed: {e}")
    return items


def _summary(items: list) -> str:
    return "; ".join(f"{i}. {item['label']}" for i, item in enumerate(items[:5], 1))


def _ask():
    items = _STATE.get("queue") or []
    if not items:
        return
    n = len(items)
    listing = _summary(items)
    if n == 1:
        core.say_lang(
            f"Sir, last time one task was left unfinished: {items[0]['label']}. "
            "Shall I finish it now? Say yes or no.",
            f"Sir, pichhli baar ek kaam adhura reh gaya tha: {items[0]['label']}. "
            "Kya main ise ab complete karun? Haan ya nahi bolein.",
            f"سر، پچھلی بار ایک کام ادھورا رہ گیا تھا: {items[0]['label']}۔ "
            "کیا میں اسے اب مکمل کروں؟ ہاں یا نہیں۔")
    else:
        core.say_lang(
            f"Sir, {n} tasks were left unfinished: {listing}. "
            "Shall I finish them now? Say yes or no.",
            f"Sir, {n} kaam adhure reh gaye the: {listing}. "
            "Kya main inhein ab complete karun? Haan ya nahi bolein.",
            f"سر، {n} کام ادھورے رہ گئے تھے: {listing}۔ "
            "کیا میں انہیں اب مکمل کروں؟ ہاں یا نہیں۔")


def _is_status_query(low: str) -> bool:
    return bool(re.search(
        r"(?:pending|unfinished|incomplete|adhura|adhure|adhuura|baqi|resume)\s*"
        r"(?:kaam|kam|task|tasks|work|jobs?)|"
        r"(?:kaam|kam|task|tasks|work)\s*(?:adhura|adhure|pending|baqi)|"
        r"(?:kaam|kam|task|tasks|work|jobs?)\s+(?:bacha|bacha\s+hai|baqi|left|remaining)|"
        r"what\s+was\s+left|what\s+is\s+left|kya\s+adhura|"
        # follow-ups such as "kia kaam tha wo batao" / "which task was it"
        r"(?:kia|kya|kaunsa|konsa|which|what)\s+(?:kaam|kam|task|work)\s+"
        r"(?:tha|thaa|hai|was|is)|"
        r"(?:kaam|kam|task|work)\s+(?:kya|kia|kaunsa|konsa)\s*(?:tha|thaa|hai)?",
        low, re.I))


def _clear_active():
    _STATE.update({"active": False, "queue": [], "asked_at": 0.0, "summary": ""})


def dismiss_prompt():
    """A new command moved the conversation on; stop showing the startup prompt.

    The saved work stays on disk and is still available through "pending work";
    only the spoken yes/no prompt is cancelled.
    """
    _clear_active()


def prompt_active() -> bool:
    return bool(_STATE.get("active"))


def startup_check(g: dict):
    """Find interrupted work and ask the user once.  Safe to call manually."""
    if _STATE.get("active"):
        return
    items = _build_queue()
    if not items:
        return
    _STATE.update({"active": True, "queue": items, "asked_at": time.time(),
                   "summary": _summary(items)})
    core.log("Unfinished work found: " + _STATE["summary"])
    print("\n[Resume] Unfinished work: " + _STATE["summary"])
    _ask()


def schedule_startup_check(g: dict, delay: float = 10.0):
    """Ask after the greeting, when Jarvis is not speaking or busy."""
    def worker():
        time.sleep(delay)
        for _ in range(120):
            busy = False
            for name in ("speaking", "main_busy"):
                event = g.get(name)
                try:
                    if event is not None and event.is_set():
                        busy = True
                        break
                except Exception:
                    pass
            if not busy:
                break
            time.sleep(0.5)
        try:
            startup_check(g)
        except Exception as e:
            core.log(f"startup resume check failed: {e}")

    threading.Thread(target=worker, daemon=True, name="jarvis-resume-check").start()


# --------------------------------------------------------------------------
# Resume execution
# --------------------------------------------------------------------------
def _resume_prompt(text: str) -> str:
    return (
        "Resume this interrupted task. First inspect what is already done so you do not "
        "repeat side effects, then finish only the missing parts. Use tools and verify "
        "the result. Original request: " + text
    )


def _enqueue_replay(g: dict, text: str):
    """Send the resumed command back through the normal main loop."""
    prompt = _resume_prompt(text)
    queue = g.get("command_queue")
    if queue is not None:
        queue.put(prompt)
        return
    handler = g.get("handle_command")
    if handler:
        threading.Thread(target=lambda: handler(prompt), daemon=True,
                         name="jarvis-resume-replay").start()


def _resume_all(g: dict, items: list | None = None):
    items = list(items if items is not None else (_STATE.get("queue") or []))
    if not items:
        return
    core.say_lang(
        f"Resuming {len(items)} unfinished task{'s' if len(items) != 1 else ''}, sir.",
        f"Sir, {len(items)} adhure kaam resume kar raha hoon.",
        f"سر، {len(items)} ادھورے کام دوبارہ شروع کر رہا ہوں۔")
    for item in items:
        try:
            kind = item.get("kind")
            if kind == "email":
                mail.resume_pending()
            elif kind == "mission":
                result = agent.resume_mission(item.get("id", ""))
                core.log("Resume mission: " + str(result))
            elif kind == "task":
                _mark(item.get("id", ""), "resumed")
                _enqueue_replay(g, item.get("text", ""))
        except Exception as e:
            core.log(f"resume {item.get('kind')} failed: {e}")
            core.say_lang(
                "Sir, one unfinished task could not be resumed: " + core.truncate(str(e), 200),
                "Sir, ek adhura kaam resume nahi ho saka: " + core.truncate(str(e), 200),
                "سر، ایک ادھورا کام دوبارہ شروع نہیں ہو سکا۔")


def _defer_all(items: list | None = None):
    """User said no: keep the records for a future session, but do not act."""
    items = list(items if items is not None else (_STATE.get("queue") or []))
    for item in items:
        if item.get("kind") == "task":
            _mark(item.get("id", ""), "deferred")
        elif item.get("kind") == "mission":
            try:
                agent.defer_mission(item.get("id", ""))
            except Exception as e:
                core.log(f"resume: could not pause mission: {e}")
    # Only touch the email draft if it was actually part of this prompt.
    if any(item.get("kind") == "email" for item in items):
        try:
            mail.defer_pending()
        except Exception:
            pass


def command_hook(text: str, g: dict) -> bool:
    """Handle yes/no for a startup resume, and the manual 'pending work' query."""
    low = (text or "").lower().strip()
    if not low:
        return False

    # An email confirmation always belongs to mail.py, even while a startup
    # resume prompt is on screen.  Never defer the draft the user is sending.
    try:
        if mail._active() and mail._is_send_confirmation(low):
            return False
    except Exception:
        pass

    if _STATE.get("active"):
        # A stale prompt must not turn an unrelated "yes" into a resume days later.
        if time.time() - float(_STATE.get("asked_at") or 0) > _RESUME_TTL:
            _clear_active()
            try:
                mail.defer_pending()
            except Exception:
                pass
            return False
        if mail._is_yes(low):
            items = list(_STATE.get("queue") or [])
            _clear_active()
            _resume_all(g, items)
            return True
        if mail._is_no(low):
            items = list(_STATE.get("queue") or [])
            _clear_active()
            _defer_all(items)
            core.say_lang(
                "Understood, sir. I will not resume it now. It is saved for later.",
                "Theek hai, sir. Abhi resume nahi karunga. Kaam save hai, baad mein kar sakte hain.",
                "ٹھیک ہے، سر۔ ابھی دوبارہ شروع نہیں کروں گا۔ کام محفوظ ہے، بعد میں کر سکتے ہیں۔")
            return True
        if _is_status_query(low):
            _ask()
            return True
        # A new command: keep the saved work for the next start, but do not let
        # an old email draft intercept the new command.
        _clear_active()
        try:
            mail.defer_pending()
        except Exception:
            pass
        return False

    if _is_status_query(low):
        items = _build_queue(include_deferred=True, exclude_text=text)
        if not items:
            core.say_lang(
                "No unfinished work, sir. Everything is complete.",
                "Koi adhura kaam nahi hai, sir. Sab complete hai.",
                "کوئی ادھورا کام نہیں ہے، سر۔ سب مکمل ہے۔")
            return True
        _STATE.update({"active": True, "queue": items, "asked_at": time.time(),
                       "summary": _summary(items)})
        _ask()
        return True
    return False
