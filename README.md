# J.A.R.V.I.S. â€” Desktop Assistant (PC)

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
   **â€œAdd Python to PATHâ€** during setup.
2. **Install the dependencies** by double-clicking `install.bat` (or run
   `python -m pip install -r requirements.txt`).
3. **Start Jarvis** by double-clicking `Jarvis.bat`.
4. On first launch the HUD opens the **GEMINI API KEY** dialog:
   - Click **OPEN GOOGLE AI STUDIO** (or visit
     <https://aistudio.google.com/app/apikey>).
   - Sign in and click **Create API key**.
   - Copy the key (it starts with `AIza...`).
   - Paste it in the dialog and click **SAVE KEY**.
5. Jarvis remembers the key and will **not ask again**.

> If Windows already has an old `GEMINI_API_KEY` variable, the dialog still
> opens once and the box is prefilled. Press **SAVE KEY** once; the key saved
> in the app takes priority from then on.

> You can change or remove the key at any time with the **`[ API KEY ]`**
> button in the top bar of the HUD.

### Where is the key stored?

```
%APPDATA%\Jarvis\config.json
```

The key is written to your Windows user profile, not to the project folder.
It is never sent anywhere except Google's Gemini API. See
[`docs/API_KEY.md`](docs/API_KEY.md) for details.

---

## Voice command examples

Say **â€œJarvis â€¦â€** followed by a command:

| Command | What it does |
|---------|--------------|
| â€œJarvis, brave kholoâ€ | Opens the Brave browser |
| â€œJarvis, YouTube par lo-fi music chalaoâ€ | Plays music on YouTube |
| â€œJarvis, notepad kholoâ€ | Opens Notepad |
| â€œJarvis, volume 40 karoâ€ | Sets the volume |
| â€œJarvis, brightness kam karoâ€ | Dims the screen |
| â€œJarvis, screenshot loâ€ | Takes a screenshot |
| â€œJarvis, ye file dhundoâ€ | Searches files |
| â€œJarvis, aaj ka mausam bataoâ€ | Answers with Gemini |
| â€œJarvis, 10 minute ka timer lagaoâ€ | Sets a timer |

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

- `jarvis_memory.json` â€” learned facts
- `jarvis_settings.json` â€” voice, language, microphone
- `jarvis_companion.json` â€” optional companion topics
- `jarvis_data/`, `Jarvis_Documents/`, `Jarvis_Reports/` â€” logs and files

These paths are listed in `.gitignore`.

---

## Privacy

- Your Gemini key lives in `%APPDATA%\Jarvis\config.json`.
- Memory and settings live in local files next to the app.
- No analytics, telemetry or cloud sync is included.
- If you publish a fork, keep `.gitignore` intact and never commit runtime
  data or keys.

---

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md). Common fixes:

- **PyAudio fails to install** â€” use a Python version with prebuilt wheels
  (3.11/3.12) or install it with `pipwin`.
- **No microphone found** â€” click **SELECT MIC** in the HUD and pick the right
  device.
- **No sound** â€” install a male English (India) voice in Windows
  Settings > Time & language > Speech.
- **Key not remembered** â€” check that `%APPDATA%\Jarvis\config.json` exists and
  is writable.
- **HUD does not start** â€” run `python jarvis_app.py` in a terminal to see the
  full error.

---

## Notes

- A Gemini API key is required. Google may offer a free tier; check your
  Google AI Studio account for current limits and billing.
- The original project included personal runtime data. This repository is a
  clean source-only copy; it intentionally omits all of it.
