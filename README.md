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
- Optional `jarvis_skills/` folder for your own Python skills.

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
`jarvis_data/smarthome_config.json` on your PC.

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
- `jarvis_data/`, `Jarvis_Documents/`, `Jarvis_Reports/` — logs and files

These paths are listed in `.gitignore`.

---

## Privacy

- Your Gemini key lives in `%APPDATA%\Jarvis\config.json`.
- Memory and settings live in local files next to the app.
- Smart-home state and an optional Home Assistant token stay on your PC.
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
- **No sound** — install a male English (India) voice in Windows
  Settings > Time & language > Speech.
- **Key not remembered** — check that `%APPDATA%\Jarvis\config.json` exists and
  is writable.
- **"Invalid key" or an expired/blocked key** — open **`[ API KEY ]`**, press
  **RESET KEY**, then paste a fresh key from Google AI Studio (new keys start
  with `AQ.`; older ones with `AIza...`).
- **HUD does not start** — run `python jarvis_app.py` in a terminal to see the
  full error.

---

## Notes

- A Gemini API key is required. Google may offer a free tier; check your
  Google AI Studio account for current limits and billing.
- The original project included personal runtime data. This repository is a
  clean source-only copy; it intentionally omits all of it.
