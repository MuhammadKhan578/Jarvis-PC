"""Web research: multi-engine search, page extraction and cited deep-research reports."""
from __future__ import annotations

import base64
import concurrent.futures
import html as htmlmod
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

from . import core

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    requests = None
    BeautifulSoup = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        s = requests.Session() if requests else None
        if s is not None:
            s.headers.update(HEADERS)
        _SESSION = s
    return _SESSION


def _get(url, timeout=12, **kwargs):
    s = _session()
    if s is None:
        raise RuntimeError("requests is not installed")
    return s.get(url, timeout=timeout, **kwargs)


def _clean(text: str) -> str:
    text = htmlmod.unescape(text or "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------
# Search engines
# --------------------------------------------------------------------------
def _ddg(query: str, n: int = 8) -> list[dict]:
    if BeautifulSoup is None:
        return []
    out = []
    try:
        r = _get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for res in soup.select(".result")[: n * 2]:
            a = res.select_one("a.result__a")
            if not a:
                continue
            href = a.get("href", "")
            if "uddg=" in href:
                try:
                    href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
                except Exception:
                    pass
            elif href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue
            snip = res.select_one(".result__snippet")
            out.append({"title": _clean(a.get_text(" ")), "url": href,
                        "snippet": _clean(snip.get_text(" ")) if snip else "", "engine": "duckduckgo"})
            if len(out) >= n:
                break
    except Exception as e:
        core.log(f"DDG search failed: {e}")
    return out


def _unwrap_bing(href: str) -> str:
    """Bing wraps results as /ck/a?...&u=a1<base64>; return the real destination."""
    try:
        if "bing.com/ck/a" not in href:
            return href
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        u = (qs.get("u") or [""])[0]
        if u.startswith("a1"):
            u = u[2:]
        if not u:
            return href
        padded = u + "=" * (-len(u) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        return decoded if decoded.startswith("http") else href
    except Exception:
        return href


def _bing(query: str, n: int = 8) -> list[dict]:
    if BeautifulSoup is None:
        return []
    out = []
    try:
        r = _get("https://www.bing.com/search", params={"q": query, "count": max(n, 10)}, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li.b_algo"):
            a = li.select_one("h2 a")
            if not a or not a.get("href", "").startswith("http"):
                continue
            href = _unwrap_bing(a["href"])
            p = li.select_one("p")
            title = _clean(a.get_text(" "))
            snippet = _clean(p.get_text(" ")) if p else ""
            if not _looks_relevant(f"{title} {snippet} {href}", query):
                continue
            out.append({"title": title, "url": href,
                        "snippet": snippet, "engine": "bing"})
            if len(out) >= n:
                break
    except Exception as e:
        core.log(f"Bing search failed: {e}")
    return out


def _looks_relevant(text: str, query: str) -> bool:
    """Reject search-engine noise (Bing sometimes returns unrelated promoted pages)."""
    q = {w for w in re.findall(r"[a-z0-9]{3,}", (query or "").lower())
         if w not in _QUESTION_STOP}
    if not q:
        return True
    t = (text or "").lower()
    return any(w in t for w in q)


def _wikipedia_search(query: str, n: int = 5) -> list[dict]:
    out = []
    try:
        r = _get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": max(1, min(n, 10)),
        }, timeout=10)
        for item in (r.json().get("query", {}).get("search", []) or []):
            title = item.get("title", "")
            out.append({
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": _clean(re.sub(r"<[^>]+>", "", item.get("snippet", ""))),
                "engine": "wikipedia",
            })
    except Exception as e:
        core.log(f"Wikipedia search failed: {e}")
    return out


def _ddgs_search(query: str, n: int = 8) -> list[dict]:
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        return []
    try:
        out = []
        with DDGS() as d:
            for r in d.text(query, max_results=max(n, 8)):
                url = r.get("href") or r.get("url") or ""
                if url:
                    out.append({"title": r.get("title", ""), "url": url,
                                "snippet": r.get("body", ""), "engine": "ddgs"})
        return out
    except Exception as e:
        core.log(f"ddgs failed: {e}")
        return []


def web_search(query: str, n: int = 8) -> list[dict]:
    """Search several engines and return de-duplicated results."""
    query = (query or "").strip()
    if not query:
        return []
    results = _ddgs_search(query, n)
    if len(results) < max(2, n // 2):
        results += _ddg(query, n)
    if not results:
        # Wikipedia is far more truthful than a bot-blocked Bing page.
        results += _wikipedia_search(query, 4)
    if not results:
        results += _bing(query, n)
    seen, clean = set(), []
    for r in results:
        u = (r.get("url") or "").strip()
        key = re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()
        if not u or key in seen:
            continue
        seen.add(key)
        clean.append(r)
    return clean[: max(1, int(n))]


# --------------------------------------------------------------------------
# Page extraction
# --------------------------------------------------------------------------
def fetch_page(url: str, max_chars: int = 18000) -> dict:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    result = {"url": url, "title": "", "text": "", "ok": False, "error": ""}
    try:
        r = _get(url, timeout=15, allow_redirects=True)
        result["url"] = r.url
        ctype = (r.headers.get("content-type") or "").lower()
        if "json" in ctype:
            text = json.dumps(r.json(), indent=2)[:max_chars]
            result.update({"text": text, "title": url, "ok": True})
            return result
        if "text/plain" in ctype or "xml" in ctype:
            result.update({"text": r.text[:max_chars], "title": url, "ok": True})
            return result
        if "html" not in ctype and "text" not in ctype:
            result["error"] = f"unsupported content type: {ctype}"
            return result

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "button",
                         "nav", "footer", "header", "aside", "menu", "dialog"]):
            tag.decompose()
        title = ""
        if soup.title:
            title = _clean(soup.title.get_text(" "))
        result["title"] = title

        candidates = []
        for sel in ("article", "main", "[role=main]", "#content", "#main", ".article", ".post-content"):
            for node in soup.select(sel):
                txt = _clean(node.get_text("\n"))
                if len(txt) > 400:
                    candidates.append(txt)
        if not candidates:
            body = soup.body or soup
            candidates.append(_clean(body.get_text("\n")))
        text = max(candidates, key=len)
        text = re.sub(r"\n{3,}", "\n\n", text)
        result["text"] = text[:max_chars]
        result["ok"] = len(result["text"]) > 200
        if not result["ok"]:
            result["error"] = "page had very little readable text"
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


def extract_links(url: str, limit: int = 40) -> list[dict]:
    try:
        r = _get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        base = r.url
        out, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(base, a["href"])
            if not href.startswith("http") or href in seen:
                continue
            seen.add(href)
            out.append({"title": _clean(a.get_text(" "))[:160], "url": href})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        core.log(f"extract_links failed: {e}")
        return []


# --------------------------------------------------------------------------
# Extractive compression (keeps research inside a sane token budget)
# --------------------------------------------------------------------------
def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])", text)
    return [p.strip() for p in parts if 40 <= len(p.strip()) <= 500]


def compress(text: str, query: str, max_chars: int = 1800) -> str:
    sents = _sentences(text)
    if not sents:
        return (text or "")[:max_chars]
    q = {w for w in re.findall(r"[a-z0-9]{3,}", query.lower())}
    scored = []
    for i, s in enumerate(sents[:220]):
        words = {w for w in re.findall(r"[a-z0-9]{3,}", s.lower())}
        overlap = len(q & words)
        score = overlap * 3.0
        score += 1.0 if i < 12 else 0.0
        if re.search(r"\b(19|20)\d{2}\b", s):
            score += 0.6
        if re.search(r"\d", s):
            score += 0.4
        if 80 <= len(s) <= 320:
            score += 0.3
        scored.append((score, i, s))
    scored.sort(reverse=True)
    chosen = sorted(scored[: max(6, max_chars // 220)], key=lambda x: x[1])
    out, size = [], 0
    for _, _, s in chosen:
        if size + len(s) > max_chars:
            break
        out.append(s)
        size += len(s) + 1
    return " ".join(out) if out else (text or "")[:max_chars]


# --------------------------------------------------------------------------
# Headlines
# --------------------------------------------------------------------------
def google_news(query: str, limit: int = 8) -> list[dict]:
    out = []
    try:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
               + "&hl=en-US&gl=US&ceid=US:en")
        r = _get(url, timeout=12)
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:limit]:
            title = _clean(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            pub = _clean(item.findtext("pubDate") or "")
            src = item.find("{*}source")
            source = _clean(src.text) if src is not None and src.text else ""
            out.append({"title": title, "url": link, "published": pub, "source": source})
    except Exception as e:
        core.log(f"Google News failed: {e}")
    return out


def wikipedia_summary(topic: str) -> str:
    topic = (topic or "").strip()
    if not topic:
        return "No topic given."
    candidates = [topic]
    try:
        for r in _wikipedia_search(topic, 3):
            t = r.get("title")
            if t and t not in candidates:
                candidates.append(t)
    except Exception:
        pass
    for title in candidates:
        try:
            r = _get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                     + urllib.parse.quote(title.replace(" ", "_")), timeout=10)
            data = r.json()
            if data.get("extract"):
                return f"{data.get('title', title)}: {data['extract']}\n{data.get('content_urls', {}).get('desktop', {}).get('page', '')}"
        except Exception:
            continue
    # last resort: a normal search
    results = web_search(topic, 4)
    if results:
        return "Wikipedia had no direct article. Top results:\n" + "\n".join(
            f"- {r['title']}: {r['url']}" for r in results)
    return f"Could not find a Wikipedia article for '{topic}'."


# --------------------------------------------------------------------------
# Deep research
# --------------------------------------------------------------------------
_DEPTHS = {
    "quick":    {"queries": 3, "pages": 4,  "words": 500,  "chars": 1200},
    "standard": {"queries": 5, "pages": 7,  "words": 900,  "chars": 1600},
    "deep":     {"queries": 7, "pages": 11, "words": 1400, "chars": 2000},
}


def _plan_queries(topic: str, n: int) -> list[str]:
    prompt = (
        f"The user wants deep research on: {json.dumps(topic)}.\n"
        f"Write {n} diverse, high-quality web search queries that together cover the topic "
        "(definition/background, latest developments, concrete data, comparisons, expert analysis, risks). "
        "Each query must be short (3-10 words), the way a person types into Google. "
        'Return ONLY JSON: {"queries":["..."]}'
    )
    data = core.llm_json(prompt, system="You are a research strategist. Return JSON only.",
                         smart=False, max_tokens=400)
    qs = []
    if isinstance(data, dict):
        for q in data.get("queries", []) or []:
            q = str(q).strip()
            if q and q.lower() not in [x.lower() for x in qs]:
                qs.append(q)
    if len(qs) < 2:
        base = _keyword_query(topic)
        qs = [base, f"{base} latest 2026", f"{base} explained", f"{base} analysis data",
              f"{base} pros and cons"]
    return qs[:n]


_QUESTION_STOP = {
    "what", "who", "when", "where", "why", "how", "which", "whose", "whom",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "from", "with", "about",
    "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "it", "its", "he", "she", "they",
    "please", "tell", "give", "find", "show", "explain", "kya", "hai", "hain", "ka",
    "ki", "ke", "ko", "se", "mein", "mujhe", "batao", "bata", "kaise", "kab", "kahan",
}


def _keyword_query(text: str, max_words: int = 9) -> str:
    """Turn a natural-language question into a compact search query."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]+", text or "")
    keep = [w for w in words if w.lower() not in _QUESTION_STOP]
    if not keep:
        return (text or "").strip()
    return " ".join(keep[:max_words])


def _score_result(r: dict, topic: str) -> float:
    q = {w for w in re.findall(r"[a-z0-9]{3,}", topic.lower())}
    text = f"{r.get('title','')} {r.get('snippet','')}".lower()
    score = sum(2.0 for w in q if w in text)
    trust = ("wikipedia.org", "reuters.com", "bbc.", "apnews.com", "nytimes.com", "theguardian.com",
             "nature.com", "science.org", "arxiv.org", "gov", "edu", "microsoft.com", "google.com",
             "who.int", "worldbank.org", "imf.org", "gartner.com", "mckinsey.com")
    if any(t in (r.get("url") or "") for t in trust):
        score += 1.5
    if any(t in (r.get("url") or "") for t in ("pinterest.", "quora.", "facebook.", "tiktok.")):
        score -= 2.0
    return score


def _build_material(pages: list[dict], topic: str, chars: int) -> str:
    blocks = []
    for i, p in enumerate(pages, 1):
        body = compress(p.get("text", ""), topic, chars)
        if len(body) < 150:
            continue
        blocks.append(f"[{i}] {p.get('title','')} — {p.get('url','')}\n{body}")
    return "\n\n".join(blocks)


def _synthesize(topic: str, material: str, depth: str, sources: list[dict]) -> str:
    cfg = _DEPTHS.get(depth, _DEPTHS["standard"])
    source_list = "\n".join(f"[{i}] {s.get('title','')} — {s.get('url','')}"
                            for i, s in enumerate(sources, 1))
    prompt = (
        f"You are J.A.R.V.I.S., writing a research report for your user.\n"
        f"TOPIC: {topic}\nDATE: {datetime.now().strftime('%d %B %Y')}\n"
        f"TARGET LENGTH: about {cfg['words']} words.\n\n"
        "Use ONLY the numbered source extracts below. Cite factual claims with [n]. "
        "If sources disagree, say so. If evidence is thin, say what is uncertain. Never invent facts or URLs.\n\n"
        "Write clean Markdown with this structure:\n"
        "# <title>\n"
        "## Executive Summary\n"
        "## Key Findings\n"
        "## Analysis\n"
        "## Risks and Uncertainties\n"
        "## Sources\n\n"
        "SOURCE EXTRACTS:\n" + material[:65000] + "\n\n"
        "SOURCE INDEX (use these exact URLs in the Sources section):\n" + source_list
    )
    try:
        report = core.llm_text(prompt, system="You are a rigorous research analyst. Cite sources precisely.",
                               smart=True, max_tokens=4600)
    except Exception as e:
        core.log(f"research synthesis failed: {e}")
        rows = ["# " + topic, "", "## Source extracts", ""]
        for i, s in enumerate(sources, 1):
            rows.append(f"### [{i}] {s.get('title','')}")
            rows.append(s.get("url", ""))
            rows.append("")
            rows.append(compress(s.get("text", ""), topic, 900))
            rows.append("")
        return "\n".join(rows)
    return report


def _spoken_summary(report: str, max_sentences: int = 3) -> str:
    m = re.search(r"##\s*Executive Summary\s*\n(.+?)(?:\n##|\Z)", report, re.S | re.I)
    text = m.group(1) if m else report
    text = re.sub(r"\[[0-9]+\]", "", text)
    text = re.sub(r"[#*_`>|]", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    sents = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sents[:max_sentences])[:700]


def _do_deep_research(topic: str, depth: str = "standard") -> dict:
    depth = (depth or "standard").lower().strip()
    if depth not in _DEPTHS:
        depth = "standard"
    cfg = _DEPTHS[depth]
    t0 = time.time()
    queries = _plan_queries(topic, cfg["queries"])
    core.log(f"Research queries: {queries}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(queries))) as ex:
        futs = [ex.submit(web_search, q, 8) for q in queries]
        try:
            for f in concurrent.futures.as_completed(futs, timeout=45):
                try:
                    results += f.result()
                except Exception:
                    pass
        except Exception as e:
            core.log(f"search batch timed out: {e}")

    # de-duplicate and score
    seen, ranked = set(), []
    for r in results:
        u = r.get("url", "")
        key = re.sub(r"^https?://(www\.)?", "", u).rstrip("/").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        r["_score"] = _score_result(r, topic)
        ranked.append(r)
    ranked.sort(key=lambda r: -r.get("_score", 0))

    picked, per_domain = [], Counter()
    for r in ranked:
        dom = urllib.parse.urlparse(r.get("url", "")).netloc.lower()
        if per_domain[dom] >= 2:
            continue
        per_domain[dom] += 1
        picked.append(r)
        if len(picked) >= cfg["pages"]:
            break

    pages = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(picked)))) as ex:
        futs = {ex.submit(fetch_page, r["url"], 20000): r for r in picked}
        try:
            for f in concurrent.futures.as_completed(futs, timeout=60):
                r = futs[f]
                try:
                    p = f.result()
                except Exception as e:
                    p = {"ok": False, "error": str(e)}
                if p.get("ok"):
                    p["title"] = p.get("title") or r.get("title", "")
                    p["snippet"] = r.get("snippet", "")
                    pages.append(p)
        except Exception as e:
            core.log(f"page batch timed out: {e}")

    if not pages:
        # fall back to snippets only
        material = "\n\n".join(
            f"[{i}] {r.get('title','')} — {r.get('url','')}\n{r.get('snippet','')}"
            for i, r in enumerate(picked, 1))
        pages = picked
    else:
        material = _build_material(pages, topic, cfg["chars"])

    report = _synthesize(topic, material, depth, pages)
    title = topic.strip().capitalize()
    md_path, html_path = core.save_report(title, report, open_it=True,
                                          subtitle=f"Deep research · {depth} · {len(pages)} sources · "
                                                   f"{time.strftime('%d %b %Y %H:%M')}")
    spoken = _spoken_summary(report)
    core.say_async("Research complete, sir. " + spoken)
    core.audit("deep_research", topic, f"{len(pages)} sources, {len(report)} chars")
    return {"topic": topic, "report": report, "spoken": spoken, "sources": len(pages),
            "md": md_path, "html": html_path, "seconds": round(time.time() - t0, 1)}


def deep_research(topic: str, depth: str = "standard", wait: bool = False) -> str:
    """Run cited multi-source research on any topic and write a report.

    depth: quick, standard or deep.  wait=False runs in the background and speaks the
    result when finished; wait=True blocks and returns the summary (use only for a
    short, urgent question).  The report is saved in Jarvis_Reports and opened.
    """
    if not (topic or "").strip():
        return "No research topic given."
    if wait:
        try:
            res = _do_deep_research(topic, depth)
            return (f"Research complete ({res['sources']} sources). {res['spoken']}\n"
                    f"Report: {res['html'] or res['md']}")
        except Exception as e:
            return f"Research failed: {e}"

    core.say_async(f"Starting deep research on {core.truncate(topic, 120)}, sir. "
                   "I will report when it is ready.")

    def _job():
        try:
            _do_deep_research(topic, depth)
        except Exception as e:
            core.log(f"deep research failed: {e}")
            core.say_async(f"Sir, the research on {core.truncate(topic, 80)} failed: {e}")

    core.run_bg(_job)
    return (f"Deep research on '{core.truncate(topic, 120)}' started in the background at {depth} depth. "
            "I will speak the findings and open the report when it is done.")


def quick_research(question: str) -> str:
    """Answer a question with a fast web lookup (2 queries, 3 pages, cited answer)."""
    question = (question or "").strip()
    if not question:
        return "No question given."
    try:
        results = []
        queries = _plan_queries(question, 3)
        core.log(f"Quick research queries: {queries}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(queries))) as ex:
            futs = [ex.submit(web_search, q, 7) for q in queries]
            try:
                for f in concurrent.futures.as_completed(futs, timeout=30):
                    try:
                        results += f.result()
                    except Exception:
                        pass
            except Exception as e:
                core.log(f"quick research search timed out: {e}")
        seen, picked = set(), []
        for r in sorted(results, key=lambda r: -_score_result(r, question)):
            key = r.get("url", "").split("#")[0]
            if key and key not in seen:
                seen.add(key)
                picked.append(r)
            if len(picked) >= 5:
                break
        pages = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(fetch_page, r["url"], 14000): r for r in picked}
            try:
                for f in concurrent.futures.as_completed(futs, timeout=35):
                    try:
                        p = f.result()
                        if p.get("ok"):
                            p["title"] = p.get("title") or futs[f].get("title", "")
                            pages.append(p)
                    except Exception:
                        pass
            except Exception as e:
                core.log(f"quick research page batch timed out: {e}")
        if not pages:
            # answer from model knowledge, clearly marked
            txt = core.llm_text(
                "Answer this question accurately and concisely. If it needs current data you do not have, "
                "say so clearly.\n\n" + question, smart=False, max_tokens=900)
            return txt
        material = _build_material(pages, question, 1400)
        prompt = (
            "Answer the user's question using ONLY these sources. Cite claims with [n]. "
            "Be direct: 4-8 short sentences or bullets. If sources disagree or evidence is thin, say so.\n\n"
            f"QUESTION: {question}\n\nSOURCES:\n{material[:22000]}"
        )
        answer = core.llm_text(prompt, system="You are JARVIS, a precise research assistant.",
                               smart=False, max_tokens=1200)
        sources = "\n".join(f"[{i}] {p.get('url','')}" for i, p in enumerate(pages, 1))
        core.save_report("Quick Research - " + question[:60],
                         f"# {question}\n\n{answer}\n\n## Sources\n{sources}", open_it=False)
        return answer + "\n\nSources:\n" + sources
    except Exception as e:
        return f"Quick research failed: {e}"


def news_briefing(topics: str = "world, technology, business", speak: bool = True) -> str:
    """Collect and summarize current headlines for the given comma-separated topics."""
    topics_list = [t.strip() for t in re.split(r"[,;]+", topics or "") if t.strip()][:5]
    if not topics_list:
        topics_list = ["world", "technology", "business"]
    items = []
    for t in topics_list:
        items += google_news(t, 6)
    if not items:
        return "I could not fetch the news right now, sir."
    # de-duplicate titles
    seen, uniq = set(), []
    for it in items:
        key = re.sub(r"\W+", "", (it.get("title") or "").lower())[:80]
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    headline_text = "\n".join(
        f"- {it['title']} ({it.get('source','')}, {it.get('published','')})"
        for it in uniq[:18])
    prompt = (
        "Write a short spoken news briefing (5-7 sentences) from these headlines. "
        "Group by theme, mention the source, and avoid speculation. End with one sentence on what to watch.\n\n"
        + headline_text
    )
    try:
        briefing = core.llm_text(prompt, system="You are a calm, precise news anchor.", smart=False,
                                 max_tokens=900)
    except Exception:
        briefing = "Here are the main headlines, sir:\n" + "\n".join(f"- {it['title']}" for it in uniq[:8])
    if speak:
        core.say_async(briefing)
    core.save_report("News Briefing", f"# News Briefing\n\n{briefing}\n\n## Headlines\n{headline_text}",
                     open_it=False)
    return briefing


def research_operation(action: str = "search", topic: str = "", url: str = "",
                       depth: str = "standard", wait: bool = False) -> str:
    """One tool for research actions.

    action:
      search    - web search results for topic
      fetch     - readable text of a URL
      links     - links on a page
      wikipedia - encyclopedia summary
      news      - current headlines
      deep      - full cited report (background by default)
      quick     - fast cited answer to a question
    """
    a = (action or "search").lower().strip()
    if a in ("deep", "report", "research"):
        return deep_research(topic or url, depth, wait)
    if a in ("quick", "answer", "ask"):
        return quick_research(topic or url)
    if a in ("search", "web"):
        results = web_search(topic or url, 8)
        if not results:
            return "No search results could be read."
        return "\n".join(f"{i}. {r['title']}\n   {r['url']}\n   {core.truncate(r.get('snippet',''), 220)}"
                         for i, r in enumerate(results, 1))
    if a in ("fetch", "read", "page"):
        p = fetch_page(url or topic, 18000)
        if not p.get("ok"):
            return f"Could not read the page: {p.get('error','unknown error')}"
        return f"{p['title']}\n{p['url']}\n\n{p['text']}"
    if a in ("links", "urls"):
        links = extract_links(url or topic)
        return "\n".join(f"- {x['title']}: {x['url']}" for x in links) if links else "No links found."
    if a in ("wikipedia", "wiki"):
        return wikipedia_summary(topic or url)
    if a in ("news", "headlines"):
        return news_briefing(topic or "world, technology, business", speak=False)
    return f"Unknown research action '{action}'."
