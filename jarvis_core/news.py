"""News briefings without any API key.

Google News RSS is public, so this works on a fresh install (no NewsAPI or
OpenWeatherMap account like other Jarvis projects require).  Results are
cached for a few minutes so repeated questions do not hammer the feed.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET

from . import core

_CACHE = {}
_CACHE_TTL = 300  # seconds
FEED = "https://news.google.com/rss"
PARAMS = "hl=en-PK&gl=PK&ceid=PK:en"


def _fetch(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"),
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _clean_title(title: str) -> str:
    text = re.sub(r"\s+", " ", (title or "")).strip()
    # Google News appends " - Source" to most headlines.
    if " - " in text:
        text = text.rsplit(" - ", 1)[0].strip()
    return text


def _parse(xml_bytes: bytes, limit: int) -> list:
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        source = ""
        source_el = item.find("source")
        if source_el is not None and (source_el.text or "").strip():
            source = source_el.text.strip()
        title = _clean_title(title)
        if not title:
            continue
        out.append((title, source))
        if len(out) >= limit:
            break
    return out


def news_brief(topic: str = "", count: int = 5) -> str:
    """Read the latest news headlines aloud (no API key needed).

    topic: optional subject, e.g. "Pakistan", "technology", "cricket",
           "artificial intelligence". Leave empty for top headlines.
    count: how many headlines (1-8, default 5).
    """
    try:
        limit = max(1, min(8, int(count)))
    except Exception:
        limit = 5
    topic = (topic or "").strip()
    key = (topic.lower(), limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    if topic:
        url = (f"{FEED}/search?q={urllib.parse.quote(topic)}&{PARAMS}")
        heading = f'News about "{topic}":'
    else:
        url = f"{FEED}?{PARAMS}"
        heading = "Top headlines:"

    try:
        items = _parse(_fetch(url), limit)
    except Exception as e:
        core.log(f"news fetch failed: {e}")
        return f"Could not fetch the news right now: {e}"

    if not items:
        return f"No news found for {topic or 'top headlines'} right now."

    lines = [heading]
    for index, (title, source) in enumerate(items, 1):
        suffix = f" ({source})" if source else ""
        lines.append(f"{index}. {title}{suffix}")
    lines.append("Source: Google News.")
    text = "\n".join(lines)
    _CACHE[key] = (now, text)
    return text
