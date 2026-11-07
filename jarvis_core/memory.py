"""Long-term memory 2.0 plus a permanent verbatim archive and exact recall.

Three layers:
  1. profile/facts/episodes  - structured, searchable knowledge about the user
  2. pins                    - explicit "never forget this" memories
  3. archive.jsonl           - append-only record of every exchange, never trimmed
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
from collections import deque

from . import core

MEMORY_FILE = os.path.join(core.DATA_DIR, "memory_v2.json")
LEGACY_FILE = os.path.join(core.BASE_DIR, "jarvis_memory.json")
ARCHIVE_FILE = os.path.join(core.DATA_DIR, "archive.jsonl")
BACKUP_DIR = os.path.join(core.DATA_DIR, "memory_backups")
_LOCK = threading.RLock()
_ARCHIVE_LOCK = threading.RLock()
_LEARNING = threading.Event()
_CACHE = None
_COUNTER = {"turns": 0}
_ARCHIVE_CACHE = {"size": -1, "mtime": 0.0, "records": []}
_LAST_ARCHIVE = {"t": 0.0, "role": "", "text": ""}

_QUERY_STOP = {
    "what", "when", "where", "why", "who", "which", "how", "did", "do", "does",
    "the", "a", "an", "i", "me", "my", "mine", "you", "your", "we", "our",
    "about", "tell", "say", "said", "remember", "recall", "please", "that",
    "this", "it", "is", "was", "were", "are", "to", "of", "in", "on", "for",
    "kya", "kia", "tha", "thi", "the", "hai", "hain", "ko", "ka", "ki", "ke",
    "se", "mein", "main", "mujhe", "mera", "meri", "tumhe", "tum", "aap",
    "batao", "bata", "yaad", "kuch", "koi", "aur", "par", "liye",
}


def _empty():
    return {
        "version": 2,
        "created": time.time(),
        "profile": {},
        "facts": {},
        "episodes": [],
        "pins": [],
        "meta": {"turns": 0, "learned": 0},
    }


def _load_raw():
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        data = core.read_json(MEMORY_FILE, None)
        if not isinstance(data, dict):
            data = _empty()
            # migrate the old flat jarvis_memory.json
            legacy = core.read_json(LEGACY_FILE, {})
            if isinstance(legacy, dict):
                for k, v in legacy.items():
                    if isinstance(v, (str, int, float, bool)):
                        data["facts"][_norm_key(k)] = {
                            "value": str(v)[:800],
                            "category": "general",
                            "importance": 3,
                            "created": time.time(),
                            "updated": time.time(),
                            "hits": 0,
                        }
        for k, default in _empty().items():
            data.setdefault(k, default)
        if not isinstance(data.get("facts"), dict):
            data["facts"] = {}
        if not isinstance(data.get("profile"), dict):
            data["profile"] = {}
        if not isinstance(data.get("episodes"), list):
            data["episodes"] = []
        if not isinstance(data.get("pins"), list):
            data["pins"] = []
        if not isinstance(data.get("meta"), dict):
            data["meta"] = {"turns": 0, "learned": 0}
        data["meta"].setdefault("turns", 0)
        data["meta"].setdefault("learned", 0)
        _CACHE = data
        return data


def _save(data=None):
    global _CACHE
    with _LOCK:
        data = data if data is not None else _CACHE
        if data is None:
            return
        core.write_json(MEMORY_FILE, data)
        # mirror simple facts to the legacy file so the original context still sees them
        try:
            flat = {}
            for k, v in data.get("facts", {}).items():
                flat[k] = v.get("value", "")
            core.write_json(LEGACY_FILE, flat)
        except Exception:
            pass


def _norm_key(key: str) -> str:
    k = re.sub(r"[^\w\s-]+", "", (key or "").strip().lower(), flags=re.UNICODE)
    k = re.sub(r"[\s-]+", "_", k).strip("_")
    return k[:80] or "note"


def _tokens(text: str):
    return {w for w in re.findall(r"[a-z0-9\u0600-\u06FF]{2,}", (text or "").lower())}


# --------------------------------------------------------------------------
# Permanent verbatim archive
# --------------------------------------------------------------------------
def _clean_text(text, limit: int = 20000) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", str(text or "")).strip()
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text[:limit]


def archive(role: str, text: str, kind: str = "message", tags=None) -> None:
    """Append one message to the permanent archive.  Never trims, never rotates."""
    text = _clean_text(text)
    if not text:
        return
    now = time.time()
    with _ARCHIVE_LOCK:
        if (role == _LAST_ARCHIVE["role"] and text == _LAST_ARCHIVE["text"]
                and now - _LAST_ARCHIVE["t"] < 8):
            return
        try:
            os.makedirs(core.DATA_DIR, exist_ok=True)
            rec = {
                "id": f"{int(now * 1000)}-{os.getpid()}",
                "t": now,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "role": str(role or "note")[:20],
                "kind": str(kind or "message")[:20],
                "text": text,
                "tags": list(tags or [])[:12] if isinstance(tags, (list, tuple, set)) else [],
            }
            with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
        except Exception as e:
            core.log(f"archive write failed: {e}")
            return
        _LAST_ARCHIVE.update({"t": now, "role": role, "text": text})
        _ARCHIVE_CACHE["size"] = -1


def archive_user(text: str) -> None:
    archive("user", text)


def archive_assistant(text: str) -> None:
    archive("assistant", text)


def ensure_archive() -> str:
    """Create the permanent archive file if it does not exist yet."""
    try:
        os.makedirs(core.DATA_DIR, exist_ok=True)
        with open(ARCHIVE_FILE, "a", encoding="utf-8"):
            pass
        return ARCHIVE_FILE
    except Exception as e:
        core.log(f"archive create failed: {e}")
        return ""


def _load_archive(force: bool = False) -> list[dict]:
    try:
        st = os.stat(ARCHIVE_FILE)
    except OSError:
        return []
    with _ARCHIVE_LOCK:
        if (not force and _ARCHIVE_CACHE["size"] == st.st_size
                and _ARCHIVE_CACHE["mtime"] == st.st_mtime):
            return _ARCHIVE_CACHE["records"]
        records = []
        try:
            with open(ARCHIVE_FILE, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict) or not rec.get("text"):
                        continue
                    rec["_toks"] = _tokens(
                        f"{rec.get('role', '')} {rec.get('text', '')} {rec.get('tags', '')}")
                    records.append(rec)
        except Exception as e:
            core.log(f"archive read failed: {e}")
            return []
        _ARCHIVE_CACHE.update({"size": st.st_size, "mtime": st.st_mtime, "records": records})
        return records


def _archive_stats_dict() -> dict:
    records = _load_archive()
    try:
        size = os.path.getsize(ARCHIVE_FILE)
    except OSError:
        size = 0
    first = records[0].get("time", "") if records else ""
    last = records[-1].get("time", "") if records else ""
    return {
        "messages": len(records),
        "user": sum(1 for r in records if r.get("role") == "user"),
        "assistant": sum(1 for r in records if r.get("role") == "assistant"),
        "bytes": size,
        "first": first,
        "last": last,
    }


def archive_stats() -> str:
    data = _load_raw()
    a = _archive_stats_dict()
    return (
        f"Permanent memory archive: {a['messages']} messages "
        f"({a['user']} from you, {a['assistant']} from Jarvis), "
        f"{a['bytes'] / 1024:.1f} KB.\n"
        f"- Pinned memories: {len(data.get('pins', []))}\n"
        f"- Facts: {len(data.get('facts', {}))}  |  Episodes: {len(data.get('episodes', []))}\n"
        f"- Archive starts: {a['first'] or '(empty)'}\n"
        f"- Last message: {a['last'] or '(empty)'}\n"
        f"- File: {ARCHIVE_FILE}"
    )


def _search_archive(query: str, limit: int = 6, exclude_last: bool = True) -> list[dict]:
    q_raw = _tokens(query)
    q = q_raw - _QUERY_STOP
    if not q:
        q = q_raw
    ql = (query or "").lower().strip()
    if not q and not ql:
        return []
    records = _load_archive()
    if exclude_last and records:
        records = records[:-1]
    if not records:
        return []
    df = {t: 0 for t in q}
    for r in records:
        toks = r.get("_toks") or set()
        for t in q:
            if t in toks:
                df[t] += 1
    n = max(1, len(records))
    idf = {t: math.log(1.0 + n / (1.0 + df[t])) for t in q}
    now = time.time()
    scored = []
    for r in records:
        text_l = (r.get("text") or "").lower()
        toks = r.get("_toks") or set()
        overlap = q & toks
        if not overlap and (not ql or ql not in text_l):
            continue
        score = sum(2.0 + 1.3 * idf.get(t, 0.0) for t in overlap)
        if ql and len(ql) >= 3 and ql in text_l:
            score += 8.0
        age_days = max(0.0, (now - float(r.get("t") or 0)) / 86400.0)
        score += max(0.0, 2.0 - age_days / 45.0)
        if r.get("role") == "user":
            score += 0.4
        if r.get("kind") == "pin":
            score += 1.5
        if score >= 2.0:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, r in scored[:max(1, int(limit))]:
        out.append({
            "t": r.get("t", 0),
            "time": r.get("time", ""),
            "role": r.get("role", ""),
            "text": r.get("text", ""),
            "score": round(score, 2),
        })
    return out


# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------
def save_fact(key: str, value: str, category: str = "general", importance: int = 3) -> str:
    key = _norm_key(key)
    value = re.sub(r"\s+", " ", str(value or "")).strip()[:2000]
    if not key or not value:
        return "No memory key or value given."
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3
    with _LOCK:
        data = _load_raw()
        now = time.time()
        existing = data["facts"].get(key)
        if existing:
            existing.update({"value": value, "category": category or existing.get("category", "general"),
                             "importance": importance, "updated": now})
        else:
            data["facts"][key] = {"value": value, "category": category or "general",
                                  "importance": importance, "created": now, "updated": now, "hits": 0}
        if category in ("identity", "profile") and key in ("name", "user_name", "city", "age", "occupation"):
            data["profile"][key] = value
        data["meta"]["learned"] = data["meta"].get("learned", 0) + 1
        _save(data)
    return f"Remembered: {key} = {value}"


def forget_fact(key: str) -> str:
    key = _norm_key(key)
    with _LOCK:
        data = _load_raw()
        if key in data["facts"]:
            del data["facts"][key]
            data["profile"].pop(key, None)
            _save(data)
            return f"Forgot: {key}"
        close = [k for k in data["facts"] if key and (key in k or k in key)]
        if close:
            for k in close[:1]:
                del data["facts"][k]
            _save(data)
            return f"Forgot: {close[0]}"
    return f"No memory named '{key}'."


def search(query: str, limit: int = 8) -> list[dict]:
    data = _load_raw()
    q = _tokens(query)
    ql = (query or "").lower().strip()
    scored = []
    for key, item in data.get("facts", {}).items():
        text = f"{key} {item.get('value','')} {item.get('category','')}".lower()
        toks = _tokens(text)
        overlap = len(q & toks)
        score = overlap * 2.0
        if ql and (ql in text or key in ql):
            score += 4.0
        try:
            import difflib
            score += max(0.0, difflib.SequenceMatcher(None, ql, key).ratio() - 0.55) * 5
        except Exception:
            pass
        score += float(item.get("importance", 3)) * 0.35
        score += min(1.0, float(item.get("hits", 0)) * 0.05)
        if score > 0.8:
            scored.append((score, key, item))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, key, item in scored[: max(1, int(limit))]:
        item["hits"] = int(item.get("hits", 0)) + 1
        out.append({"key": key, "value": item.get("value", ""), "category": item.get("category", ""),
                    "importance": item.get("importance", 3), "score": round(score, 2)})
    if out:
        _save(data)
    return out


def add_episode(summary: str, tags="", importance: int = 2) -> str:
    summary = re.sub(r"\s+", " ", str(summary or "")).strip()[:900]
    if not summary:
        return "Nothing to remember."
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,;]+", tags) if t.strip()]
    with _LOCK:
        data = _load_raw()
        data["episodes"].append({"t": time.time(), "summary": summary, "tags": tags[:8],
                                 "importance": max(1, min(5, int(importance or 2)))})
        data["episodes"] = data["episodes"][-2000:]
        _save(data)
    return "Episode saved."


def recent_episodes(n: int = 5) -> list[dict]:
    data = _load_raw()
    eps = list(data.get("episodes", []))
    eps.sort(key=lambda e: e.get("t", 0), reverse=True)
    return eps[: max(1, int(n))]


# --------------------------------------------------------------------------
# Pins: "never forget this"
# --------------------------------------------------------------------------
def remember_exact(text: str, tags="", importance: int = 5) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()[:8000]
    if not text:
        return "Nothing to remember."
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,;]+", tags) if t.strip()]
    with _LOCK:
        data = _load_raw()
        data["pins"].append({
            "t": time.time(),
            "text": text,
            "tags": tags[:12],
            "importance": max(1, min(5, int(importance or 5))),
        })
        _save(data)
    return f"Pinned permanently: {core.truncate(text, 200)}"


def list_pins(n: int = 20) -> list[dict]:
    data = _load_raw()
    return list(reversed(data.get("pins", [])))[:max(1, int(n))]


def search_pins(query: str = "", limit: int = 5) -> list[dict]:
    data = _load_raw()
    pins = data.get("pins", [])
    if not query:
        return list(reversed(pins))[:max(1, int(limit))]
    q = _tokens(query) - _QUERY_STOP
    if not q:
        q = _tokens(query)
    ql = (query or "").lower().strip()
    scored = []
    for p in pins:
        text = (p.get("text") or "")
        toks = _tokens(text)
        overlap = q & toks
        score = len(overlap) * 2.5
        if ql and len(ql) >= 3 and ql in text.lower():
            score += 6.0
        score += float(p.get("importance", 5)) * 0.35
        if score >= 2.0:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:max(1, int(limit))]]


def recall_all(query: str, limit: int = 10) -> str:
    query = (query or "").strip()
    if not query:
        return memory_stats()
    lines = []
    pins = search_pins(query, 5)
    for p in pins:
        when = time.strftime("%d %b %Y %H:%M", time.localtime(p.get("t", 0)))
        lines.append(f"[PINNED {when}] {p.get('text', '')}")
    facts = search(query, 6)
    for h in facts:
        lines.append(f"[FACT] {h['key']}: {h['value']}")
    arch = _search_archive(query, limit)
    for a in arch:
        lines.append(f"[{a['time']} {a['role']}] {core.truncate(a['text'], 500)}")
    if not lines:
        return f"I searched facts, pins and the permanent archive, sir. Nothing matched '{query}'."
    return f"Memory recall for '{query}':\n" + "\n".join(lines[:max(1, int(limit)) + 8])


def timeline(query: str = "", limit: int = 12) -> str:
    if query:
        hits = _search_archive(query, limit, exclude_last=False)
        if hits:
            return "Timeline matching '{0}':\n".format(query) + "\n".join(
                f"- {h['time']} [{h['role']}] {core.truncate(h['text'], 400)}" for h in hits)
    records = _load_archive()
    records = records[-max(1, int(limit)):]
    if not records:
        return "The permanent archive is empty."
    return "Recent timeline:\n" + "\n".join(
        f"- {r.get('time', '')} [{r.get('role', '')}] {core.truncate(r.get('text', ''), 400)}"
        for r in records)


def overview() -> str:
    data = _load_raw()
    facts = data.get("facts", {})
    pins = data.get("pins", [])
    stats = _archive_stats_dict()
    if not facts and not pins and not data.get("episodes") and not stats["messages"]:
        return "No long-term memories saved yet."
    by_cat = {}
    for k, v in facts.items():
        by_cat.setdefault(v.get("category", "general"), []).append((k, v.get("value", "")))
    lines = [f"Long-term memory: {len(facts)} facts, {len(pins)} pinned, "
             f"{len(data.get('episodes', []))} episodes, {stats['messages']} archived messages."]
    if pins:
        lines.append("\n[Pinned memories]")
        for p in list_pins(12):
            lines.append(f"  - {time.strftime('%d %b %Y', time.localtime(p.get('t', 0)))}: "
                         f"{core.truncate(p.get('text', ''), 220)}")
    for cat in sorted(by_cat):
        items = by_cat[cat]
        lines.append(f"\n[{cat}]")
        for k, v in sorted(items, key=lambda x: -_importance(facts, x[0]))[:12]:
            lines.append(f"  - {k}: {core.truncate(v, 160)}")
    eps = recent_episodes(5)
    if eps:
        lines.append("\nRecent episodes:")
        for e in eps:
            lines.append(f"  - {time.strftime('%d %b', time.localtime(e.get('t', 0)))}: "
                         f"{core.truncate(e.get('summary', ''), 180)}")
    return "\n".join(lines)


def memory_stats() -> str:
    data = _load_raw()
    a = _archive_stats_dict()
    return (
        f"Memory status, sir:\n"
        f"- Structured facts: {len(data.get('facts', {}))}\n"
        f"- Pinned memories: {len(data.get('pins', []))}\n"
        f"- Episodes: {len(data.get('episodes', []))}\n"
        f"- Verbatim archive: {a['messages']} messages ({a['user']} user / {a['assistant']} Jarvis)\n"
        f"- Archive size: {a['bytes'] / 1024:.1f} KB\n"
        f"- First archived: {a['first'] or '(empty)'}\n"
        f"- Latest archived: {a['last'] or '(empty)'}\n"
        f"- Archive file: {ARCHIVE_FILE}"
    )


def _importance(facts: dict, key: str) -> int:
    try:
        return int(facts.get(key, {}).get("importance", 3))
    except Exception:
        return 3


def context_for(query: str = "", limit: int = 6) -> str:
    """Compact memory block injected into every Gemini request."""
    try:
        data = _load_raw()
        facts = data.get("facts", {})
        pins = search_pins(query, 4) if query else list_pins(4)
        arch = _search_archive(query, 4) if query else []
        eps = recent_episodes(3)
        if not facts and not pins and not eps and not arch:
            return ""
        lines = []
        profile = data.get("profile", {})
        if profile:
            lines.append("Profile: " + "; ".join(f"{k}={v}" for k, v in list(profile.items())[:8]))
        if pins:
            lines.append("Pinned memories: " + " | ".join(
                f"{time.strftime('%d %b', time.localtime(p.get('t', 0)))} "
                f"{core.truncate(p.get('text', ''), 200)}" for p in pins[:4]))
        hits = search(query, limit) if query else []
        if not hits:
            ranked = sorted(facts.items(), key=lambda kv: (-_importance(facts, kv[0]), kv[0]))[:limit]
            hits = [{"key": k, "value": v.get("value", ""), "category": v.get("category", "")}
                    for k, v in ranked]
        if hits:
            lines.append("Relevant facts: " + " | ".join(
                f"{h['key']}={core.truncate(h['value'], 180)}" for h in hits[:limit]))
        if arch:
            lines.append("Relevant past conversation: " + " | ".join(
                f"{time.strftime('%d %b', time.localtime(a.get('t', 0)))} "
                f"[{a.get('role', '')}] {core.truncate(a.get('text', ''), 260)}" for a in arch))
        if eps:
            lines.append("Recent episodes: " + " | ".join(
                f"{time.strftime('%d %b', time.localtime(e.get('t', 0)))} "
                f"{core.truncate(e.get('summary', ''), 140)}" for e in eps))
        text = "\n".join(lines)
        return "[LONG-TERM MEMORY (use naturally, never recite verbatim)]\n" + core.truncate(text, 3000)
    except Exception as e:
        try:
            core.log(f"memory context failed: {e}")
        except Exception:
            pass
        return ""


# --------------------------------------------------------------------------
# Automatic learning
# --------------------------------------------------------------------------
def _conversation(role: str, text: str):
    # The permanent archive is written at the command boundary (user) and in the
    # reply wrapper (assistant), so this only maintains the legacy tail file used
    # for episode summaries.
    try:
        with open(core.CONVERSATION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "role": role, "text": core.truncate(text, 2000)},
                               ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _conversation_tail(n: int = 10) -> list[dict]:
    try:
        with open(core.CONVERSATION_FILE, "r", encoding="utf-8") as f:
            lines = deque(f, maxlen=max(2, int(n)))
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _extract_facts(user: str, assistant: str):
    prompt = (
        "Extract up to 5 DURABLE facts or important details about the user from this exchange. "
        "Include stable identity, city, work/study, projects, tools, preferences, important people, "
        "routines, goals, health, dates, numbers, decisions, promises, and specific project details. "
        "Small concrete details matter: names of apps, file names, deadlines, budgets, preferences. "
        "Ignore one-time commands, small talk, and anything purely temporary.\n\n"
        f"USER: {core.truncate(user, 1800)}\nJARVIS: {core.truncate(assistant, 1800)}\n\n"
        'Return ONLY JSON: {"facts":[{"key":"short_english_key","value":"the fact",'
        '"category":"identity|work|preference|people|routine|goal|project|health|other",'
        '"importance":1-5}]}'
    )
    data = core.llm_json(prompt, system="You are a precise memory extraction engine. Return JSON only.",
                         smart=False, fallback={"facts": []}, max_tokens=1600)
    facts = (data or {}).get("facts", []) if isinstance(data, dict) else []
    saved = []
    for f in facts[:5]:
        if not isinstance(f, dict):
            continue
        k, v = f.get("key"), f.get("value")
        if k and v:
            save_fact(str(k), str(v), str(f.get("category", "general")), int(f.get("importance", 3) or 3))
            saved.append(str(k))
    if saved:
        core.log(f"Memory learned: {', '.join(saved)}")


def _summarize_episode():
    tail = _conversation_tail(12)
    if len(tail) < 4:
        return
    text = "\n".join(f"{e.get('role','?').upper()}: {core.truncate(e.get('text',''), 700)}" for e in tail)
    prompt = (
        "Summarize this recent interaction in 1-2 sentences: what the user wanted and what Jarvis did. "
        "Focus on outcomes, decisions, promises, and details that may matter later.\n\n" + text + "\n\n"
        'Return ONLY JSON: {"summary":"...","tags":["..."],"importance":1-5}'
    )
    data = core.llm_json(prompt, system="You write short, factual episodic memories. Return JSON only.",
                         smart=False, fallback=None, max_tokens=600)
    if isinstance(data, dict) and data.get("summary"):
        add_episode(str(data["summary"]), data.get("tags", []), int(data.get("importance", 2) or 2))


def maybe_learn(user: str, assistant: str):
    """Called after each completed LLM command. Never blocks the main loop."""
    if not user or not assistant:
        return
    _conversation("user", user)
    _conversation("assistant", assistant)
    if not core.config_get("auto_learn", True):
        return
    _COUNTER["turns"] += 1
    turns = _COUNTER["turns"]
    if _LEARNING.is_set():
        return
    if turns % 4 == 0:
        def _job():
            _LEARNING.set()
            try:
                _extract_facts(user, assistant)
            finally:
                _LEARNING.clear()
        core.run_bg(_job)
    elif turns % 10 == 0:
        def _job2():
            _LEARNING.set()
            try:
                _summarize_episode()
            finally:
                _LEARNING.clear()
        core.run_bg(_job2)


# --------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------
def backup_memory(force: bool = False) -> str:
    """Copy the two irreplaceable files into a dated backup folder."""
    day = time.strftime("%Y%m%d")
    target = os.path.join(BACKUP_DIR, day)
    if os.path.isdir(target) and not force:
        return f"Today's memory backup already exists: {target}"
    try:
        # make sure the structured memory file exists and is current
        try:
            _save(_load_raw())
        except Exception as e:
            core.log(f"memory flush before backup failed: {e}")
        os.makedirs(target, exist_ok=True)
        copied = []
        for src in (MEMORY_FILE, ARCHIVE_FILE):
            if os.path.exists(src):
                dst = os.path.join(target, os.path.basename(src))
                shutil.copy2(src, dst)
                copied.append(os.path.basename(src))
        try:
            days = sorted(d for d in os.listdir(BACKUP_DIR)
                          if os.path.isdir(os.path.join(BACKUP_DIR, d)))
            for old in days[:-14]:
                shutil.rmtree(os.path.join(BACKUP_DIR, old), ignore_errors=True)
        except Exception:
            pass
        return f"Memory backed up ({', '.join(copied) or 'nothing yet'}) to {target}"
    except Exception as e:
        return f"Memory backup failed: {e}"


# --------------------------------------------------------------------------
# Tool
# --------------------------------------------------------------------------
def memory_operation(action: str = "overview", key: str = "", value: str = "",
                     category: str = "general", importance: int = 3,
                     query: str = "", limit: int = 8, confirmed: bool = False) -> str:
    """One tool for all memory actions.

    action:
      save          - save/update a durable fact (key, value, category, importance 1-5)
      remember_exact- pin a verbatim detail forever (value = text)
      pins          - list pinned memories
      search        - find structured facts relevant to a query
      recall        - search facts, pins AND the permanent verbatim archive
      timeline      - show the chronological archive (query optional)
      stats         - memory sizes and archive status
      overview      - show everything remembered
      forget        - delete one structured fact by key (archive is kept)
      episode       - save an episodic memory (value = summary, category = comma tags)
      recent        - recent episodes
      export        - write a readable memory report and open it
      backup        - copy memory + archive into a dated backup
      clear         - wipe structured facts/pins/episodes (the verbatim archive is kept)
    """
    a = (action or "overview").lower().strip()
    if a in ("save", "remember", "add", "set"):
        return save_fact(key, value, category, importance)
    if a in ("remember_exact", "pin", "never_forget", "exact", "pin_exact"):
        return remember_exact(value or key, category if category != "general" else "explicit", importance)
    if a in ("pins", "pinned", "list_pins"):
        pins = list_pins(limit)
        if not pins:
            return "No pinned memories yet."
        return "\n".join(
            f"- {time.strftime('%d %b %Y %H:%M', time.localtime(p.get('t', 0)))}: {p.get('text', '')}"
            for p in pins)
    if a in ("search", "find_facts"):
        hits = search(query or key or value, limit)
        if not hits:
            return "Nothing relevant in structured memory."
        return "\n".join(f"- {h['key']}: {h['value']} [{h['category']}, importance {h['importance']}]"
                         for h in hits)
    if a in ("recall", "find", "remember_what", "search_all"):
        return recall_all(query or key or value, limit)
    if a in ("timeline", "history", "chronology"):
        return timeline(query or key or value, limit)
    if a in ("stats", "status", "memory_status"):
        return memory_stats()
    if a in ("overview", "all", "list"):
        return overview()
    if a in ("forget", "delete", "remove"):
        return forget_fact(key or query or value)
    if a in ("episode", "log"):
        return add_episode(value or key, category, importance)
    if a in ("recent", "episodes"):
        eps = recent_episodes(limit)
        if not eps:
            return "No episodes recorded yet."
        return "\n".join(f"- {time.strftime('%d %b %H:%M', time.localtime(e.get('t', 0)))}: {e.get('summary','')}"
                         for e in eps)
    if a == "export":
        md = "# J.A.R.V.I.S. Memory Report\n\n" + overview().replace("\n", "\n\n")
        md += "\n\n## Permanent archive\n\n" + archive_stats()
        md += "\n\n## Pinned memories\n\n" + "\n".join(
            f"- {p.get('text', '')}" for p in list_pins(50))
        md_path, html_path = core.save_report("Jarvis Memory Report", md)
        return f"Memory report saved and opened: {html_path or md_path}"
    if a in ("backup", "back_up"):
        return backup_memory(force=bool(confirmed))
    if a in ("clear", "wipe", "reset"):
        msg = core.guard("memory_operation:clear", confirmed,
                         "This will erase every structured memory, pin and episode. "
                         "The permanent verbatim archive is kept.")
        if msg:
            return msg
        global _CACHE
        with _LOCK:
            _CACHE = _empty()
            _save(_CACHE)
            core.write_json(LEGACY_FILE, {})
        return ("Structured memory, pins and episodes erased. The permanent verbatim archive "
                "is still intact and searchable.")
    return f"Unknown memory action '{action}'."
