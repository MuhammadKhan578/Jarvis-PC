# Jarvis assistant features (v2.4.5)

This guide covers the assistant layer through **v2.4.5**: global dictation,
personality and writing voice, email/calendar, routines, real browser/Windows
automation, connected work tools, MCP, reel features, the phone-to-PC Device
Link and privacy controls. Runtime data stays on your PC unless you explicitly
invoke a cloud model/service.

### Device Link (phone → PC, v2.4.3)

Say **"device link start"** and **"device link code"**, then enter the shown LAN
IP, port `8766` and the one-time code in the Mobile Jarvis Connect panel. Say
**"ye file PC par bhejo"** on the phone; the real file arrives into staging and
PC Jarvis asks where to save it. Reply **"Downloads"** or
**"D:\backup\photo.jpg mein save karo"**. If the target exists, say
**"confirm save"**; no overwrite happens without that. **"PC Jarvis ko call
karo"** on the phone starts a Wi-Fi voice intercom — no phone number is involved.
See `docs/PC_LINK.md`.

### Free Asterisk voice line (v2.4.4)

Twilio ke bina bhi phone-style commands chal sakte hain. Run
`asterisk\setup_asterisk.ps1` once: wo WSL me free Asterisk install karke
softphone extension `1001` aur AMI secret banayega. Phir bolo
`asterisk setup <host> jarvis <secret> 1001` aur `asterisk line start`.
Ab softphone se `1002` dial karke command do, ya bolo
`mujhe asterisk se call karo` — Jarvis aapko call karega. Ye local extension hai;
real SIM/number ke liye SIP trunk/GSM gateway chahiye. See
`docs/ASTERISK_LINE.md`.

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
- `dictation_operation(action="status")` reports the measured last and average
  recognition latency. There is no fake fixed-latency promise: real timing
  depends on phrase length, microphone, recogniser and network.

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
with a standard `.ics` attachment after explicit send confirmation. Because the
visible Gmail browser composer cannot attach files reliably, invitations require
the optional SMTP account path; otherwise Jarvis keeps the `.ics` file and says
exactly what is missing.

---

## 4. Work tools: GitHub, Slack, Notion, Linear, Jira

Each service uses its own official HTTPS API with **your** token. On Windows,
tokens are protected with DPAPI in the local, git-ignored
`jarvis_data/config.json`; they are never printed back, logged or committed.

Ask Jarvis:

- *"Show my work tools status"*
- *"List my GitHub issues"*
- *"Summarize the Slack channel #engineering"*
- *"Draft a reply to that Slack thread"*
- *"Create a GitHub issue: login page flickers on Safari"*
- *"Search Notion for the Q4 plan"*
- *"Create a Linear issue: fix onboarding copy"*
- *"List Jira issues assigned to me"*
- *"List open GitHub pull requests"*
- *"Show rows in this Notion database: <database id>"*

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
- `jarvis_workspace_query` — read/search/summarize connected work services
  (strictly read-only over MCP)
- `jarvis_research_quick` — current web research with sources

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

## 6. Email triage and safe organization

- `email_operation(action="triage")` classifies available previews into urgent,
  action, reply, waiting, info and newsletter. It does not change the inbox.
- `email_operation(action="summarize", query="...")` summarizes a matching
  thread/set and extracts decisions, deadlines and action items.
- Listing/searching/triage are read-only. Jarvis no longer marks messages read
  merely because it listed them.
- `mark_read` and `organize` require confirmation. `organize` is deliberately
  conservative: it marks only messages classified as newsletters read; it does
  not delete or archive email.
- A routine such as *"every morning triage my inbox"* is read-only. If a
  recurring routine will change data, Jarvis shows the exact action and asks for
  preapproval once; that approval cannot be reused for another action.

---

## 7. Routines and multi-app missions

Examples:

- `in 20 minutes remind me to drink water`
- `every morning summarize what changed overnight`
- `every Friday at 5 pm run my weekly review`
- `every 2 hours check the project dashboard`

Daily, weekly, interval and one-off jobs persist in
`jarvis_data/schedule.json`. They run while Jarvis and the PC are awake; overdue
jobs are picked up when the PC wakes or Jarvis starts again.

For goals with dependent steps, `mission_operation` plans and executes across
research, browser, files, documents and connected tools, persists progress and
writes a report. A blocked/failed step now leaves the mission **partial** instead
of falsely announcing full completion.

---

## 8. Browser, Windows apps and research

- `browser_operation` drives a dedicated persistent Brave/Chrome/Edge profile
  through DevTools: open/read/find/fill/click, tabs, screenshots and page text.
- When you explicitly request a browser, Jarvis does not silently substitute a
  different installed browser.
- `ui_operation` uses Windows UI Automation for windows and controls; human
  shortcuts such as `ctrl+s` are translated correctly.
- `research_operation(action="quick"|"deep")` searches multiple sources,
  reads pages and produces cited answers/reports with uncertainties.
- Browser/UI send, delete, payment, purchase, account and similar controls are
  blocked until confirmed. Browser automation remains experimental, so verify
  important outcomes.

---

## 9. Live ISS tracking

Say *"where is the ISS"*, *"track the ISS"* or *"open the ISS map"*. Jarvis reads
the public Open Notify endpoint, reports the real latitude/longitude/altitude and
can open `Jarvis_Reports/ISS_Live_Tracker.html`, an HUD map that refreshes every
five seconds. No API key is required. If the endpoint is offline, Jarvis says so.

## 10. Local video understanding and real edits

`video_operation` reads a local video with Gemini when a key is configured and
creates real MP4 outputs with the bundled FFmpeg from `imageio-ffmpeg`:

- `info` — duration, resolution and codec facts from FFprobe.
- `analyze` / `summarize` — sampled frames plus a question; large videos are
  sampled, and the report states that audio was not inspected.
- `trim` — exact `start`/`end` seconds.
- `cut` / `keep` — include or remove several `a-b` segments.
- `auto_cut` — deterministic highlight-style segments without claiming creative
  judgement.
- `open` — open the resulting file.

The source is never overwritten. An existing destination requires confirmation.
Captions, transitions, speed ramps and audio replacement are not claimed.

**No path needed:** *"edit this video"*, *"trim this clip"* or *"clean this
footage"* picks the newest video in `Downloads`/`Desktop` and runs `auto_cut`.
Give a path or a destination when you want exact control. This is a real FFmpeg
edit, not a Premiere Pro timeline; Premiere is not required.

## 11. Local photo analysis and edits

`image_operation` reads a local image with Gemini or creates a separate edited
file with Pillow. Actions: `info`, `analyze`, `open`, `resize`, `crop`,
`rotate`, `flip`, `enhance`, `grayscale`, `sepia`, `blur` and `text`.
`preset="9:16"`, `"1:1"`, `"16:9"`, `"4:3"` or `"3:2"` performs a centre crop for
social exports. Originals are never overwritten. Complex layers, masks,
background removal and generative fill are not claimed.

**No path needed:** *"edit this photo"* or *"enhance this image"* picks the
newest image in `Downloads`/`Desktop` and saves an enhanced copy beside it.

## 12. Visual guide

`visual_guide(target="Export button")` asks the screen reader to locate an
element and draws a temporary purple/cyan highlight plus a label over it. It
never clicks, so it is safe to use as a teaching overlay.

## 13. Food, groceries and commerce hand-off

`commerce_operation` manages `jarvis_data/shopping_list.json` and opens real
food/grocery search results. It can add, remove, list and clear items. `order`
is confirmation-gated and opens the chosen service; Jarvis explicitly reports
that no purchase or payment was made.

## 14. Social analytics

`analytics_operation` stores public profile/post URLs in
`jarvis_data/social_monitors.json`, fetches public pages on request and reports
views/likes/comments only when the page exposes them. Instagram/YouTube
login-only insights are not scraped; Jarvis says that a login or official API is
needed. Optional threshold alerts go through `notification_operation` after
confirmation.

## 15. Remote alerts

`notification_operation(action="configure", server="https://ntfy.example",
topic="...", token="...")` saves an ntfy-compatible topic/token. Saved tokens use
the same Windows DPAPI protection as other credentials. Sending an alert always
requires `confirmed=True`; the response reports the real provider result.

## 16. Phone agent

`phone_agent_operation` can prepare an ADB dial hand-off or a provider call
through an endpoint you configure. Provider calls require confirmation. It never
claims a call was answered or recorded. `call_status` and `transcript` report
only what the configured provider actually returns.

## 17. Steam and Epic libraries

`game_operation` reads real Steam manifests and Epic launcher metadata, reports
installed games and available update flags, and checks disk space before a
hand-off. Installing or updating opens the real Steam/Epic client only after
confirmation. It does not fabricate library contents or installation success.

---

## 18. Privacy

- Dictation audio goes to the speech recogniser exactly like normal voice input.
- Memory, calendar, persona and tokens live in local files:
  `jarvis_data/config.json`, `jarvis_data/calendar.json`,
  `jarvis_memory.json`.
- Gemini/work/MCP/Home Assistant/ntfy/phone-provider credentials use Windows
  DPAPI. Legacy plaintext
  values are upgraded when read. They are **never** committed.
- Use `privacy_operation(action="status")` or the **[ PRIVACY ]** Assistant Hub
  button to inspect network use and local data. `memory_enabled`, `auto_learn`
  and `archive_enabled` can be switched off independently.
- Windows itself controls microphone access. Unlike macOS, Windows has no
  separate desktop screen-recording/accessibility/local-calendar permission
  prompt. Screen reading/UI automation and calendar export run only when you
  invoke those features; Jarvis does not pretend an OS permission exists.
- No analytics, telemetry or cloud sync is included.

If you publish a fork, keep `.gitignore` intact and never commit APKs, keys or
tokens.
