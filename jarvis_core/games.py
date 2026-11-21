"""Steam/Epic library discovery, update scanning and guarded install hand-off."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request

from . import core

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _steam_root() -> str:
    candidates = []
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key in (r"Software\Valve\Steam", r"Software\WOW6432Node\Valve\Steam"):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                candidates.append(str(winreg.QueryValueEx(handle, name)[0]))
                            except Exception:
                                pass
                except Exception:
                    continue
    except Exception:
        pass
    candidates += [
        os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
        os.path.expandvars(r"%ProgramFiles%\Steam"),
    ]
    return next((os.path.normpath(p) for p in candidates if p and "%" not in p and os.path.isdir(p)), "")


def _vdf_pairs(text: str) -> dict:
    return {k: v.replace("\\\\", "\\") for k, v in
            re.findall(r'"([^"\r\n]+)"\s+"([^"\r\n]*)"', text or "")}


def steam_libraries() -> list[dict]:
    root = _steam_root()
    if not root:
        return []
    paths = [root]
    file = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(file, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for path in re.findall(r'"path"\s+"([^"]+)"', text, re.I):
            path = path.replace("\\\\", "\\")
            if os.path.isdir(path) and path.lower() not in [x.lower() for x in paths]:
                paths.append(path)
    except Exception:
        pass
    rows = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path)
            rows.append({"path": path, "free": usage.free, "total": usage.total,
                         "steamapps": os.path.join(path, "steamapps")})
        except Exception:
            rows.append({"path": path, "free": 0, "total": 0,
                         "steamapps": os.path.join(path, "steamapps")})
    return rows


def steam_games() -> list[dict]:
    games = []
    for library in steam_libraries():
        for manifest in glob.glob(os.path.join(library["steamapps"], "appmanifest_*.acf")):
            try:
                with open(manifest, "r", encoding="utf-8", errors="replace") as handle:
                    data = _vdf_pairs(handle.read())
                appid = data.get("appid") or re.search(r"(\d+)", os.path.basename(manifest)).group(1)
                down = int(data.get("BytesToDownload") or data.get("bytes_to_download") or 0)
                staged = int(data.get("BytesDownloaded") or data.get("bytes_downloaded") or 0)
                state = int(data.get("StateFlags") or 0)
                games.append({
                    "platform": "Steam", "appid": str(appid), "name": data.get("name") or f"App {appid}",
                    "library": library["path"], "install_dir": data.get("installdir") or "",
                    "state_flags": state, "bytes_to_download": down,
                    "bytes_downloaded": staged, "manifest": manifest,
                    "update_pending": down > 0 or state not in (0, 4),
                    "last_updated": int(data.get("LastUpdated") or 0),
                })
            except Exception:
                continue
    return games


def epic_games() -> list[dict]:
    folder = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                          "Epic", "EpicGamesLauncher", "Data", "Manifests")
    rows = []
    for filename in glob.glob(os.path.join(folder, "*.item")):
        try:
            data = json.load(open(filename, "r", encoding="utf-8"))
            rows.append({
                "platform": "Epic", "appid": str(data.get("CatalogItemId") or data.get("AppName") or ""),
                "name": str(data.get("DisplayName") or data.get("AppName") or "Unknown game"),
                "library": str(data.get("InstallLocation") or ""),
                "version": str(data.get("AppVersionString") or data.get("BuildVersion") or ""),
                "manifest": filename,
            })
        except Exception:
            continue
    return rows


def _steam_search(query: str) -> list[dict]:
    if requests is None:
        return []
    try:
        response = requests.get("https://store.steampowered.com/api/storesearch/",
                                params={"term": query, "l": "english", "cc": "US"},
                                headers={"User-Agent": "Jarvis/2.4"}, timeout=20)
        response.raise_for_status()
        data = response.json()
        return [{"appid": str(x.get("id")), "name": x.get("name", ""),
                 "price": ((x.get("price") or {}).get("final") or 0) / 100,
                 "tiny_image": x.get("tiny_image", "")} for x in (data.get("items") or [])[:8]]
    except Exception as e:
        core.log(f"Steam search failed: {e}")
        return []


def _open_uri(uri: str) -> bool:
    try:
        os.startfile(uri)
        return True
    except Exception:
        try:
            root = _steam_root()
            exe = os.path.join(root, "steam.exe") if root else ""
            if exe and os.path.exists(exe):
                subprocess = __import__("subprocess")
                subprocess.Popen([exe, uri])
                return True
        except Exception:
            pass
    return False


def _steam_store_search(query: str) -> dict:
    """Public Steam storesearch lookup via urllib (no private API, no key)."""
    url = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode(
        {"term": query, "l": "english", "cc": "US"})
    request = urllib.request.Request(url, headers={"User-Agent": "Jarvis/2.4"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    items = payload.get("items") or []
    first = items[0] if items and isinstance(items[0], dict) else {}
    return {"appid": str(first.get("id") or ""), "name": str(first.get("name") or "")}


def _steam_client_path() -> str:
    candidates = []
    for name in ("steam.exe", "steam"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    root = _steam_root()
    if root:
        candidates.append(os.path.join(root, "steam.exe"))
    for raw in (r"%ProgramFiles(x86)%\Steam\steam.exe", r"%ProgramFiles%\Steam\steam.exe"):
        expanded = os.path.expandvars(raw)
        if expanded and "%" not in expanded:
            candidates.append(expanded)
    return next((p for p in candidates if p and os.path.isfile(p)), "")


def _legendary_cfg() -> dict:
    raw = core.config_get("legendary_cli", {}) or {}
    cfg = dict(raw) if isinstance(raw, dict) else {}
    cfg["token"] = core.unprotect_secret(str(cfg.get("token") or ""))
    return cfg


def _library_text() -> str:
    libraries = steam_libraries()
    if not libraries:
        return "Steam was not found on this PC."
    return "Steam libraries:\n" + "\n".join(
        f"- {row['path']} — {core.human_bytes(row['free'])} free / {core.human_bytes(row['total'])}"
        for row in sorted(libraries, key=lambda x: -x["free"]))


def game_operation(action: str = "status", query: str = "", appid: str = "",
                   platform: str = "steam", confirmed: bool = False,
                   token: str = "") -> str:
    """Inspect Steam/Epic libraries and safely launch installs or updates.

    action:
      status/libraries - clients and disk space
      list             - installed games
      updates          - Steam manifests needing downloads + Epic local versions
      search           - find a Steam store app id
      install          - open Steam's real install dialog (confirmation required)
      download         - resolve appid via storesearch and launch steam://install
      update           - open Steam Downloads or Epic Library (confirmation required)
      configure_legendary - save a protected legendary CLI token (optional)

    Download completion and selected drive are reported only from real client
    state. Jarvis recommends the library with most free space; Steam owns the
    final install dialog and download. No silent install is ever performed.
    """
    a = (action or "status").strip().lower()
    plat = (platform or "steam").strip().lower()
    if a == "configure_legendary":
        if not token.strip():
            return "Legendary CLI ka protected token do."
        cfg = _legendary_cfg()
        cfg["token"] = core.protect_secret(token.strip(), "jarvis-legendary-cli")
        core.save_config({"legendary_cli": cfg})
        return "Legendary CLI token locally protected ho gaya. Koi install nahi chalaya."
    if a in ("status", "libraries", "storage"):
        return _library_text() + f"\nInstalled: {len(steam_games())} Steam, {len(epic_games())} Epic."
    if a in ("list", "installed"):
        rows = steam_games() + epic_games()
        if query:
            rows = [r for r in rows if query.lower() in r.get("name", "").lower()]
        return ("Installed games:\n" + "\n".join(
            f"- [{r['platform']}] {r['name']}" + (f" ({r.get('version')})" if r.get("version") else "")
            for r in rows[:100])) if rows else "No matching installed games were found."
    if a in ("updates", "scan_updates", "check_updates"):
        steam = steam_games()
        pending = [g for g in steam if g.get("update_pending")]
        epic = epic_games()
        lines = [f"Steam: {len(pending)} possible update/download(s) from local manifests."]
        lines += [f"- {g['name']}: {core.human_bytes(g['bytes_to_download'])} queued, state {g['state_flags']}"
                  for g in pending[:30]]
        lines.append(f"Epic: {len(epic)} installed title(s). Epic's launcher must check remote versions.")
        if epic:
            lines += [f"- {g['name']} {g.get('version','')}" for g in epic[:20]]
        lines.append("Say 'update my games' to open the clients' verified update screens.")
        return "\n".join(lines)
    if a in ("search", "find"):
        rows = _steam_search(query)
        return ("Steam results:\n" + "\n".join(
            f"- {r['appid']}: {r['name']}" + (f" — ${r['price']:.2f}" if r["price"] else "") for r in rows)) \
            if rows else f"No Steam result for '{query}'."
    if a == "download":
        if plat in ("epic", "legendary"):
            cfg = _legendary_cfg()
            if not cfg.get("token"):
                return ("Epic download handoff: legendary CLI token configured nahi hai. "
                        "Epic Games Launcher kholo aur wahan se install karo; main silent install nahi karta.")
            msg = core.guard("game_operation:download", confirmed,
                             f"Prepare a legendary CLI install command for '{query or appid}'.")
            if msg:
                return msg
            exe = str(cfg.get("exe") or "legendary").strip() or "legendary"
            command = [exe, "install", str(appid or query or "").strip()]
            line = "Legendary install command prepared (NOT executed): " + " ".join(command)
            core.audit("game_operation", f"epic download {command}", "command prepared", risk="high")
            return line + " Jarvis ne silent install nahi kiya; is command ko terminal mein chalao."
        name = (query or "").strip()
        wanted = re.sub(r"\D", "", str(appid or "").strip())
        label = name or (f"app {wanted}" if wanted else "")
        if not wanted:
            if not name:
                return "Download ke liye game ka naam ya Steam appid do."
            try:
                result = _steam_store_search(name)
            except Exception as e:
                return f"Steam storesearch failed: {core.truncate(e, 240)}. Koi install request nahi bheja."
            wanted, label = result.get("appid", ""), result.get("name") or name
        if not wanted:
            return f"Steam store me '{name}' nahi mila. Koi install request nahi bheja."
        if not _steam_client_path():
            return "Steam installed nahi. steam://install URI nahi bheja; pehle Steam client install karo."
        msg = core.guard("game_operation:download", confirmed,
                         f"Send steam://install/{wanted} to the real Steam client for '{label}'.")
        if msg:
            return msg
        uri = "steam://install/" + wanted
        opened = core.open_url(uri)
        ok = "opened" in str(opened).lower() and not str(opened).lower().startswith("could not")
        if not ok:
            return (f"Steam install URI launch failed: {core.truncate(opened, 240)}. "
                    "Koi download start nahi hua.")
        core.audit("game_operation", f"download appid={wanted}", "URI launched", risk="high")
        return (f"install request bheja; Steam client download karega. {label} (appid {wanted}). "
                "Completion aur drive selection Steam client hi batayega; yahan install complete nahi claim kiya.")
    if a == "install":
        msg = core.guard("game_operation:install", confirmed,
                         f"Open the real Steam install dialog for '{query or appid}'.")
        if msg:
            return msg
        wanted = str(appid or "").strip()
        label = query or wanted
        if not wanted:
            results = _steam_search(query)
            if not results:
                return f"Could not find '{query}' in the Steam store."
            wanted, label = results[0]["appid"], results[0]["name"]
        libraries = steam_libraries()
        if not libraries:
            return "Steam is not installed or no Steam library was found."
        best = max(libraries, key=lambda x: x["free"])
        if not _open_uri("steam://install/" + re.sub(r"\D", "", wanted)):
            return "Steam install dialog could not be opened."
        core.audit("game_operation", f"install appid={wanted}", "Steam dialog opened", risk="high")
        return (f"Steam install dialog opened for {label} (appid {wanted}). Recommended library: "
                f"{best['path']} with {core.human_bytes(best['free'])} free. "
                "Steam must confirm the selected drive and download; installation is not yet claimed complete.")
    if a in ("update", "update_all", "downloads"):
        msg = core.guard("game_operation:update", confirmed,
                         f"Open the {plat} client update/download screen.")
        if msg:
            return msg
        if plat == "steam":
            ok = _open_uri("steam://open/downloads")
        else:
            opened = core.open_url("com.epicgames.launcher://store/library")
            ok = not str(opened).lower().startswith("could not")
        return (f"Opened {plat} updates. The client will report real progress."
                if ok else f"Could not open {plat} updates.")
    return ("Game actions: status, libraries, list, updates, search, install, download, "
            "update, configure_legendary.")
