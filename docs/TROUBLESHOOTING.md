# Troubleshooting

## The HUD does not start

Run it from a terminal so the error stays visible:

```powershell
cd "path\to\jarvis-pc"
python jarvis_app.py
```

Common causes:

- Python is not on `PATH` — reinstall Python and tick “Add Python to PATH”.
- A dependency is missing — run `install.bat` again.
- `jarvis.py` or `jarvis_config.py` is missing from the folder.

## PyAudio will not install

PyAudio needs a wheel that matches your Python version. The easiest options:

```powershell
# Python 3.11 / 3.12 usually have wheels
python -m pip install --upgrade pip
python -m pip install pyaudio

# If that fails, try pipwin
python -m pip install pipwin
pipwin install pyaudio
```

If you do not need the built-in mic, you can still use the HUD text box.

## No microphone / wrong microphone

First open **Settings > Privacy & security > Microphone** and allow desktop apps
to use the microphone. Windows owns this permission; Jarvis cannot bypass it.

1. Click **`[ SELECT MIC ]`** in the HUD.
2. Pick the device you actually speak into.
3. Press **ACTIVATE SELECTED MIC**.

The choice is saved in `jarvis_settings.json`.

## No sound / wrong voice

- Install a local male English voice if you want an offline fallback:
  Settings > Time & language > Speech > Manage voices.
- The primary voices are Edge TTS **en-GB-RyanNeural** and Urdu male
  **ur-PK-AsadNeural**; they need internet access.
- If the online voice is slow, Jarvis may fall back to a local Windows voice.

## The API key dialog does not appear

- The key may already be saved. Click **`[ API KEY ]`** in the top bar to edit
  it.
- Check `%APPDATA%\Jarvis\config.json`. If it exists and contains
  `gemini_api_key`, Jarvis skips the first-run dialog.
- If no key is saved there, the app asks on every start until you press
  **SAVE KEY** — even if an old Windows `GEMINI_API_KEY` variable still exists.
- To force the dialog, reset the key with the **RESET KEY** button or delete
  the config file.

## “Invalid key”

- Paste the complete key with no spaces or line breaks. New Google AI Studio
  keys start with `AQ.`; older keys start with `AIza`. Both are accepted.
- If an old key stopped working, open **`[ API KEY ]`**, press **RESET KEY**,
  then paste a fresh key and press **SAVE KEY**.
- Create a fresh key at <https://aistudio.google.com/app/apikey>.
- Make sure the Gemini API is enabled for the Google Cloud project.

## Gemini says the model is unavailable

Google changes model names over time. Jarvis tries several fallback models.
Update the `MODEL_CANDIDATES` / `SMART_CANDIDATES` lists in `jarvis.py` if your
account only has access to newer names.

## Wake word does not work

- Use the mic button or **TEAM COMMS** box instead.
- Check that the correct microphone is selected.
- Background noise and laptop sleep can interrupt listening; restart the HUD.

## Browser automation cannot attach

- Jarvis uses its own persistent browser profile and debugging port. Close the
  existing automation browser once, then ask Jarvis to open it again.
- If you explicitly request Brave/Chrome/Edge, that exact browser must be
  installed; v2.3 does not silently substitute another browser.
- CAPTCHA, sign-in challenges and redesigned pages may need manual review.

## Files and memory

Jarvis writes these next to the app:

- `jarvis_memory.json`
- `jarvis_data/memory_v2.json` and `jarvis_data/archive.jsonl`
- `jarvis_data/calendar.json`, `schedule.json`, and `missions.json`
- `jarvis_settings.json`
- `jarvis_companion.json`
- `jarvis_data/`, `Jarvis_Documents/`, `Jarvis_Reports/`

They are ignored by git. Prefer the Privacy/Memory controls over manually
deleting files. The API key is separate, lives in `%APPDATA%\Jarvis\config.json`
and is DPAPI-protected on Windows.
