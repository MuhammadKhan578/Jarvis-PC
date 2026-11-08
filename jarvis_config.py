"""Persistent configuration for Jarvis (PC).

The Gemini API key is stored in the current user's config directory, never in
the project folder and never in source control.

Locations
---------
Windows : %APPDATA%\\Jarvis\\config.json
Linux   : $XDG_CONFIG_HOME/jarvis/config.json  (or ~/.config/jarvis/config.json)
macOS   : ~/Library/Application Support/Jarvis/config.json

You can override the directory with the JARVIS_CONFIG environment variable.
The GEMINI_API_KEY / GOOGLE_API_KEY environment variables take priority over
the saved file, which is handy for CI or temporary runs.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Jarvis"
CONFIG_ENV = "JARVIS_CONFIG"
KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
AI_STUDIO_URL = "https://aistudio.google.com/app/apikey"
KEY_MIN_LENGTH = 20
# Google rotates key formats: standard "AIza..." keys and the newer "AQ..."
# auth keys. Keep both prefixes here for messages, but validation below only
# rejects obvious typos so a future format cannot lock users out again.
KEY_PREFIXES = ("AIza", "AQ.")


def config_dir() -> Path:
    """Return the per-user Jarvis config directory."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return Path(base) / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "jarvis"


def config_path() -> Path:
    """Full path of the JSON config file."""
    return config_dir() / "config.json"


def load_config() -> Dict[str, Any]:
    """Read the config file. Missing or broken files return an empty dict."""
    try:
        with open(config_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_config(data: Dict[str, Any]) -> Path:
    """Write the whole config atomically. Internal helper."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=".config-", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            os.chmod(temp_name, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
    return path


def save_config(patch: Dict[str, Any] | None = None, **values: Any) -> Path:
    """Merge values into the config file atomically and return its path."""
    data = load_config()
    if patch is not None:
        data.update(patch)
    data.update(values)
    return _write_config(data)


def normalize_key(key: str) -> str:
    """Trim a pasted key and drop accidental surrounding quotes."""
    value = (key or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def is_valid_key(key: str) -> bool:
    """Loose validation, so new Google key formats are still accepted.

    Google now issues "AQ..." auth keys, while older accounts still have
    "AIza..." keys. We only reject empty/short values, whitespace and control
    characters; the Gemini API remains the final judge of a key.
    """
    value = normalize_key(key)
    if len(value) < KEY_MIN_LENGTH:
        return False
    return all(33 <= ord(ch) <= 126 for ch in value)


def get_saved_api_key() -> str:
    """Return only the key saved in the app config (never the environment)."""
    value = load_config().get("gemini_api_key", "")
    return normalize_key(str(value or ""))


def get_api_key() -> str:
    """The app-saved key first, then environment variables as a fallback.

    Keeping the app key first means a key saved in the HUD always wins, even
    if an old GEMINI_API_KEY variable is still present in Windows.
    """
    saved = get_saved_api_key()
    if saved:
        return saved
    for name in KEY_ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def save_api_key(key: str) -> str:
    """Validate and persist the key. Raises ValueError for a bad key."""
    value = normalize_key(key)
    if not is_valid_key(value):
        raise ValueError(
            "That does not look like a Gemini API key. Paste the whole key "
            "(it starts with AIza or AQ). Create one at " + AI_STUDIO_URL
        )
    save_config(gemini_api_key=value)
    os.environ["GEMINI_API_KEY"] = value
    return value


def clear_api_key() -> None:
    """Remove the saved key (environment variables are left alone)."""
    data = load_config()
    data.pop("gemini_api_key", None)
    _write_config(data)


def reset_api_key() -> None:
    """Completely reset the key: forget it on disk and in this process.

    Use this before entering a new key when the old one is expired, revoked or
    in an unsupported format.
    """
    clear_api_key()
    for name in KEY_ENV_VARS:
        os.environ.pop(name, None)


def apply_api_key_to_env(key: str | None = None) -> str:
    """Put the key into GEMINI_API_KEY so google-genai can use it."""
    value = (key or get_api_key()).strip()
    if value:
        os.environ["GEMINI_API_KEY"] = value
    return value


def mask_key(key: str | None = None) -> str:
    """Show only the start and end of a key, never the whole thing."""
    value = (key or get_api_key()).strip()
    if not value:
        return ""
    if len(value) <= 12:
        return value[:3] + "..." + value[-2:]
    return value[:6] + "..." + value[-4:]


def describe_location() -> str:
    return str(config_path())
