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

1. Click **`[ SELECT MIC ]`** in the HUD.
2. Pick the device you actually speak into.
3. Press **ACTIVATE SELECTED MIC**.

The choice is saved in `jarvis_settings.json`.

## No sound / wrong voice

- Install a **male English (India)** voice:
  Settings > Time & language > Speech > Manage voices.
- Edge TTS needs internet access.
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

## Files and memory

Jarvis writes these next to the app:

- `jarvis_memory.json`
- `jarvis_settings.json`
- `jarvis_companion.json`
- `jarvis_data/`, `Jarvis_Documents/`, `Jarvis_Reports/`

They are ignored by git. Delete them to reset Jarvis completely. The API key is
separate and lives in `%APPDATA%\Jarvis\config.json`.
