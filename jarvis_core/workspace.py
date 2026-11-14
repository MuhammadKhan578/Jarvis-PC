"""Connected work tools: GitHub, Slack, Notion, Linear and Jira.

Every adapter uses the service's own HTTPS API with a token the user pastes
into Jarvis.  Tokens are stored only in the local, git-ignored
``jarvis_data/config.json`` and are never printed back or written to logs.

No third-party SDK is required: the adapters use ``urllib`` so the module keeps
working on a stock Python install.

Public API:
    workspace_operation(...)  - the tool Gemini calls
    status_text()             - what is connected / what is missing
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import core

_SERVICES = ("github", "slack", "notion", "linear", "jira")
_WRITE_ACTIONS = {"send", "create", "comment", "append", "update", "post"}


# --------------------------------------------------------------------------- http
def _http(method: str, url: str, headers: dict | None = None,
          payload: dict | None = None, timeout: int = 25) -> tuple[int, str, dict]:
    body = None
    hdrs = {"User-Agent": "Jarvis/2.2 (+local assistant)", "Accept": "application/json"}
    hdrs.update(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = str(e)
        return e.code, text, dict(e.headers or {})
    except Exception as e:
        return 0, f"NETWORK: {e}", {}


def _json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def _short(text: str, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _api_error(service: str, status: int, text: str) -> str:
    data = _json(text) or {}
    detail = ""
    if isinstance(data, dict):
        detail = (data.get("message") or data.get("error_description")
                  or (data.get("error") if isinstance(data.get("error"), str) else "")
                  or data.get("errors") or "")
    return f"{service} API error ({status}): {_short(detail or text, 320)}"


def _llm(prompt: str, system: str = "") -> str:
    try:
        out = core.llm_text(prompt, system=system or "You are Jarvis, a precise work assistant.")
        return (out or "").strip()
    except Exception as e:
        return ""


def _summarise(label: str, text: str) -> str:
    out = _llm(
        f"Summarise this {label} for the user in 4-7 short bullet points. "
        f"Then add one line: 'Action for you:' with the single most useful next step. "
        f"Use only facts in the text; do not invent people, dates or decisions.\n\n{core.truncate(text, 12000)}"
    )
    if out:
        return out
    return "Summary model unavailable, so here is the raw text:\n" + core.truncate(text, 2500)


def _draft_reply(label: str, text: str) -> str:
    out = _llm(
        f"Write a short, professional reply to this {label}. Match the language of the source "
        f"(English or Roman Urdu), be specific, do not invent facts, and do not include a subject "
        f"line or commentary. Return only the reply body.\n\n{core.truncate(text, 9000)}"
    )
    return out or "Draft model unavailable. Configure the Gemini key, or tell me the points to include."


# ---------------------------------------------------------------------------- config
def _all() -> dict:
    raw = core.config_get("workspace", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _cfg(service: str) -> dict:
    cfg = _all().get(service) or {}
    return cfg if isinstance(cfg, dict) else {}


def _save_cfg(service: str, data: dict):
    all_cfg = _all()
    all_cfg[service] = data
    core.save_config({"workspace": all_cfg})


def _token(service: str) -> str:
    return str(_cfg(service).get("token") or "").strip()


def status_text() -> str:
    lines = []
    missing = []
    for name in _SERVICES:
        cfg = _cfg(name)
        if name == "github":
            ok = bool(cfg.get("token")) and bool(cfg.get("repo"))
            need = "token + repo (owner/name)"
        elif name == "slack":
            ok = bool(cfg.get("token"))
            need = "bot token with channels:history and chat:write"
        elif name == "notion":
            ok = bool(cfg.get("token"))
            need = "integration token + page shared with the integration"
        elif name == "linear":
            ok = bool(cfg.get("token"))
            need = "API key (+ optional team id)"
        else:
            ok = bool(cfg.get("token")) and bool(cfg.get("url")) and bool(cfg.get("email"))
            need = "base URL + account email + API token"
        lines.append(f"- {name}: " + ("connected" if ok else "not configured (" + need + ")"))
        if not ok:
            missing.append(name)
    head = "Work tools:\n" + "\n".join(lines)
    if missing:
        head += ("\nConfigure with workspace_operation(action=\"configure\", service=\"...\"). "
                 "Tokens stay in the local config only.")
    return head


def _configure(service: str, token: str, url: str, email: str, repo: str,
               project: str, channel: str) -> str:
    name = (service or "").lower().strip()
    if name not in _SERVICES:
        return "Unknown service. Use github, slack, notion, linear or jira."
    cfg = dict(_cfg(name))
    if token:
        cfg["token"] = token.strip()
    if url:
        cfg["url"] = url.strip().rstrip("/")
    if email:
        cfg["email"] = email.strip()
    if repo:
        cfg["repo"] = repo.strip()
    if project:
        cfg["project"] = project.strip()
    if channel:
        cfg["channel"] = channel.strip()
    if not cfg.get("token"):
        return f"No token saved for {name}. Call configure again with a token."
    _save_cfg(name, cfg)
    core.audit("workspace_operation", "configure", name)
    extra = []
    for key in ("repo", "url", "email", "project", "channel"):
        if cfg.get(key):
            extra.append(f"{key}={cfg[key]}")
    return f"{name} configured" + (" (" + ", ".join(extra) + ")" if extra else "") + \
        ". Token stored locally and hidden."


# ---------------------------------------------------------------------------- github
def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github(action: str, query: str, title: str, body: str, number: str,
            confirmed: bool) -> str:
    cfg = _cfg("github")
    token = _token("github")
    repo = str(cfg.get("repo") or "").strip()
    if not token:
        return "GitHub is not configured. Add a personal access token with repo scope."
    if not repo:
        return "GitHub needs a repository, e.g. 'owner/name'. Configure repo first."
    base = f"https://api.github.com/repos/{repo}"
    h = _gh_headers(token)
    num = re.sub(r"[^0-9]", "", number or query or "")

    if action in ("list", "read", "search"):
        if num and action != "search":
            st, text, _ = _http("GET", f"{base}/issues/{num}", h)
            if st != 200:
                return _api_error("GitHub", st, text)
            issue = _json(text) or {}
            head = (f"#{issue.get('number')} {issue.get('title')}\n"
                    f"State: {issue.get('state')} | by {issue.get('user', {}).get('login')} | "
                    f"{issue.get('comments', 0)} comments\n{issue.get('html_url')}\n\n"
                    f"{core.truncate(issue.get('body') or '(no description)', 4000)}")
            if action in ("summarize", "draft_reply"):
                pass
            st2, text2, _ = _http("GET", f"{base}/issues/{num}/comments?per_page=30", h)
            comments = _json(text2) or []
            thread = "\n\n".join(
                f"{c.get('user', {}).get('login', 'user')}: {c.get('body', '')}" for c in comments
                if isinstance(c, dict))
            if action == "draft_reply":
                return _draft_reply("GitHub issue thread", head + "\n\n" + thread)
            if action == "summarize":
                return _summarise("GitHub issue thread", head + "\n\n" + thread)
            if thread:
                head += "\n\nRecent comments:\n" + core.truncate(thread, 2500)
            return head

        if action == "search" or query:
            q = query or "is:open"
            if "repo:" not in q:
                q += f" repo:{repo}"
            url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
                {"q": q, "per_page": 10})
            st, text, _ = _http("GET", url, h)
            data = _json(text) or {}
            if st != 200:
                return _api_error("GitHub", st, text)
            items = data.get("items") or []
            if not items:
                return f"No GitHub issues matched '{query}' in {repo}."
            out = [f"{len(items)} result(s) in {repo}:"]
            for it in items[:10]:
                kind = "PR" if it.get("pull_request") else "issue"
                out.append(f"#{it.get('number')} [{kind}] {it.get('title')} "
                           f"({it.get('state')}, {it.get('user', {}).get('login')})")
            return "\n".join(out)

        st, text, _ = _http("GET", f"{base}/issues?state=open&per_page=15", h)
        items = _json(text) or []
        if st != 200:
            return _api_error("GitHub", st, text)
        if not items:
            return f"No open issues in {repo}."
        out = [f"Open items in {repo}:"]
        for it in items[:15]:
            kind = "PR" if it.get("pull_request") else "issue"
            out.append(f"#{it.get('number')} [{kind}] {it.get('title')} "
                       f"({it.get('user', {}).get('login')}, {it.get('comments', 0)} comments)")
        return "\n".join(out)

    if action == "create":
        if not title.strip():
            return "What should the GitHub issue title be?"
        msg = core.guard("workspace:github:create", confirmed,
                         f"Create GitHub issue in {repo}: {title}")
        if msg:
            return msg
        st, text, _ = _http("POST", f"{base}/issues", h, {"title": title, "body": body})
        data = _json(text) or {}
        if st not in (200, 201):
            return _api_error("GitHub", st, text)
        core.audit("workspace_operation", "github:create", str(data.get("number")))
        return f"GitHub issue created: #{data.get('number')} {data.get('html_url')}"

    if action == "comment":
        if not num:
            return "Which issue number should I comment on?"
        if not body.strip():
            return "What should the comment say?"
        msg = core.guard("workspace:github:comment", confirmed,
                         f"Comment on GitHub issue #{num} in {repo}")
        if msg:
            return msg
        st, text, _ = _http("POST", f"{base}/issues/{num}/comments", h, {"body": body})
        if st not in (200, 201):
            return _api_error("GitHub", st, text)
        return f"Comment posted on #{num}, sir."

    if action in ("summarize", "draft_reply"):
        return _github("read", query, title, body, num, confirmed)

    return "GitHub actions: list, search, read, summarize, draft_reply, create, comment."


# ----------------------------------------------------------------------------- slack
def _slack_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _slack_api(method: str, token: str, params: dict | None = None) -> tuple[bool, dict | str]:
    url = f"https://slack.com/api/{method}"
    st, text, _ = _http("GET" if params is None else "POST", url,
                        {**_slack_headers(token), "Content-Type": "application/json"},
                        params)
    data = _json(text)
    if st != 200:
        return False, _api_error("Slack", st, text)
    if not isinstance(data, dict):
        return False, "Slack returned an unexpected response."
    if not data.get("ok"):
        return False, f"Slack error: {data.get('error') or text}"
    return True, data


def _slack_channel(token: str, wanted: str) -> tuple[str | None, str]:
    name = (wanted or "").strip().lstrip("#")
    if re.fullmatch(r"[CGD][A-Z0-9]{6,}", name):
        return name, ""
    ok, data = _slack_api("conversations.list", token)
    if not ok:
        return None, str(data)
    channels = data.get("channels") or []
    for ch in channels:
        if (ch.get("name") or "").lower() == name.lower():
            return ch.get("id"), ""
    if name:
        for ch in channels:
            if name.lower() in (ch.get("name") or "").lower():
                return ch.get("id"), ""
    names = ", ".join("#" + str(c.get("name")) for c in channels[:25])
    return None, f"I could not find channel '{wanted}'. Available: {names or 'none visible'}"


def _slack(action: str, query: str, title: str, body: str, channel: str,
           confirmed: bool) -> str:
    token = _token("slack")
    if not token:
        return "Slack is not configured. Add a bot token (channels:history, chat:write)."
    wanted = channel or str(_cfg("slack").get("channel") or "") or query

    if action in ("send", "create", "post"):
        if not body.strip():
            return "What should I post in Slack?"
        msg = core.guard("workspace:slack:send", confirmed,
                         f"Post a Slack message to {wanted or 'the configured channel'}")
        if msg:
            return msg
        ch_id, err = _slack_channel(token, wanted)
        if not ch_id:
            return err
        ok, data = _slack_api("chat.postMessage", token, {"channel": ch_id, "text": body})
        if not ok:
            return str(data)
        core.audit("workspace_operation", "slack:send", ch_id)
        return "Message posted in Slack, sir."

    ch_id, err = _slack_channel(token, wanted)
    if not ch_id:
        return err
    ok, data = _slack_api("conversations.history", token,
                          {"channel": ch_id, "limit": 20})
    if not ok:
        return str(data)
    messages = [m for m in data.get("messages") or [] if m.get("text") and not m.get("bot_id")]
    if not messages:
        return "No recent messages in that channel."
    transcript = "\n".join(f"{m.get('user') or 'user'}: {m.get('text')}" for m in reversed(messages))
    if action == "summarize":
        return _summarise("Slack conversation", transcript)
    if action == "draft_reply":
        return _draft_reply("Slack conversation", transcript)
    return f"Recent messages in {wanted or 'the channel'}:\n" + core.truncate(transcript, 3000)


# ---------------------------------------------------------------------------- notion
def _notion_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"}


def _notion_plain(rich) -> str:
    if isinstance(rich, str):
        return rich
    if isinstance(rich, list):
        return "".join(str((r or {}).get("plain_text") or (r or {}).get("text", {}).get("content", ""))
                       for r in rich if isinstance(r, dict))
    return ""


def _notion_id(text: str) -> str:
    m = re.search(r"([0-9a-f]{32})", (text or "").replace("-", ""), re.I)
    return m.group(1) if m else (text or "").strip()


def _notion_page_text(token: str, page_id: str) -> tuple[bool, str]:
    st, text, _ = _http("GET", f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
                        _notion_headers(token))
    data = _json(text) or {}
    if st != 200:
        return False, _api_error("Notion", st, text)
    lines = []
    for block in data.get("results") or []:
        kind = block.get("type")
        payload = block.get(kind) or {}
        piece = _notion_plain(payload.get("rich_text") or payload.get("title"))
        if piece:
            lines.append(piece)
    return True, "\n".join(lines)


def _notion(action: str, query: str, title: str, body: str, confirmed: bool) -> str:
    token = _token("notion")
    if not token:
        return "Notion is not configured. Add an integration token and share the page with it."
    h = _notion_headers(token)

    if action == "search":
        st, text, _ = _http("POST", "https://api.notion.com/v1/search", h,
                            {"query": query or "", "page_size": 10})
        data = _json(text) or {}
        if st != 200:
            return _api_error("Notion", st, text)
        results = data.get("results") or []
        if not results:
            return f"No Notion pages matched '{query}'."
        out = ["Notion results:"]
        for r in results[:10]:
            title_text = _notion_plain(((r.get("properties") or {}).get("title") or {}).get("title"))
            if not title_text and r.get("object") == "database":
                title_text = _notion_plain(r.get("title"))
            out.append(f"- {title_text or '(untitled)'}  id={_notion_id(r.get('id', ''))}")
        return "\n".join(out)

    page_id = _notion_id(query)
    if action in ("read", "summarize", "draft_reply", "list"):
        if not page_id:
            return _notion("search", query, title, body, confirmed)
        ok, page_text = _notion_page_text(token, page_id)
        if not ok:
            return page_text
        if action == "summarize":
            return _summarise("Notion page", page_text)
        if action == "draft_reply":
            return _draft_reply("Notion page", page_text)
        return core.truncate(page_text, 4000) or "That page has no readable text blocks."

    if action == "create":
        if not page_id:
            return "Which Notion parent page id should the new page go inside?"
        if not title.strip():
            return "What should the Notion page title be?"
        msg = core.guard("workspace:notion:create", confirmed,
                         f"Create a Notion page '{title}' inside {page_id}")
        if msg:
            return msg
        children = []
        for line in (body or "").splitlines():
            if line.strip():
                children.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line[:1900]}}]}
                })
        payload = {
            "parent": {"page_id": page_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        if children:
            payload["children"] = children[:80]
        st, text, _ = _http("POST", "https://api.notion.com/v1/pages", h, payload)
        data = _json(text) or {}
        if st not in (200, 201):
            return _api_error("Notion", st, text)
        core.audit("workspace_operation", "notion:create", str(data.get("id", "")))
        return f"Notion page created: {data.get('url') or data.get('id')}"

    if action == "append":
        if not page_id or not body.strip():
            return "Give me the page id and the text to append."
        msg = core.guard("workspace:notion:append", confirmed, f"Append text to Notion page {page_id}")
        if msg:
            return msg
        children = [{
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": body[:1900]}}]},
        }]
        st, text, _ = _http("PATCH", f"https://api.notion.com/v1/blocks/{page_id}/children", h,
                            {"children": children})
        if st != 200:
            return _api_error("Notion", st, text)
        return "Text appended to the Notion page, sir."

    if action == "comment":
        if not page_id or not body.strip():
            return "Give me the page id and the comment text."
        msg = core.guard("workspace:notion:comment", confirmed, f"Comment on Notion page {page_id}")
        if msg:
            return msg
        st, text, _ = _http("POST", "https://api.notion.com/v1/comments", h, {
            "parent": {"page_id": page_id},
            "rich_text": [{"type": "text", "text": {"content": body[:1900]}}],
        })
        if st != 200:
            return _api_error("Notion", st, text)
        return "Comment added to the Notion page, sir."

    return "Notion actions: search, read, summarize, create, append, comment."


# ---------------------------------------------------------------------------- linear
def _linear_graphql(token: str, query: str, variables: dict | None = None) -> tuple[bool, dict | str]:
    st, text, _ = _http("POST", "https://api.linear.app/graphql",
                        {"Authorization": token, "Content-Type": "application/json"},
                        {"query": query, "variables": variables or {}})
    data = _json(text)
    if st != 200:
        return False, _api_error("Linear", st, text)
    if not isinstance(data, dict):
        return False, "Linear returned an unexpected response."
    if data.get("errors"):
        first = data["errors"][0] if isinstance(data["errors"], list) else data["errors"]
        return False, "Linear error: " + _short(str(first), 300)
    return True, data.get("data") or {}


def _linear(action: str, query: str, title: str, body: str, confirmed: bool) -> str:
    token = _token("linear")
    if not token:
        return "Linear is not configured. Add an API key."
    gql_issues = """
    query Issues($first: Int, $filter: IssueFilter) {
      issues(first: $first, filter: $filter, orderBy: updatedAt) {
        nodes { identifier title state { name } assignee { name } url }
      }
    }"""
    if action in ("list", "read", "search", "summarize", "draft_reply"):
        ok, data = _linear_graphql(token, gql_issues, {"first": 20})
        if not ok:
            return str(data)
        nodes = ((data.get("issues") or {}).get("nodes") or [])
        if query:
            q = query.lower()
            nodes = [n for n in nodes if q in (n.get("title") or "").lower()
                     or q in (n.get("identifier") or "").lower()]
        if not nodes:
            return "No Linear issues matched."
        lines = [f"{n.get('identifier')} [{n.get('state', {}).get('name')}] {n.get('title')} "
                 f"({(n.get('assignee') or {}).get('name') or 'unassigned'})" for n in nodes]
        if action == "summarize":
            return _summarise("Linear issue list", "\n".join(lines))
        if action == "draft_reply":
            return _draft_reply("Linear issue", "\n".join(lines))
        return "Linear issues:\n" + "\n".join(lines)

    if action == "create":
        if not title.strip():
            return "What should the Linear issue title be?"
        team_id = str(_cfg("linear").get("project") or "").strip()
        if not team_id:
            ok, data = _linear_graphql(token, "query { teams(first: 5) { nodes { id name } } }")
            if not ok:
                return str(data)
            teams = ((data.get("teams") or {}).get("nodes") or [])
            if not teams:
                return "No Linear team is visible for this API key."
            team_id = teams[0]["id"]
        msg = core.guard("workspace:linear:create", confirmed, f"Create Linear issue: {title}")
        if msg:
            return msg
        mutation = """
        mutation Create($input: IssueCreateInput!) {
          issueCreate(input: $input) { success issue { identifier title url } }
        }"""
        ok, data = _linear_graphql(token, mutation,
                                   {"input": {"teamId": team_id, "title": title, "description": body}})
        if not ok:
            return str(data)
        issue = ((data.get("issueCreate") or {}).get("issue") or {})
        core.audit("workspace_operation", "linear:create", str(issue.get("identifier", "")))
        return f"Linear issue created: {issue.get('identifier')} {issue.get('url')}"

    if action == "comment":
        ident = (query or title or "").strip().upper()
        if not ident or not body.strip():
            return "Give me the Linear issue identifier (e.g. ENG-12) and the comment text."
        ok, data = _linear_graphql(token,
                                   "query Find($term: String!) { issueSearch(query: $term, first: 5) "
                                   "{ nodes { id identifier } } }", {"term": ident})
        if not ok:
            return str(data)
        nodes = ((data.get("issueSearch") or {}).get("nodes") or [])
        if not nodes:
            return f"I could not find Linear issue {ident}."
        msg = core.guard("workspace:linear:comment", confirmed, f"Comment on Linear issue {ident}")
        if msg:
            return msg
        mutation = """
        mutation Comment($input: CommentCreateInput!) {
          commentCreate(input: $input) { success }
        }"""
        ok, data = _linear_graphql(token, mutation, {"input": {"issueId": nodes[0]["id"], "body": body}})
        if not ok:
            return str(data)
        return f"Comment added to {ident}, sir."

    return "Linear actions: list, search, summarize, create, comment."


# ------------------------------------------------------------------------------ jira
def _jira_headers() -> dict:
    cfg = _cfg("jira")
    raw = f"{cfg.get('email')}:{cfg.get('token')}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
        "Accept": "application/json",
    }


def _adf(text: str) -> dict:
    paragraphs = []
    for line in (text or "").splitlines():
        paragraphs.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": line}] if line else [],
        })
    return {"type": "doc", "version": 1, "content": paragraphs or [{"type": "paragraph", "content": []}]}


def _jira_base() -> str:
    return str(_cfg("jira").get("url") or "").rstrip("/")


def _jira(action: str, query: str, title: str, body: str, confirmed: bool) -> str:
    base = _jira_base()
    if not _token("jira") or not base or not _cfg("jira").get("email"):
        return "Jira is not configured. Add base URL, account email and API token."
    if not base.startswith("http"):
        base = "https://" + base
    h = _jira_headers()

    if action in ("list", "read", "search", "summarize", "draft_reply"):
        jql = query if (query and re.search(r"\b(ORDER BY|=|~|AND|OR)\b", query, re.I)) else (
            f'text ~ "{query}" ORDER BY updated DESC' if query else "ORDER BY updated DESC")
        url = base + "/rest/api/3/search?" + urllib.parse.urlencode(
            {"jql": jql, "maxResults": 10, "fields": "summary,status,assignee,updated"})
        st, text, _ = _http("GET", url, h)
        data = _json(text) or {}
        if st != 200:
            return _api_error("Jira", st, text)
        issues = data.get("issues") or []
        if not issues:
            return f"No Jira issues matched '{query}'."
        lines = []
        for it in issues[:10]:
            f = it.get("fields") or {}
            lines.append(f"{it.get('key')} [{f.get('status', {}).get('name')}] {f.get('summary')} "
                         f"({(f.get('assignee') or {}).get('displayName') or 'unassigned'})")
        if action == "summarize":
            return _summarise("Jira issue list", "\n".join(lines))
        if action == "draft_reply":
            return _draft_reply("Jira issue", "\n".join(lines))
        return "Jira issues:\n" + "\n".join(lines)

    if action == "create":
        project = str(_cfg("jira").get("project") or "").strip()
        if not project:
            return "Jira needs a project key. Configure project first."
        if not title.strip():
            return "What should the Jira issue summary be?"
        msg = core.guard("workspace:jira:create", confirmed, f"Create Jira issue in {project}: {title}")
        if msg:
            return msg
        payload = {"fields": {
            "project": {"key": project},
            "summary": title,
            "issuetype": {"name": "Task"},
            "description": _adf(body),
        }}
        st, text, _ = _http("POST", base + "/rest/api/3/issue", h, payload)
        data = _json(text) or {}
        if st not in (200, 201):
            return _api_error("Jira", st, text)
        core.audit("workspace_operation", "jira:create", str(data.get("key", "")))
        return f"Jira issue created: {data.get('key')} {base}/browse/{data.get('key')}"

    if action == "comment":
        key = (query or title or "").strip().upper()
        if not key or not body.strip():
            return "Give me the Jira issue key (e.g. ABC-12) and the comment text."
        msg = core.guard("workspace:jira:comment", confirmed, f"Comment on Jira issue {key}")
        if msg:
            return msg
        st, text, _ = _http("POST", base + f"/rest/api/3/issue/{key}/comment", h,
                            {"body": _adf(body)})
        if st not in (200, 201):
            return _api_error("Jira", st, text)
        return f"Comment added to {key}, sir."

    return "Jira actions: list, search, summarize, create, comment."


# ------------------------------------------------------------------------------ tool
def workspace_operation(action: str = "status", service: str = "", query: str = "",
                        title: str = "", body: str = "", repo: str = "", channel: str = "",
                        number: str = "", token: str = "", url: str = "", email: str = "",
                        project: str = "", confirmed: bool = False) -> str:
    """Work with GitHub, Slack, Notion, Linear and Jira through their real APIs.

    action:
      status      - show which services are connected
      configure   - save credentials for a service (service, token, plus repo/url/email/project/channel)
      list        - list recent open issues / messages / pages
      search      - search a service (query)
      read        - read one item (GitHub issue number, Notion page id, or list)
      summarize   - summarise a thread, page or issue list
      draft_reply - draft a reply to a thread in the user's style
      send        - post a Slack message (channel, body)
      create      - create a GitHub/Jira/Linear issue or a Notion page (title, body)
      comment     - comment on a GitHub/Jira/Linear/Notion item (number/query, body)
      append      - append text to a Notion page (query=page id, body)

    Writes ask for confirmation in safe mode. Tokens are never returned.
    """
    a = (action or "status").strip().lower()
    svc = (service or "").strip().lower()

    if a in ("status", "help", "services"):
        text = status_text()
        if svc in _SERVICES:
            text += "\n\n" + _service_help(svc)
        return text

    if a in ("configure", "setup", "connect"):
        return _configure(svc, token, url, email, repo, project, channel)

    if svc not in _SERVICES:
        return "Choose a service: github, slack, notion, linear or jira."

    try:
        if svc == "github":
            return _github(a, query, title, body, number, confirmed)
        if svc == "slack":
            return _slack(a, query, title, body, channel, confirmed)
        if svc == "notion":
            return _notion(a, query, title, body, confirmed)
        if svc == "linear":
            return _linear(a, query, title, body, confirmed)
        return _jira(a, query, title, body, confirmed)
    except Exception as e:
        core.log(f"workspace {svc}/{a} failed: {e}")
        return f"{svc} request failed: {e}"


def _service_help(name: str) -> str:
    return {
        "github": ("GitHub setup: create a fine-grained token with Issues read/write for the repo, then "
                   "configure service=github, token=..., repo=owner/name."),
        "slack": ("Slack setup: create a bot, add channels:history, channels:read, chat:write, "
                  "invite the bot to the channel, then configure service=slack, token=xoxb-..."),
        "notion": ("Notion setup: create an internal integration, copy its token, share the page/database "
                   "with the integration, then configure service=notion, token=secret_..."),
        "linear": ("Linear setup: Settings > API > personal API key. Optional project=<team id>. "
                   "Then configure service=linear, token=lin_api_..."),
        "jira": ("Jira setup: use an API token from id.atlassian.com, then configure service=jira, "
                 "url=https://yourteam.atlassian.net, email=you@example.com, token=..., project=KEY."),
    }.get(name, "")
