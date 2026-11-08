"""Smart home control for Jarvis.

Two modes:

  * Virtual home (default): every device lives in
    ``jarvis_data/smarthome.json``, so the assistant can control the house
    immediately with no hardware and no account.
  * Home Assistant (optional): after ``smart_home_setup(url, token)`` every
    command is also mirrored to the real Home Assistant instance.

The module never raises: every public function returns short, speakable text.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request

from . import core

_STATE_FILE = os.path.join(core.DATA_DIR, "smarthome.json")
_CONFIG_FILE = os.path.join(core.DATA_DIR, "smarthome_config.json")
_LOCK = threading.RLock()

DEFAULT_STATE = {
    "lights": {
        "drawing_room": {"on": False, "brightness": 100},
        "bedroom": {"on": False, "brightness": 100},
        "kitchen": {"on": False, "brightness": 100},
        "bathroom": {"on": False, "brightness": 100},
        "study": {"on": False, "brightness": 100},
        "garden": {"on": False, "brightness": 100},
    },
    "fans": {
        "bedroom": {"on": False, "speed": 2},
        "drawing_room": {"on": False, "speed": 2},
    },
    "ac": {
        "drawing_room": {"on": False, "temperature": 24},
        "bedroom": {"on": False, "temperature": 24},
    },
    "tv": {
        "drawing_room": {"on": False, "channel": 1, "volume": 20},
    },
    "doors": {
        "main": {"locked": True},
        "back": {"locked": True},
    },
    "blinds": {
        "drawing_room": {"state": "closed"},
        "bedroom": {"state": "closed"},
        "kitchen": {"state": "closed"},
    },
    "coffee": {
        "kitchen": {"on": False},
    },
    "plugs": {
        "charger": {"on": False},
        "iron": {"on": False},
    },
}

TYPE_ORDER = ("lights", "fans", "ac", "tv", "doors", "blinds", "coffee", "plugs")

TYPE_WORDS = {
    "lights": ("light", "lights", "lamp", "lamps", "batti", "bati", "roshni", "chiragh", "bulb", "bulbs"),
    "fans": ("fan", "fans", "pankha", "pankhe", "pankhaa"),
    "ac": ("ac", "acs", "air conditioner", "air conditioners", "aircon", "air conditioning", "cooler"),
    "tv": ("tv", "television", "telly", "screen"),
    "doors": ("door", "doors", "darwaza", "darwaze", "gate", "gates"),
    "blinds": ("blind", "blinds", "curtain", "curtains", "parda", "parde", "shutter", "shutters"),
    "coffee": ("coffee", "coffee machine", "coffee maker", "espresso", "cappuccino"),
    "plugs": ("plug", "plugs", "socket", "sockets", "charger", "iron", "press"),
}

ROOM_LABELS = {
    "drawing_room": "drawing room",
    "bedroom": "bedroom",
    "kitchen": "kitchen",
    "bathroom": "bathroom",
    "study": "study",
    "garden": "garden",
    "main": "main",
    "back": "back",
    "charger": "charger",
    "iron": "iron",
}

ROOM_ALIASES = {
    "drawing_room": ("drawing room", "living room", "lounge", "hall", "drawing",
                     "baitha kamra", "bara kamra", "drawn room"),
    "bedroom": ("bedroom", "bed room", "bed rooms", "room", "kamra", "kamre", "sleeping room"),
    "kitchen": ("kitchen", "rasoi", "kitchen room", "cook room"),
    "bathroom": ("bathroom", "bath room", "washroom", "ghusal khana", "toilet"),
    "study": ("study", "study room", "office", "library"),
    "garden": ("garden", "lawn", "yard", "bagh", "bahar"),
    "main": ("main door", "front door", "main gate", "front gate", "darwaza", "gate", "front"),
    "back": ("back door", "back gate", "pichla darwaza", "back"),
    "charger": ("charger", "phone charger", "mobile charger"),
    "iron": ("iron", "press", "iron plug"),
}

ALL_WORDS = ("all", "sab", "sare", "saari", "sabhi", "sab kuch", "poore ghar", "pura ghar")

SCENES = {
    "morning": [
        ("lights", "bedroom", {"on": True, "brightness": 40}),
        ("lights", "kitchen", {"on": True, "brightness": 80}),
        ("lights", "drawing_room", {"on": False}),
        ("lights", "bathroom", {"on": True, "brightness": 60}),
        ("blinds", "bedroom", {"state": "open"}),
        ("blinds", "kitchen", {"state": "open"}),
        ("coffee", "kitchen", {"on": True}),
        ("tv", "drawing_room", {"on": False}),
    ],
    "movie": [
        ("lights", "drawing_room", {"on": True, "brightness": 20}),
        ("lights", "bedroom", {"on": False}),
        ("lights", "kitchen", {"on": False}),
        ("lights", "bathroom", {"on": False}),
        ("lights", "study", {"on": False}),
        ("lights", "garden", {"on": False}),
        ("tv", "drawing_room", {"on": True, "volume": 35}),
        ("blinds", "drawing_room", {"state": "closed"}),
        ("ac", "drawing_room", {"on": True, "temperature": 24}),
        ("doors", "main", {"locked": True}),
        ("doors", "back", {"locked": True}),
        ("coffee", "kitchen", {"on": False}),
    ],
    "sleep": [
        ("lights", "drawing_room", {"on": False}),
        ("lights", "bedroom", {"on": False}),
        ("lights", "kitchen", {"on": False}),
        ("lights", "bathroom", {"on": False}),
        ("lights", "study", {"on": False}),
        ("lights", "garden", {"on": False}),
        ("tv", "drawing_room", {"on": False}),
        ("fans", "bedroom", {"on": True, "speed": 2}),
        ("ac", "bedroom", {"on": True, "temperature": 25}),
        ("ac", "drawing_room", {"on": False}),
        ("blinds", "drawing_room", {"state": "closed"}),
        ("blinds", "bedroom", {"state": "closed"}),
        ("blinds", "kitchen", {"state": "closed"}),
        ("doors", "main", {"locked": True}),
        ("doors", "back", {"locked": True}),
        ("coffee", "kitchen", {"on": False}),
        ("plugs", "iron", {"on": False}),
    ],
    "guest": [
        ("lights", "drawing_room", {"on": True, "brightness": 80}),
        ("lights", "kitchen", {"on": True, "brightness": 90}),
        ("ac", "drawing_room", {"on": True, "temperature": 22}),
        ("blinds", "drawing_room", {"state": "open"}),
        ("blinds", "bedroom", {"state": "open"}),
        ("blinds", "kitchen", {"state": "open"}),
        ("doors", "main", {"locked": False}),
        ("tv", "drawing_room", {"on": True, "volume": 25}),
        ("coffee", "kitchen", {"on": True}),
    ],
    "work": [
        ("lights", "study", {"on": True, "brightness": 90}),
        ("lights", "drawing_room", {"on": False}),
        ("lights", "bedroom", {"on": False}),
        ("tv", "drawing_room", {"on": False}),
        ("ac", "drawing_room", {"on": True, "temperature": 24}),
        ("coffee", "kitchen", {"on": True}),
        ("doors", "main", {"locked": True}),
    ],
    "away": [
        ("lights", "drawing_room", {"on": False}),
        ("lights", "bedroom", {"on": False}),
        ("lights", "kitchen", {"on": False}),
        ("lights", "bathroom", {"on": False}),
        ("lights", "study", {"on": False}),
        ("lights", "garden", {"on": False}),
        ("fans", "bedroom", {"on": False}),
        ("fans", "drawing_room", {"on": False}),
        ("ac", "drawing_room", {"on": False}),
        ("ac", "bedroom", {"on": False}),
        ("tv", "drawing_room", {"on": False}),
        ("coffee", "kitchen", {"on": False}),
        ("plugs", "charger", {"on": False}),
        ("plugs", "iron", {"on": False}),
        ("blinds", "drawing_room", {"state": "closed"}),
        ("blinds", "bedroom", {"state": "closed"}),
        ("blinds", "kitchen", {"state": "closed"}),
        ("doors", "main", {"locked": True}),
        ("doors", "back", {"locked": True}),
    ],
    "party": [
        ("lights", "drawing_room", {"on": True, "brightness": 100}),
        ("lights", "kitchen", {"on": True, "brightness": 100}),
        ("lights", "garden", {"on": True, "brightness": 100}),
        ("tv", "drawing_room", {"on": True, "volume": 55}),
        ("blinds", "drawing_room", {"state": "open"}),
        ("ac", "drawing_room", {"on": True, "temperature": 22}),
        ("doors", "main", {"locked": True}),
        ("coffee", "kitchen", {"on": False}),
    ],
}

SCENE_ALIASES = {
    "morning": ("morning", "good morning", "subah", "seher"),
    "movie": ("movie", "film", "cinema", "movie mode", "picture"),
    "sleep": ("sleep", "sleep mode", "night", "good night", "raat", "sona", "so jao"),
    "guest": ("guest", "guest mode", "mehman", "mehmaan", "guests"),
    "work": ("work", "work mode", "office", "kaam", "study mode"),
    "away": ("away", "away mode", "bahar", "leave", "lock down", "lockdown", "bahar ja raha"),
    "party": ("party", "party mode", "mehfil", "dawat", "celebration"),
}


# ----------------------------------------------------------------- state file

def _deep_merge(base: dict, data: dict) -> dict:
    out = {}
    for key, value in base.items():
        if isinstance(value, dict):
            out[key] = _deep_merge(value, data.get(key) if isinstance(data.get(key), dict) else {})
        else:
            out[key] = data.get(key, value)
    # keep unknown devices the user added by hand
    for key, value in (data or {}).items():
        if key not in out:
            out[key] = value
    return out


def _load_state() -> dict:
    with _LOCK:
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        return _deep_merge(DEFAULT_STATE, data)


def _save_state(state: dict) -> None:
    with _LOCK:
        try:
            os.makedirs(core.DATA_DIR, exist_ok=True)
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, _STATE_FILE)
        except Exception as e:
            core.log(f"smarthome save failed: {e}")


def _load_config() -> dict:
    default = {"enabled": False, "url": "", "token": "", "entities": {}}
    with _LOCK:
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        for key, value in default.items():
            data.setdefault(key, value)
        if not isinstance(data.get("entities"), dict):
            data["entities"] = {}
        return data


def _save_config(config: dict) -> None:
    with _LOCK:
        try:
            os.makedirs(core.DATA_DIR, exist_ok=True)
            tmp = _CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(config, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, _CONFIG_FILE)
        except Exception as e:
            core.log(f"smarthome config save failed: {e}")


# --------------------------------------------------------------- small utils

def _norm(text: str) -> str:
    t = (text or "").lower().replace("-", " ").replace("_", " ")
    t = re.sub(r"[^a-z0-9% ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _has_word(text: str, word: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text))


def _int(value, default=None):
    if value is None:
        return default
    match = re.search(r"-?\d+", str(value))
    if not match:
        return default
    try:
        return int(match.group(0))
    except Exception:
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def _available(state: dict, dtype: str) -> list:
    devices = state.get(dtype) or {}
    return [did for did in devices if isinstance(devices.get(did), dict)]


def _singular(dtype: str) -> str:
    return {
        "lights": "light", "fans": "fan", "ac": "AC", "tv": "TV",
        "doors": "door", "blinds": "blinds", "coffee": "coffee machine", "plugs": "plug",
    }.get(dtype, dtype)


def _label(dtype: str, did: str) -> str:
    room = ROOM_LABELS.get(did, did.replace("_", " "))
    if dtype == "tv":
        return "TV"
    if dtype == "coffee":
        return "coffee machine"
    if dtype == "doors":
        return f"{room} door"
    if dtype == "plugs":
        return f"{room} plug"
    if dtype == "blinds":
        return f"{room} blinds"
    return f"{room} {_singular(dtype)}"


def _device_menu() -> str:
    return ("Devices: drawing room, bedroom, kitchen, bathroom, study and garden lights; "
            "bedroom and drawing room fans and ACs; TV; main and back doors; "
            "drawing room, bedroom and kitchen blinds; coffee machine; charger and iron plugs.")


def _status_line(dtype: str, did: str, data: dict) -> str:
    label = _label(dtype, did)
    if dtype == "lights":
        if data.get("on"):
            return f"{label} on {int(data.get('brightness', 100))}%"
        return f"{label} off"
    if dtype == "fans":
        if data.get("on"):
            return f"{label} on speed {int(data.get('speed', 2))}"
        return f"{label} off"
    if dtype == "ac":
        if data.get("on"):
            return f"{label} on {int(data.get('temperature', 24))}C"
        return f"{label} off"
    if dtype == "tv":
        if data.get("on"):
            return (f"TV on, channel {int(data.get('channel', 1))}, "
                    f"volume {int(data.get('volume', 20))}%")
        return "TV off"
    if dtype == "doors":
        return f"{label} {'locked' if data.get('locked') else 'unlocked'}"
    if dtype == "blinds":
        return f"{label} {data.get('state', 'closed')}"
    return f"{label} {'on' if data.get('on') else 'off'}"


# ------------------------------------------------------------------- resolve

def _types_in(text: str) -> list:
    found = []
    for dtype in TYPE_ORDER:
        for word in TYPE_WORDS[dtype]:
            if _has_word(text, word):
                found.append(dtype)
                break
    return found


def _rooms_in(text: str) -> list:
    found = []
    # Longest aliases first so "drawing room" wins over "room".
    pairs = []
    for rid, aliases in ROOM_ALIASES.items():
        for alias in aliases:
            pairs.append((len(alias), rid, alias))
    pairs.sort(reverse=True)
    used = set()
    remaining = " " + text + " "
    for _, rid, alias in pairs:
        if rid in used:
            continue
        if _has_word(remaining, alias):
            found.append(rid)
            used.add(rid)
            # Remove the matched words so a shorter alias inside them cannot
            # match a different room ("drawing room" must not also match "room").
            remaining = re.sub(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])",
                               " ", remaining)
    return found


def _all_requested(text: str) -> bool:
    return any(_has_word(text, word) for word in ALL_WORDS)


def _resolve_targets(text: str, action: str = "") -> object:
    """Return a list of (type, id, label) or a short message string."""
    state = _load_state()
    types = _types_in(text)
    rooms = [r for r in _rooms_in(text) if r in ROOM_LABELS]
    want_all = _all_requested(text) or text.strip() in ("", "ghar", "home", "house")

    if not types and want_all:
        if action in ("lock", "unlock"):
            types = ["doors"]
        elif action in ("open", "close"):
            types = ["blinds"]
        elif action in ("brightness", "dim"):
            types = ["lights"]
        elif action in ("temperature", "temp"):
            types = ["ac"]
        elif action == "volume":
            types = ["tv"]
        elif action == "speed":
            types = ["fans"]
        else:
            types = ["lights", "fans", "ac", "tv", "coffee", "plugs"]
        rooms = []

    if not types:
        if rooms:
            room = rooms[0]
            options = [t for t in TYPE_ORDER if room in (state.get(t) or {})]
            names = ", ".join(_singular(t) for t in options)
            return f"Which device in the {ROOM_LABELS.get(room, room)}? {names}."
        return "I could not find that device. " + _device_menu()

    targets = []
    for dtype in types:
        ids = _available(state, dtype)
        if dtype == "tv":
            chosen = ["drawing_room"]
        elif dtype == "coffee":
            chosen = ["kitchen"]
        elif dtype in ("doors", "plugs"):
            chosen = [rid for rid in rooms if rid in ids]
            if not chosen:
                # "main door", "charger", "iron" already become rooms above.
                chosen = ids if (want_all or not rooms) else []
        else:
            chosen = [rid for rid in rooms if rid in ids]
            if not chosen and want_all:
                pass
        if want_all or (not rooms and dtype in ("tv", "coffee")):
            chosen = ids
        elif not chosen and not rooms:
            if len(ids) == 1:
                chosen = ids
            else:
                return f"Which {_singular(dtype)}? " + ", ".join(ROOM_LABELS.get(i, i) for i in ids) + "."
        for did in chosen:
            targets.append((dtype, did, _label(dtype, did)))

    # remove duplicates, keep order
    seen = set()
    unique = []
    for item in targets:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ------------------------------------------------------------ Home Assistant

_HA_DOMAIN = {
    "lights": "light",
    "fans": "fan",
    "ac": "climate",
    "tv": "media_player",
    "doors": "lock",
    "blinds": "cover",
    "coffee": "switch",
    "plugs": "switch",
}


def _ha_entity(dtype: str, did: str) -> str:
    cfg = _load_config()
    override = (cfg.get("entities") or {}).get(f"{dtype}.{did}")
    if override:
        return str(override)
    return f"{_HA_DOMAIN.get(dtype, 'switch')}.{did}"


def _ha_request(method: str, path: str, payload=None):
    cfg = _load_config()
    if not cfg.get("enabled") or not cfg.get("url") or not cfg.get("token"):
        return False, "not configured"
    url = str(cfg["url"]).rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Authorization", "Bearer " + str(cfg["token"]))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            return True, response.read(400).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:120]


def _ha_service(dtype: str, did: str, state: dict):
    entity = _ha_entity(dtype, did)
    if dtype == "lights":
        if state.get("on"):
            return "light", "turn_on", {"entity_id": entity,
                                        "brightness_pct": int(state.get("brightness", 100))}
        return "light", "turn_off", {"entity_id": entity}
    if dtype == "fans":
        if state.get("on"):
            return "fan", "turn_on", {"entity_id": entity,
                                      "percentage": int(state.get("speed", 2)) * 20}
        return "fan", "turn_off", {"entity_id": entity}
    if dtype == "ac":
        if state.get("on"):
            return "climate", "set_temperature", {"entity_id": entity,
                                                  "temperature": int(state.get("temperature", 24))}
        return "climate", "turn_off", {"entity_id": entity}
    if dtype == "tv":
        if state.get("on"):
            return "media_player", "volume_set", {"entity_id": entity,
                                                  "volume_level": int(state.get("volume", 20)) / 100.0}
        return "media_player", "turn_off", {"entity_id": entity}
    if dtype == "doors":
        return "lock", ("lock" if state.get("locked") else "unlock"), {"entity_id": entity}
    if dtype == "blinds":
        return "cover", ("open_cover" if state.get("state") == "open" else "close_cover"), {"entity_id": entity}
    return "switch", ("turn_on" if state.get("on") else "turn_off"), {"entity_id": entity}


def _ha_push(dtype: str, did: str, state: dict):
    domain, service, data = _ha_service(dtype, did, state)
    return _ha_request("POST", f"/api/services/{domain}/{service}", data)


def _sync_from_ha() -> str:
    cfg = _load_config()
    if not cfg.get("enabled") or not cfg.get("url") or not cfg.get("token"):
        return "Home Assistant is not configured. Use smart_home_setup with the URL and a long-lived token."
    ok, body = _ha_request("GET", "/api/states")
    if not ok:
        return f"Could not read Home Assistant states: {body}."
    try:
        states = json.loads(body)
    except Exception:
        return "Home Assistant returned an unexpected response."
    by_entity = {}
    if isinstance(states, list):
        for item in states:
            if isinstance(item, dict) and item.get("entity_id"):
                by_entity[item["entity_id"]] = item

    state = _load_state()
    updated = 0
    for dtype in TYPE_ORDER:
        for did, data in (state.get(dtype) or {}).items():
            if not isinstance(data, dict):
                continue
            entity = by_entity.get(_ha_entity(dtype, did))
            if not entity:
                continue
            raw = str(entity.get("state", "")).lower()
            attrs = entity.get("attributes") or {}
            try:
                if dtype == "lights":
                    data["on"] = raw == "on"
                    if attrs.get("brightness") is not None:
                        data["brightness"] = _clamp(round(int(attrs["brightness"]) * 100 / 255), 0, 100)
                elif dtype == "fans":
                    data["on"] = raw == "on"
                    if attrs.get("percentage") is not None:
                        data["speed"] = _clamp(round(int(attrs["percentage"]) / 20), 1, 5)
                elif dtype == "ac":
                    data["on"] = raw not in ("off", "unavailable", "unknown")
                    if attrs.get("temperature") is not None:
                        data["temperature"] = _clamp(round(float(attrs["temperature"])), 16, 30)
                elif dtype == "tv":
                    data["on"] = raw not in ("off", "standby", "unavailable", "unknown")
                    if attrs.get("volume_level") is not None:
                        data["volume"] = _clamp(round(float(attrs["volume_level"]) * 100), 0, 100)
                elif dtype == "doors":
                    data["locked"] = raw == "locked"
                elif dtype == "blinds":
                    data["state"] = "open" if raw == "open" else "closed"
                else:
                    data["on"] = raw == "on"
                updated += 1
            except Exception:
                continue
    _save_state(state)
    return f"Synced {updated} devices from Home Assistant."


# ------------------------------------------------------------------- actions

_ACTION_ALIASES = {
    "turn on": "on", "switch on": "on", "start": "on", "chalu": "on", "chalao": "on",
    "turn off": "off", "switch off": "off", "stop": "off", "band": "off", "bandh": "off",
    "flip": "toggle", "switch": "toggle",
    "dim": "brightness", "bright": "brightness", "percent": "brightness", "percentage": "brightness",
    "temp": "temperature",
    "lock": "lock", "unlock": "unlock", "open": "open", "close": "close",
    "speed": "speed", "channel": "channel", "volume": "volume",
    "refresh": "sync", "update": "sync",
}


def _norm_action(action: str) -> str:
    act = _norm(action)
    act = _ACTION_ALIASES.get(act, act)
    if act in ("state", "report", "list", "info", ""):
        return "status"
    return act


def _set_fields(dtype: str, did: str, data: dict, action: str, value: str):
    """Apply one action to one device. Returns (ok, message)."""
    num = _int(value)
    if dtype == "lights":
        if action == "on":
            data["on"] = True
        elif action == "off":
            data["on"] = False
        elif action == "toggle":
            data["on"] = not data.get("on")
        elif action in ("brightness", "set"):
            percent = num if num is not None else 100
            data["brightness"] = _clamp(percent, 0, 100)
            data["on"] = data["brightness"] > 0
        elif action == "status":
            return True, _status_line(dtype, did, data)
        else:
            return False, f"The light supports on, off, toggle and brightness."
    elif dtype == "fans":
        if action == "on":
            data["on"] = True
        elif action == "off":
            data["on"] = False
        elif action == "toggle":
            data["on"] = not data.get("on")
        elif action in ("speed", "set"):
            data["speed"] = _clamp(num if num is not None else 2, 1, 5)
            data["on"] = True
        else:
            return False, "The fan supports on, off, toggle and speed."
    elif dtype == "ac":
        if action == "on":
            data["on"] = True
        elif action == "off":
            data["on"] = False
        elif action == "toggle":
            data["on"] = not data.get("on")
        elif action in ("temperature", "set"):
            data["temperature"] = _clamp(num if num is not None else 24, 16, 30)
            data["on"] = True
        else:
            return False, "The AC supports on, off, toggle and temperature."
    elif dtype == "tv":
        if action == "on":
            data["on"] = True
        elif action == "off":
            data["on"] = False
        elif action == "toggle":
            data["on"] = not data.get("on")
        elif action == "volume":
            data["volume"] = _clamp(num if num is not None else 20, 0, 100)
            data["on"] = True
        elif action == "channel":
            data["channel"] = max(1, num if num is not None else 1)
            data["on"] = True
        elif action == "set":
            if value and "%" in value:
                data["volume"] = _clamp(num if num is not None else 20, 0, 100)
            else:
                data["channel"] = max(1, num if num is not None else 1)
            data["on"] = True
        else:
            return False, "The TV supports on, off, toggle, channel and volume."
    elif dtype == "doors":
        if action == "lock":
            data["locked"] = True
        elif action == "unlock":
            data["locked"] = False
        elif action == "toggle":
            data["locked"] = not data.get("locked")
        else:
            return False, "The door supports lock and unlock."
    elif dtype == "blinds":
        if action in ("open", "on"):
            data["state"] = "open"
        elif action in ("close", "off"):
            data["state"] = "closed"
        elif action == "toggle":
            data["state"] = "closed" if data.get("state") == "open" else "open"
        else:
            return False, "The blinds support open and close."
    elif dtype in ("coffee", "plugs"):
        if action == "on":
            data["on"] = True
        elif action == "off":
            data["on"] = False
        elif action == "toggle":
            data["on"] = not data.get("on")
        else:
            return False, f"The {_singular(dtype)} supports on, off and toggle."
    else:
        return False, "Unknown device type."

    return True, _status_line(dtype, did, data)


def home_status() -> str:
    state = _load_state()
    lines = ["Smart home status:"]
    for dtype in TYPE_ORDER:
        devices = state.get(dtype) or {}
        if not devices:
            continue
        items = [_status_line(dtype, did, data) for did, data in devices.items()
                 if isinstance(data, dict)]
        if items:
            lines.append(f"- {dtype.replace('_', ' ').title()}: " + ", ".join(items) + ".")
    cfg = _load_config()
    if cfg.get("enabled") and cfg.get("url"):
        lines.append(f"- Home Assistant: connected at {cfg['url']} (say 'sync home' to refresh).")
    else:
        lines.append("- Home Assistant: not configured (virtual devices only).")
    return "\n".join(lines)


def _summarize_changes(changes: list) -> str:
    counts = {}
    for item in changes:
        dtype = item[0]
        counts[dtype] = counts.get(dtype, 0) + 1
    parts = [f"{n} {name.replace('_', ' ')}" for name, n in counts.items()]
    return ", ".join(parts)


def _cap(text: str) -> str:
    text = str(text or "")
    return text[:1].upper() + text[1:]


def smart_home(action: str = "status", device: str = "", value: str = "") -> str:
    """Control the smart home (lights, fans, AC, TV, doors, blinds, coffee, plugs).

    action:
      status      - show every device (default)
      on / off / toggle
      brightness  - lights, value 0-100
      temperature - AC, value 16-30 (turns it on)
      volume      - TV, value 0-100
      channel     - TV, value 1+
      speed       - fan, value 1-5
      lock / unlock - doors
      open / close  - blinds
      sync        - refresh state from Home Assistant
    device: room and/or type, e.g. "drawing room light", "bedroom ac", "tv",
      "main door", "kitchen blinds", "coffee machine", "iron plug".
      Use "all" / "sab" for every device of the chosen type.
    value: number/text for brightness, temperature, volume, channel or speed.
    """
    act = _norm_action(action)
    if act == "status":
        return home_status()
    if act == "sync":
        return _sync_from_ha()
    if act not in ("on", "off", "toggle", "brightness", "temperature", "volume",
                   "channel", "speed", "lock", "unlock", "open", "close", "set"):
        return ("Unknown action. Use status, on, off, toggle, brightness, temperature, "
                "volume, channel, speed, lock, unlock, open, close or sync.")

    raw_device = _norm(device)
    targets = _resolve_targets(raw_device, act)
    if isinstance(targets, str):
        return targets
    if not targets:
        return "I could not find that device. " + _device_menu()
    if act in ("lock", "unlock"):
        targets = [t for t in targets if t[0] == "doors"]
    if act in ("open", "close"):
        targets = [t for t in targets if t[0] in ("blinds",)]
    if not targets:
        return "That action only works on doors or blinds."

    state = _load_state()
    changed = []
    messages = []
    notes = []
    for dtype, did, label in targets:
        data = state.get(dtype, {}).get(did)
        if not isinstance(data, dict):
            continue
        ok, msg = _set_fields(dtype, did, data, act, value)
        if not ok:
            return msg
        changed.append((dtype, did))
        messages.append(msg)

    _save_state(state)

    cfg = _load_config()
    if cfg.get("enabled"):
        for dtype, did in changed:
            ok, note = _ha_push(dtype, did, state[dtype][did])
            if not ok:
                notes.append(note)

    if len(messages) == 1:
        reply = _cap(messages[0]) + "."
    elif len(messages) <= 4:
        reply = "Done: " + "; ".join(messages) + "."
    else:
        reply = f"Done: {_summarize_changes(changed)} updated."
    if notes:
        reply += " Home Assistant reported: " + notes[0] + "."
    return reply


def smart_scene(name: str = "") -> str:
    """Apply a whole-house scene: morning, movie, sleep, guest, work, away or party.

    name: the scene name (English or Roman Urdu, e.g. "movie", "sleep",
    "good morning", "mehman", "bahar ja raha").
    """
    text = _norm(name)
    scene = None
    for key, aliases in SCENE_ALIASES.items():
        if text == key or any(_has_word(text, alias) or text == alias for alias in aliases):
            scene = key
            break
    if scene is None:
        return ("Unknown scene. Available scenes: morning, movie, sleep, guest, work, away, party.")

    state = _load_state()
    changed = []
    for dtype, did, fields in SCENES[scene]:
        data = state.get(dtype, {}).get(did)
        if not isinstance(data, dict):
            continue
        data.update(fields)
        changed.append((dtype, did))

    _save_state(state)

    notes = []
    cfg = _load_config()
    if cfg.get("enabled"):
        for dtype, did in changed:
            ok, note = _ha_push(dtype, did, state[dtype][did])
            if not ok:
                notes.append(note)

    reply = f"Scene '{scene}' applied: {_summarize_changes(changed)} updated."
    if notes:
        reply += " Home Assistant reported: " + notes[0] + "."
    return reply


def smart_home_setup(url: str = "", token: str = "", enabled: bool = True) -> str:
    """Connect or disconnect Home Assistant (optional).

    url:   Home Assistant address, e.g. "http://192.168.1.10:8123"
    token: a long-lived access token from the Home Assistant profile page.
           Leave empty to keep the saved token.
    enabled: false disables Home Assistant and keeps the virtual home only.
    """
    cfg = _load_config()
    if not enabled:
        cfg["enabled"] = False
        _save_config(cfg)
        return "Home Assistant disabled. The virtual smart home still works."

    new_url = (url or "").strip()
    new_token = (token or "").strip()
    if new_url:
        if not re.match(r"^https?://", new_url, re.I):
            new_url = "http://" + new_url
        cfg["url"] = new_url.rstrip("/")
    if new_token:
        cfg["token"] = new_token
    if not cfg.get("url"):
        return "Give me the Home Assistant URL first, for example http://192.168.1.10:8123."
    if not cfg.get("token"):
        return "I still need a long-lived access token from Home Assistant."
    cfg["enabled"] = True
    _save_config(cfg)

    ok, body = _ha_request("GET", "/api/")
    if not ok:
        return ("Saved, but the connection failed: " + body +
                ". Check the URL and token, then say 'test home assistant'.")
    location = ""
    try:
        data = json.loads(body)
        location = data.get("location_name") or ""
    except Exception:
        pass
    return ("Home Assistant connected" + (f": {location}" if location else "") +
            ". Say 'sync home' to import the device states.")


def smart_home_help() -> str:
    """Explain the smart home commands and available devices."""
    return (_device_menu() + " Scenes: morning, movie, sleep, guest, work, away, party. "
            "Home Assistant is optional; say 'connect home assistant' with the URL and token.")
