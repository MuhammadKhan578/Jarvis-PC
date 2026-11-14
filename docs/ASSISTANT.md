# Jarvis assistant features (v2.2.0)

This guide covers the new assistant layer added in **v2.2.0**: global dictation,
personality and writing voice, the local calendar, real work tools, and MCP.
Everything runs on your PC unless you explicitly connect a service.

---

## 1. Global dictation (any Windows app)

Say **"start dictation"** or press **Ctrl+Alt+V**. Jarvis listens and types your
speech into whichever window has focus: Outlook, Word, Slack, Discord, a browser
field, VS Code, Notepad, anything that accepts typed text.

While dictating:

| Say | Result |
|-----|--------|
| `scratch that` / `woh hata do` | delete the last sentence |
| `delete last word` | delete one word |
| `capitalize that` | Capitalise the last word |
| `uppercase that` | UPPERCASE the last sentence |
| `new paragraph` / `naya paragraph` | start a new paragraph |
| `new line` | insert a line break |
| `comma` / `period` / `question mark` | add punctuation |
| `stop dictation` / `band karo` | finish |

Notes:

- The normal Jarvis microphone pauses while dictation is active so the two do
  not fight over the device.
- Dictation needs `keyboard` (installed by `install.bat`) and
  `SpeechRecognition`/PyAudio, which the voice feature already uses.
- On systems that block global keyboard hooks, use
  `dictation_operation(action="type", text="...")` instead: it types exact text.
- Speech recognition accuracy depends on your mic and Google's recogniser; the
  audio is sent for recognition exactly like normal voice input.

---

## 2. Personality and your writing voice

Ask Jarvis to change its personality:

- *"Be more concise"* → concise style
- *"Use a professional tone"* → professional style
- *"Show my personality settings"*
- *"Learn my writing: <paste a paragraph you wrote>"*
- *"Give feedback: you are too formal, be warmer"*
- *"Rewrite this in my voice: <draft>"*

Built-in styles: `jarvis`, `professional`, `friendly`, `concise`, `mentor`,
`creative`, `custom`. A custom instruction can be saved with
`persona_operation(action="custom", text="...")`.

Your samples and feedback are stored locally in `jarvis_data/config.json` and
are injected into every Gemini request as a private style block. They are never
shown in the HUD log and never leave your PC except as part of the model request.

---

## 3. Local calendar

Events are stored in `jarvis_data/calendar.json`. No Google/Microsoft account is
required. Example commands:

- *"Meeting with Ali tomorrow 3 pm for 45 minutes"*
- *"What's on my calendar this week?"*
- *"Reschedule the Ali meeting to Friday 11 am"*
- *"Delete the dentist appointment"* (asks for confirmation in safe mode)
- *"Invite ali@example.com to the project review"*
- *"Export my calendar"* → `Jarvis_Calendar.ics` on the Desktop

Times understood: `tomorrow 5 pm`, `kal 3 baje`, `today 18:30`, `in 2 hours`,
`2026-11-14 09:30`, plus `d/m/Y` formats. Default duration is 30 minutes.

Invitations need the email account already configured for Jarvis and are sent
with a standard `.ics` attachment.

---

## 4. Work tools: GitHub, Slack, Notion, Linear, Jira

Each service uses its own official HTTPS API with **your** token. Tokens are
saved only in the local, git-ignored `jarvis_data/config.json`; they are never
printed back, logged or committed.

Ask Jarvis:

- *"Show my work tools status"*
- *"List my GitHub issues"*
- *"Summarize the Slack channel #engineering"*
- *"Draft a reply to that Slack thread"*
- *"Create a GitHub issue: login page flickers on Safari"*
- *"Search Notion for the Q4 plan"*
- *"Create a Linear issue: fix onboarding copy"*
- *"List Jira issues assigned to me"*

### Setup

Use the tool directly (or ask Jarvis in chat):

```
workspace_operation(action="configure", service="github", token="ghp_...", repo="owner/name")
workspace_operation(action="configure", service="slack", token="xoxb-...", channel="engineering")
workspace_operation(action="configure", service="notion", token="secret_...")
workspace_operation(action="configure", service="linear", token="lin_api_...", project="<team id>")
workspace_operation(action="configure", service="jira", url="https://team.atlassian.net",
                    email="you@example.com", token="...", project="KEY")
```

Least-privilege scopes:

- **GitHub** — fine-grained token with Issues read/write (and Pull requests read)
  for the one repository.
- **Slack** — bot scopes `channels:history`, `channels:read`, `chat:write`; invite
  the bot to each channel.
- **Notion** — internal integration token; share the page/database with the
  integration.
- **Linear** — personal API key; optional team id for issue creation.
- **Jira** — API token from <https://id.atlassian.com/manage-profile/security/api-tokens>,
  base URL and account email.

Writes (post, create, comment, append) ask for confirmation while **safe mode**
is on. Reads and summaries never write anything.

---

## 5. MCP: help other AI tools, and use other tools

### Jarvis as an MCP server (`jarvis-memory`)

Point Claude Code, Cursor, Codex or any MCP client at:

```
python jarvis_mcp_server.py
```

Example Claude Desktop / Cursor config:

```json
{
  "mcpServers": {
    "jarvis-memory": {
      "command": "python",
      "args": ["C:/path/to/jarvis_mcp_server.py"]
    }
  }
}
```

Ask Jarvis for the exact config: *"Show the MCP server config"* or
`mcp_operation(action="config")`.

Tools exposed:

- `jarvis_memory_search` — search facts, pins and archive
- `jarvis_memory_remember` — save one durable fact
- `jarvis_memory_overview` — read the structured memory
- `jarvis_calendar_upcoming` — upcoming events
- `jarvis_writing_style` — personality and learned voice
- `jarvis_workspace_status` — which work services are connected

Resources: `jarvis://memory/overview`, `jarvis://calendar/upcoming`.

The server uses stdio only, writes protocol data to stdout and logs to stderr.
It opens no network port.

### Jarvis as an MCP client

Jarvis can call remote **streamable-HTTP** MCP servers:

```
mcp_operation(action="add_server", server="my-tools", url="https://example.com/mcp", token="...")
mcp_operation(action="list_tools", server="my-tools")
mcp_operation(action="call", server="my-tools", tool="search", arguments="{\"q\":\"x\"}")
```

Tokens stay in the local config. Only HTTP(S) URLs are accepted.

**Platform note:** the built-in server is stdio, which is right for desktop
agents. Phones and hosted chat apps cannot spawn a local process, so they need
an HTTP bridge; this desktop build does not pretend otherwise.

---

## 6. Privacy

- Dictation audio goes to the speech recogniser exactly like normal voice input.
- Memory, calendar, persona and tokens live in local files:
  `jarvis_data/config.json`, `jarvis_data/calendar.json`,
  `jarvis_memory.json`.
- Work-tool tokens are stored in plain JSON locally (like the Gemini key) and
  are **never** committed: `jarvis_data/` is in `.gitignore`.
- Jarvis asks for microphone/accessibility permissions first:
  Windows microphone access for voice and dictation, and only the permissions
  the feature you use needs. Screen reading and calendar export are used only
  when you ask for them.
- No analytics, telemetry or cloud sync is included.

If you publish a fork, keep `.gitignore` intact and never commit APKs, keys or
tokens.
