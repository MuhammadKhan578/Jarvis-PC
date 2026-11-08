# Gemini API key

Jarvis needs a Google Gemini API key to answer questions and use the cloud
brain. The key belongs to **you** — this project does not include one.

## Create a key

1. Open <https://aistudio.google.com/app/apikey> in a browser.
2. Sign in with your Google account.
3. Click **Create API key**.
4. Choose a Google Cloud project (the default is fine).
5. Copy the key. New AI Studio keys start with `AQ.` (auth keys); older keys
   start with `AIza` and are about 39 characters long.

## Add it to Jarvis

### First launch

The HUD shows a **GEMINI API KEY** dialog. Paste the key and press
**SAVE KEY**. That is all — Jarvis will remember it.

If an old `GEMINI_API_KEY` already exists in Windows, the box is prefilled with
it. Just press **SAVE KEY** once. The app key is what Jarvis uses from then on.

### Later

Click the **`[ API KEY ]`** button in the top bar of the HUD. The same dialog
opens with the saved key masked. You can:

- Replace it and press **SAVE KEY** (applied live).
- Press **RESET KEY** to completely delete the old key from the app config and
  from the Windows `GEMINI_API_KEY` / `GOOGLE_API_KEY` variables. Paste a new
  key afterwards and press **SAVE KEY**.
- Press **OPEN GOOGLE AI STUDIO** to create a new key.

## Where it is stored

```
Windows : %APPDATA%\Jarvis\config.json
Linux   : ~/.config/jarvis/config.json
macOS   : ~/Library/Application Support/Jarvis/config.json
```

The file is created with user-only permissions where the OS supports it. It is
**never** written into the project folder and is excluded from git by
`.gitignore`.

You can move the folder with the `JARVIS_CONFIG` environment variable:

```powershell
$env:JARVIS_CONFIG = "D:\MyJarvisConfig"
python jarvis_app.py
```

## Environment variables

The key saved by the app always comes first. Environment variables are only a
fallback when no app key is saved yet — useful for temporary runs or CI:

```powershell
$env:GEMINI_API_KEY = "AQ..."   # or "AIza..." for an older key
python jarvis_app.py
```

`GOOGLE_API_KEY` is also accepted.

To make Jarvis use a different key, save it in the **`[ API KEY ]`** dialog.
You do not need to edit environment variables.

## Running `jarvis.py` directly

If you start the core file instead of the HUD:

```powershell
python jarvis.py
```

Jarvis reads the saved key first. If none exists, it prints the AI Studio link
and asks for the key in the terminal, then saves it for next time.

## Common problems

| Problem | Fix |
|---------|-----|
| “Invalid key” | Paste the whole key with no spaces. Both `AQ.` (new) and `AIza` (older) formats are accepted. |
| Old key stopped working | Open **`[ API KEY ]`**, press **RESET KEY**, then save a fresh key from Google AI Studio. |
| Key works once, then fails | The key may be restricted to an API or project. Check Google AI Studio. |
| “API key not valid” from Google | The key was deleted or the project was disabled. Create a new key. |
| Key not remembered | Ensure `%APPDATA%\Jarvis` is writable and not blocked by antivirus. |
| Different Windows user | Each Windows user has their own `%APPDATA%`, so each needs a key. |

## Security

- Treat the key like a password.
- Do not commit `config.json` or paste the key into issues/screenshots.
- If a key leaks, delete it in Google AI Studio and create a new one.
