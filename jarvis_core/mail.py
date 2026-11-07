"""Reliable email commands with a mandatory preview and explicit permission.

The language model is good at writing prose but it used to "help" by opening
Gmail and claiming an email was sent.  This module makes the important path
deterministic:

    user asks to send email
        -> extract recipient and details
        -> write the draft
        -> show/speak the draft
        -> ask permission
        -> send through Gmail in Brave (or SMTP when configured) after a clear yes

The visible Gmail path is the default: Brave opens, the message is written in
Gmail's own compose window, and Send is pressed there.  SMTP remains available
when an account is configured.  Nothing is reported as sent unless Gmail or the
mail server confirms it.

Reading is deterministic too: "check my inbox" / "koi nayi email aayi hai?"
reads Gmail's list rows (never opening a message), summarises who sent what and
what needs action, and then marks those same unread emails read through Gmail's
own toolbar, as the user asked.  If Gmail is not signed in, the reply says
exactly that instead of inventing mail, and nothing is marked.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque

from . import core, gmail_web, integrations, memory

# A trailing full stop/comma/quote is allowed; a trailing letter/hyphen is not.
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?![\w\-])"
)
_PASSWORD_RE = re.compile(
    r"(?i)\b(?:app\s*password|password|pass)\b\s*(?:is|:|-)?\s*"
    r"((?:[A-Za-z0-9]{4}[\s-]+){3}[A-Za-z0-9]{4}|[A-Za-z0-9]{12,64})"
)

_EMAIL_WORDS = {"email", "mail", "e-mail", "gmail"}
_SEND_VERBS = {"send", "bhej", "bhejo", "bhejdo", "bhejna", "bhejni", "bhejain",
               "likh", "likho", "likhna", "compose", "draft", "write",
               "tell", "message", "inform", "contact"}
_READ_WORDS = {"inbox", "status", "configure", "configured", "setup", "read", "search",
               "check", "delete", "remove", "trash", "archive", "spam", "mark", "list",
               "count", "unread", "reply", "forward",
               # Attachments need a real file path; let the model/tool handle them
               # instead of drafting a nonsense body like "send file to".
               "file", "files", "document", "documents", "attachment", "attachments"}

_YES_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|haan|han|ha|haa|bilkul|ok|okay|theek|thik|ji|jee|"
    r"sure|zaroor|acha|accha|sahi|chalo)"
    r"(?:\s+(?:hai|hain))?"
    r"(?:\s+(?:please|plz|na|naa|yarr|yaar|yarrr|bhai|sir|zara|bas))*"
    r"[\s.!?]*$", re.I)

# Words that may surround a send-confirmation without changing its meaning.
# "send it again on Brave", "bhai dobara sab kuch karo na yarrr send it" and
# "ha bhej do" are all confirmations of the draft that is already waiting.
_AFFIRM_WORDS = {
    "yes", "yeah", "yep", "yup", "haan", "han", "ha", "haa", "bilkul", "ok",
    "okay", "theek", "thik", "ji", "jee", "sure", "zaroor", "acha", "accha",
    "sahi", "chalo",
}
_POLITE_WORDS = {
    "please", "plz", "na", "naa", "yarr", "yaar", "yarrr", "bhai", "sir",
    "zara", "bas", "hai", "hain", "to", "ko", "k", "ke", "ki", "ka", "liye",
    "ji", "jee",
}
_CONFIRM_FILLER = _AFFIRM_WORDS | _POLITE_WORDS | {
    "send", "bhej", "bhejo", "bhejdo", "bhejna", "bhejni", "bhejain",
    "bhejiye", "bhejdein", "bhejdena", "it", "this", "that", "email", "mail",
    "e-mail", "draft", "message", "again", "dobara", "phir", "fir", "now",
    "abhi", "foran", "jaldi", "on", "in", "from", "brave", "chrome", "edge",
    "firefox", "browser", "gmail", "kuch", "sab", "karo", "kar", "krna",
    "karna", "kardo", "do", "de", "dena", "dein", "dijiye", "ary", "arey",
    "at", "once", "right", "today", "aaj",
}
_CORE_SEND_RE = re.compile(r"^(?:send|bhej\w*)$", re.I)
_NEG_START_RE = re.compile(
    r"^\s*(?:no|nope|nahi|nahin|nai|na|naa|cancel|mat|ruko|ruk|chhodo|"
    r"chodo|rehne|rehna|stop|later|baad\s+mein|baad\s+me|abhi\s+nahi)\b",
    re.I)
_NEG_PHRASE_RE = re.compile(
    r"\b(?:cancel(?:\s+it)?|rehne\s+do|chhod\s+do|chhodo|"
    r"mat\s+(?:bhej\w*|send\w*|kar\w*)|"
    r"(?:nahi|nahin|nai)\s+(?:bhej\w*|send\w*|kar\w*)|"
    r"do\s+not\s+send|don'?t\s+send|not\s+now|no\s+need)\b", re.I)

_PENDING = {"stage": "", "draft": None, "text": "", "to": "", "created": 0.0,
            "restored": False, "maybe_sent": False, "deferred": False}
_SETUP = {"stage": "", "address": "", "created": 0.0}
_LOCK = threading.RLock()
_TTL = 24 * 3600             # a draft stays available for a day
_RESTORED_TTL = 24 * 3600    # a draft restored after a restart gets the same
_SETUP_TTL = 900.0
_PENDING_FILE = os.path.join(core.DATA_DIR, "pending_email.json")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w']+", (text or "").lower()))


def _active() -> bool:
    with _LOCK:
        if not _PENDING["stage"]:
            return False
        ttl = _RESTORED_TTL if _PENDING.get("restored") else _TTL
        if time.time() - float(_PENDING.get("created") or 0) > ttl:
            _reset()
            return False
        return True


def _active_setup() -> bool:
    with _LOCK:
        if not _SETUP["stage"]:
            return False
        if time.time() - float(_SETUP.get("created") or 0) > _SETUP_TTL:
            _reset_setup()
            return False
        return True


def _save_pending():
    """Write the waiting draft to disk so a shutdown cannot lose it."""
    with _LOCK:
        stage = _PENDING.get("stage")
        if not stage:
            try:
                os.remove(_PENDING_FILE)
            except OSError:
                pass
            return
        if stage not in ("draft", "to", "content", "sending", "resend_confirm"):
            return
        core.write_json(_PENDING_FILE, {
            "stage": stage,
            "draft": _PENDING.get("draft"),
            "text": _PENDING.get("text", ""),
            "to": _PENDING.get("to", ""),
            "created": _PENDING.get("created") or time.time(),
            "restored": bool(_PENDING.get("restored")),
            "maybe_sent": bool(_PENDING.get("maybe_sent")),
            "deferred": bool(_PENDING.get("deferred")),
        })


def _clear_memory():
    with _LOCK:
        _PENDING.update({"stage": "", "draft": None, "text": "", "to": "",
                         "created": 0.0, "restored": False, "maybe_sent": False,
                         "deferred": False})


def _reset():
    _clear_memory()
    try:
        os.remove(_PENDING_FILE)
    except OSError:
        pass


def restore_pending(include_deferred: bool = False):
    """Load a draft saved by a previous session.  Returns the state or None.

    ``include_deferred`` is used by the manual "pending work" command; the
    automatic startup prompt leaves a draft alone after the user said no.
    """
    data = core.read_json(_PENDING_FILE, {})
    if not isinstance(data, dict):
        return None
    if data.get("deferred") and not include_deferred:
        return None
    stage = str(data.get("stage") or "")
    if stage not in ("draft", "to", "content", "sending", "resend_confirm"):
        return None
    created = float(data.get("created") or 0)
    if created and time.time() - created > _RESTORED_TTL:
        try:
            os.remove(_PENDING_FILE)
        except OSError:
            pass
        return None
    draft = data.get("draft") if isinstance(data.get("draft"), dict) else None
    if stage in ("draft", "sending", "resend_confirm") and not draft:
        return None
    with _LOCK:
        _PENDING.update({
            "stage": stage,
            "draft": draft,
            "text": str(data.get("text") or ""),
            "to": str(data.get("to") or ""),
            "created": time.time(),
            "restored": True,
            "maybe_sent": bool(data.get("maybe_sent")) or stage == "sending",
            "deferred": False,
        })
    _save_pending()
    return dict(_PENDING)


def defer_pending():
    """Keep the on-disk draft but stop it intercepting unrelated commands.

    The draft is marked ``deferred`` so the next automatic startup does not ask
    about it again.  Saying "pending work" still brings it back.
    """
    with _LOCK:
        stage = _PENDING.get("stage")
        if stage:
            core.write_json(_PENDING_FILE, {
                "stage": stage,
                "draft": _PENDING.get("draft"),
                "text": _PENDING.get("text", ""),
                "to": _PENDING.get("to", ""),
                "created": _PENDING.get("created") or time.time(),
                "restored": True,
                "maybe_sent": bool(_PENDING.get("maybe_sent")),
                "deferred": True,
            })
        else:
            data = core.read_json(_PENDING_FILE, {})
            if isinstance(data, dict) and data:
                data["deferred"] = True
                core.write_json(_PENDING_FILE, data)
    _clear_memory()


def cancel_pending() -> bool:
    """Discard a restored draft after the user says no."""
    had = bool(_PENDING.get("stage")) or os.path.exists(_PENDING_FILE)
    if not had:
        return False
    _reset()
    core.say_lang("Cancelled, sir. The saved email draft was discarded.",
                  "Cancel kar diya, sir. Saved email draft discard ho gaya.",
                  "منسوخ کر دیا، سر۔ محفوظ ای میل ڈرافٹ خارج کر دیا گیا۔")
    return True


def _reset_setup():
    with _LOCK:
        _SETUP.update({"stage": "", "address": "", "created": 0.0})


def _legacy_question_is_newer(g: dict) -> bool:
    """True if the original Jarvis asked a newer yes/no question than the draft.

    In that case a bare "haan" answers the newer question (cleanup, kill, ...),
    not the older email draft.
    """
    try:
        question = (g or {}).get("last_question") or {}
        asked = float(question.get("t") or 0)
        created = float(_PENDING.get("created") or 0)
        return bool(question.get("text")) and asked > created + 1.0
    except Exception:
        return False


def _set_pending(stage: str, text: str = "", to: str = "", draft: dict | None = None):
    with _LOCK:
        _PENDING.update({"stage": stage, "draft": draft, "text": text,
                         "to": to, "created": time.time(),
                         "restored": False, "maybe_sent": False, "deferred": False})
    _save_pending()


def _extract_password(text: str) -> str:
    m = _PASSWORD_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"[\s-]+", "", m.group(1))


def _looks_like_password(text: str) -> str:
    """Accept a bare 16-character App Password typed by itself."""
    t = _plain(text).strip()
    if re.fullmatch(r"[A-Za-z0-9]{12,64}", t):
        return t
    if re.fullmatch(r"(?:[A-Za-z0-9]{4}[\s-]+){3}[A-Za-z0-9]{4}", t):
        return re.sub(r"[\s-]+", "", t)
    return ""


def redact_secrets(text: str) -> str:
    """Keep App Passwords out of the permanent archive and learned facts."""
    if not text:
        return text
    # While the setup wizard is waiting for the password, the whole message is
    # the secret (the user may type only the 16 characters).
    if _active_setup() and _SETUP.get("stage") == "password":
        return "[REDACTED APP PASSWORD]"
    low = text.lower()
    if not ("password" in low or " pass" in low):
        return text
    if not any(w in low for w in ("email", "mail", "gmail", "smtp", "configure",
                                  "login", "app password")):
        return text
    return _PASSWORD_RE.sub(
        lambda m: m.group(0).replace(m.group(1), "[REDACTED APP PASSWORD]"), text)


def _is_yes(low: str) -> bool:
    """A pure yes, never a send command.

    Send confirmations are handled by ``_is_send_confirmation`` so a startup
    resume prompt cannot mistake "send it again" for "resume all old work".
    """
    text = _plain(low).lower()
    if not text or _is_no(text):
        return False
    if _YES_RE.match(text):
        return True
    words = re.findall(r"[\w']+", text)
    if not words or words[0] not in _AFFIRM_WORDS:
        return False
    rest = [w for w in words[1:] if w not in _POLITE_WORDS and w not in {"hai", "hain"}]
    return not rest


def _is_no(low: str) -> bool:
    """Context-aware no.

    The old version treated any "na" anywhere as a refusal, so
    "bhai dobara sab kuch karo na yarrr send it" cancelled the draft.  A
    negative now has to be at the start or form a real negative phrase.
    """
    text = _plain(low).lower().strip()
    if not text:
        return False
    if _NEG_START_RE.match(text) or _NEG_PHRASE_RE.search(text):
        return True
    return text.strip(" .!?,") in {"na", "naa", "nah", "nope"}


def _is_send_confirmation(text: str) -> bool:
    """True for a command that only confirms sending the waiting draft.

    It deliberately rejects anything with a new email address or extra
    substantive words, so "send it to ali@example.com about the meeting" is a
    new request, not a confirmation.
    """
    low = _plain(text).lower()
    if not low or _is_no(low):
        return False
    if _EMAIL_RE.search(low):
        return False
    words = re.findall(r"[\w']+", low)
    if not words:
        return False
    if not any(_CORE_SEND_RE.match(w) for w in words):
        return False
    return all(w in _CONFIRM_FILLER for w in words)


_FUTURE_WORDS = {
    "tomorrow", "kal", "later", "baad", "after", "baje", "pm", "am",
    "morning", "evening", "night", "subah", "shaam", "raat", "schedule",
    "scheduled", "tonight",
}
_FUTURE_REMOVERS = (
    r"\b(?:tomorrow|tonight|kal|later|baad\s+mein|baad\s+me|"
    r"after|schedule[ds]?)\b",
    r"\b(?:at|ko)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|baje)?\b",
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|baje)\b",
    r"\bin\s+\d+\s*(?:sec(?:ond)?s?|min(?:ute)?s?|hours?|ghant[ae])\b",
    r"\b(?:morning|evening|night|subah|shaam|raat)\b",
)
_FUTURE_ALLOWED = _CONFIRM_FILLER | _POLITE_WORDS | _AFFIRM_WORDS | {
    "the", "a", "an", "and", "aur", "but", "lekin", "magar", "then",
    "also", "bhi", "tomorrow", "tonight", "kal", "later",
    "baad", "after", "schedule", "scheduled", "morning", "evening", "night",
    "subah", "shaam", "raat", "am", "pm", "baje", "ko", "minutes", "minute",
    "min", "mins", "hours", "hour", "ghanta", "ghante", "seconds", "second",
    "sec",
}


def _is_future_send(text: str) -> bool:
    """True for a short scheduled-send command, not for email content.

    "send it tomorrow" / "kal bhej do" / "send it at 8 pm" are scheduling
    commands.  "send email to ali@example.com about leaving tomorrow at 8 AM"
    is a normal email request: after the time words are removed, "about" and
    "leaving" remain, so it is not treated as scheduling.
    """
    low = _plain(text).lower()
    if not low:
        return False
    if re.search(r"\b(?:at\s+once|right\s+now|abhi|foran)\b", low):
        return False
    words = _words(low)
    if not any(_CORE_SEND_RE.match(w) for w in words):
        return False
    has_time = bool(words & _FUTURE_WORDS) or bool(re.search(
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|baje)\b|"
        r"\b(?:at|ko)\s+\d{1,2}(?::\d{2})?\b|"
        r"\bin\s+\d+\s*(?:sec(?:ond)?s?|min(?:ute)?s?|hours?|ghant[ae])\b",
        low))
    if not has_time:
        return False

    rest = low
    for pattern in _FUTURE_REMOVERS:
        rest = re.sub(pattern, " ", rest, flags=re.I)
    rest = _EMAIL_RE.sub(" ", rest)
    rest_words = {w for w in re.findall(r"[\w']+", rest) if not w.isdigit()}
    return not (rest_words - _FUTURE_ALLOWED)


def _future_send_reply(has_draft: bool = True):
    if has_draft:
        core.say_lang(
            "Sir, I can send the waiting draft now, but I cannot schedule email "
            "from this fast path yet. The draft is still saved. Say 'send it' to "
            "send now, or 'cancel' to discard it.",
            "Sir, main waiting draft abhi bhej sakta hoon, lekin is fast path se "
            "email schedule nahi kar sakta. Draft save hai. Abhi bhejne ke liye "
            "'send it' bolein, ya 'cancel' karein.",
            "سر، میں منتظر ڈرافٹ ابھی بھیج سکتا ہوں، لیکن اس فاسٹ پاتھ سے ای میل "
            "شیڈول نہیں کر سکتا۔ ڈرافٹ محفوظ ہے۔ ابھی بھیجنے کے لیے 'send it' "
            "کہیں، یا 'cancel' کریں۔")
        return
    core.say_lang(
        "Sir, scheduled email is not supported from this fast path yet. Tell me "
        "the recipient and message to prepare a draft now; then say 'send it' "
        "when you want it sent.",
        "Sir, is fast path se scheduled email support nahi hai. Recipient aur "
        "message bolein taake main abhi draft tayyar karoon; phir jab bhejna ho "
        "'send it' bolein.",
        "سر، اس فاسٹ پاتھ سے شیڈول ای میل کی سہولت نہیں ہے۔ وصول کنندہ اور پیغام "
        "بتائیں تاکہ میں ابھی ڈرافٹ تیار کروں؛ پھر جب بھیجنا ہو 'send it' کہیں۔")


def looks_email_related(text: str) -> bool:
    """Used by the hook layer to cancel a stale spoken question."""
    words = _words(text)
    if words & _EMAIL_WORDS or _EMAIL_RE.search(text or "") \
            or _is_send_confirmation(text):
        return True
    try:
        if _active() and (_is_draft_question(text) or _draft_edit(text) is not None):
            return True
    except Exception:
        pass
    return False


def _is_send_request(text: str) -> bool:
    if _is_email_question(text):
        return False
    words = _words(text)
    has_email_word = bool(words & _EMAIL_WORDS)
    has_address = bool(_EMAIL_RE.search(text))
    if not (has_email_word or has_address):
        return False
    if words & _READ_WORDS:
        return False
    # "Gmail band karo" / "Gmail kholo" are browser commands, not a request to
    # write and send a message.  A real send verb keeps the request alive even
    # if the sentence also mentions opening Brave.
    if (words & {"band", "close", "kholo", "khol", "open", "tab", "window"}
            and not words & _SEND_VERBS):
        return False
    if words & _SEND_VERBS:
        return True
    # "email ali@example.com" / "write to ali@example.com"
    if has_address and has_email_word:
        return True
    # "email karo" / "mail kar do" (but not "email status")
    return bool(has_email_word and words & {"karo", "kar", "kardo", "karden"})


def _is_status_request(text: str) -> bool:
    words = _words(text)
    if not (words & _EMAIL_WORDS):
        return False
    if words & {"send", "bhej", "bhejo", "inbox", "read", "search"}:
        return False
    if words & {"status", "configured", "ready"}:
        return True
    # "kya email configure hai?" is a status question, not a setup command.
    plain = _plain(text).lower()
    return bool(words & {"configure", "configuration", "setup"}
                and (plain.endswith("?") or words & {"kya", "kia", "hai", "hain"}))


def _is_gmail_close_request(text: str) -> bool:
    """True for "Gmail band karo" / "close Gmail", not a send command."""
    words = _words(text)
    if not (words & _EMAIL_WORDS):
        return False
    if words & _SEND_VERBS:
        return False
    return bool(words & {"band", "close", "off", "shutdown", "exit"})


def _close_gmail() -> bool:
    if _PENDING.get("stage") in ("draft", "resend_confirm", "sending"):
        tail = (" The email draft is still saved; say 'send it' when you want "
                "me to reopen Gmail and send it.")
        tail_rm = (" Email draft abhi bhi saved hai; jab bhejna ho 'send it' "
                   "bolein, main Gmail dobara khol kar bhej doonga.")
    else:
        tail = ""
        tail_rm = ""
    try:
        result = gmail_web.close_gmail()
    except Exception as e:
        result = f"I could not close the Gmail tab: {e}"
    core.say_lang(result + tail, result + tail_rm, result + tail)
    return True


_INBOX_PATTERNS = (
    r"\binbox\b",
    r"\bunread\b",
    r"\b(?:new|latest|recent)\s+(?:e-?mails?|mails?)\b",
    r"\b(?:nayi|nayee|naya|naye|nawin)\s+(?:e-?mail|mail)\b",
    r"\b(?:e-?mail|mail)\s+(?:check|dekho|dekhein|dekh\s+lo|parho|padho|batao|bata\s+do)\b",
    r"\b(?:check|read|scan|dekho|dekhein)\s+(?:my\s+|meri\s+|mera\s+)?(?:e-?mails?|mails?|gmail|inbox)\b",
    r"\b(?:e-?mail|mail)\s+(?:aayi|aai|aya|aaya|aayin|aain)\b",
    r"\bwhat(?:'s|s|\s+is)\s+(?:in\s+)?(?:my\s+)?(?:inbox|gmail|mail)\b",
    r"\b(?:koi\s+)?(?:nayi|nayee|new)\s+(?:e-?mail|mail)\b.*\b(?:batao|tell|about|bare|baare|kya)\b",
)

# Verbs that mean "write and send", not "read".  "tell"/"message"/"inform"
# stay out so "new email ... tell me what it is about" is still a read request.
_SEND_ONLY = _SEND_VERBS - {"tell", "message", "inform", "contact"}


def _is_inbox_request(text: str) -> bool:
    """True for "check my inbox" / "koi nayi email aayi hai?", not "send email"."""
    words = _words(text)
    if not (words & (_EMAIL_WORDS | {"inbox", "unread"})):
        return False
    if words & _SEND_ONLY:
        return False
    if _is_gmail_close_request(text):
        return False
    low = _plain(text).lower()
    return any(re.search(pattern, low) for pattern in _INBOX_PATTERNS)


def _summarize_inbox(msgs: list, unread_only: bool) -> dict:
    """Turn inbox rows into a short spoken summary in all three languages."""
    count = len(msgs)
    first = msgs[0] if msgs else {}
    sender0 = first.get("sender") or "unknown sender"
    subject0 = first.get("subject") or "(no subject)"
    snippet0 = core.truncate(first.get("snippet") or "", 160)
    fallback = {
        "en": (f"Sir, {count} email{'s are' if count != 1 else ' is'} showing. "
               f"The newest is from {sender0}, about '{subject0}'. {snippet0}").strip(),
        "roman": (f"Sir, {count} email hain. Sab se nayi {sender0} ki hai, "
                  f"'{subject0}' ke bare mein. {snippet0}").strip(),
        "urdu": (f"سر، {count} ای میل ہیں۔ سب سے نئی {sender0} کی ہے، "
                 f"'{subject0}' کے بارے میں۔"),
    }
    if not msgs:
        return fallback
    lines = []
    for i, m in enumerate(msgs[:6], 1):
        lines.append(
            f"{i}. From: {core.truncate(m.get('sender') or 'unknown', 60)}"
            f" | Subject: {core.truncate(m.get('subject') or '(none)', 120)}"
            f" | Unread: {'yes' if m.get('unread') else 'no'}"
            f" | Preview: {core.truncate(m.get('snippet') or '', 220)}")
    prompt = (
        "Report the user's Gmail inbox using ONLY these emails. In 2-4 short spoken "
        "sentences: say how many emails there are, then the gist of the most "
        "important 1-3 (who sent it and what it is about), and clearly mention "
        "anything that needs action (verification, payment, deadline). Never invent "
        "senders, amounts, links, subjects or dates. If a preview is unclear, say "
        "that email needs to be opened instead of guessing.\n\n"
        f"Unread only: {'yes' if unread_only else 'no'}\n"
        + "\n".join(lines)
        + '\n\nReturn ONLY JSON: {"en": "English", '
          '"roman": "Roman Urdu as spoken in Pakistan", "urdu": "Urdu script"}'
    )
    data = core.llm_json(
        prompt,
        system="You report email facts accurately and never invent details.",
        smart=False, fallback={}, max_tokens=900)
    out = dict(fallback)
    if isinstance(data, dict):
        for key in ("en", "roman", "urdu"):
            val = str(data.get(key) or "").strip()
            if val:
                out[key] = val
    return out


def _check_inbox(text: str) -> bool:
    """Read Gmail in Brave and summarise the newest mail honestly."""
    words = _words(text)
    unread_only = bool(words & {"unread", "new", "nayi", "nayee", "naya", "naye",
                                "latest", "recent"})
    core.say_lang(
        "Reading your Gmail now, sir.",
        "Sir, Gmail padh raha hoon.",
        "سر، جی میل پڑھ رہا ہوں۔")
    try:
        data = gmail_web.read_inbox(limit=8, unread_only=unread_only)
    except Exception as e:
        detail = core.truncate(str(e), 200)
        core.say_lang(
            "Sir, I could not read your Gmail inbox: " + detail + " Nothing was changed.",
            "Sir, main aapka Gmail inbox nahi padh saka: " + detail + " Kuch change nahi kiya.",
            "سر، میں آپ کا جی میل ان باکس نہیں پڑھ سکا۔ کچھ تبدیل نہیں کیا۔")
        return True

    if not data.get("ok"):
        detail = core.truncate(str(data.get("message") or "I could not read Gmail."), 300)
        core.say_lang(
            "Sir, I could not read your Gmail inbox. " + detail,
            "Sir, main aapka Gmail inbox nahi padh saka. " + detail,
            "سر، میں آپ کا جی میل ان باکس نہیں پڑھ سکا۔ " + detail)
        return True

    msgs = data.get("messages") or []
    if not msgs:
        if unread_only:
            core.say_lang(
                "Sir, there are no unread emails in your Gmail inbox right now.",
                "Sir, abhi aapke Gmail inbox mein koi unread email nahi hai.",
                "سر، ابھی آپ کے جی میل ان باکس میں کوئی نہ پڑھی گئی ای میل نہیں ہے۔")
        else:
            core.say_lang(
                "Sir, your Gmail inbox has no messages to show right now.",
                "Sir, abhi aapke Gmail inbox mein dikhane ke liye koi email nahi hai.",
                "سر، ابھی آپ کے جی میل ان باکس میں دکھانے کے لیے کوئی ای میل نہیں ہے۔")
        return True

    print("\n[Gmail inbox]")
    for i, m in enumerate(msgs, 1):
        print(f"{i}. {m.get('sender', '')} — {m.get('subject', '')} [{m.get('date', '')}]")
        print(f"   {m.get('snippet', '')}")
    print()

    summary = _summarize_inbox(msgs, unread_only)
    core.say_lang(summary["en"], summary["roman"], summary["urdu"])

    # The user asked for the mail they were just told about to end up read.
    targets = [m for m in msgs if m.get("unread")]
    if not targets:
        return True
    try:
        result = gmail_web.mark_inbox_read(messages=targets,
                                           url=data.get("url") or "")
    except Exception as e:
        result = {"ok": False, "marked": 0,
                  "message": core.truncate(str(e), 160)}
    print(f"[Gmail] mark read: {result}")
    if result.get("ok"):
        marked = int(result.get("marked") or 0)
        if marked:
            core.say_lang(
                f"I have marked {marked} email{'s' if marked != 1 else ''} as read, sir.",
                (f"Sir, {marked} email read mark kar diya hai." if marked == 1
                 else f"Sir, {marked} emails read mark kar diye hain."),
                "سر، میں نے وہ ای میل پڑھی ہوئی نشان زد کر دی ہیں۔")
    else:
        core.say_lang(
            "I told you about them, sir, but Gmail did not confirm that they "
            "were marked as read. They may still be unread.",
            "Sir, un ke bare mein bata diya, lekin Gmail ne unhe read mark karne "
            "ki tasdeeq nahi ki. Woh ab bhi unread ho sakti hain.",
            "سر، میں نے ان کے بارے میں بتا دیا، لیکن جی میل نے پڑھا ہوا نشان زد "
            "کرنے کی تصدیق نہیں کی۔ وہ اب بھی غیر پڑھی ہو سکتی ہیں۔")
    return True


_QUESTION_START_RE = re.compile(
    r"^\s*(?:did|do|does|have|has|had|was|were|is|are|can|could|would|will|"
    r"kya|kia|kyaa|tumne|tum\s+ne|aap\s+ne|kab|when|where|kaun|who)\b", re.I)


def _is_email_question(text: str) -> bool:
    """A status/capability question about email, not a request to send one.

    "did you send the email?" and "kya email bhej di?" must not create a new
    draft, while "can you send an email to ali@example.com about the meeting?"
    is a real request and must still be prepared.
    """
    words = _words(text)
    if not (words & _EMAIL_WORDS):
        return False
    # "email bhej do?" is a send instruction with a question mark, not a
    # status question.  A clear confirmation always wins.
    if _is_send_confirmation(text):
        return False
    plain = _plain(text)
    low = plain.lower()
    has_address = bool(_EMAIL_RE.search(plain))
    past = bool(words & {"sent", "bheja", "bheji", "bhej", "gayi", "gaya",
                         "hua", "hui", "kiya", "ki"})
    first = (re.findall(r"[a-z]+", low) or [""])[0]

    if first in {"did", "have", "has", "had", "was", "were"}:
        return True
    if first in {"kya", "kia", "kyaa", "tumne", "aap"}:
        return past or not has_address
    if first in {"can", "could", "would", "will"}:
        return not has_address
    if first in {"do", "does", "is", "are"}:
        return not has_address
    if plain.endswith("?") and words & {"kab", "when", "what", "which",
                                        "kaun", "who"}:
        return True
    return bool(plain.endswith("?") and past)


_QUESTION_WORDS = {
    "kya", "kia", "kyaa", "did", "do", "does", "have", "has", "had", "was",
    "were", "is", "are", "can", "could", "would", "will", "kab", "when",
    "what", "which", "kaun", "who", "kitna", "kitni",
}
_DRAFT_WORDS = {
    "draft", "subject", "topic", "body", "message", "text", "content",
    "recipient", "address", "email", "mail", "it", "isko", "ise", "yeh", "ye",
    "send", "bhej", "bhejo", "bhejna", "bhejni", "bhejoge", "bhejogi",
    "bhejega", "likha", "likhi",
}
_NO_DRAFT_WORDS = {
    "draft", "subject", "topic", "body", "message", "text", "content",
    "recipient", "address", "email", "mail", "send", "bhej", "bhejo",
    "bhejna", "bhejni", "bhejoge", "bhejogi", "bhejega", "sent", "bheja",
    "bheji",
}
_EDIT_VERBS = {
    "change", "badlo", "badal", "update", "set", "rakho", "rakh", "make",
    "edit", "modify", "replace", "add", "append", "insert", "daal", "dal",
    "likho", "likh", "remove", "hata", "hatao",
}
_RECIPIENT_WORDS = {"recipient", "address", "kisko", "jisko", "badlo", "badal"}

_SUBJECT_EDIT_RE = re.compile(
    r"(?:change|badlo|badal|update|set|rakho|rakh|make|edit|modify|replace)"
    r"\s+(?:the\s+)?(?:email\s+)?(?:subject|topic)"
    r"\s*(?:to|:|is|should\s+be|-)?\s*(.+)$", re.I)
_SUBJECT_EDIT_MID_RE = re.compile(
    r"(?:email\s+)?(?:subject|topic)\s+(?:change|badlo|badal|update|set)"
    r"\s*(?:karo|kar\s*do|kardo|kar)?\s*(?:to|:)?\s*(.+)$", re.I)
_SUBJECT_EDIT_REV_RE = re.compile(
    r"(?:email\s+)?(?:subject|topic)\s*(?:ko\s+)?(.+?)\s+"
    r"(?:kar\s*do|kardo|karo|kar|badlo|badal\s*do|rakho|set\s*karo|"
    r"change\s*karo)$", re.I)
_SUBJECT_COLON_RE = re.compile(
    r"^(?:email\s+)?(?:subject|topic)\s*[:\-]\s*(.+)$", re.I)
_BODY_EDIT_RE = re.compile(
    r"(?:change|badlo|badal|update|set|replace|edit|modify)"
    r"\s+(?:the\s+)?(?:email\s+)?(?:body|message|text|content)"
    r"\s*(?:to|:|is|should\s+be|-)?\s*(.+)$", re.I)
_BODY_EDIT_REV_RE = re.compile(
    r"(?:body|message|text|content)\s+(?:change|badlo|badal|update|set|replace)"
    r"\s*(?:karo|kar\s*do|kardo|kar)?\s*(?:to|:)?\s*(.+)$", re.I)
_BODY_ADD_RE = re.compile(
    r"(?:add|append|insert|daal\s*do|dal\s*do|likh\s*do|likho)"
    r"\s+(.+?)\s+(?:to|in|into|mein|me)\s+(?:the\s+)?(?:body|message|email)$",
    re.I)
_BODY_ADD_REV_RE = re.compile(
    r"(?:body|message|email)\s+(?:mein|me|in)\s+(.+?)\s+"
    r"(?:add|append|insert|daal|dal|likh)\s*(?:karo|kar\s*do|kardo|do)?$",
    re.I)
# "change subject to Meeting and send it" edits first; the trailing send
# instruction must not become part of the new subject/body.
_EDIT_SEND_SUFFIX_RE = re.compile(
    r"(?i)\s*(?:,|;|\band\b|\baur\b|\bphir\b|\bfir\b|\bthen\b)\s*"
    r"(?:please\s+|plz\s+)?"
    r"(?:send\s*kar\s*do"
    r"|send(?:\s+(?:it|this|that|the\s+email|the\s+mail))?"
    r"|bhej\s*(?:do|dein|dena|dijiye|naa?))\s*[.!?]*$")


def _clean_edit_value(value: str, limit: int = 160) -> str:
    v = _EMAIL_RE.sub(" ", value or "")
    v = _plain(v).strip(" .,:;-\"'“”")
    v = re.sub(r"(?i)\s+(?:please|plz|na|naa|yarr|yaar|bhai|sir)$", "", v).strip()
    return v[:limit]


def _draft_edit(text: str) -> dict | None:
    """Apply an edit to the waiting draft and return the updated draft.

    Handles "change subject to Meeting", "subject Meeting kar do",
    "body mein ... add karo" and "send it to new@example.com" (recipient
    change).  Returns None when the message is not an edit.
    """
    draft = dict(_PENDING.get("draft") or {})
    if not draft:
        return None
    plain = _plain(text)
    plain = _EDIT_SEND_SUFFIX_RE.sub(" ", plain).strip()
    changed = False

    for regex in (_SUBJECT_EDIT_RE, _SUBJECT_EDIT_MID_RE,
                  _SUBJECT_EDIT_REV_RE, _SUBJECT_COLON_RE):
        m = regex.search(plain)
        if m:
            value = _clean_edit_value(m.group(1), 160)
            if value:
                draft["subject"] = value
                changed = True
            break

    m = _BODY_EDIT_RE.search(plain) or _BODY_EDIT_REV_RE.search(plain)
    if m:
        value = _clean_edit_value(m.group(1), 12000)
        if value:
            draft["body"] = value
            changed = True
    else:
        m = _BODY_ADD_RE.search(plain) or _BODY_ADD_REV_RE.search(plain)
        if m:
            value = _clean_edit_value(m.group(1), 4000)
            if value:
                draft["body"] = (str(draft.get("body") or "").rstrip()
                                 + "\n\n" + value).strip()
                changed = True

    addresses = _EMAIL_RE.findall(plain)
    if addresses:
        words = _words(plain)
        has_email_word = bool(words & _EMAIL_WORDS)
        has_send_verb = any(_CORE_SEND_RE.match(w) for w in words)
        leftover = _EMAIL_RE.sub(" ", plain)
        leftover_words = set(re.findall(r"[\w']+", leftover.lower()))
        # Extra content words mean this is a new email request, not a bare
        # recipient edit.  "send it to ali@example.com about the party" must
        # keep "about the party" instead of silently sending the old body.
        content_words = leftover_words - (_CONFIRM_FILLER | _EDIT_VERBS
                                          | _RECIPIENT_WORDS)
        # A bare "send it to ali@..." or "change recipient to ali@..." changes
        # the recipient.  "send email to ali@... about the party" keeps the
        # word "email" and is treated as a new draft, not a bare edit.
        if not content_words and (
                words & _RECIPIENT_WORDS or words & _EDIT_VERBS
                or (has_send_verb and not has_email_word)):
            draft["to"] = addresses[0]
            changed = True

    return draft if changed else None


def _is_draft_question(text: str) -> bool:
    """A question about the waiting draft, even without the word "email"."""
    plain = _plain(text)
    if not plain:
        return False
    # A full request such as "can you send email to ali@example.com about the
    # meeting" is a draft request, not a question about an existing draft.
    if _EMAIL_RE.search(plain) and _is_send_request(text):
        return False
    low = plain.lower()
    if _is_send_confirmation(text) or _is_yes(low) or _is_no(low):
        return False
    words = _words(text)
    if not (words & _DRAFT_WORDS):
        return False
    first = (re.findall(r"[a-z]+", low) or [""])[0]
    question = (plain.endswith("?") or first in _QUESTION_WORDS
                or bool(words & {"kya", "kia", "kyaa", "what", "which"}))
    if not question:
        return False
    if _active() and _PENDING.get("draft"):
        return True
    # Without a draft, vague words like "it" must not hijack a generic
    # question such as "what is it?".  Only a real email/draft word counts.
    return bool(words & _NO_DRAFT_WORDS)


def _answer_draft_question(text: str):
    draft = _PENDING.get("draft") or {}
    words = _words(text)
    if not draft:
        if words & {"send", "bhej", "bhejo", "bhejna", "bhejni", "bhejoge",
                    "bhejogi", "bhejega", "sent", "bheja", "bheji"}:
            _answer_email_question(text)
            return
        core.say_lang(
            "Sir, there is no email draft waiting right now. Tell me the recipient "
            "and the message, for example: send email to name@example.com about ...",
            "Sir, abhi koi email draft waiting nahi hai. Recipient aur message "
            "bolein, jaise: send email to name@example.com about ...",
            "سر، ابھی کوئی ای میل ڈرافٹ منتظر نہیں ہے۔ وصول کنندہ اور پیغام بتائیں۔")
        return
    to = _PENDING.get("to") or draft.get("to") or "the recipient"
    subject = draft.get("subject") or "(no subject)"
    if words & {"subject", "topic"}:
        core.say_lang(
            f"The subject is '{subject}', sir. The draft has not been sent yet.",
            f"Subject '{subject}' hai, sir. Draft abhi bheja nahi gaya.",
            f"موضوع '{subject}' ہے، سر۔ ڈرافٹ ابھی نہیں بھیجا گیا۔")
        return
    if words & {"body", "message", "text", "content", "likha", "likhi"}:
        body = re.sub(r"\s+", " ", str(draft.get("body") or "")).strip()
        core.say_lang(
            f"The body says: {core.truncate(body, 320)} The draft has not been sent yet.",
            f"Body mein likha hai: {core.truncate(body, 300)} Draft abhi bheja nahi gaya.",
            f"پیغام یہ ہے: {core.truncate(body, 300)} ڈرافٹ ابھی نہیں بھیجا گیا۔")
        return
    if words & {"recipient", "address", "kisko", "jisko"}:
        core.say_lang(
            f"The draft is addressed to {to}, sir. It has not been sent yet.",
            f"Draft {to} ke naam hai, sir. Abhi bheja nahi gaya.",
            f"ڈرافٹ {to} کے نام ہے، سر۔ ابھی نہیں بھیجا گیا۔")
        return
    core.say_lang(
        f"Sir, the draft to {to} is still waiting. It has not been sent yet. "
        "Say 'send it' to send it, or 'cancel' to discard it.",
        f"Sir, {to} ka draft abhi bhi waiting hai. Abhi tak bheja nahi gaya. "
        "Bhejne ke liye 'send it' bolein, ya 'cancel' karein.",
        f"سر، {to} کا ڈرافٹ ابھی منتظر ہے۔ ابھی تک نہیں بھیجا گیا۔ "
        "بھیجنے کے لیے 'send it' کہیں، یا 'cancel' کریں۔")


def last_send_result():
    """The most recent recorded send_email result, or None."""
    try:
        with open(core.AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=300)
    except Exception:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("tool") or "") == "send_email":
            return row
    return None


def _answer_email_question(text: str = ""):
    if _active() and _PENDING.get("draft"):
        to = _PENDING.get("to") or _PENDING["draft"].get("to")
        core.say_lang(
            f"Sir, the draft to {to} is still waiting. It has not been sent yet. "
            "Say 'send it' to send it, or 'cancel' to discard it.",
            f"Sir, {to} ka draft abhi bhi waiting hai. Abhi tak bheja nahi gaya. "
            "Bhejne ke liye 'send it' bolein, ya 'cancel' karein.",
            f"سر، {to} کا ڈرافٹ ابھی منتظر ہے۔ ابھی تک نہیں بھیجا گیا۔ "
            "بھیجنے کے لیے 'send it' کہیں، یا 'cancel' کریں۔")
        return
    words = _words(text)
    if words & {"will", "would", "going", "bhejoge", "bhejogi", "bhejega",
                "bhejna", "bhejni", "doge", "dega", "degi"} and not words & {
            "sent", "bheja", "bheji", "gayi", "gaya"}:
        core.say_lang(
            "Sir, there is no email draft waiting right now. Tell me the recipient "
            "and the message, for example: send email to name@example.com about ...",
            "Sir, abhi koi email draft waiting nahi hai. Recipient aur message "
            "bolein, jaise: send email to name@example.com about ...",
            "سر، ابھی کوئی ای میل ڈرافٹ منتظر نہیں ہے۔ وصول کنندہ اور پیغام بتائیں۔")
        return
    if words & {"can", "could", "sakta", "sakte", "sakti"} and not words & {
            "sent", "bheja", "bheji", "gayi", "gaya"}:
        status = integrations.email_status()
        core.say_lang(
            "Yes sir, I can read your Gmail inbox in Brave and summarise the new mail, "
            "and I can send email through Gmail or through SMTP if an account is "
            f"configured. Current status: {core.truncate(status, 240)}",
            "Ji sir, main Brave mein aapka Gmail inbox padh kar nayi email ka khulasa "
            "bata sakta hoon, aur Gmail ya SMTP se email bhej sakta hoon. "
            f"Abhi status: {core.truncate(status, 220)}",
            "جی سر، میں بریو میں آپ کا جی میل ان باکس پڑھ کر نئی ای میل کا خلاصہ بتا "
            f"سکتا ہوں، اور ای میل بھیج سکتا ہوں۔ ابھی اسٹیٹس: {core.truncate(status, 220)}")
        return
    row = last_send_result()
    if not row:
        core.say_lang(
            "Sir, I have no record of an email send in this session. I cannot confirm "
            "that any email was sent.",
            "Sir, is session mein email bhejne ka koi record nahi hai. Main confirm "
            "nahi kar sakta ke koi email bheji gayi hai.",
            "سر، اس سیشن میں ای میل بھیجنے کا کوئی ریکارڈ نہیں ہے۔ میں تصدیق نہیں کر سکتا۔")
        return
    result = str(row.get("result") or "")
    when = str(row.get("time") or "")
    if result.lower().startswith("sent"):
        core.say_lang(
            f"Sir, the last recorded email send succeeded: {result} ({when}).",
            f"Sir, aakhri record ke mutabiq email send hui: {result} ({when}).",
            f"سر، آخری ریکارڈ کے مطابق ای میل بھیج دی گئی: {result} ({when})۔")
    else:
        core.say_lang(
            f"Sir, the last recorded email send did not succeed: {result} ({when}).",
            f"Sir, aakhri record ke mutabiq email send nahi hui: {result} ({when}).",
            f"سر، آخری ریکارڈ کے مطابق ای میل نہیں بھیجی جا سکی: {result} ({when})۔")


def _is_configure_request(text: str) -> bool:
    words = _words(text)
    if not (words & _EMAIL_WORDS):
        return False
    return bool(words & {"configure", "configuration", "setup", "set", "login",
                         "password", "app", "pass"})


def _sender_name() -> str:
    try:
        profile = memory._load_raw().get("profile", {})
        for key in ("user_name", "name", "full_name"):
            if profile.get(key):
                return str(profile[key]).strip()
    except Exception:
        pass
    return ""


def _clean_content(text: str) -> str:
    """Strip the command and browser noise, keep the facts the user supplied."""
    t = _EMAIL_RE.sub(" ", text or "")

    # Speech recognition sometimes glues words together: "khologmail".
    t = re.sub(r"(?i)\b(?:kholo|khol|open)(gmail|email|mail)\b", " ", t)
    t = re.sub(r"(?i)\b(email|mail)(bhejo|bhej|send|karo|likho)\b", " ", t)

    patterns = (
        r"\b(?:achaw|acha|achha|ok|okay|please|plz|abhi|chalo|zara|ary|arey)\b",
        r"\b(?:brave|chrome|edge|firefox|gmail|browser)\b",
        r"\b(?:kholo|khol|open)\b",
        r"\b(?:send|bhej(?:o|do|na|ni|en|iye|ain)?)\s+(?:an?\s+)?(?:email|mail|e-mail)\b",
        r"\b(?:email|mail|e-mail)\s+(?:send|bhej(?:o|do|na|ni|en|iye|ain)?|karo|"
        r"kar\s+do|likho|likh\s+do)\b",
        r"\b(?:compose|draft|write|likh(?:o|na|en)?)\s+(?:an?\s+)?(?:email|mail|e-mail)\b",
        r"^\s*(?:write|message|tell|inform|contact)\s+(?:to\s+)?",
        r"^\s*send\s+(?:a\s+)?message\s+(?:to\s+)?",
        r"\b(?:just\s+)?(?:topic|subject)\s+(?:wagira|wagerah|etc)\s+(?:sab\s+)?"
        r"(?:cheez|cheezein)\s+(?:k|ke)\s+(?:sath|saath)\b",
        r"\b(?:aur\s+)?(?:baki|baqi)\s+sab\s+(?:khud\s+)?"
        r"(?:add|likh|likha|likhna|likhdo|karna|krna|karo|kardo|kar\s+do|kar\s+dena)"
        r"(?:\s+(?:karo|karna|krna|do|dena))?\b",
        r"\b(?:khud\s+)?(?:add|likh|likha|likhna|likhdo)\s+(?:karo|karna|krna|do|dena)\b",
        r"\b(?:email|mail|e-mail)\b",
        r"\b(?:na{3,}|ya+r|pl+[sz])\b",
    )
    for pattern in patterns:
        t = re.sub(pattern, " ", t, flags=re.I)

    t = re.sub(r'["“”]', " ", t)
    # Remove command filler left at the start (after the address was removed).
    t = re.sub(r"^(?:\s*(?:ko|to|k|ke|ki|ka|liye|that|aur|and|then|phir|fir|"
               r"about|regarding|subject|topic|ab)\b[\s,;:\-]*)+", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .,:;-")
    return t[:4000]


def _has_details(content: str) -> bool:
    return bool(re.search(r"[A-Za-z\u0600-\u06FF]{3,}", content or ""))


def _fallback_draft(content: str, to: str) -> tuple[str, str]:
    name = _sender_name()
    subject = _plain(content.split(".")[0])[:70] or "Message"
    if len(subject.split()) < 3:
        subject = "Message" + (f" from {name}" if name else "")
    body = content.strip() or "Please see this message."
    if body and body[0].islower():
        body = body[0].upper() + body[1:]
    if not body.endswith((".", "!", "?")):
        body += "."
    if name:
        body += f"\n\nRegards,\n{name}"
    return subject, body


def _make_draft(to: str, content: str, original: str) -> dict:
    """Ask the model for subject+body, with a safe deterministic fallback."""
    name = _sender_name()
    prompt = (
        "Write a complete email for the user. Return ONLY JSON: "
        '{"subject": "short specific subject", "body": "full email body"}\n\n'
        "Rules:\n"
        "- Include every concrete detail the user gave (names, dates, times, places).\n"
        "- Do not invent facts, links, prices, promises or recipients.\n"
        "- Be polite, clear and concise. Use the same language as the request; if it is "
        "mixed Roman Urdu/English, write natural English unless the content is clearly Urdu.\n"
        "- Do not put 'Subject:' or 'To:' inside the body.\n"
        "- Sign with the sender's name if known.\n\n"
        f"Today: {time.strftime('%A, %d %B %Y %H:%M')}\n"
        f"Sender name: {name or '(unknown)'}\n"
        f"Recipient: {to}\n"
        f"User's request: {core.truncate(original, 2500)}\n"
        f"Important details extracted: {core.truncate(content, 1800)}"
    )
    data = core.llm_json(prompt, system="You write trustworthy emails. Return JSON only.",
                         smart=False, fallback={}, max_tokens=1400)
    subject = ""
    body = ""
    if isinstance(data, dict):
        subject = str(data.get("subject") or "").strip()
        body = str(data.get("body") or "").strip()
    if not subject or not body:
        f_subject, f_body = _fallback_draft(content, to)
        subject = subject or f_subject
        body = body or f_body
    subject = re.sub(r"^(?:subject|topic)\s*[:\-]\s*", "", subject, flags=re.I).strip()
    body = re.sub(r"^(?:subject|topic)\s*[:\-].*\n+", "", body, flags=re.I).strip()
    return {"to": to.strip(), "subject": subject[:160], "body": body[:12000]}


def _preview_and_ask(draft: dict) -> str:
    body_one_line = re.sub(r"\s+", " ", draft.get("body", "")).strip()
    print("\n[Email draft]")
    print(f"To: {draft.get('to')}")
    print(f"Subject: {draft.get('subject')}")
    print("Body:")
    print(draft.get("body"))
    print("[Waiting for your permission: yes / no]\n")
    core.say_lang(
        f"Draft ready, sir. To {draft.get('to')}, subject '{draft.get('subject')}'. "
        f"Body: {core.truncate(body_one_line, 240)}. Shall I send it? Say yes or no.",
        f"Sir, email draft tayyar hai. {draft.get('to')} ko, subject '{draft.get('subject')}'. "
        f"Body: {core.truncate(body_one_line, 220)}. Bhej doon? Haan ya nahi bolein.",
        f"سر، ای میل کا ڈرافٹ تیار ہے۔ {draft.get('to')} کو، موضوع '{draft.get('subject')}'۔ "
        f"کیا بھیج دوں؟ ہاں یا نہیں بولیں۔")
    return "I have prepared the email and asked for permission, sir."


def _ask_recipient():
    core.say_lang(
        "I can send it, sir, but I need the recipient's email address. "
        "Tell me the address, for example: send email to name@example.com.",
        "Sir, bhej sakta hoon, lekin recipient ka email address chahiye. "
        "Address bolein, jaise: send email to name@example.com.",
        "سر، بھیج سکتا ہوں، لیکن وصول کنندہ کا ای میل ایڈریس چاہیے۔ "
        "ایڈریس بتائیں، مثلاً: send email to name@example.com۔")


def _ask_content(to: str):
    core.say_lang(
        f"I have the address {to}, sir, but I need to know what the email should say. "
        "Tell me the message, for example: tell him I will arrive tomorrow at 8 AM.",
        f"Address {to} mil gaya, sir, lekin email mein kya likhna hai? "
        "Message bolein, jaise: likho ke main kal subah 8 baje pahunchunga.",
        f"ایڈریس {to} مل گیا، سر، لیکن ای میل میں کیا لکھنا ہے؟ "
        "پیغام بتائیں، مثلاً: لکھو کہ میں کل صبح 8 بجے پہنچوں گا۔")


def _prepare(text: str, to: str = "") -> bool:
    to = (to or "").strip()
    if not to:
        addresses = _EMAIL_RE.findall(text or "")
        to = addresses[0] if addresses else ""
    if not to:
        _set_pending("to", text=text or "")
        _ask_recipient()
        return True

    content = _clean_content(text)
    if not _has_details(content):
        _set_pending("content", text=text or "", to=to)
        _ask_content(to)
        return True

    draft = _make_draft(to, content, text)
    _set_pending("draft", text=text or "", to=to, draft=draft)
    _preview_and_ask(draft)
    return True


def _send_pending() -> bool:
    with _LOCK:
        stage = _PENDING.get("stage")
        if stage not in ("draft", "resend_confirm", "sending") or not _PENDING.get("draft"):
            return False
        draft = dict(_PENDING["draft"])
        maybe_sent = stage == "sending" or bool(_PENDING.get("maybe_sent"))
        # Keep the draft on disk until the mail server answers.  If the PC dies
        # during SMTP, the next start asks whether to retry instead of losing it.
        _PENDING.update({"stage": "sending", "created": time.time(),
                         "restored": bool(_PENDING.get("restored")),
                         "maybe_sent": maybe_sent})
        _save_pending()
    if maybe_sent:
        core.say_lang(
            "Sending the email again, sir. If the earlier attempt reached the server, "
            "this will be a second copy.",
            "Email dobara bhej raha hoon, sir. Agar pehli koshish server tak pahunch gayi thi "
            "to yeh doosri copy hogi.",
            "ای میل دوبارہ بھیج رہا ہوں، سر۔ اگر پہلی کوشش سرور تک پہنچ گئی تھی تو یہ دوسری کاپی ہوگی۔")
    else:
        core.say_lang("Sending the email now, sir.", "Email bhej raha hoon, sir.",
                      "ای میل بھیج رہا ہوں، سر۔")
    try:
        result = integrations.email_operation(
            action="send", to=draft["to"], subject=draft["subject"],
            body=draft["body"], confirmed=True)
    except Exception as e:
        result = f"Could not send the email: {e}"
    print(f"[Email result]: {result}")
    if str(result).lower().startswith("email sent"):
        _reset()
        core.say_lang(f"Email sent to {draft['to']}, sir.",
                      f"Email {draft['to']} ko send ho gayi, sir.",
                      f"ای میل {draft['to']} کو بھیج دی گئی، سر۔")
        try:
            memory.add_episode(f"Sent email to {draft['to']}: {draft['subject']}",
                               ["email", "sent"], 3)
        except Exception:
            pass
    else:
        # Keep the draft: the user can fix the account and say "send it" again.
        # Treat it as restored so it stays available for a day, not ten minutes.
        _set_pending("draft", text="", to=draft["to"], draft=draft)
        # If Gmail clicked Send but could not confirm it, the next attempt must
        # warn about a possible duplicate.  A clear "not signed in" failure is
        # definitely not sent, so it keeps maybe_sent false.
        uncertain = any(phrase in str(result).lower() for phrase in (
            "could not confirm", "did not show a confirmation",
            "may already have", "possible duplicate"))
        with _LOCK:
            _PENDING["restored"] = True
            _PENDING["created"] = time.time()
            _PENDING["maybe_sent"] = uncertain
        _save_pending()
        # Some failure strings already end with "The draft is still saved."
        # Strip that tail so the spoken sentence does not repeat it.
        detail = str(result).strip()
        for phrase in ("The email draft is still saved.", "The draft is still saved.",
                       "Email draft abhi bhi saved hai.", "Draft save hai."):
            if detail.endswith(phrase):
                detail = detail[:-len(phrase)].rstrip()
                if detail and not detail.endswith((".", "!", "?")):
                    detail += "."
                break
        core.say_lang(
            "Sir, the email was not sent. " + core.truncate(detail, 280) +
            " The draft is still saved. Say 'send it' to retry, or 'cancel' to discard it.",
            "Sir, email send nahi hui. " + core.truncate(detail, 260) +
            " Draft save hai. Dobara bhejne ke liye 'send it' bolein, ya 'cancel' karein.",
            "سر، ای میل نہیں بھیجی جا سکی۔ ڈرافٹ محفوظ ہے۔ دوبارہ بھیجنے کے لیے "
            "'send it' کہیں، یا 'cancel' کریں۔")
    return True


def resume_pending() -> bool:
    """Continue a draft that was restored after a restart.

    A normal draft is sent immediately because the startup prompt already asked
    for permission.  An interrupted send is never repeated silently: the user
    gets a second, explicit warning that it may already have gone out.
    """
    if not _active():
        return False
    stage = _PENDING.get("stage")
    if stage == "draft":
        return _send_pending()
    if stage == "sending":
        with _LOCK:
            _PENDING.update({"stage": "resend_confirm", "created": time.time(),
                             "restored": True, "maybe_sent": True})
        _save_pending()
        core.say_lang(
            "Sir, the previous send was interrupted. It may already have reached the "
            "recipient. Should I send it again? Say yes or no.",
            "Sir, pichhli baar email bhejne ka amal adhura reh gaya. Ho sakta hai email pehle "
            "hi chali gayi ho. Kya main dobara bhejun? Haan ya nahi bolein.",
            "سر، پچھلی بار ای میل بھیجنے کا عمل ادھورا رہ گیا۔ ہو سکتا ہے ای میل پہلے ہی چلی گئی ہو۔ "
            "کیا میں دوبارہ بھیجوں؟ ہاں یا نہیں۔")
        return True
    if stage == "resend_confirm":
        core.say_lang(
            "Sir, should I send the interrupted email again? It may already have been sent. "
            "Say yes or no.",
            "Sir, kya adhuri email dobara bhejun? Ho sakta hai pehle hi chali gayi ho. "
            "Haan ya nahi bolein.",
            "سر، کیا ادھوری ای میل دوبارہ بھیجوں؟ ہو سکتا ہے پہلے ہی چلی گئی ہو۔ ہاں یا نہیں۔")
        return True
    if stage == "to":
        _ask_recipient()
        return True
    if stage == "content":
        _ask_content(_PENDING.get("to", ""))
        return True
    return False


def _configure_with(address: str, password: str) -> bool:
    """Save credentials, verify the login, and keep any waiting draft alive."""
    result = integrations.email_operation(action="configure", address=address,
                                          app_password=password, confirmed=True)
    if not str(result).lower().startswith("email configured"):
        core.say_lang("I could not save the email settings, sir. " +
                      core.truncate(result, 300),
                      "Email settings save nahi ho sakeen, sir. " +
                      core.truncate(result, 300),
                      "ای میل کی سیٹنگز محفوظ نہیں ہو سکیں، سر۔")
        return True

    verify = integrations.email_operation(action="verify")
    if str(verify).lower().startswith("email login verified"):
        msg = f"Email configured and login verified for {address}, sir."
    else:
        msg = (f"Email settings saved for {address}, sir, but the login test failed: " +
               core.truncate(verify, 240))
    if _PENDING.get("stage") in ("draft", "resend_confirm", "sending") and _PENDING.get("draft"):
        msg += (f" Your draft to {_PENDING.get('to')} is still waiting. "
                "Say 'send it' to send it.")
    core.say_lang(msg, msg, msg)
    return True


def _configure(text: str) -> bool:
    addresses = _EMAIL_RE.findall(text or "")
    password = _extract_password(text)
    if addresses and password:
        _reset_setup()
        return _configure_with(addresses[0], password)
    if addresses:
        with _LOCK:
            _SETUP.update({"stage": "password", "address": addresses[0],
                           "created": time.time()})
        core.say_lang(
            f"Address saved, sir: {addresses[0]}. Now type the Gmail App Password "
            "(the 16-character password, not your normal Gmail password).",
            f"Address save ho gaya, sir: {addresses[0]}. Ab Gmail App Password type karein "
            "(16 characters, normal Gmail password nahi).",
            f"ایڈریس محفوظ ہو گیا، سر: {addresses[0]}۔ اب جی میل ایپ پاس ورڈ ٹائپ کریں "
            "(16 حروف، عام جی میل پاس ورڈ نہیں)۔")
        return True
    with _LOCK:
        _SETUP.update({"stage": "address", "address": "", "created": time.time()})
    core.say_lang(
        "Email setup needs your Gmail address and a Gmail App Password. "
        "Say or type: configure email with address you@gmail.com, then I will ask for "
        "the App Password. For Gmail, turn on 2-Step Verification and create an App "
        "Password in Google Account security settings.",
        "Email setup ke liye Gmail address aur Gmail App Password chahiye. "
        "Bolein ya type karein: configure email with address you@gmail.com, phir main "
        "App Password poochh loonga. Gmail ke liye 2-Step Verification on kar ke Google "
        "Account security settings mein App Password banayein.",
        "ای میل سیٹ اپ کے لیے جی میل ایڈریس اور ایپ پاس ورڈ چاہیے۔ "
        "کہیں یا لکھیں: configure email with address you@gmail.com، پھر میں ایپ پاس ورڈ پوچھوں گا۔")
    return True


def _show_status():
    result = integrations.email_status()
    core.say_lang(core.truncate(result, 500), core.truncate(result, 500),
                  core.truncate(result, 500))


def _handle_setup(text: str, low: str) -> bool:
    """One small, safe setup wizard.  The App Password is never archived."""
    stage = _SETUP.get("stage")

    # A complete one-line configure command always wins.
    if _is_configure_request(text) and _EMAIL_RE.search(text) and _extract_password(text):
        _reset_setup()
        return _configure(text)

    # While waiting for the address, a real address wins even if its local part
    # is "na" or the sentence happens to contain the word "no".
    if stage == "address":
        addresses = _EMAIL_RE.findall(text or "")
        if addresses:
            with _LOCK:
                _SETUP.update({"stage": "password", "address": addresses[0],
                               "created": time.time()})
            core.say_lang(
                f"Address saved, sir: {addresses[0]}. Now type the 16-character Gmail "
                "App Password. It will be stored encrypted and will not be saved in memory.",
                f"Address save ho gaya, sir: {addresses[0]}. Ab 16-character Gmail App Password "
                "type karein. Yeh encrypted save hoga aur memory mein nahi jayega.",
                f"ایڈریس محفوظ ہو گیا، سر: {addresses[0]}۔ اب 16 حروف کا جی میل ایپ پاس ورڈ "
                "ٹائپ کریں۔ یہ encrypted محفوظ ہوگا اور میموری میں نہیں جائے گا۔")
            return True

    if _is_no(low):
        _reset_setup()
        core.say_lang("Email setup cancelled, sir. Nothing was saved.",
                      "Email setup cancel kar diya, sir. Kuch save nahi hua.",
                      "ای میل سیٹ اپ منسوخ کر دیا، سر۔ کچھ محفوظ نہیں ہوا۔")
        return True

    if _is_status_request(text):
        _reset_setup()
        _show_status()
        return True

    if _is_send_request(text) and _EMAIL_RE.search(text):
        _reset_setup()
        return _prepare(text)

    if stage == "address":
        core.say_lang(
            "I still need the Gmail address, sir. For example: you@gmail.com.",
            "Mujhe abhi bhi Gmail address chahiye, sir. Jaise: you@gmail.com.",
            "مجھے ابھی بھی جی میل ایڈریس چاہیے، سر۔ مثلاً: you@gmail.com۔")
        return True

    if stage == "password":
        password = _extract_password(text) or _looks_like_password(text)
        if not password:
            core.say_lang(
                "I need the 16-character Gmail App Password, sir. Type only the password, "
                "or say: app password abcd efgh ijkl mnop.",
                "Mujhe 16-character Gmail App Password chahiye, sir. Sirf password type karein, "
                "ya bolein: app password abcd efgh ijkl mnop.",
                "مجھے 16 حروف کا جی میل ایپ پاس ورڈ چاہیے، سر۔ صرف پاس ورڈ ٹائپ کریں۔")
            return True
        address = _SETUP.get("address", "")
        _reset_setup()
        return _configure_with(address, password)

    _reset_setup()
    return False


def command_hook(text: str, g: dict) -> bool:
    """Handle email commands before the language model can hallucinate them."""
    low = _plain(text).lower()
    if not low:
        return False

    # The setup wizard runs first and never touches the waiting draft.
    if _active_setup():
        if _handle_setup(text, low):
            return True

    if _is_gmail_close_request(text):
        return _close_gmail()
    if _is_status_request(text):
        _show_status()
        return True
    if _is_configure_request(text):
        return _configure(text)
    if _is_inbox_request(text):
        return _check_inbox(text)
    if _is_email_question(text):
        _answer_email_question(text)
        return True
    if _is_draft_question(text):
        _answer_draft_question(text)
        return True

    # A confirmation belongs to the pending draft, never to a new command.
    if _active():
        stage = _PENDING.get("stage")
        draft = _PENDING.get("draft")

        # "send it tomorrow" / "kal bhej do" must not send now or reach Gemini.
        if _is_future_send(text):
            _future_send_reply(bool(draft))
            return True

        # The user is supplying the missing recipient address.
        if stage == "to":
            addresses = _EMAIL_RE.findall(text or "")
            if addresses:
                original = _PENDING.get("text", "")
                to = addresses[0]
                _reset()
                return _prepare(original + " " + text, to)
            if _is_send_confirmation(text) or _is_yes(low):
                _ask_recipient()
                return True
            if _is_send_request(text):
                _reset()
                return _prepare(text)
            # An unrelated command must not silently throw the draft away.
            defer_pending()
            return False

        # The user is supplying what the email should say.
        if stage == "content":
            if _is_send_request(text) and _EMAIL_RE.search(text):
                _reset()
                return _prepare(text)
            if _is_send_confirmation(text) or _is_yes(low):
                _ask_content(_PENDING.get("to", ""))
                return True
            original = _PENDING.get("text", "")
            to = _PENDING.get("to", "")
            _reset()
            return _prepare(original + " " + text, to)

        if _is_no(low):
            _reset()
            core.say_lang("Cancelled, sir. The email was not sent.",
                          "Cancel kar diya, sir. Email nahi bheji.",
                          "منسوخ کر دیا، سر۔ ای میل نہیں بھیجی گئی۔")
            return True

        if stage in ("draft", "resend_confirm", "sending") and draft:
            # Edit the waiting draft first.  The updated draft is shown again
            # and still needs permission, even if the command also said "send".
            edited = _draft_edit(text)
            if edited:
                maybe_sent = stage == "sending" or bool(_PENDING.get("maybe_sent"))
                _set_pending("draft", text=_PENDING.get("text", ""),
                             to=edited.get("to", ""), draft=edited)
                if maybe_sent:
                    with _LOCK:
                        _PENDING["maybe_sent"] = True
                    _save_pending()
                _preview_and_ask(edited)
                return True
            # "Haan" answers the question; "Ha bhej do", "send it again on
            # Brave", "bhai ... send it" and "Ary bhej do naa" are the same
            # instruction in fuller words.
            if _is_send_confirmation(text) or _is_yes(low):
                # A bare yes goes to the newest question.  A send phrase always
                # means the email, even if an old cleanup prompt is still alive.
                if (_is_yes(low) and not _is_send_confirmation(text)
                        and _legacy_question_is_newer(g)):
                    return False
                return _send_pending()
            # A genuine new email request replaces the old draft.
            if _is_send_request(text):
                _reset()
                return _prepare(text)
            # "send it to ali@example.com about the party" is a new request even
            # without the word "email"; keep it deterministic instead of Gemini.
            if _EMAIL_RE.search(text) and any(_CORE_SEND_RE.match(w)
                                              for w in _words(text)):
                _reset()
                return _prepare(text)
            # Any other command: keep the draft on disk, but stop it from
            # intercepting this command or a later unrelated "yes".
            defer_pending()
            return False

        if _is_yes(low) and stage in ("to", "content"):
            core.say_lang(
                "I still need the missing detail before I can prepare the email, sir.",
                "Email tayyar karne se pehle mujhe baqi detail chahiye, sir.",
                "ای میل تیار کرنے سے پہلے مجھے باقی تفصیل چاہیے، سر۔")
            return True

        defer_pending()
        return False

    if _is_future_send(text):
        _future_send_reply(False)
        return True

    if _is_send_request(text):
        return _prepare(text)
    if _is_send_confirmation(text):
        core.say_lang(
            "There is no email draft waiting, sir. Tell me the recipient and the "
            "message, for example: send email to name@example.com about ...",
            "Sir, abhi koi email draft waiting nahi hai. Recipient aur message "
            "bolein, jaise: send email to name@example.com about ...",
            "سر، ابھی کوئی ای میل ڈرافٹ منتظر نہیں ہے۔ وصول کنندہ اور پیغام بتائیں۔")
        return True
    return False
