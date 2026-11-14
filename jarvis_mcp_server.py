"""Jarvis memory MCP server (stdio).

Point Claude Code, Cursor, Codex or another MCP client at:

    python jarvis_mcp_server.py

The server exposes Jarvis's long-term memory, calendar, writing style and
workspace status.  It writes protocol messages to stdout only; logs go to
stderr, exactly as the MCP stdio transport requires.
"""
from jarvis_core.mcp import serve_stdio

if __name__ == "__main__":
    serve_stdio()
