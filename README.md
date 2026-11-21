# J.A.R.V.I.S. Desktop Assistant (PC)

A Windows voice assistant with a Stark-style HUD. Talk in English or Roman
Urdu and Jarvis can open apps, search the web, read your screen, manage files,
play music, control volume and brightness, write documents, and answer
questions with Google Gemini.

This is a clean, open-source-ready project. It contains **no personal memory,
no API keys, no logs, and no private data**.

---

## Features

- Animated HUD with live mic level, CPU/RAM telemetry and a command log.
- Wake word / push-to-talk voice input (English + Roman Urdu).
- Opens apps and websites, searches Google/YouTube, plays media.
- Reads the screen and helps with research.
- Creates and edits documents (DOCX, XLSX, PPTX, PDF).
- Sends email through Gmail (optional, configured inside the app).
- File search, cleanup, downloads and system controls.
- Long-term memory, settings and companion topics stored locally.
- **Smart home control** for lights, fans, AC, TV, doors, blinds, coffee machine
  and plugs, plus one-word scenes (morning, movie, sleep, guest, work, away,
  party). Works out of the box with a virtual home; optional Home Assistant
  connection for real devices.
- **News briefings** from Google News with no extra API key.
- **Ultra Fast voice mode (v2.0.0)** — flash-lite model first, minimal thinking,
  shorter context, an ultra-short first TTS piece and tighter fallback timing so
  the voice starts right after the reply text.
- **Full-reply voice fix (v2.0.0)** — if the first audio arrives a little late,
  Jarvis now speaks every remaining piece instead of stopping after the first
  few words.
- **Reliable name memory (v2.0.0)** — tell Jarvis your name once and it is saved
  automatically, even if the model forgets to call the memory tool.
- **Memory Core panel + instant recap (v2.1.0)** — a new **[ MEMORY ]** button in
  the HUD opens a live view of everything Jarvis knows (facts by category, pins,
  episodes and archive). It can refresh, show a spoken-style recap, back up the
  memory files and export a report. Say "memory recap" for the same summary
  instantly, without waiting for Gemini.
- **Global dictation + voice edits (v2.2.0)** - press **Ctrl+Alt+V** (or say
  "start dictation") and speak into any Windows app: Word, Outlook, Slack, a
  browser field or a code editor. Say "scratch that", "capitalize that",
  "new paragraph", "comma" or "period" to edit, and "stop dictation" to finish.
- **Personality and your writing voice (v2.2.0)** - choose a personality
  (jarvis, professional, friendly, concise, mentor, creative or custom) and
  teach Jarvis your own writing style from samples. Give feedback such as
  "be less formal" and it applies to future drafts.
- **Local calendar (v2.2.0)** - create, read, reschedule and delete events in
  natural language ("meeting kal 3 baje"), invite people by email with an
  `.ics` attachment, and export the whole calendar to the Desktop.
- **Real work tools (v2.2.0)** - GitHub (issues and PRs), Slack (read, summarize
  and post), Notion (search, read, create, append, comment), Linear and Jira
  through their official APIs. On Windows, tokens are protected with DPAPI in
  the local, git-ignored config.
- **MCP server + client (v2.2.0)** - `jarvis-memory` exposes memory, calendar,
  persona and workspace status to Claude Code, Cursor or Codex over stdio, and
  Jarvis can call remote streamable-HTTP MCP servers with their own tools.
- **Assistant Hub (v2.2.0)** - a new **[ ASSISTANT ]** button shows dictation
  status, personality, the next 7 days of calendar, connected work tools and MCP
  helpers in one panel.
- **Complete assistant reliability pass (v2.3.0)** - email triage and thread
  summaries, read-only inbox checks, safe inbox organization, daily/weekly/
  interval routines (including “every morning”), persistent multi-app missions,
  and a Privacy view in the Assistant Hub.
- **Real browser + Windows UI automation (v2.3.0)** - open/read webpages, find,
  fill and click controls through Chromium DevTools; focus/read/type/save in
  Windows apps through UI Automation. A dedicated browser profile keeps logins.
- **Hard confirmation boundaries (v2.3.0)** - send/delete/payment/account,
  overwrite, close-with-unsaved-work, remote MCP writes and other high-impact
  actions are blocked until confirmed. Preapproved scheduled actions are limited
  to the exact routine the user approved.
- **Credential and privacy hardening (v2.3.0)** - Gemini, work-tool, MCP and Home
  Assistant credentials use Windows DPAPI; secrets are redacted from command
  logs and memory. Memory learning and the verbatim archive can be switched off.
- **MCP connections for coding agents (v2.3.0)** - `jarvis-memory` now adds
  read-only connected-workspace queries and quick cited research, alongside
  memory, calendar and writing-style context.
- **Reel feature pack (v2.4.2)** - live ISS position and a refreshable HUD map;
  real FFmpeg video trim/cut/auto-cut and local video understanding; local photo
  analysis and real photo edits (resize, crop, 9:16/1:1/16:9 presets, rotate,
  flip, enhance, grayscale, sepia, blur and text); a temporary visual guide that
  highlights a UI target without clicking; food/grocery lists and service
  hand-offs; public views/comments monitoring; ntfy/webhook alerts; a
  confirmation-gated call hand-off; and Steam/Epic library/update scans with
  guarded install hand-offs.
- **All-yes add-on (v2.4.2)** - real Twilio voice line (call me + inbound voice
  commands with consent and local transcripts), real rembg background removal,
  real add-to-cart attempt on a logged-in food site, official Instagram/YouTube
  insights with your token, and a real `steam://install/<appid>` download trigger.
  See `docs/PHONE_LINE.md` and `docs/ALL_YES_ADDON.md` for setup and limits.
- **Device Link (v2.4.3)** - pair the mobile Jarvis over the local network with a
  one-time code, receive any file (photo, zip, video, document) directly into PC
  Jarvis, answer where to save it by voice, and take voice commands from the
  phone without a SIM number. See `docs/PC_LINK.md`.
- Optional `jarvis_skills/` folder for your own Python skills.

> Dictation latency depends on the microphone, phrase length, speech-recognition
> service and network. Jarvis reports the measured last/average recognition
> latency; it does **not** advertise an unverified fixed “240 ms” figure.

See [`docs/ASSISTANT.md`](docs/ASSISTANT.md) for dictation, calendar, work-tool,
MCP, personality setup and the privacy/platform notes. The item-by-item status
and test boundaries are in [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md).

---

## Requirements

- Windows 10 or 11
- Python 3.10 or newer (3.12 recommended)
- A working microphone and speakers/headphones
- Internet connection
- A free Google Gemini API key

---

## Quick start

1. **Install Python 3.10+** from <https://www.python.org/downloads/> and tick
   **“Add Python to PATH”** during setup.
2. **Install the dependencies** by double-clicking `install.bat` (or run
   `python -m pip install -r requirements.txt`).
3. **Start Jarvis** by double-clicking `Jarvis.bat`.
4. On first launch the HUD opens the **GEMINI API KEY** dialog:
   - Click **OPEN GOOGLE AI STUDIO** (or visit
     <https://aistudio.google.com/app/apikey>).
   - Sign in and click **Create API key**.
   - Copy the key. New Google AI Studio keys start with **`AQ.`**; older
     keys start with `AIza...`.
   - Paste it in the dialog and click **SAVE KEY**.
5. Jarvis remembers the key and will **not ask again**.

> If Windows already has an old `GEMINI_API_KEY` variable, the dialog still
> opens once and the box is prefilled. Press **SAVE KEY** once; the key saved
> in the app takes priority from then on.

> You can change the key at any time with the **`[ API KEY ]`** button in the
> top bar of the HUD. Use **RESET KEY** there to completely delete the old key
> (app config + Windows variables), then paste a fresh one and press
> **SAVE KEY**. Both `AQ.` and `AIza...` keys are supported.

### Where is the key stored?

```
%APPDATA%\Jarvis\config.json
```

The key is written to your Windows user profile, not to the project folder.
It is never sent anywhere except Google's Gemini API. See
[`docs/API_KEY.md`](docs/API_KEY.md) for details.

---

## Voice command examples

Say **“Jarvis …”** followed by a command:

| Command | What it does |
|---------|--------------|
| “Jarvis, brave kholo” | Opens the Brave browser |
| “Jarvis, YouTube par lo-fi music chalao” | Plays music on YouTube |
| “Jarvis, notepad kholo” | Opens Notepad |
| “Jarvis, volume 40 karo” | Sets the volume |
| “Jarvis, brightness kam karo” | Dims the screen |
| “Jarvis, screenshot lo” | Takes a screenshot |
| “Jarvis, ye file dhundo” | Searches files |
| “Jarvis, aaj ka mausam batao” | Answers with Gemini |
| “Jarvis, 10 minute ka timer lagao” | Sets a timer |
| “Jarvis, drawing room ki light on karo” | Turns on a smart-home light |
| “Jarvis, bedroom AC 22 degree karo” | Sets the AC temperature |
| “Jarvis, movie mode chalao” | Applies the movie scene |
| “Jarvis, ghar ka status batao” | Reports every smart device |
| “Jarvis, news sunao” | Reads the latest headlines |

---

## Smart home

Jarvis ships with a complete **virtual home**, so nothing extra is required to
try it. Every device keeps its state in `jarvis_data/smarthome.json`:

- Lights in the drawing room, bedroom, kitchen, bathroom, study and garden
  (on/off and brightness).
- Fans in the bedroom and drawing room (on/off and speed).
- ACs in the drawing room and bedroom (on/off and temperature).
- TV (on/off, channel and volume).
- Main and back doors (lock/unlock).
- Blinds in the drawing room, bedroom and kitchen (open/close).
- Coffee machine and charger/iron plugs (on/off).
- Scenes: `morning`, `movie`, `sleep`, `guest`, `work`, `away`, `party`.

### Optional Home Assistant

If you already run Home Assistant, say **“connect home assistant”** and give
Jarvis the URL (for example `http://192.168.1.10:8123`) and a long-lived access
token. Jarvis then mirrors every command to the real devices and can import
their current state with **“sync home”**. The token is stored only in
`jarvis_data/smarthome_config.json` on your PC and is protected with Windows
DPAPI.

Without Home Assistant everything still works locally, so the feature can never
block the rest of the assistant.

---

## Project layout

| Path | Purpose |
|------|---------|
| `jarvis.py` | Core assistant: speech, TTS, Gemini tools, commands |
| `jarvis_app.py` | Stark HUD (Tkinter) and first-run API key dialog |
| `jarvis_config.py` | Per-user config / API-key storage |
| `jarvis_core/` | Upgrade layer: memory, documents, mail, research, HUD tools |
| `jarvis_core/dictation.py` | Global dictation + voice edits (Ctrl+Alt+V) |
| `jarvis_core/calendar_tools.py` | Local calendar, invitations and `.ics` export |
| `jarvis_core/workspace.py` | GitHub, Slack, Notion, Linear and Jira adapters |
| `jarvis_core/mcp.py` | `jarvis-memory` MCP server + HTTP MCP client |
| `jarvis_core/persona.py` | Personality and writing-voice learning |
| `jarvis_core/privacy.py` | Privacy status, Windows permission links and local data controls |
| `jarvis_core/media_tools.py` | Real video/photo analysis and deterministic local edits |
| `jarvis_core/showcase.py` | ISS, visual guide, commerce, analytics, alerts and phone hand-off |
| `jarvis_core/games.py` | Steam/Epic library, update scan and guarded install hand-off |
| `jarvis_mcp_server.py` | stdio entrypoint for other MCP agents |
| `jarvis_skills/` | Optional user skills |
| `Jarvis.bat` | Launches the HUD |
| `install.bat` | Installs Python dependencies |
| `requirements.txt` | Dependency list |
| `docs/` | API-key and troubleshooting guides |

Runtime data is created on your PC, never in the repository:

- `jarvis_memory.json` — learned facts
- `jarvis_settings.json` — voice, language, microphone
- `jarvis_companion.json` — optional companion topics
- `jarvis_data/smarthome.json` — smart-home device states
- `jarvis_data/smarthome_config.json` — optional Home Assistant URL/token
- `jarvis_data/shopping_list.json` — local grocery list
- `jarvis_data/social_monitors.json` — public metrics you asked Jarvis to watch
- `Jarvis_Reports/ISS_Live_Tracker.html` — refreshable live ISS map
- `jarvis_data/`, `Jarvis_Documents/`, `Jarvis_Reports/` — logs and files

These paths are listed in `.gitignore`.

---

## Privacy

- Your Gemini key lives in `%APPDATA%\Jarvis\config.json`.
- On Windows, saved Gemini/work/MCP/Home Assistant/ntfy/phone-provider credentials
  are protected with the current user's DPAPI key.
- Memory and settings live in local files next to the app. You can disable
  automatic learning or the verbatim archive from `privacy_operation`.
- Smart-home state and an optional protected Home Assistant token stay on your PC.
- No analytics, telemetry or cloud sync is included.
- If you publish a fork, keep `.gitignore` intact and never commit runtime
  data or keys.

---

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md). Common fixes:

- **PyAudio fails to install** — use a Python version with prebuilt wheels
  (3.11/3.12) or install it with `pipwin`.
- **No microphone found** — click **SELECT MIC** in the HUD and pick the right
  device.
- **No sound** — Edge TTS needs internet; install a local male English voice in
  Windows Settings > Time & language > Speech for offline fallback.
- **Key not remembered** — check that `%APPDATA%\Jarvis\config.json` exists and
  is writable.
- **"Invalid key" or an expired/blocked key** — open **`[ API KEY ]`**, press
  **RESET KEY**, then paste a fresh key from Google AI Studio (new keys start
  with `AQ.`; older ones with `AIza...`).
- **HUD does not start** — run `python jarvis_app.py` in a terminal to see the
  full error.

---

## Testing

```powershell
python -m compileall -q -f .
python -m unittest discover -s tests -p "test_*.py" -v
python -m pip check
```

Live third-party writes (orders, payments, calls, social posts) are not performed
by the test suite. Those paths use mocked official responses plus real
confirmation-guard tests; local media edits, UI checks, STT/TTS and non-writing
network reads are exercised directly.

---

## Notes

- A Gemini API key is required. Google may offer a free tier; check your
  Google AI Studio account for current limits and billing.
- Recurring work runs while Jarvis is running and the PC is awake; a due job is
  picked up after the PC wakes or Jarvis starts again.
- Browser control is experimental. Read-only navigation runs directly; sending,
  deleting, purchasing, account changes and similar actions require review.
- Reel features use real endpoints and local tools where possible. ISS comes from
  the public Open Notify API; ntfy needs a topic you control; social metrics are
  best-effort public-page checks; Steam/ADB actions open the real client/dialer
  after confirmation. Jarvis never claims a purchase, call or installation that
  the provider did not confirm. Video FFmpeg is provided by `imageio-ffmpeg` from
  `requirements.txt`; a system FFmpeg installation is optional.
- Windows controls microphone access in **Settings > Privacy & security >
  Microphone**. Unlike macOS, Windows has no separate desktop screen-recording,
  accessibility or local-calendar permission prompt; Jarvis reports this
  honestly in its Privacy view instead of pretending to request one.
- The original project included personal runtime data. This repository is a
  clean source-only copy; it intentionally omits all of it.
