"""Model Context Protocol (MCP) support for Jarvis 2.2.

Two halves:

* **Server** - ``jarvis-memory`` exposes Jarvis's memory, calendar, persona and
  workspace status to other agents (Claude Code, Cursor, Codex, ...) over the
  standard MCP stdio transport.  Run ``python jarvis_mcp_server.py`` and point
  the other tool at that command.
* **Client** - connect to remote MCP servers that speak "streamable HTTP"
  JSON-RPC, list their tools and call them.

Nothing here opens a port or uploads anything by itself.  The server talks on
stdin/stdout; the client only calls URLs the user configured.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from . import core

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "jarvis-memory"
SERVER_VERSION = "2.2.0"

# --------------------------------------------------------------------------- server
_SERVER_TOOLS = [
    {
        "name": "jarvis_memory_search",
        "description": "Search Jarvis's long-term memory (facts, pins and archive) for a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic, person, project or phrase"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "jarvis_memory_remember",
        "description": "Save one durable fact into Jarvis's memory so it survives restarts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string"},
                "category": {"type": "string", "default": "general"},
                "importance": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                "pin": {"type": "boolean", "default": False},
            },
            "required": ["fact"],
        },
    },
    {
        "name": "jarvis_memory_overview",
        "description": "Read Jarvis's whole structured memory and pinned details.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "jarvis_calendar_upcoming",
        "description": "List Jarvis's upcoming local calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 7}},
        },
    },
    {
        "name": "jarvis_writing_style",
        "description": "Read the user's assistant personality and learned writing voice.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "jarvis_workspace_status",
        "description": "Show which work services (GitHub, Slack, Notion, Linear, Jira) are connected.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _stderr(text: str):
    try:
        sys.stderr.write("[jarvis-mcp] " + str(text) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _server_call(name: str, args: dict) -> str:
    from . import calendar_tools, memory, persona, workspace

    args = args or {}
    if name == "jarvis_memory_search":
        return memory.memory_operation("recall", query=str(args.get("query") or ""),
                                       limit=int(args.get("limit") or 8))
    if name == "jarvis_memory_remember":
        fact = str(args.get("fact") or "").strip()
        if not fact:
            raise ValueError("fact is required")
        if args.get("pin"):
            return memory.remember_exact(fact)
        return memory.save_fact(fact[:80], fact, str(args.get("category") or "general"),
                                int(args.get("importance") or 3))
    if name == "jarvis_memory_overview":
        return memory.overview()
    if name == "jarvis_calendar_upcoming":
        return calendar_tools.upcoming(int(args.get("days") or 7))
    if name == "jarvis_writing_style":
        return persona.persona_operation("show")
    if name == "jarvis_workspace_status":
        return workspace.status_text()
    raise ValueError("unknown tool: " + name)


def handle_message(message: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    method = message.get("method")
    msg_id = message.get("id")
    is_notification = "id" not in message
    params = message.get("params") or {}

    if is_notification:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Jarvis memory server. Use jarvis_memory_search first when the user refers to "
                "something from before. Save only durable facts with jarvis_memory_remember."
            ),
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": _SERVER_TOOLS})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        try:
            text = _server_call(name, args)
            return ok({"content": [{"type": "text", "text": str(text)}], "isError": False})
        except Exception as e:
            return ok({"content": [{"type": "text", "text": f"{name} failed: {e}"}], "isError": True})
    if method == "resources/list":
        return ok({"resources": [
            {"uri": "jarvis://memory/overview", "name": "Jarvis memory overview",
             "mimeType": "text/plain"},
            {"uri": "jarvis://calendar/upcoming", "name": "Upcoming calendar",
             "mimeType": "text/plain"},
        ]})
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            if uri == "jarvis://memory/overview":
                from . import memory
                text = memory.overview()
            elif uri == "jarvis://calendar/upcoming":
                from . import calendar_tools
                text = calendar_tools.upcoming(14)
            else:
                return err(-32602, f"Unknown resource: {uri}")
            return ok({"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]})
        except Exception as e:
            return err(-32603, str(e))
    if method == "prompts/list":
        return ok({"prompts": []})
    return err(-32601, f"Method not found: {method}")


def serve_stdio():
    """Run the MCP stdio server until stdin closes. Only stdout carries protocol data."""
    _stderr(f"{SERVER_NAME} {SERVER_VERSION} ready on stdio")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            response = handle_message(message)
        except Exception as e:
            _stderr("handler crash: " + str(e))
            response = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                        "error": {"code": -32603, "message": str(e)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def server_config(server_path: str = "") -> str:
    """Ready-to-paste JSON for Claude Desktop / Cursor."""
    path = server_path or core.resolve_path("jarvis_mcp_server.py")
    config = {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable or "python",
                "args": [path],
            }
        }
    }
    return json.dumps(config, indent=2)


# --------------------------------------------------------------------------- client
def _servers() -> dict:
    raw = core.config_get("mcp_servers", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _save_servers(data: dict):
    core.save_config({"mcp_servers": data})


def _parse_rpc_body(text: str):
    """Accept plain JSON or a streamable-HTTP SSE body."""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except Exception:
            return None
    payloads = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payloads.append(line[5:].strip())
    for payload in reversed(payloads):
        try:
            return json.loads(payload)
        except Exception:
            continue
    return None


def _post(url: str, token: str, message: dict, session: str = "",
          timeout: int = 25) -> tuple[int, dict, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "User-Agent": "Jarvis-MCP-Client/2.2",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if session:
        headers["mcp-session-id"] = session
    req = urllib.request.Request(url, data=json.dumps(message).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.headers), text
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = str(e)
        return e.code, dict(e.headers or {}), text
    except Exception as e:
        return 0, {}, f"NETWORK: {e}"


def _session_header(headers: dict) -> str:
    for key, value in (headers or {}).items():
        if key.lower() == "mcp-session-id":
            return str(value)
    return ""


def _rpc(server: str, method: str, params: dict | None = None, call_id: int = 2) -> dict:
    cfg = _servers().get(server) or {}
    url = str(cfg.get("url") or "").strip()
    token = str(cfg.get("token") or "").strip()
    if not url:
        raise RuntimeError(f"MCP server '{server}' is not configured.")

    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "jarvis-desktop", "version": SERVER_VERSION},
        },
    }
    status, headers, text = _post(url, token, init)
    if status == 0:
        raise RuntimeError(text)
    if status >= 400:
        raise RuntimeError(f"MCP HTTP {status}: {text[:300]}")
    session = _session_header(headers)
    init_data = _parse_rpc_body(text) or {}
    if init_data.get("error"):
        raise RuntimeError("MCP initialize failed: " + str(init_data["error"]))

    if method == "initialize":
        return init_data.get("result") or {}

    # Best-effort initialized notification; servers that do not need it ignore it.
    _post(url, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)

    message = {"jsonrpc": "2.0", "id": call_id, "method": method}
    if params is not None:
        message["params"] = params
    status, headers2, text2 = _post(url, token, message, session)
    if status == 0:
        raise RuntimeError(text2)
    if status >= 400:
        raise RuntimeError(f"MCP HTTP {status}: {text2[:300]}")
    data = _parse_rpc_body(text2) or {}
    if data.get("error"):
        raise RuntimeError("MCP error: " + str(data["error"]))
    return data.get("result") or {}


def mcp_operation(action: str = "status", server: str = "", tool: str = "",
                  arguments: str = "", url: str = "", token: str = "",
                  confirmed: bool = False) -> str:
    """Connect Jarvis to MCP servers and let other agents use Jarvis's memory.

    action:
      status       - show the built-in server and configured client servers
      config       - print the jarvis-memory server config for Claude Code / Cursor
      add_server   - save a streamable-HTTP MCP server (server=name, url, token optional)
      remove_server- delete a configured MCP server
      list_tools   - list tools exposed by a configured server
      call         - call a remote MCP tool (server, tool, arguments as a JSON object string)
      resources    - list resources exposed by a configured server

    The built-in jarvis-memory server runs with: python jarvis_mcp_server.py
    Platform note: the server is stdio-only, which is correct for desktop agents;
    phones and hosted chat apps need an HTTP bridge.
    """
    a = (action or "status").strip().lower()
    name = (server or "").strip()

    if a in ("status", "show"):
        servers = _servers()
        lines = [
            f"Built-in MCP server: {SERVER_NAME} (stdio) - python jarvis_mcp_server.py",
            f"Client servers configured: {len(servers)}",
        ]
        for sname, cfg in servers.items():
            lines.append(f"- {sname}: {cfg.get('url', 'no url')}"
                         + (" (token saved)" if cfg.get("token") else ""))
        if not servers:
            lines.append("Add one with mcp_operation(action=\"add_server\", server=..., url=...).")
        lines.append("Only streamable-HTTP MCP servers are supported by the client.")
        return "\n".join(lines)

    if a in ("config", "setup", "instructions"):
        return ("Add this to your MCP client config (Claude Desktop, Cursor, Codex):\n\n"
                + server_config())

    if a in ("add_server", "add", "connect"):
        if not name or not url:
            return "Give the server a name and its streamable-HTTP URL."
        if not url.startswith(("http://", "https://")):
            return "The MCP URL must start with http:// or https://."
        servers = _servers()
        entry = {"url": url.strip()}
        if token:
            entry["token"] = token.strip()
        elif (servers.get(name) or {}).get("token"):
            entry["token"] = servers[name]["token"]
        servers[name] = entry
        _save_servers(servers)
        core.audit("mcp_operation", "add_server", name)
        return f"MCP server '{name}' saved. Test it with action=\"list_tools\", server=\"{name}\"."

    if a in ("remove_server", "remove", "delete"):
        servers = _servers()
        if name not in servers:
            return f"No MCP server named '{name}'."
        msg = core.guard("mcp_operation:remove_server", confirmed,
                         f"Remove MCP server '{name}'")
        if msg:
            return msg
        servers.pop(name, None)
        _save_servers(servers)
        return f"MCP server '{name}' removed."

    if name not in _servers():
        return f"MCP server '{name}' is not configured. Use action=\"add_server\" first."

    try:
        if a in ("list_tools", "tools"):
            result = _rpc(name, "tools/list", {})
            tools = result.get("tools") or []
            if not tools:
                return f"'{name}' exposes no tools."
            out = [f"Tools on {name}:"]
            for item in tools[:40]:
                out.append("- " + str(item.get("name")) + ": " + _short(str(item.get("description") or ""), 160))
            return "\n".join(out)
        if a in ("resources", "list_resources"):
            result = _rpc(name, "resources/list", {})
            items = result.get("resources") or []
            if not items:
                return f"'{name}' exposes no resources."
            return "\n".join("- " + str(i.get("uri")) + " - " + str(i.get("name") or "") for i in items[:40])
        if a == "call":
            if not tool:
                return "Which MCP tool should I call?"
            args = {}
            if arguments:
                try:
                    args = json.loads(arguments)
                except Exception:
                    return "arguments must be a JSON object string, e.g. {\"query\":\"x\"}."
                if not isinstance(args, dict):
                    return "arguments must be a JSON object."
            result = _rpc(name, "tools/call", {"name": tool, "arguments": args})
            content = result.get("content") or []
            pieces = [str(c.get("text") or "") for c in content if isinstance(c, dict)]
            text_out = "\n".join(p for p in pieces if p) or json.dumps(result)[:3000]
            if result.get("isError"):
                return f"MCP tool '{tool}' reported an error:\n{text_out}"
            return text_out
    except Exception as e:
        core.log(f"mcp client {name}/{a} failed: {e}")
        return f"MCP request failed: {e}"

    return "MCP actions: status, config, add_server, remove_server, list_tools, call, resources."


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")
