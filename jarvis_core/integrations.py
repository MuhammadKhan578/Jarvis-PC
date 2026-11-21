"""Everyday integrations: email, translation, summaries and the morning briefing."""
from __future__ import annotations

import base64
import email
import email.utils
import imaplib
import mimetypes
import os
import re
import smtplib
import ssl
import time
from email.header import decode_header
from email.message import EmailMessage

from . import core, gmail_web


# --------------------------------------------------------------------------
# Password protection (Windows DPAPI when available)
# --------------------------------------------------------------------------
def _protect(text: str) -> str:
    if not text:
        return ""
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(text.encode("utf-8"), "jarvis-email", None, None, None, 0)
        return "dpapi:" + base64.b64encode(blob).decode("ascii")
    except Exception:
        return "plain:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unprotect(value: str) -> str:
    if not value:
        return ""
    try:
        if value.startswith("dpapi:"):
            import win32crypt
            blob = base64.b64decode(value.split(":", 1)[1])
            return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")
        if value.startswith("plain:"):
            return base64.b64decode(value.split(":", 1)[1]).decode("utf-8")
    except Exception:
        pass
    return value


def _cfg() -> dict:
    cfg = core.load_config().get("email") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    out = dict(cfg)
    out["password"] = _unprotect(out.get("password", ""))
    return out


def email_status() -> str:
    cfg = _cfg()
    if not cfg.get("address"):
        return ("Email is ready through Gmail in the Brave window: I can read and "
                "summarize your inbox, and send new mail after your permission. "
                "Say 'check my inbox' or 'send email to ...'. If Gmail asks you to "
                "sign in, sign in once in the Brave window Jarvis opens; the session "
                "is kept for later.")
    method = _email_send_method(cfg)
    if method == "gmail":
        return (f"Email is set up for {cfg['address']}. Sends go through Gmail in Brave "
                f"({gmail_web.gmail_status()}). SMTP is also available as a fallback.")
    return (f"Email configured for {cfg['address']} via {cfg.get('smtp_host', 'smtp.gmail.com')}. "
            f"IMAP: {cfg.get('imap_host', 'imap.gmail.com')}.")


def _email_send_method(cfg: dict) -> str:
    """Pick the real send path: Gmail in Brave, or SMTP.

    ``JARVIS_EMAIL_METHOD`` exists for the regression tests so they never open
    a browser.  In normal use, an explicitly configured method wins; otherwise
    an SMTP account means SMTP and no account means the visible Gmail path.
    """
    raw = (os.environ.get("JARVIS_EMAIL_METHOD")
           or cfg.get("send_method")
           or core.load_config().get("email_send_method")
           or "")
    method = str(raw).strip().lower()
    if method in ("brave", "browser", "gmail", "gmail_web", "web"):
        return "gmail"
    if method in ("smtp", "mail", "server"):
        return "smtp"
    return "smtp" if (cfg.get("address") and cfg.get("password")) else "gmail"



def configure_email(address: str, app_password: str = "", smtp_host: str = "smtp.gmail.com",
                    smtp_port: int = 465, imap_host: str = "imap.gmail.com",
                    imap_port: int = 993, display_name: str = "") -> str:
    """Save email credentials (app password is encrypted with Windows DPAPI)."""
    address = (address or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", address):
        return "That does not look like an email address."
    current = core.load_config().get("email") or {}
    if not isinstance(current, dict):
        current = {}
    cfg = dict(current)
    cfg.update({
        "address": address,
        "smtp_host": smtp_host or "smtp.gmail.com",
        "smtp_port": int(smtp_port or 465),
        "imap_host": imap_host or "imap.gmail.com",
        "imap_port": int(imap_port or 993),
        "display_name": display_name or current.get("display_name", ""),
    })
    if app_password:
        cfg["password"] = _protect(app_password.strip().replace(" ", ""))
    core.save_config({"email": cfg})
    core.audit("configure_email", address, "saved", risk="normal")
    return email_status()


def verify_email() -> str:
    """Log in to SMTP once so a wrong App Password is caught during setup."""
    cfg = _cfg()
    if not cfg.get("address") or not cfg.get("password"):
        return email_status()
    try:
        s = _smtp_connect(cfg)
        try:
            s.noop()
        finally:
            try:
                s.quit()
            except Exception:
                pass
        core.audit("verify_email", cfg["address"], "verified", risk="normal")
        return f"Email login verified for {cfg['address']}."
    except Exception as e:
        core.audit("verify_email", cfg["address"], f"failed: {e}", risk="normal")
        return f"Email login failed for {cfg['address']}: {e}"


# --------------------------------------------------------------------------
# SMTP / IMAP
# --------------------------------------------------------------------------
def _smtp_connect(cfg: dict):
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 465) or 465)
    if port == 587:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls(context=ssl.create_default_context())
    else:
        s = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    s.login(cfg["address"], cfg["password"])
    return s


def _imap_connect(cfg: dict):
    host = cfg.get("imap_host", "imap.gmail.com")
    port = int(cfg.get("imap_port", 993) or 993)
    m = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    m.login(cfg["address"], cfg["password"])
    return m


def _decode(value) -> str:
    if not value:
        return ""
    parts = []
    try:
        for raw, enc in decode_header(str(value)):
            if isinstance(raw, bytes):
                parts.append(raw.decode(enc or "utf-8", errors="replace"))
            else:
                parts.append(str(raw))
    except Exception:
        return str(value)
    return " ".join(parts)


def _body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8",
                                                                errors="replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8",
                                                                errors="replace")
                    return re.sub(r"<[^>]+>", " ", html)
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return str(msg.get_payload())[:8000]


def _send_email_smtp(to: str, subject: str, body: str, cc: str = "",
                     attachments: str = "", cfg: dict | None = None) -> str:
    """The deterministic SMTP path (kept as a reliable fallback)."""
    cfg = cfg or _cfg()
    if not cfg.get("address") or not cfg.get("password"):
        return email_status()
    try:
        m = EmailMessage()
        name = cfg.get("display_name") or ""
        m["From"] = email.utils.formataddr((name, cfg["address"])) if name else cfg["address"]
        m["To"] = to
        if cc:
            m["Cc"] = cc
        m["Subject"] = subject or "(no subject)"
        m["Date"] = email.utils.formatdate(localtime=True)
        m.set_content(body or "")
        for path in [p.strip() for p in re.split(r"[,;]+", attachments or "") if p.strip()]:
            p = core.resolve_path(path)
            if not os.path.isfile(p):
                continue
            ctype, _ = mimetypes.guess_type(p)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            with open(p, "rb") as f:
                m.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                                 filename=os.path.basename(p))
        with _smtp_connect(cfg) as s:
            s.send_message(m)
        core.audit("send_email", f"to={to} subject={subject}", "sent", risk="high")
        return f"Email sent to {to}."
    except Exception as e:
        core.audit("send_email", f"to={to} subject={subject}", f"failed: {e}", risk="high")
        return f"Could not send the email: {e}"


def send_email(to: str, subject: str, body: str, cc: str = "", attachments: str = "",
               confirmed: bool = False) -> str:
    """Send through Gmail in Brave, or through SMTP when that is configured.

    The Gmail path is the visible one the user asked for: Brave opens, Gmail's
    own compose window is filled, and Send is clicked there.  Success is only
    reported when Gmail itself confirms it.  Attachments and Cc need the SMTP
    path because the Gmail compose automation does not add them yet.
    """
    if not (to or "").strip():
        return "No recipient address given."
    msg = core.guard("send_email", confirmed,
                     f"Send an email to {to} with subject '{core.truncate(subject, 80)}'.")
    if msg:
        return msg
    cfg = _cfg()
    method = _email_send_method(cfg)
    if method == "gmail":
        if cc or attachments:
            # The browser composer cannot reliably add these yet; use SMTP if
            # it is configured, otherwise say exactly what is missing.
            if cfg.get("address") and cfg.get("password"):
                return _send_email_smtp(to, subject, body, cc, attachments, cfg)
            return ("Gmail in Brave cannot add Cc or attachments yet, sir. "
                    "Configure an SMTP account for that, or send without them.")
        result = str(gmail_web.send_via_gmail(to, subject, body))
        if result.lower().startswith("gmail sent"):
            core.audit("send_email", f"to={to} subject={subject}",
                       "sent via Gmail in Brave", risk="high")
            return f"Email sent to {to}."
        core.audit("send_email", f"to={to} subject={subject}",
                   f"failed via Gmail: {result}", risk="high")
        # SMTP is a safe fallback only when it is really configured.
        if cfg.get("address") and cfg.get("password"):
            fallback = _send_email_smtp(to, subject, body, cc, attachments, cfg)
            if fallback.lower().startswith("email sent"):
                return fallback + " It went through the configured SMTP account."
            return fallback
        return result
    return _send_email_smtp(to, subject, body, cc, attachments, cfg)


def _fetch_inbox(cfg: dict, limit: int = 10, query: str = "",
                 unread_only: bool = False) -> list[dict]:
    limit = max(1, min(50, int(limit or 10)))
    m = _imap_connect(cfg)
    try:
        m.select("INBOX", readonly=True)
        ids = []
        if unread_only:
            typ, data = m.search(None, "UNSEEN")
            ids = (data[0].split() if data and data[0] else [])[-int(limit):]
        elif query:
            typ, data = m.search(None, "TEXT", f'"{query}"')
            ids = (data[0].split() if data and data[0] else [])[-int(limit):]
        else:
            typ, data = m.search(None, "ALL")
            ids = (data[0].split() if data and data[0] else [])[-int(limit):]
        out = []
        for uid in reversed(ids):
            typ, data = m.fetch(uid, "(RFC822 FLAGS)")
            if typ != "OK" or not data:
                continue
            raw = next((d[1] for d in data if isinstance(d, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            meta = b" ".join(d[0] for d in data if isinstance(d, tuple)
                             and isinstance(d[0], (bytes, bytearray)))
            out.append({
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "from": _decode(msg.get("From")),
                "subject": _decode(msg.get("Subject")),
                "date": _decode(msg.get("Date")),
                "snippet": re.sub(r"\s+", " ", _body_text(msg))[:300],
                "body": _body_text(msg)[:12000],
                "unread": b"\\Seen" not in meta,
            })
        return out
    finally:
        try:
            m.logout()
        except Exception:
            pass


def _gmail_web_inbox_text(limit: int = 10, query: str = "",
                          unread_only: bool = False,
                          mark_read: bool = False) -> str:
    """Read the Gmail inbox through Brave when no IMAP account is configured.

    With ``mark_read`` the messages that were just listed are marked read
    afterwards, using Gmail's own toolbar; the list is checked again and the
    note says exactly what Gmail confirmed.
    """
    try:
        data = gmail_web.read_inbox(limit=limit, query=query,
                                    unread_only=unread_only)
    except Exception as e:
        return f"I could not read Gmail in Brave: {e}"
    if not data.get("ok"):
        return str(data.get("message") or "I could not read Gmail in Brave.")
    msgs = data.get("messages") or []
    if not msgs:
        if unread_only:
            return "No unread email in your Gmail inbox."
        if query:
            return f"No Gmail messages matching '{query}'."
        return "Your Gmail inbox has no messages to show."
    lines = []
    for i, m in enumerate(msgs, 1):
        sender = core.truncate(m.get("sender") or "unknown sender", 60)
        subject = core.truncate(m.get("subject") or "(no subject)", 110)
        flag = " (unread)" if m.get("unread") else ""
        when = f"  [{m.get('date')}]" if m.get("date") else ""
        lines.append(f"{i}. {sender} — {subject}{flag}{when}")
        if m.get("snippet"):
            lines.append(f"   {core.truncate(m['snippet'], 200)}")
    note = ""
    if mark_read:
        targets = [m for m in msgs if m.get("unread")]
        if targets:
            try:
                res = gmail_web.mark_inbox_read(messages=targets,
                                                url=data.get("url") or "")
            except Exception as e:
                res = {"ok": False, "marked": 0, "message": str(e)}
            if res.get("ok"):
                marked = int(res.get("marked") or 0)
                if marked:
                    note = (f"\n(Gmail: {marked} message"
                            f"{'s' if marked != 1 else ''} marked as read.)")
            else:
                note = ("\n(Gmail could not confirm marking them as read: "
                        + core.truncate(str(res.get("message") or ""), 160) + ")")
    return "\n".join(lines) + note


def _gmail_web_read_text(index: int = 0) -> str:
    try:
        data = gmail_web.read_message(index=index)
    except Exception as e:
        return f"I could not open that email in Gmail: {e}"
    if not data.get("ok"):
        return str(data.get("message") or "I could not open that email in Gmail.")
    m = data.get("data") or {}
    return (f"From: {m.get('sender', '')}\n"
            f"Subject: {m.get('subject', '')}\n"
            f"Date: {m.get('date', '')}\n\n"
            f"{core.truncate(m.get('body', ''), 8000)}")


def _load_mail_rows(limit: int = 10, query: str = "",
                    unread_only: bool = False) -> tuple[dict, str, list[dict], dict]:
    """Return (config, mode, normalized messages, Gmail response)."""
    cfg = _cfg()
    has_imap = bool(cfg.get("address") and cfg.get("password"))
    if has_imap:
        rows = _fetch_inbox(cfg, limit, query=query, unread_only=unread_only)
        for row in rows:
            row.setdefault("sender", row.get("from") or "")
        return cfg, "imap", rows, {}
    data = gmail_web.read_inbox(limit=limit, query=query, unread_only=unread_only)
    if not data.get("ok"):
        raise RuntimeError(str(data.get("message") or "I could not read Gmail in Brave."))
    return cfg, "gmail", list(data.get("messages") or []), data


def _triage_rows(rows: list[dict]) -> dict:
    """Classify inbox previews without changing the mailbox."""
    if not rows:
        return {"items": [], "summary": "No messages to triage."}
    material = []
    for i, row in enumerate(rows[:25], 1):
        material.append(
            f"{i}. From: {core.truncate(row.get('sender') or row.get('from') or '', 80)} | "
            f"Subject: {core.truncate(row.get('subject') or '', 140)} | "
            f"Preview: {core.truncate(row.get('snippet') or row.get('body') or '', 260)}"
        )
    prompt = (
        "Triage these email previews using only their text. Categories: urgent, action, reply, "
        "waiting, info, newsletter. Urgent means a credible deadline/security/payment problem; "
        "newsletter means bulk digest/promotion. Never invent facts. Return ONLY JSON: "
        '{"summary":"2-4 sentence overview","items":[{"index":1,"category":"info",'
        '"reason":"short factual reason"}]}.\n\n' + "\n".join(material)
    )
    data = core.llm_json(prompt, system="You are a cautious email triage assistant. Return JSON only.",
                         smart=False, fallback=None, max_tokens=1800)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        clean = []
        allowed = {"urgent", "action", "reply", "waiting", "info", "newsletter"}
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            if not 1 <= index <= len(rows):
                continue
            category = str(item.get("category") or "info").lower()
            if category not in allowed:
                category = "info"
            clean.append({"index": index, "category": category,
                          "reason": core.truncate(item.get("reason") or "", 180)})
        if clean:
            return {"items": clean, "summary": core.truncate(data.get("summary") or "", 1200)}

    # Deterministic offline fallback when Gemini is unavailable.
    out = []
    for i, row in enumerate(rows, 1):
        text = " ".join(str(row.get(k) or "") for k in ("sender", "from", "subject", "snippet")).lower()
        if re.search(r"\b(urgent|asap|overdue|security alert|verify|deadline|payment due)\b", text):
            category, reason = "urgent", "deadline, security or payment wording"
        elif re.search(r"\b(action required|approval|approve|invoice|meeting request|please review)\b", text):
            category, reason = "action", "explicit action requested"
        elif re.search(r"\b(newsletter|digest|unsubscribe|promotion|weekly update)\b", text):
            category, reason = "newsletter", "bulk update/newsletter wording"
        elif "?" in text or re.search(r"\b(reply|respond|your thoughts)\b", text):
            category, reason = "reply", "appears to request a response"
        else:
            category, reason = "info", "informational preview"
        out.append({"index": i, "category": category, "reason": reason})
    return {"items": out, "summary": "Triage completed from the available previews."}


def _triage_text(rows: list[dict], triage: dict) -> str:
    lines = [str(triage.get("summary") or "Inbox triage:"), ""]
    for item in triage.get("items") or []:
        index = int(item.get("index") or 0)
        if not 1 <= index <= len(rows):
            continue
        row = rows[index - 1]
        lines.append(
            f"{index}. [{str(item.get('category') or 'info').upper()}] "
            f"{core.truncate(row.get('subject') or '(no subject)', 110)} — "
            f"{core.truncate(row.get('sender') or row.get('from') or 'unknown', 60)}"
            + (f" ({item.get('reason')})" if item.get("reason") else "")
        )
    return "\n".join(lines)


def _mark_imap_seen(cfg: dict, rows: list[dict]) -> tuple[bool, int, str]:
    uids = [str(row.get("uid") or "") for row in rows if row.get("uid")]
    if not uids:
        return True, 0, "No matching IMAP messages."
    m = _imap_connect(cfg)
    marked = 0
    try:
        m.select("INBOX", readonly=False)
        for uid in uids:
            typ, _ = m.store(uid, "+FLAGS", "\\Seen")
            if typ == "OK":
                marked += 1
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return marked == len(uids), marked, f"Marked {marked} message(s) as read."


def _mark_rows(cfg: dict, mode: str, rows: list[dict], gmail_data: dict) -> tuple[bool, int, str]:
    if mode == "imap":
        return _mark_imap_seen(cfg, rows)
    result = gmail_web.mark_inbox_read(messages=rows, url=gmail_data.get("url") or "")
    return bool(result.get("ok")), int(result.get("marked") or 0), str(result.get("message") or "")


def email_operation(action: str = "status", to: str = "", subject: str = "", body: str = "",
                    cc: str = "", attachments: str = "", query: str = "", uid: str = "",
                    limit: int = 10, address: str = "", app_password: str = "",
                    smtp_host: str = "", smtp_port: int = 0, imap_host: str = "",
                    imap_port: int = 0, display_name: str = "", confirmed: bool = False) -> str:
    """Read and send email through Gmail in Brave, or any IMAP/SMTP account.

    action:
      status    - is email ready, and which path is used?
      configure - save account (address, app_password, optional smtp_host/smtp_port/imap_host/imap_port)
      send      - send mail (to, subject, body, cc, attachments) — needs confirmed=true
      inbox     - list the latest messages in the inbox
      unread    - list only unread messages
      search    - search the mailbox (query)
      read      - read one message (uid from inbox; with Gmail-in-Brave it is the list position)
      draft     - draft a message with AI (to, subject, body = what it should say)
      triage    - classify latest mail into urgent/action/reply/info/newsletter without changing it
      summarize - summarize a mailbox search/thread (query optional)
      mark_read - explicitly mark matching/latest unread messages read (confirmation required)
      organize  - triage and mark only newsletter messages read (confirmation required)

    With no IMAP account configured, inbox/unread/search/read use the visible
    Gmail page in Brave. Listing, searching, summarizing and triage are read-only.
    An explicit mark_read/organize action requires confirmation before changing
    message state. Opening one message may naturally mark that message read in Gmail.
    """
    a = (action or "status").lower().strip()
    if a in ("status", "info"):
        return email_status()
    if a in ("configure", "setup", "login"):
        return configure_email(address, app_password, smtp_host or "smtp.gmail.com",
                               smtp_port or 465, imap_host or "imap.gmail.com",
                               imap_port or 993, display_name)
    if a in ("verify", "test"):
        return verify_email()
    if a in ("send", "write"):
        return send_email(to, subject, body, cc, attachments, confirmed)
    if a in ("draft", "compose"):
        text = core.llm_text(
            "Write a clear, well-mannered email. Return only the email body (no headers).\n\n"
            f"TO: {to}\nSUBJECT: {subject}\nWHAT IT SHOULD SAY: {body}",
            system="You write concise professional emails for the user. Sign as the user, never invent facts.",
            smart=False, max_tokens=1200)
        return f"Subject: {subject}\nTo: {to}\n\n{text}\n\nSay 'send it' to send this email."
    if a in ("triage", "prioritize", "prioritise"):
        try:
            _, _, rows, _ = _load_mail_rows(max(3, min(25, int(limit or 10))), query=query)
        except Exception as e:
            return f"Inbox triage failed: {e}"
        triage = _triage_rows(rows)
        result = _triage_text(rows, triage)
        core.audit("email_operation", "triage", f"{len(rows)} messages (read-only)")
        return result
    if a in ("summarize", "summarise", "thread", "thread_summary"):
        try:
            _, _, rows, _ = _load_mail_rows(max(3, min(25, int(limit or 10))), query=query)
        except Exception as e:
            return f"Email summary failed: {e}"
        if not rows:
            return f"No messages matched '{query}'." if query else "No messages to summarize."
        material = "\n\n".join(
            f"From: {r.get('sender') or r.get('from') or ''}\nSubject: {r.get('subject') or ''}\n"
            f"Date: {r.get('date') or ''}\n{core.truncate(r.get('body') or r.get('snippet') or '', 1800)}"
            for r in rows)
        try:
            summary = core.llm_text(
                "Summarize this email set/thread using only the supplied messages. State key decisions, "
                "deadlines, questions awaiting a reply and action items. Do not invent missing context.\n\n"
                + material[:30000],
                system="You are a factual email analyst.", smart=False, max_tokens=1800)
        except Exception:
            summary = "\n".join(
                f"- {core.truncate(r.get('subject') or '(no subject)', 100)} — "
                f"{core.truncate(r.get('snippet') or r.get('body') or '', 180)}" for r in rows)
        return summary
    if a in ("mark_read", "markread", "read_state"):
        msg = core.guard("email_operation:mark_read", confirmed,
                         f"Mark up to {max(1, min(50, int(limit or 10)))} matching inbox messages as read.")
        if msg:
            return msg
        try:
            cfg2, mode, rows, gmail_data = _load_mail_rows(
                max(1, min(50, int(limit or 10))), query=query, unread_only=not bool(query))
            targets = [r for r in rows if r.get("unread", True)]
            ok, marked, detail = _mark_rows(cfg2, mode, targets, gmail_data)
            core.audit("email_operation", "mark_read", f"marked={marked} ok={ok}", risk="high")
            return (f"Marked {marked} email(s) as read." if ok else
                    f"Could not confirm all messages were marked read ({marked} changed): {detail}")
        except Exception as e:
            return f"Could not mark email as read: {e}"
    if a in ("organize", "organise"):
        try:
            cfg2, mode, rows, gmail_data = _load_mail_rows(
                max(3, min(25, int(limit or 10))), query=query, unread_only=True)
        except Exception as e:
            return f"Inbox organization failed: {e}"
        triage = _triage_rows(rows)
        by_index = {int(x.get("index") or 0): x for x in triage.get("items") or []}
        targets = [row for i, row in enumerate(rows, 1)
                   if (by_index.get(i) or {}).get("category") == "newsletter" and row.get("unread", True)]
        preview = _triage_text(rows, triage)
        if not targets:
            return preview + "\n\nNo unread newsletter messages were selected; nothing changed."
        msg = core.guard("email_operation:organize", confirmed,
                         f"Mark {len(targets)} newsletter message(s) as read. No email will be deleted or archived.")
        if msg:
            return preview + "\n\n" + msg
        try:
            ok, marked, detail = _mark_rows(cfg2, mode, targets, gmail_data)
            core.audit("email_operation", "organize", f"newsletter marked={marked} ok={ok}", risk="high")
            return preview + (f"\n\nMarked {marked} newsletter message(s) as read."
                              if ok else f"\n\nCould not confirm every change ({marked} marked): {detail}")
        except Exception as e:
            return preview + f"\n\nOrganization failed without deleting anything: {e}"
    cfg = _cfg()
    has_imap = bool(cfg.get("address") and cfg.get("password"))
    if a in ("inbox", "list", "latest", "unread"):
        unread_only = a == "unread"
        if has_imap:
            try:
                msgs = _fetch_inbox(cfg, limit, unread_only=unread_only)
            except Exception as e:
                return f"Could not read the inbox: {e}"
            if not msgs:
                return ("No unread messages in the inbox." if unread_only
                        else "The inbox is empty.")
            return "\n".join(
                f"{i}. [{m['uid']}] {core.truncate(m['subject'], 90)} — {core.truncate(m['from'], 60)} "
                f"({m['date']})\n   {core.truncate(m['snippet'], 140)}"
                for i, m in enumerate(msgs, 1))
        return _gmail_web_inbox_text(limit, unread_only=unread_only,
                                     mark_read=False)
    if a in ("search", "find"):
        if has_imap:
            try:
                msgs = _fetch_inbox(cfg, max(3, limit), query)
            except Exception as e:
                return f"Search failed: {e}"
            if not msgs:
                return f"No messages matching '{query}'."
            return "\n".join(f"{i}. [{m['uid']}] {core.truncate(m['subject'], 90)} — {core.truncate(m['from'], 60)}"
                             for i, m in enumerate(msgs, 1))
        return _gmail_web_inbox_text(max(3, limit), query=query)
    if a in ("read", "open"):
        if not has_imap:
            try:
                index = max(0, int(uid or 0) - (1 if str(uid or "").strip().isdigit() else 0))
            except Exception:
                index = 0
            return _gmail_web_read_text(index)
        if not uid:
            return "Give the message uid from the inbox list."
        try:
            m = _imap_connect(cfg)
            try:
                m.select("INBOX", readonly=True)
                typ, data = m.fetch(uid.encode(), "(RFC822)")
                raw = next((d[1] for d in data if isinstance(d, tuple)), None) if data else None
                if not raw:
                    return f"Could not find message {uid}."
                msg = email.message_from_bytes(raw)
                return (f"From: {_decode(msg.get('From'))}\n"
                        f"Subject: {_decode(msg.get('Subject'))}\n"
                        f"Date: {_decode(msg.get('Date'))}\n\n{_body_text(msg)[:10000]}")
            finally:
                try:
                    m.logout()
                except Exception:
                    pass
        except Exception as e:
            return f"Could not read the message: {e}"
    return f"Unknown email action '{action}'."


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------
_LANG_NAMES = {
    "urdu": "Urdu", "ur": "Urdu", "roman urdu": "Roman Urdu", "roman": "Roman Urdu",
    "english": "English", "en": "English", "hindi": "Hindi", "arabic": "Arabic",
    "french": "French", "german": "German", "spanish": "Spanish", "chinese": "Chinese",
    "japanese": "Japanese", "russian": "Russian", "turkish": "Turkish", "punjabi": "Punjabi",
    "sindhi": "Sindhi", "pashto": "Pashto", "bengali": "Bengali", "korean": "Korean",
    "italian": "Italian", "portuguese": "Portuguese", "dutch": "Dutch",
}


def translate_text(text: str, target: str = "Urdu", roman: bool = True) -> str:
    """Translate text into any language (Urdu, English, Arabic, ...)."""
    text = (text or "").strip()
    if not text:
        return "No text to translate."
    tgt = _LANG_NAMES.get((target or "urdu").lower().strip(), (target or "Urdu").strip())
    body = f"Translate the following text into {tgt}. Preserve meaning, tone and names.\n\n{text}"
    try:
        result = core.llm_text(body, system="You are an accurate professional translator. Output only the translation.",
                               smart=False, max_tokens=2000)
    except Exception as e:
        return f"Translation failed: {e}"
    out = [f"[{tgt}]", result]
    if roman and tgt in ("Urdu", "Hindi", "Punjabi", "Sindhi", "Pashto", "Bengali", "Arabic"):
        try:
            roman_text = core.llm_text(
                f"Write this {tgt} text in Roman letters (transliteration, not translation):\n\n{result}",
                system="You transliterate accurately. Output only the Roman text.", smart=False,
                max_tokens=2000)
            out += ["", "[Roman]", roman_text]
        except Exception:
            pass
    return "\n".join(out)


# --------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------
def summarize_content(text_or_url: str, length: str = "medium", open_report: bool = False) -> str:
    """Summarize a block of text, a URL, or (if a path) a local document."""
    src = (text_or_url or "").strip()
    if not src:
        return "Nothing to summarize."
    if src.lower().startswith(("http://", "https://")) or (
            "." in src and " " not in src and not os.path.exists(core.resolve_path(src))):
        from . import research
        page = research.fetch_page(src, 60000)
        if not page.get("ok"):
            return f"I could not read that page: {page.get('error', '')}"
        label, content = page.get("title") or src, page["text"]
    elif os.path.exists(core.resolve_path(src)) and os.path.isfile(core.resolve_path(src)):
        from . import documents
        label, content = os.path.basename(src), documents.read_document(src, 50000)
    else:
        label, content = "text", src
    if len(content.strip()) < 30:
        return "There is not enough text to summarize."
    size = {"short": "5 bullets", "medium": "8 bullets", "long": "12 bullets with detail"}.get(
        (length or "medium").lower(), "8 bullets")
    prompt = (
        f"Summarize the following in {size}, in Markdown.\n"
        "Include: a one-line bottom line, key points, important numbers/dates, and any action items.\n"
        "Be faithful to the source; never invent facts.\n\n"
        f"SOURCE: {label}\n\n{content[:45000]}"
    )
    try:
        summary = core.llm_text(prompt, system="You are a precise analyst. Summaries are clear and factual.",
                                smart=True, max_tokens=2000)
    except Exception as e:
        return f"Summarization failed: {e}"
    md = f"# Summary: {label}\n\n{summary}"
    if open_report:
        md_path, html_path = core.save_report("Summary - " + core.slugify(label)[:60], md, open_it=True)
        return summary + f"\n\nReport: {html_path or md_path}"
    return summary


def ask_about_content(question: str, text_or_url: str = "") -> str:
    """Answer a question about a document, page or text."""
    source = (text_or_url or "").strip()
    if source.lower().startswith(("http://", "https://")):
        from . import research
        page = research.fetch_page(source, 45000)
        material = page.get("text", "") if page.get("ok") else ""
        label = page.get("title") or source
    elif source and os.path.isfile(core.resolve_path(source)):
        from . import documents
        material = documents.read_document(source, 45000)
        label = os.path.basename(source)
    else:
        material, label = source, "the provided text"
    if not material:
        return "I need the document, URL or text to answer that."
    try:
        return core.llm_text(
            f"Answer the question using only this content. Cite sections by name when useful.\n\n"
            f"QUESTION: {question}\n\nCONTENT ({label}):\n{material[:45000]}",
            system="You are a precise research assistant. If the answer is not in the content, say so.",
            smart=True, max_tokens=1600)
    except Exception as e:
        return f"Could not answer: {e}"


# --------------------------------------------------------------------------
# Morning briefing
# --------------------------------------------------------------------------
def daily_briefing(topics: str = "world, technology, business", city: str = "",
                   speak: bool = True) -> str:
    """One spoken briefing: weather, schedule, system health and the news."""
    parts = [f"Good {('evening' if time.localtime().tm_hour >= 17 else 'morning' if time.localtime().tm_hour < 12 else 'afternoon')}, sir."]
    lines = ["# Daily Briefing", "", f"**{core.now_str()}**", ""]

    weather = ""
    try:
        fn = core.G.get("get_weather")
        if fn:
            weather = fn(city or "")
    except Exception as e:
        weather = f"Weather unavailable: {e}"
    if weather:
        parts.append("Weather: " + core.truncate(weather, 300))
        lines += ["## Weather", "", weather, ""]

    try:
        from . import agent as agent_mod
        jobs = agent_mod._load_schedule()
        soon = sorted((j for j in jobs.values() if j.get("enabled", True)),
                      key=lambda j: j.get("next") or 0)[:6]
        if soon:
            rows = ["- " + time.strftime("%a %d %b %I:%M %p", time.localtime(j.get("next") or 0))
                    + ": " + core.truncate(j.get("prompt", ""), 120) for j in soon]
            lines += ["## Schedule", ""] + rows + [""]
            parts.append(f"You have {len(soon)} scheduled item(s) coming up.")
    except Exception:
        pass

    try:
        from . import agent as agent_mod
        missions = agent_mod._load_missions()
        running = [m for m in missions.values() if m.get("status") in ("running", "planning")]
        if running:
            parts.append(f"{len(running)} mission(s) are still running.")
            lines += ["## Missions", ""] + [
                f"- {m['id']}: {core.truncate(m.get('goal',''), 120)} ({m.get('status')})" for m in running] + [""]
    except Exception:
        pass

    news = ""
    try:
        from . import research
        news = research.news_briefing(topics, speak=False)
        parts.append("In the news: " + core.truncate(news, 800))
        lines += ["## News", "", news, ""]
    except Exception as e:
        lines += ["## News", "", f"Could not fetch news: {e}", ""]

    try:
        from . import diagnostics
        checks = diagnostics.run_checks(full=False)
        bad = [c["name"] for c in checks["checks"] if not c["ok"]]
        lines += ["## System", "", ("All monitored systems nominal." if not bad
                                    else "Issues: " + ", ".join(bad)), ""]
        if bad:
            parts.append("One system needs attention: " + ", ".join(bad[:3]) + ".")
            if core.config_get("auto_repair", False):
                diagnostics.self_repair()
    except Exception:
        pass

    try:
        from . import memory
        eps = memory.recent_episodes(3)
        if eps:
            lines += ["## Recently", ""] + [
                f"- {time.strftime('%d %b', time.localtime(e.get('t', 0)))}: {core.truncate(e.get('summary',''), 200)}"
                for e in eps] + [""]
    except Exception:
        pass

    md = "\n".join(lines)
    md_path, html_path = core.save_report("Daily Briefing", md, open_it=True)
    spoken = " ".join(parts)[:1600]
    if speak:
        core.say_async(spoken)
    core.audit("daily_briefing", topics, "ok")
    return spoken + f"\n\nFull briefing: {html_path or md_path}"


def integration_operation(action: str = "briefing", text: str = "", target: str = "Urdu",
                          question: str = "", source: str = "", topics: str = "",
                          city: str = "", length: str = "medium") -> str:
    """Everyday helpers: translate, summarize, ask about a document, morning briefing.

    action:
      translate  - translate `text` into `target` (default Urdu; also gives Roman Urdu)
      summarize  - summarize `text` or `source` (URL/path)
      ask        - answer `question` about `source` (URL/path) or `text`
      briefing   - weather + schedule + system + news briefing (topics, city)
    """
    a = (action or "briefing").lower().strip()
    if a in ("translate", "tarjuma", "translate_text"):
        return translate_text(text or source, target)
    if a in ("summarize", "summary", "summarise"):
        return summarize_content(text or source, length, open_report=False)
    if a in ("ask", "question", "about"):
        return ask_about_content(question, source or text)
    if a in ("briefing", "morning", "daily"):
        return daily_briefing(topics or "world, technology, business", city)
    return f"Unknown integration action '{action}'."
