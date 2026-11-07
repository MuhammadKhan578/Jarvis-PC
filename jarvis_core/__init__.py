"""J.A.R.V.I.S. ULTIMATE — the upgrade layer for the original jarvis.py.

The original file is not replaced.  ``install(globals())`` is called from inside
jarvis.py, binds the running module's globals, appends the new tools to the
Gemini tool list, rebuilds the chat with the expanded system prompt, and wraps
the command loop so memory and the natural-language scheduler work.

Public API:
    install(globals())        - wire the upgrade into the running Jarvis
    start_background(globals())- start the scheduler and the HUD
    command_hook(text)        - instant fast-path commands; True = handled
    after_command(text)       - record a completed command (optional)
    PROMPT_ADDENDUM           - the extra system prompt text
    TOOLS                     - the new tool callables
"""
from __future__ import annotations

import re
import threading
import time
import typing

from . import agent, brain, core, diagnostics, documents, hud, integrations, mail, memory, research, resume, tools, voice

__version__ = "3.0"

PROMPT_ADDENDUM = r"""
## ULTIMATE CAPABILITIES (added by jarvis_core)

You are no longer limited to a handful of desktop actions. You have real hands, a
permanent memory archive and a separate deep-reasoning core. Use these tools proactively
and chain them until the task is truly done.

NEW TOOLS
- research_operation(action="search"|"fetch"|"links"|"wikipedia"|"news"|"deep"|"quick", topic/url, depth)
  Deep research plans queries, reads many pages, writes a cited report, opens it and speaks the summary.
- mission_operation(action="start", goal=...) — for large multi-step jobs (build a project, research a
  market and produce a deck, organise the PC, etc.). The mission engine plans and executes autonomously
  in the background and reports when finished. Use it when a request needs 4+ dependent steps.
- file_operation(...) — list, find, copy, move, rename, delete, organise, zip, search inside files,
  duplicates, disk usage, recent files, downloads, read/write text.
- document_operation(...) — create real Word/Excel/PowerPoint/PDF files from Markdown or JSON, read and
  summarise documents, OCR images.
- browser_operation(...) — drive a real Chrome/Edge/Brave window: open, read the page text, click by text
  or selector, type, run JavaScript, screenshot. Use action="open" before reading a page.
- ui_operation(...) — control Windows apps through UI Automation: list windows/controls, click buttons,
  type into fields, menus, shortcuts. Reliable for apps that pyautogui cannot see.
- system_operation(...) — full system report, processes, brightness, volume, Wi-Fi, dark mode, installed
  apps, startup apps, clean temp, recycle bin, power, settings.
- network_operation(...) — IP/DNS/ports/ping/speed test/traceroute/port check.
- memory_operation(...) — save/search facts, pin an exact detail forever, recall the permanent verbatim
  archive, show a timeline, export a memory report, back up memory.
- brain_operation(...) — the separate Ultimate Reasoning Core. Use action="think" for hard reasoning,
  "decide" for a weighted decision, "review_code" for a senior-engineer review, "debate" for both sides.
  depth="quick" answers synchronously; depth="deep"/"max" runs in the background and speaks the result.
  Use it for hard maths, logic, strategy, architecture, debugging, medical/legal-style analysis and
  decisions — not for simple commands.
- schedule_operation(...) — "in 20 minutes", "at 6 pm", "daily at 9 am", "every 2 hours".
- skill_operation(...) — list and run user-authored skills in the jarvis_skills folder.
- diagnostics_operation(...) — check every subsystem and repair common problems.
- integration_operation(...) — translate, summarise a page/document, ask about a document, daily briefing.
- email_operation(...) — the only way to read or send email. Sending uses Gmail's own compose
  window in Brave, or SMTP when an account is configured. Reading uses action="inbox"/"unread"/
  "search"/"read" (Gmail page in Brave when no IMAP account exists). For inbox/unread, the
  messages that were listed are then marked read in Gmail, as the user asked; search stays
  read-only. Use action="send" with the full subject and body. Never claim an email was sent
  unless the tool returns "Email sent". Do not open Gmail yourself as a substitute for calling
  the tool. When the user asks "any new email?" or "what is it about?", call
  email_operation(action="unread") first, then summarise only what the tool actually returned.
- hud_operation(...) — show/hide the arc-reactor overlay.
- config_operation(...) / ultimate_status() / audit_operation(...) — settings, status, transparency.

HOW TO USE THEM
1. Prefer ONE strong tool over many small steps. For example, for "make me a report on X and a Word
   file", call research_operation(deep) once; when it returns, call document_operation(create_word).
2. For a big goal with several dependent stages, start a mission instead of doing everything in this
   reply. Tell the user the mission id and that it runs in the background.
3. For anything "latest", "today", prices, scores or news: never guess. Use research_operation
   (quick for one answer, deep for a report).
4. Read before you write: if the user says "this page", "yeh document", "isko", use browser_operation
   read / document_operation read and resolve the reference from context.
5. After creating a file, state the exact path. After research, give the key findings and the report path.
6. When a tool fails, try another route (browser vs UI automation vs shell-free file tools) before giving up.
7. Use Brave for browser work by default. If the user names Chrome, Edge or Firefox, use that exact
   browser and never silently switch to Edge.

RELIABILITY AND HONESTY
- Never pretend. If you did not call a tool, you did not do the work.
- Only claim success when the tool result says success. If a tool says "not configured", "failed",
  "CONFIRMATION REQUIRED" or returns an error, stop and tell the user exactly what is missing.
- Never repeat the same failed action and claim it is working. Diagnose it or use a different tool.
- EMAIL: extract the recipient, subject and every concrete detail. Use email_operation for the
  real send. Always show a draft and ask permission first, even if safe mode is off. The send
  path opens Gmail in Brave and presses Send there. If Gmail asks for sign-in, tell the user to
  sign in once in that Brave window; do not claim the email was sent before Gmail confirms it.
  To read mail, call email_operation(action="unread"/"inbox"/"search"/"read"). Summarise only
  what the tool returned; if it says Gmail is not signed in or could not read the inbox, say
  that plainly and change nothing. Only configure SMTP when the user asks for a non-browser path.
- BROWSER: default to Brave. Never silently use Microsoft Edge when the user asked for Brave.
- Before destructive or irreversible actions, ask permission. After acting, verify the result
  and report exactly what happened, including failures.

UNFINISHED WORK
- Jarvis journals every command. If the PC or Jarvis stopped while a command was still
  running, the next start asks: "Sir, this work was left unfinished — shall I complete it?"
  A clear yes resumes it; a clear no leaves it saved for later. Never resume silently.
- When resuming, inspect the current state first. Do not repeat a side effect that may
  already have happened (files, emails, purchases, messages). Finish only the missing part.
- A prepared email draft survives a shutdown. If the user says yes, send it; if the send
  itself was interrupted, warn that it may already have gone out before retrying.

EXACT EXECUTION
- Do exactly what the user asked, in the order asked. Do not substitute an easier task.
- For a request with several dependent steps, use mission_operation and let it run to the end.
- Keep going until the whole request is genuinely done. If one route fails, try another
  (browser, UI automation, files, shell-free tools) before reporting a failure.
- If something is truly impossible or needs the user's secret/permission/account, say
  exactly which single thing is missing. Never pretend the work is done.

SAFETY (overrides the old "never ask" rule)
Destructive or irreversible actions require confirmation. This includes delete, move, organise,
batch rename, kill process, clean temp, empty recycle bin, shutdown/restart, sending email, clearing
memory/schedule. In safe mode the tool returns "CONFIRMATION REQUIRED": ask the user in one short
sentence and wait for a clear yes. Only then call the same tool again with confirmed=true. Never set
safe_mode off unless the user explicitly orders it. Everything else (opening apps, reading, browsing,
creating files, research, typing, normal clicks) runs immediately without asking.

MEMORY
Every exchange is stored permanently in an append-only archive and cannot be lost through
normal use. A [LONG-TERM MEMORY] block is injected into each message with relevant facts,
pins and past conversation. Use it naturally; never recite it verbatim.
- If the user asks "do you remember...", "tumhe yaad hai...", or refers to anything from
  before, call memory_operation(action="recall", query=...) FIRST. Never say you forgot
  without searching.
- When the user says "remember this exactly", "yaad rakhna", "never forget", or shares a
  detail that must survive forever, call memory_operation(action="remember_exact", ...).
- Use memory_operation(action="timeline") for chronology and action="stats" for memory size.
- The system also learns structured facts automatically every few turns.

STYLE
Speak like J.A.R.V.I.S.: calm, precise, quietly witty, always "sir". Keep spoken replies short (1-4
sentences) unless the user asked for detail. Put long content in a report or page, not in speech.
Match the user's language: English, Roman Urdu or Urdu, exactly as they spoke.
"""

_INSTALL_LOCK = threading.Lock()
_LAST_REPLY = {"text": "", "t": 0.0}
_CURRENT_INPUT = {"text": ""}

_ACTION_WORDS = {
    "open", "kholo", "khol", "banao", "bana", "create", "make", "delete",
    "remove", "hata", "clean", "saaf", "move", "copy", "rename", "install",
    "download", "upload", "send", "bhej", "bhejo", "type", "click", "play",
    "shutdown", "restart", "run", "execute", "fix", "build", "organise",
    "organize", "write", "likho", "save", "print", "schedule", "call",
}


def _looks_action_request(text: str) -> bool:
    return bool(set(re.findall(r"[\w']+", (text or "").lower())) & _ACTION_WORDS)


def _relevant_tool_success(text: str) -> bool:
    """Check a recent success from a tool family that matches this request."""
    words = set(re.findall(r"[\w']+", (text or "").lower()))
    if words & {"send", "bhej", "bhejo", "bhejna", "bhejni", "bhejdo"}:
        return core.recent_tool_success(("send_email", "email_operation"), seconds=180)
    if words & {"email", "mail", "gmail", "inbox"} and not words & {
            "open", "kholo", "khol", "browser", "brave", "chrome", "edge",
            "firefox"}:
        return core.recent_tool_success(("email_operation", "send_email"), seconds=180)
    if words & {"delete", "remove", "hata", "clean", "saaf", "trash", "recycle",
                "organise", "organize", "move", "copy", "rename"}:
        return core.recent_tool_success(
            ("file_operation", "delete", "remove", "clean", "temp",
             "system_operation"), seconds=180)
    if words & {"open", "kholo", "khol", "play", "type", "click", "browser",
                "brave", "chrome", "edge", "firefox", "search", "google",
                "youtube"}:
        return core.recent_tool_success(
            ("ui_operation", "browser_operation", "system_operation"), seconds=180)
    if words & {"schedule", "remind", "reminder", "timer"}:
        return core.recent_tool_success(("schedule_operation",), seconds=180)
    if words & {"research", "find", "look"}:
        return core.recent_tool_success(("research", "browser_operation"), seconds=180)
    if words & {"document", "report", "pdf", "write", "likho", "save"}:
        return core.recent_tool_success(
            ("document_operation", "file_operation"), seconds=180)
    if words & {"shutdown", "restart", "volume", "brightness", "kill", "process"}:
        return core.recent_tool_success(("system_operation",), seconds=180)
    if words & {"remember", "yaad", "memory"}:
        return core.recent_tool_success(("memory_operation",), seconds=180)
    if words & {"mission", "build", "create", "banao", "bana"}:
        return core.recent_tool_success(
            ("mission", "file_operation", "document_operation"), seconds=180)
    return core.recent_tool_success(seconds=180)


def _truth_guard(text: str) -> str:
    """Replace an unsupported success claim with the honest version.

    Only claims that can be checked are guarded: email sent, files deleted and
    generic "done" after an action request.  A real tool success in the audit
    log allows the claim to stand.
    """
    if not text:
        return text
    low = text.lower()
    current = _CURRENT_INPUT.get("text", "")

    def fresh_send_success() -> bool:
        row = mail.last_send_result()
        try:
            fresh = bool(row) and time.time() - float(row.get("t") or 0) <= 600
        except Exception:
            fresh = False
        return fresh and str(row.get("result") or "").lower().startswith("sent")

    email_lie = (
        "ROMAN: Sir, I cannot confirm that an email was sent. No successful "
        "send is recorded, so I will not claim it. URDU: سر، میں ای میل بھیجے "
        "جانے کی تصدیق نہیں کر سکتا، اس لیے جھوٹ نہیں بولوں گا۔")

    if re.search(
            r"\b(?:email|mail)\b.{0,100}\b(?:sent|bhej\s+di(?:ya)?|"
            r"bhej\s+di\s+gayi|send\s+ho\s+gay[ai]|send\s+kar\s+di(?:ya)?)\b|"
            r"\b(?:sent|bhej\s+di(?:ya)?)\b.{0,100}\b(?:email|mail)\b|"
            r"(?:ای میل|میل).{0,100}(?:بھیج دی|بھیج دیا|بھیج دی گئی)|"
            r"(?:بھیج دی|بھیج دیا|بھیج دی گئی).{0,100}(?:ای میل|میل)",
            low, re.S):
        if not fresh_send_success():
            return email_lie

    # A reply to "did you send it?" can claim success without repeating the
    # word "email".  Block that too unless the audit log proves a send.
    asked_send = re.search(
        r"\b(?:did|have|has|will|can|could|would|do)\s+you\s+"
        r"(?:send|bhej\w*)\b|"
        r"\b(?:send|bhej\w*)\s+ho\s+gay[ai]\b|"
        r"\bkya\s+(?:tum|aap)?\s*(?:ne\s+)?(?:send|bhej\w*)\b",
        current, re.I)
    generic_send_claim = re.search(
        r"\b(?:sent|send\s+kar\s+di(?:ya)?|bhej\s+di(?:ya)?|"
        r"bhej\s+di\s+gayi|send\s+ho\s+gay[ai])\b|"
        r"(?:بھیج دی|بھیج دیا|بھیج دی گئی)",
        low)
    if asked_send and generic_send_claim and not fresh_send_success():
        # An honest denial is allowed.
        if not re.search(r"\b(?:not|never|nahi|nahin|cannot|can't|unable)\b|"
                         r"(?:نہیں|نہ)", low):
            return email_lie

    if re.search(
            r"\b(?:files?|documents?|folders?)\b.{0,100}\b(?:deleted|removed|"
            r"hata\s+di(?:ye)?|delete\s+kar\s+di(?:ye)?|saaf\s+kar\s+di(?:ye)?)\b|"
            r"\b(?:hata\s+di(?:ye)?|delete\s+kar\s+di(?:ye)?)\b.{0,100}\b"
            r"(?:files?|documents?|folders?)\b|"
            r"(?:فائل|فائلیں|فائلوں|ڈاکومنٹ).{0,100}(?:حذف|ہٹا دی|ڈیلیٹ)|"
            r"(?:حذف|ہٹا دی|ڈیلیٹ).{0,100}(?:فائل|فائلیں|فائلوں|ڈاکومنٹ)",
            low, re.S):
        if not core.recent_tool_success(
                ("file_operation", "delete", "remove", "clean", "temp"), seconds=300):
            return (
                "ROMAN: Sir, I cannot confirm that any files were deleted. No successful "
                "delete is recorded, so I will not claim it. URDU: سر، میں فائلوں کے حذف "
                "ہونے کی تصدیق نہیں کر سکتا، اس لیے جھوٹ نہیں بولوں گا۔")

    if re.search(
            r"(?<!kya\s)\b(?:kaam\s+)?(?:kar\s+diya|ho\s+gaya)\b|"
            r"\b(?:task\s+complete(?:d)?|all\s+done|sab\s+ho\s+gaya)\b|"
            r"(?<!کیا\s)(?:کام\s+)?(?:کر\s+دیا|ہو\s+گیا)",
            low):
        if _looks_action_request(current) and not \
                _relevant_tool_success(current):
            return (
                "ROMAN: Sir, I cannot confirm that the task is complete. No tool reported "
                "success, so I will not claim it. URDU: سر، میں کام مکمل ہونے کی تصدیق "
                "نہیں کر سکتا، اس لیے جھوٹ نہیں بولوں گا۔")
    return text


def _spoken_text(text: str) -> str:
    """Keep the Roman/English line that is actually spoken, not the duplicate Urdu line.

    The original ``speak_reply`` receives 'ROMAN: ...\\nURDU: ...'.  Archiving the
    whole block duplicated every reply and could store mojibake Urdu; the Roman
    line is the spoken content in Roman Urdu / English mode.
    """
    text = text or ""
    m = re.search(r"ROMAN:\s*(.+)", text, re.I)
    if m:
        return m.group(1).strip()
    return re.sub(r"URDU:.*", "", text, flags=re.S | re.I).strip() or text


# --------------------------------------------------------------------------
# Context and command wrapping
# --------------------------------------------------------------------------
def _install_context(g: dict):
    orig = g.get("_with_context")
    if not orig or getattr(orig, "_jarvis_ultimate_context", False):
        return
    types_mod = g.get("types")

    def context_wrapper(msg):
        out = orig(msg)
        try:
            if isinstance(msg, list):
                text = " ".join(getattr(p, "text", "") or "" for p in msg)
            else:
                text = str(msg)
            extra = memory.context_for(text)
            hints = agent._skill_hint_block()
            block = "\n\n".join(x for x in (extra, hints) if x)
            if block and isinstance(out, list):
                # Prefix with the same marker the original compactor drops, so the
                # memory block is always fresh instead of piling up in history.
                prefix = g.get("CONTEXT_NOTE") or "[CONTEXT"
                block = f"{prefix} — long-term memory and available skills]\n{block}"
                part = types_mod.Part(text=block) if types_mod else None
                if part is not None:
                    return [out[0], part] + out[1:]
        except Exception as e:
            core.log(f"context wrapper failed: {e}")
        return out

    context_wrapper._jarvis_ultimate_context = True
    g["_with_context"] = context_wrapper


def _install_reply_capture(g: dict):
    orig = g.get("speak_reply")
    if not orig or getattr(orig, "_jarvis_ultimate_reply", False):
        return

    def speak_reply(text):
        guarded = _truth_guard(text)
        spoken = _spoken_text(guarded)
        try:
            _LAST_REPLY["text"] = spoken
            _LAST_REPLY["t"] = time.time()
        except Exception:
            pass
        try:
            memory.archive_assistant(mail.redact_secrets(spoken))
        except Exception:
            pass
        return orig(guarded)

    speak_reply._jarvis_ultimate_reply = True
    g["speak_reply"] = speak_reply


def _install_handle_wrapper(g: dict):
    orig = g.get("handle_command")
    if not orig or getattr(orig, "_jarvis_ultimate_handler", False):
        return

    def handle_command(user_input: str):
        # Never write an App Password into the permanent archive or learned facts.
        safe_input = mail.redact_secrets(user_input)
        _CURRENT_INPUT["text"] = user_input or ""
        # Journal the command first.  If the PC stops while it is running, the
        # next start can offer to finish it instead of silently forgetting.
        task_id = resume.begin(user_input)
        try:
            try:
                memory.archive_user(safe_input)
            except Exception:
                pass
            _LAST_REPLY["text"] = ""
            try:
                if command_hook(user_input, g):
                    return
            except Exception as e:
                core.log(f"command hook failed: {e}")
            return orig(user_input)
        except BaseException as e:
            resume.fail(task_id, e)
            raise
        finally:
            try:
                text = _LAST_REPLY["text"]
                if text and time.time() - _LAST_REPLY["t"] < 120:
                    memory.maybe_learn(safe_input, text)
            except Exception as e:
                core.log(f"learning hook failed: {e}")
            resume.complete(task_id)

    handle_command._jarvis_ultimate_handler = True
    g["handle_command"] = handle_command


def _install_run_wrapper(g: dict):
    orig = g.get("run_jarvis")
    if not orig or getattr(orig, "_jarvis_ultimate_run", False):
        return

    def run_jarvis():
        try:
            start_background(g)
        except Exception as e:
            core.log(f"background start failed: {e}")
        return orig()

    run_jarvis._jarvis_ultimate_run = True
    g["run_jarvis"] = run_jarvis


def _continue_after_tools(g: dict):
    """Ask the live chat for a final answer after a tool already ran.

    The original Jarvis raises ToolsRanError when a tool executed but the model then
    failed, so it cannot safely repeat the whole command.  The chat history already
    contains the function call and its result, so a short continuation is safe.
    """
    chat = g.get("chat")
    if chat is None:
        return None
    try:
        resp = chat.send_message(
            "Do not call any more tools. Using the tool results above, answer the user's "
            "original request clearly and briefly (1-4 sentences)."
        )
        text = (getattr(resp, "text", "") or "").strip()
        return resp if text else None
    except Exception as e:
        core.log(f"continuation after tools failed: {e}")
        return None


def _install_ask_wrapper(g: dict):
    orig = g.get("ask_gemini")
    err_cls = g.get("ToolsRanError")
    if not orig or err_cls is None or getattr(orig, "_jarvis_ultimate_ask", False):
        return

    def ask_gemini(user_input: str):
        try:
            return orig(user_input)
        except err_cls as e:
            code = None
            try:
                fn = g.get("_err_code")
                code = fn(e) if fn else None
            except Exception:
                code = None
            retryable = code in (None, 500, 502, 503, 504)
            try:
                net = g.get("_is_net_error")
                retryable = retryable or bool(net and net(e))
            except Exception:
                pass
            if retryable:
                cont = _continue_after_tools(g)
                if cont is not None:
                    core.log("Continued after a tool call instead of failing the command.")
                    return cont
            raise

    ask_gemini._jarvis_ultimate_ask = True
    g["ask_gemini"] = ask_gemini


def _install_client(g: dict):
    """Give the main chat a timeout that still fits the 5-10 second voice budget."""
    if g.get("_jarvis_ultimate_client"):
        return
    try:
        genai_mod = g.get("genai")
        types_mod = g.get("types")
        if genai_mod and types_mod:
            # 8 s: long enough for the 70+ tool schemas, short enough that a
            # dead request cannot make the user wait 30-47 seconds.
            g["client_fast"] = genai_mod.Client(http_options=types_mod.HttpOptions(timeout=15000))
            g["_jarvis_ultimate_client"] = True
            core.log("Chat client timeout set to 15s (tool calls need room; API minimum is 10s).")
    except Exception as e:
        core.log(f"could not set the chat timeout: {e}")


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------
def _install_preferences(g: dict):
    """Default to Brave and keep the permission (safe) mode in sync.

    The original ``PREFERRED_BROWSER`` was ``None``, so Windows could silently
    open Microsoft Edge.  Brave is now the default, while an explicit request
    for Chrome/Edge/Firefox still wins inside the original command parser.
    """
    try:
        raw = core.read_json(core.CONFIG_FILE, {}) or {}
        pref = str(raw.get("preferred_browser") or
                   core.CONFIG_DEFAULTS.get("preferred_browser") or "brave").lower().strip()
        if pref not in ("brave", "chrome", "edge", "firefox"):
            pref = "brave"
        g["PREFERRED_BROWSER"] = pref
        if raw.get("preferred_browser") != pref:
            core.save_config({"preferred_browser": pref})
        # Safe mode is on unless the user explicitly turned it off.  This makes
        # delete/move/send/shutdown ask for permission instead of acting silently.
        desired_safe = bool(raw.get("safe_mode", True))
        if core.safe_mode() != desired_safe:
            core.set_safe_mode(desired_safe)
    except Exception as e:
        core.log(f"preference install failed: {e}")


def install(g: dict) -> dict:
    """Wire the upgrade into the running jarvis.py module globals."""
    global _INSTALL_LOCK
    with _INSTALL_LOCK:
        core.bind(g)
        core.install_logging()
        _install_preferences(g)
        try:
            voice._install_mic_resolver(g)
        except Exception as e:
            core.log(f"mic resolver install failed: {e}")
        g["_jarvis_archive_say"] = memory.archive_assistant
        try:
            memory.ensure_archive()
        except Exception as e:
            core.log(f"archive init failed: {e}")
        _install_client(g)
        if g.get("_jarvis_ultimate_installed"):
            _install_context(g)
            return g

        # 1. Resolve PEP 563 string annotations so Gemini sees real types.
        resolved = []
        for fn in tools.TOOL_FUNCTIONS:
            try:
                fn.__annotations__ = typing.get_type_hints(fn)
            except Exception as e:
                core.log(f"type hints for {getattr(fn, '__name__', '?')}: {e}")
            resolved.append(fn)

        # 2. Append the tools using Jarvis's own wrapper (stop flag, game guard, errors).
        existing = {getattr(f, "__name__", "") for f in (g.get("TOOLS") or [])}
        wrap = g.get("_wrap_tool")
        added = []
        for fn in resolved:
            name = getattr(fn, "__name__", "")
            if not name or name in existing:
                continue
            g.setdefault("TOOLS", []).append(wrap(fn) if callable(wrap) else fn)
            existing.add(name)
            added.append(name)

        # 3. Extend the system prompt and neutralize the old "never ask" rule.
        base_prompt = g.get("SYSTEM_PROMPT") or ""
        base_prompt = base_prompt.replace(
            "Execute immediately and never ask for confirmation.",
            "Execute normal actions immediately. For destructive or irreversible actions, "
            "ask for permission first.")
        base_prompt = base_prompt.replace(
            "NEVER answer with instructions telling the user to do the remaining steps themselves: do ALL the "
            "steps with tools first and only then reply.",
            "Do ALL the steps with tools first and only then reply, except when a step genuinely needs the "
            "user's secret, permission or a missing account; in that case ask for exactly that one thing.")
        g["SYSTEM_PROMPT"] = base_prompt + "\n\n" + PROMPT_ADDENDUM

        # 4. Memory in every request, capture replies, learn after every command.
        _install_context(g)
        _install_reply_capture(g)
        _install_handle_wrapper(g)
        _install_run_wrapper(g)
        _install_ask_wrapper(g)

        # 5. Rebuild the live chat so it uses the new prompt and tools.
        try:
            model = g.get("active_model") or (g.get("MODEL_NAME") or "")
            smart = bool(g.get("chat_cfg", [False, False])[1])
            g["_rebuild_chat"](model, smart)
        except Exception as e:
            core.log(f"chat rebuild after install failed: {e}")

        g["_jarvis_ultimate_installed"] = True
        core.log(f"Ultimate upgrade installed: {len(added)} new tools.")
        try:
            names = ", ".join(added)
            print(f"[JARVIS ULTIMATE] Tools online ({len(added)}): {names}")
        except Exception:
            pass
    return g


# --------------------------------------------------------------------------
# Background services
# --------------------------------------------------------------------------
def start_background(g: dict) -> str:
    """Start the scheduler, the HUD and the mission watcher."""
    core.bind(g)
    messages = []
    try:
        agent.start_background()
        messages.append("scheduler")
    except Exception as e:
        core.log(f"scheduler start failed: {e}")
    try:
        if core.config_get("hud", True):
            hud.start_hud()
            messages.append("HUD")
    except Exception as e:
        core.log(f"HUD start failed: {e}")
    try:
        resume.schedule_startup_check(g)
        messages.append("resume")
    except Exception as e:
        core.log(f"resume startup check failed: {e}")
    try:
        memory.ensure_archive()
        mem = memory.overview()
        core.log("Memory online: " + (mem.splitlines()[0] if mem else "empty"))
        try:
            core.log(memory.backup_memory())
        except Exception as e:
            core.log(f"memory backup skipped: {e}")
    except Exception:
        pass
    print(f"[JARVIS ULTIMATE] Background services: {', '.join(messages) or 'none'}")
    return ", ".join(messages)


def after_command(user_input: str, reply: str = ""):
    """Optional explicit learning hook (the handler wrapper already does this)."""
    try:
        if reply:
            memory.maybe_learn(user_input, reply)
    except Exception as e:
        core.log(f"after_command failed: {e}")


# --------------------------------------------------------------------------
# Natural-language fast paths
# --------------------------------------------------------------------------
def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", (text or "").lower()))


def _remove_schedule_phrase(text: str) -> str:
    t = agent._extract_prompt(text)
    t = re.sub(r"^(?:please\s+)?(?:remind\s+me|mujhe\s+yaad\s+dila(?:na|o|dena)?|yaad\s+dila(?:na|o)?|"
               r"schedule|set\s+a\s+reminder|reminder)\b[,\s:]*", "", t, flags=re.I).strip(" ,:-")
    t = re.sub(r"^(?:to|ke\s+liye|k\s+liye|that)\b[,\s:]*", "", t, flags=re.I).strip(" ,:-")
    return t

def _cancel_legacy_question(g: dict):
    """Cancel an old spoken yes/no question from the original Jarvis.

    Without this, the startup question "shall I clean temporary files?" stayed
    alive and swallowed "Ha bhej do", running a temp cleanup instead of sending
    the email.  The question belongs to the previous topic and must die when the
    user starts a new one.
    """
    try:
        pending = g.get("pending")
        if isinstance(pending, dict):
            pending["data"] = None
        question = g.get("last_question")
        if isinstance(question, dict):
            question["text"] = ""
            question["t"] = 0.0
    except Exception as e:
        core.log(f"could not cancel old question: {e}")


def command_hook(user_input: str, g: dict | None = None) -> bool:
    """Instant commands that should never wait for Gemini. True = already handled."""
    g = g or core.G
    low = (user_input or "").lower().strip()
    words = _word_set(low)
    if not low:
        return False

    # The user has moved to email: cancel any old temp-cleanup / kill / search
    # question so its yes/no handler can never steal this command.
    emailish = False
    try:
        emailish = mail.looks_email_related(user_input)
    except Exception:
        pass
    if emailish:
        _cancel_legacy_question(g)
        try:
            resume.dismiss_prompt()
        except Exception:
            pass

    # A pure yes/no while the startup resume prompt is active belongs to that
    # prompt, because it may cover several tasks (email + mission + command).
    if not emailish and resume.prompt_active():
        try:
            if mail._is_yes(low) or mail._is_no(low):
                if resume.command_hook(user_input, g):
                    _cancel_legacy_question(g)
                    return True
        except Exception as e:
            core.log(f"resume command hook failed: {e}")

    # email: deterministic draft -> preview -> permission -> SMTP send.
    # This runs before the general resume hook so "send it again" can never be
    # treated as "resume old work" or be sent to the language model.
    try:
        if mail.command_hook(user_input, g):
            _cancel_legacy_question(g)
            try:
                resume.dismiss_prompt()
            except Exception:
                pass
            return True
    except Exception as e:
        core.log(f"email command hook failed: {e}")

    # unfinished work: manual "pending work" query or a new-command dismissal
    try:
        if resume.command_hook(user_input, g):
            _cancel_legacy_question(g)
            return True
    except Exception as e:
        core.log(f"resume command hook failed: {e}")

    # voice: phone microphone and natural conversation -------------------
    try:
        if voice.command_hook(user_input, g):
            return True
    except Exception as e:
        core.log(f"voice command hook failed: {e}")

    # permanent memory: explicit "never forget" -------------------------
    exact_m = re.match(
        r"^(?:please\s+)?(?:yaad\s+rakh(?:o|na|en|iye|ain)|yaad\s+rakhna|"
        r"mujhe\s+yaad\s+rakh(?:o|na)|yeh\s+baat\s+yaad\s+rakh(?:o|na)|"
        r"isay\s+yaad\s+rakh(?:o|na)|remember(?:\s+this)?|never\s+forget(?:\s+this)?|"
        r"note\s+this)[\s:,\-]+(.+)$",
        user_input, re.I | re.S)
    if exact_m:
        note = exact_m.group(1).strip()
        if note:
            memory.remember_exact(note, tags="explicit", importance=5)
            core.say_lang(
                "Pinned permanently, sir. That detail is now part of my permanent memory.",
                "Yaad rakh liya, sir. Woh baat ab meri permanent memory ka hissa hai.",
                "یاد رکھ لی، سر۔ وہ بات اب میری مستقل میموری کا حصہ ہے۔")
            return True

    # permanent memory: recall ------------------------------------------
    recall_q = ""
    m = re.match(r"^(?:what\s+do\s+you\s+remember(?:\s+about)?|do\s+you\s+remember(?:\s+about)?)"
                 r"\s*(.*)$", user_input, re.I)
    if m:
        recall_q = m.group(1).strip()
    if not m:
        m = re.match(r"^(?:tumhe(?:n)?\s+kya\s+yaad\s+hai|kya\s+yaad\s+hai\s+tumhe(?:n)?|"
                     r"yaad\s+hai\s+tumhe(?:n)?)\s*(.*)$", user_input, re.I)
        if m:
            recall_q = m.group(1).strip()
    if not m:
        m = re.match(r"^tumhe(?:n)?\s+(.+?)\s+ke\s+bare\s+mein?\s+kya\s+yaad\s+hai\s*$",
                     user_input, re.I)
        if m:
            recall_q = m.group(1).strip()
    if recall_q.startswith(("about ", "ke ", "ka ", "ki ")):
        recall_q = recall_q.split(" ", 1)[1].strip()
    if m or low in ("what do you remember", "tumhe kya yaad hai", "kya yaad hai tumhe"):
        text = memory.recall_all(recall_q, limit=10) if recall_q else memory.overview()
        core.say_lang(core.truncate(text, 1100), core.truncate(text, 1100),
                      core.truncate(text, 1100))
        return True

    # memory status ------------------------------------------------------
    if low in ("memory status", "memory stats", "memory report status", "yaad kitna hai",
               "memory kaisi hai", "memory kitni hai") or \
            ("memory" in words and words & {"status", "stats", "size"}):
        text = memory.memory_stats()
        core.say_lang(text, text, text)
        return True

    # Ultimate Reasoning Core -------------------------------------------
    if "brain status" in low or "reasoning core status" in low or "ultimate brain status" in low:
        text = brain.brain_operation("status")
        core.say_lang(text, text, text)
        return True

    brain_triggers = ("ultimate iq", "deep think", "think hard", "soch samajh", "soch ke batao",
                      "soch kar batao", "max reasoning", "deep reasoning", "ultimate brain",
                      "brain use karo", "dimagh lagao", "dimag lagao")
    if any(t in low for t in brain_triggers):
        q = user_input
        for t in brain_triggers:
            q = re.sub(re.escape(t), " ", q, flags=re.I)
        q = re.sub(r"^(?:please\s+)?(?:ke|that|about|to)\b[,\s:]*", "", q.strip(), flags=re.I)
        q = q.strip(" ,:-")
        if not q:
            q = user_input
        core.say_lang("Deep reasoning core engaged, sir. I am working through it.",
                      "Deep reasoning core on kar diya, sir. Main soch raha hoon.",
                      "ڈیپ ریزننگ کور آن کر دیا، سر۔ میں سوچ رہا ہوں۔")

        def _brain_job():
            try:
                answer = brain.think(q, "deep")
                md_path, html_path = core.save_report(
                    "Deep Reasoning - " + q[:70],
                    f"# Deep Reasoning\n\n**Question:** {q}\n\n{answer}",
                    open_it=False)
                core.say_async("Sir, my conclusion: " + core.truncate(answer, 900) +
                               f" Full reasoning saved to {html_path or md_path}.")
                memory.add_episode("Deep reasoning: " + core.truncate(q, 180),
                                   ["brain", "reasoning"], 3)
            except Exception as e:
                core.log(f"deep reasoning failed: {e}")
                core.say_async("Sir, the reasoning core failed: " + core.truncate(str(e), 180))

        core.run_bg(_brain_job)
        return True

    # HUD -----------------------------------------------------------------
    if words & {"hud", "overlay", "reactor"} or "arc reactor" in low:
        if words & {"off", "band", "hide", "chhupao", "close"}:
            core.say_lang("HUD hidden, sir.", "HUD chhupa diya hai, sir.", "HUD چھپا دیا ہے، سر۔")
            hud.hud_operation("hide")
            return True
        if words & {"on", "show", "dikhao", "kholo", "start", "chalao"}:
            hud.hud_operation("show")
            core.say_lang("HUD online, sir.", "HUD on hai, sir.", "HUD آن ہے، سر۔")
            return True
        if words & {"status", "haal"}:
            text = hud.hud_operation("status")
            core.say_lang(text, text, text)
            return True

    # safety mode ---------------------------------------------------------
    if "safe mode" in low or "safety mode" in low:
        if words & {"off", "band", "disable", "no"}:
            if "confirm" in low or "confirmed" in low:
                core.set_safe_mode(False)
                core.say_lang("Safety confirmations are off, sir. Be careful.",
                              "Safety confirmations band kar di hain, sir. Ehtiyat rakhein.",
                              "سیفٹی کنفرمیشنز بند کر دی ہیں، سر۔ احتیاط رکھیں۔")
            else:
                core.say_lang("This removes the confirmation step for destructive actions. "
                              "Say 'confirm safe mode off' if you are sure.",
                              "Yeh destructive actions ki confirmation hata dega. Agar yaqeen hai to "
                              "'confirm safe mode off' bolein.",
                              "یہ ڈسٹرکٹو اقدامات کی تصدیق ہٹا دے گا۔ اگر یقین ہے تو "
                              "'confirm safe mode off' کہیں۔")
            return True
        if words & {"on", "enable", "chalu"}:
            core.set_safe_mode(True)
            core.say_lang("Safety mode on, sir. Destructive actions will ask first.",
                          "Safety mode on hai, sir. Destructive kaam pehle poochenge.",
                          "سیفٹی موڈ آن ہے، سر۔ نقصان دہ کام پہلے پوچھیں گے۔")
            return True
        core.say_lang("Safety mode is " + ("on." if core.safe_mode() else "off."),
                      "Safety mode " + ("on hai." if core.safe_mode() else "off hai."),
                      "سیفٹی موڈ " + ("آن ہے۔" if core.safe_mode() else "بند ہے۔"))
        return True

    # schedule listing ----------------------------------------------------
    if words & {"schedule", "scheduled", "reminders", "reminder"} and words & {
            "list", "show", "dikhao", "kya", "what", "all", "sab"}:
        try:
            text = agent.schedule_operation("list")
        except Exception as e:
            text = f"Scheduler error: {e}"
        core.say_lang(text, text, text)
        return True

    # "what missions are running" ----------------------------------------
    if (words & {"mission", "missions", "kaam"}) and words & {"status", "list", "show", "kya", "running", "dikhao"}:
        text = agent.mission_operation("list")
        core.say_lang(text, text, text)
        return True

    # natural-language scheduling ----------------------------------------
    intent = bool(words & {"remind", "reminder", "yaad", "schedule", "scheduled", "alarm", "daily",
                           "roz", "har", "every", "task"})
    has_time = bool(re.search(
        r"\b(in|after)\s+\d+\s*(sec|second|seconds|min|minute|minutes|hour|hours|ghanta|ghante)\b|"
        r"\b(at|ko)\s+\d{1,2}(?::\d{2})?\s*(am|pm)?\b|"
        r"\b(daily|roz|every\s+day|har\s+roz|every\s+\d+)\b", low))
    if intent and has_time:
        parsed = agent.parse_schedule_text(user_input)
        if parsed:
            task = _remove_schedule_phrase(user_input)
            if task:
                job = agent.add_schedule(parsed["when"], task, kind=parsed.get("kind", "once"),
                                         time_str=parsed.get("time", ""),
                                         interval=parsed.get("interval", 0),
                                         label=parsed.get("label", ""))
                when_txt = time.strftime("%A at %I:%M %p", time.localtime(job["when"]))
                core.say_lang(f"Scheduled, sir. {parsed.get('label','')}, next run {when_txt}: {task}",
                              f"Schedule ho gaya, sir. {when_txt} par: {task}",
                              f"شیڈول ہو گیا، سر۔ {when_txt} پر: {task}")
                core.audit("schedule_operation", task, f"{job['id']} {parsed.get('label')}")
                return True

    # daily briefing ------------------------------------------------------
    if words & {"briefing", "brief"} or ("aaj" in words and words & {"khabar", "news", "update"}) \
            or ("morning" in words and words & {"report", "update", "briefing"}):
        core.say_lang("Preparing your briefing, sir.", "Aap ka briefing tayyar kar raha hoon, sir.",
                      "آپ کا بریفنگ تیار کر رہا ہوں، سر۔")

        def _job():
            try:
                integrations.daily_briefing()
            except Exception as e:
                core.log(f"briefing failed: {e}")
                core.say_async("Sir, the briefing failed: " + core.truncate(str(e), 160))
        core.run_bg(_job)
        return True

    # diagnostics ---------------------------------------------------------
    if (words & {"diagnostics", "diagnostic", "checkup"}) or \
            ("check" in words and words & {"system", "jarvis", "apna", "khud"}) or \
            ("test" in words and words & {"system", "jarvis", "apna"}):
        core.say_lang("Running a full diagnostic, sir.", "Poora diagnostic chala raha hoon, sir.",
                      "پورا ڈائگناسٹک چلا رہا ہوں، سر۔")

        def _diag():
            try:
                diagnostics.diagnostics_operation("full")
            except Exception as e:
                core.log(f"diagnostics failed: {e}")
        core.run_bg(_diag)
        return True

    # status --------------------------------------------------------------
    if low in ("ultimate status", "jarvis status", "full status", "system status",
               "status report", "jarvis ultimate status"):
        text = tools.ultimate_status()
        core.say_lang(text, text, text)
        return True

    # mission -------------------------------------------------------------
    m = re.match(r"^(?:start\s+)?mission[:\s]+(.+)$", user_input, re.I)
    if m:
        goal = m.group(1).strip()
        agent.start_mission(goal, background=True)
        return True

    return False


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------
__all__ = [
    "install", "start_background", "command_hook", "after_command", "PROMPT_ADDENDUM",
    "TOOLS", "__version__", "core", "memory", "research", "documents", "agent", "hud",
    "integrations", "diagnostics", "tools", "brain", "voice", "mail", "resume",
]

TOOLS = tools.TOOL_FUNCTIONS
