"""Real hands for JARVIS: Windows UI automation, files, system and network control."""
from __future__ import annotations

import concurrent.futures
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from . import core

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

# --------------------------------------------------------------------------
# Windows UI Automation (pywinauto)
# --------------------------------------------------------------------------
_UI_READY = None


def _uia_available() -> bool:
    global _UI_READY
    if _UI_READY is None:
        try:
            import pywinauto  # noqa: F401
            _UI_READY = True
        except Exception:
            _UI_READY = False
    return bool(_UI_READY)


def _desktop():
    from pywinauto import Desktop
    return Desktop(backend="uia")


def _match_window(title: str):
    title_l = (title or "").lower().strip()
    if not title_l:
        return None
    try:
        wins = _desktop().windows()
    except Exception:
        return None
    visible = []
    for w in wins:
        try:
            if not w.is_visible():
                continue
            visible.append(w)
        except Exception:
            continue
    for w in visible:
        try:
            if (w.window_text() or "").strip().lower() == title_l:
                return w
        except Exception:
            continue
    for w in visible:
        try:
            if title_l in (w.window_text() or "").lower():
                return w
        except Exception:
            continue
    return None


def _rect_text(rect) -> str:
    try:
        l, t, r, b = rect.left, rect.top, rect.right, rect.bottom
        return f"{r - l}x{b - t} at ({l},{t})"
    except Exception:
        return "?"


def list_windows_detailed() -> str:
    """List every visible window with its process, size and position."""
    if not _uia_available():
        try:
            import pyautogui
            return "\n".join(f"- {w.title}" for w in pyautogui.getAllWindows() if w.title)
        except Exception:
            return "UI automation is not available."
    rows = []
    try:
        for w in _desktop().windows():
            try:
                if not w.is_visible():
                    continue
                title = (w.window_text() or "").strip()
                if not title:
                    continue
                pid = w.process_id()
                try:
                    pname = psutil.Process(pid).name() if psutil else "?"
                except Exception:
                    pname = "?"
                rows.append((title, pname, pid, _rect_text(w.rectangle())))
            except Exception:
                continue
    except Exception as e:
        return f"Could not list windows: {e}"
    if not rows:
        return "No visible windows found."
    seen = set()
    out = []
    for title, pname, pid, rect in rows:
        key = (title, pid)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"- {title}  [{pname}, pid {pid}, {rect}]")
    return "\n".join(out[:60])


def _control_rows(win, limit: int = 140):
    rows = []
    try:
        for c in win.descendants():
            try:
                info = c.element_info
                ctype = (info.control_type or "").strip()
                name = (info.name or "").strip()
                auto = (info.automation_id or "").strip()
                if not name and not auto:
                    continue
                if ctype in ("Pane", "Group", "Custom", "Document") and not name:
                    continue
                rows.append({"type": ctype, "name": name, "id": auto,
                             "rect": info.rectangle, "control": c})
            except Exception:
                continue
            if len(rows) >= limit:
                break
    except Exception:
        pass
    return rows


def list_window_controls(window_title: str) -> str:
    """List the buttons, fields, menus and tabs inside a window (by title)."""
    if not _uia_available():
        return "UI automation is not available."
    win = _match_window(window_title)
    if win is None:
        return f"No visible window matching '{window_title}'."
    rows = _control_rows(win)
    if not rows:
        return f"'{window_title}' has no readable controls."
    out = [f"Controls in '{win.window_text()}':"]
    for i, r in enumerate(rows, 1):
        label = r["name"] or r["id"]
        extra = f" id={r['id']}" if r["id"] and r["name"] else ""
        out.append(f"{i}. [{r['type']}] {label}{extra}  {_rect_text(r['rect'])}")
    return "\n".join(out)


def _find_control(win, wanted: str):
    wanted_l = (wanted or "").strip().lower()
    if not wanted_l:
        return None
    rows = _control_rows(win, 400)
    # exact name, exact id, then contains
    for r in rows:
        if (r["name"] or "").lower() == wanted_l or (r["id"] or "").lower() == wanted_l:
            return r["control"]
    for r in rows:
        if wanted_l in (r["name"] or "").lower() or wanted_l in (r["id"] or "").lower():
            return r["control"]
    return None


def _vision_click(description: str) -> bool:
    fn = core.G.get("_find_and_click")
    if not fn:
        return False
    try:
        return bool(fn(description))
    except Exception:
        return False


def ui_operation(action: str = "status", window: str = "", control: str = "",
                 text: str = "", keys: str = "", double: bool = False) -> str:
    """Control Windows apps through real UI Automation (reliable, no guessing).

    action:
      status      - active window info
      list        - visible windows
      controls    - list controls inside a window
      click       - click a button/link/menu item by its name
      double_click- double-click a control
      type        - type text into a field (control = field name; empty = focused field)
      set_text    - replace a field's text directly
      press       - send keys/shortcut to the window (e.g. 'ctrl+s', 'enter')
      focus       - bring a window to the front
      minimize / maximize / restore / close
      menu        - open a menu by name (control)
      read        - read all visible text from the window
      select      - choose an item in a combo box (control = combo, text = item)
      toggle      - check/uncheck a checkbox
    """
    a = (action or "status").lower().strip().replace("-", "_")
    if a in ("status", "active", "info"):
        try:
            import pyautogui
            title = pyautogui.getActiveWindowTitle() or "unknown"
            w = _match_window(title) if title != "unknown" else None
            if w:
                return (f"Active window: {w.window_text()}  pid {w.process_id()}  "
                        f"{_rect_text(w.rectangle())}")
            return f"Active window: {title}"
        except Exception as e:
            return f"Could not read the active window: {e}"
    if a in ("list", "windows", "list_windows"):
        return list_windows_detailed()
    if a in ("controls", "elements", "list_controls"):
        return list_window_controls(window)

    if not _uia_available():
        # graceful fallback to the original vision-based tools
        if a == "type" and text:
            fn = core.G.get("type_text")
            return fn(text) if fn else "Typing is unavailable."
        if a == "press" and keys:
            fn = core.G.get("press_keys")
            return fn(keys) if fn else "Key presses are unavailable."
        if a in ("click", "double_click") and control:
            return (f"Clicked {control}." if _vision_click(control)
                    else f"Could not see {control} on screen.")
        return "UI automation is not available."

    win = _match_window(window) if window else None
    if win is None and a not in ("list",):
        return f"No visible window matching '{window}'."
    try:
        if a == "focus":
            try:
                if win.is_minimized():
                    win.restore()
            except Exception:
                pass
            win.set_focus()
            return f"Focused: {win.window_text()}"
        if a == "minimize":
            win.minimize()
            return f"Minimized: {win.window_text()}"
        if a == "maximize":
            win.maximize()
            return f"Maximized: {win.window_text()}"
        if a == "restore":
            win.restore()
            return f"Restored: {win.window_text()}"
        if a == "close":
            win.close()
            return f"Closed: {win.window_text()}"
        if a == "menu":
            win.menu_select(control)
            return f"Opened menu: {control}"
        if a in ("click", "double_click"):
            c = _find_control(win, control)
            if c is not None:
                try:
                    c.invoke()
                except Exception:
                    try:
                        c.click_input(double=bool(double or a == "double_click"))
                    except Exception:
                        c.click_input()
                time.sleep(0.3)
                return f"Clicked '{control}' in {win.window_text()}."
            if _vision_click(control):
                return f"Clicked '{control}' (found visually)."
            return f"Could not find a control named '{control}' in {win.window_text()}."
        if a in ("type", "set_text"):
            c = _find_control(win, control) if control else None
            if c is None:
                win.set_focus()
                time.sleep(0.2)
                if a == "set_text":
                    try:
                        win.type_keys("^a{BACKSPACE}" + text, with_spaces=True)
                    except Exception:
                        import pyautogui
                        pyautogui.hotkey("ctrl", "a")
                        pyautogui.press("backspace")
                        pyautogui.typewrite(text, interval=0.01)
                else:
                    win.type_keys(text, with_spaces=True)
                return f"Typed into the focused window: {core.truncate(text, 120)}"
            try:
                c.set_focus()
            except Exception:
                pass
            if a == "set_text":
                try:
                    c.set_edit_text(text)
                except Exception:
                    try:
                        c.type_keys("^a{BACKSPACE}" + text, with_spaces=True)
                    except Exception:
                        c.click_input()
                        import pyautogui
                        pyautogui.hotkey("ctrl", "a")
                        pyautogui.press("backspace")
                        pyautogui.typewrite(text, interval=0.01)
            else:
                try:
                    c.type_keys(text, with_spaces=True)
                except Exception:
                    c.click_input()
                    import pyautogui
                    pyautogui.typewrite(text, interval=0.01)
            return f"Typed into '{control or 'focused field'}'."
        if a == "press":
            win.set_focus()
            time.sleep(0.2)
            win.type_keys(keys or "enter", with_spaces=True)
            return f"Pressed {keys or 'enter'} in {win.window_text()}."
        if a == "read":
            texts = []
            for r in _control_rows(win, 300):
                if r["name"] and r["name"] not in texts:
                    texts.append(r["name"])
            return "\n".join(texts[:120]) if texts else "No readable text."
        if a == "select":
            c = _find_control(win, control)
            if c is None:
                return f"Could not find '{control}'."
            try:
                c.select(text)
            except Exception:
                try:
                    c.click_input()
                    time.sleep(0.2)
                    c.select(text)
                except Exception as e:
                    return f"Could not select '{text}': {e}"
            return f"Selected '{text}' in '{control}'."
        if a == "toggle":
            c = _find_control(win, control)
            if c is None:
                return f"Could not find '{control}'."
            try:
                state = c.get_toggle_state()
                if state:
                    c.uncheck()
                else:
                    c.check()
                return f"Toggled '{control}'."
            except Exception:
                try:
                    c.click_input()
                    return f"Clicked '{control}'."
                except Exception as e:
                    return f"Could not toggle '{control}': {e}"
    except Exception as e:
        return f"UI operation '{action}' failed: {e}"
    return f"Unknown UI action '{action}'."


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
def _fmt_time(ts) -> str:
    try:
        return time.strftime("%d %b %Y %H:%M", time.localtime(ts))
    except Exception:
        return "?"


def _unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        p = f"{base}_{i}{ext}"
        if not os.path.exists(p):
            return p
    return path


def _size_tree(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total


_CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".ico"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv",
                  ".ppt", ".pptx", ".md"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".java", ".c", ".cpp",
             ".cs", ".php", ".rb", ".go", ".rs", ".sh", ".bat", ".ps1"},
    "Installers": {".exe", ".msi", ".dmg", ".pkg", ".apk"},
}


def _category_for(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in _CATEGORIES.items():
        if ext in exts:
            return cat
    return "Other"


def file_operation(action: str = "list", path: str = "", destination: str = "",
                   pattern: str = "*", recursive: bool = False, content: str = "",
                   query: str = "", extensions: str = "", days: int = 7,
                   limit: int = 50, overwrite: bool = False, confirmed: bool = False) -> str:
    """All local file work in one tool.

    action:
      list         - list a folder (pattern, recursive)
      info         - size, dates and type of a file/folder
      find         - search names recursively (query)
      mkdir        - create a folder
      copy         - copy a file/folder to destination
      move         - move a file/folder to destination (confirmed=true)
      rename       - rename to destination (new name)
      delete       - move to the Recycle Bin (confirmed=true)
      organize     - sort files into category folders (confirmed=true)
      batch_rename - replace query with content in file names (confirmed=true)
      zip / unzip  - create/extract an archive
      search_text  - find text inside files (query, extensions)
      duplicates   - find duplicate files by hash
      disk         - disk usage for every drive
      recent       - recently modified files (days)
      download     - download a URL (path = url, destination = filename)
      open         - open with the default app
      read / write / append - text files
      exists       - check existence
      tree         - folder tree (3 levels)
    """
    a = (action or "list").lower().strip().replace("-", "_")
    p = core.resolve_path(path) if path else core.desktop()

    try:
        if a in ("list", "ls", "dir"):
            if not os.path.isdir(p):
                return f"Not a folder: {p}"
            rows = []
            for entry in os.scandir(p):
                try:
                    if pattern and pattern != "*" and not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        rows.append((entry.name, "<folder>", "", ""))
                    else:
                        st = entry.stat()
                        rows.append((entry.name, core.human_bytes(st.st_size), _fmt_time(st.st_mtime), ""))
                except Exception:
                    continue
            rows.sort(key=lambda x: (x[1] != "<folder>", x[0].lower()))
            if not rows:
                return f"No matching items in {p}."
            out = [f"{p} ({len(rows)} items):"]
            for name, size, mtime, _ in rows[: max(1, int(limit))]:
                out.append(f"- {name}  {size}  {mtime}".rstrip())
            if len(rows) > limit:
                out.append(f"... and {len(rows) - limit} more.")
            return "\n".join(out)

        if a in ("info", "stat"):
            if not os.path.exists(p):
                return f"Not found: {p}"
            st = os.stat(p)
            kind = "folder" if os.path.isdir(p) else (os.path.splitext(p)[1] or "file")
            size = _size_tree(p) if os.path.isdir(p) else st.st_size
            return (f"{p}\nType: {kind}\nSize: {core.human_bytes(size)}\n"
                    f"Created: {_fmt_time(st.st_ctime)}\nModified: {_fmt_time(st.st_mtime)}\n"
                    f"Read-only: {not bool(st.st_mode & 0o200)}")

        if a in ("find", "search"):
            root = p if os.path.isdir(p) else os.path.dirname(p)
            needle = (query or path or "").lower()
            if not needle:
                return "No search name given."
            hits = []
            t0 = time.time()
            for dp, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d.lower() not in
                           ("appdata", "node_modules", ".git", "$recycle.bin", "windows", "__pycache__")]
                for n in dirs + files:
                    if needle in n.lower():
                        hits.append(os.path.join(dp, n))
                if len(hits) >= max(1, int(limit)) or time.time() - t0 > 20:
                    break
            return "\n".join(hits[:limit]) if hits else f"Nothing matching '{needle}' in {root}."

        if a in ("mkdir", "new_folder"):
            os.makedirs(p, exist_ok=True)
            return f"Folder ready: {p}"

        if a in ("copy", "cp"):
            dest = core.resolve_path(destination)
            if not os.path.exists(p):
                return f"Not found: {p}"
            if os.path.isdir(dest) or dest.endswith("\\"):
                dest = os.path.join(dest, os.path.basename(p.rstrip("\\/")))
            if os.path.exists(dest) and not overwrite:
                dest = _unique_path(dest)
            if os.path.isdir(p):
                shutil.copytree(p, dest, dirs_exist_ok=bool(overwrite))
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(p, dest)
            return f"Copied to: {dest}"

        if a in ("move", "mv"):
            msg = core.guard("file_operation:move", confirmed, f"Move '{p}' to '{destination}'.")
            if msg:
                return msg
            dest = core.resolve_path(destination)
            if not os.path.exists(p):
                return f"Not found: {p}"
            if os.path.isdir(dest):
                dest = os.path.join(dest, os.path.basename(p.rstrip("\\/")))
            if os.path.exists(dest) and not overwrite:
                dest = _unique_path(dest)
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            shutil.move(p, dest)
            return f"Moved to: {dest}"

        if a in ("rename", "ren"):
            if not os.path.exists(p):
                return f"Not found: {p}"
            new_name = destination or content
            if not new_name:
                return "No new name given (use destination)."
            dest = os.path.join(os.path.dirname(p), os.path.basename(new_name))
            if os.path.exists(dest):
                return f"Already exists: {dest}"
            os.rename(p, dest)
            return f"Renamed to: {dest}"

        if a in ("delete", "del", "remove"):
            msg = core.guard("file_operation:delete", confirmed, f"Delete '{p}' (to the Recycle Bin).")
            if msg:
                return msg
            if not os.path.exists(p):
                return f"Not found: {p}"
            fn = core.G.get("delete_to_recycle_bin")
            if fn:
                return fn(p)
            try:
                import send2trash  # type: ignore
                send2trash.send2trash(p)
                return f"Moved to the Recycle Bin: {p}"
            except Exception:
                q = p.replace("'", "''")
                call = "DeleteDirectory" if os.path.isdir(p) else "DeleteFile"
                ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; "
                      f"[Microsoft.VisualBasic.FileIO.FileSystem]::{call}('{q}','OnlyErrorDialogs','SendToRecycleBin')")
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=30)
                return f"Moved to the Recycle Bin: {p}" if not os.path.exists(p) else f"Could not delete: {p}"

        if a in ("organize", "sort"):
            msg = core.guard("file_operation:organize", confirmed,
                             f"Sort the files inside '{p}' into category folders.")
            if msg:
                return msg
            if not os.path.isdir(p):
                return f"Not a folder: {p}"
            moved = 0
            for entry in list(os.scandir(p)):
                if entry.is_dir(follow_symlinks=False):
                    continue
                cat = _category_for(entry.name)
                target = os.path.join(p, cat)
                os.makedirs(target, exist_ok=True)
                try:
                    shutil.move(entry.path, _unique_path(os.path.join(target, entry.name)))
                    moved += 1
                except Exception:
                    continue
            return f"Organized {moved} files in {p}."

        if a in ("batch_rename", "mass_rename"):
            msg = core.guard("file_operation:batch_rename", confirmed,
                             f"Rename files inside '{p}' (replace '{query}' with '{content}').")
            if msg:
                return msg
            if not os.path.isdir(p):
                return f"Not a folder: {p}"
            changed = 0
            for entry in list(os.scandir(p)):
                if not entry.is_file():
                    continue
                old = entry.name
                new = old.replace(query, content) if query else (content + old)
                if new and new != old:
                    try:
                        os.rename(entry.path, _unique_path(os.path.join(p, new)))
                        changed += 1
                    except Exception:
                        continue
            return f"Renamed {changed} files in {p}."

        if a == "zip":
            dest = core.resolve_path(destination) if destination else p.rstrip("\\/") + ".zip"
            base = dest[:-4] if dest.lower().endswith(".zip") else dest
            shutil.make_archive(base, "zip", root_dir=p)
            return f"Archive created: {base}.zip"

        if a == "unzip":
            dest = core.resolve_path(destination) if destination else os.path.dirname(p)
            shutil.unpack_archive(p, dest)
            return f"Extracted to: {dest}"

        if a in ("search_text", "grep"):
            if not query:
                return "No text to search for (use query)."
            exts = [e.strip().lower() for e in re.split(r"[,;]+", extensions or "txt,py,md,json,csv,log,html,js,ts,css") if e.strip()]
            hits, scanned = [], 0
            t0 = time.time()
            for dp, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d.lower() not in
                           ("node_modules", ".git", "appdata", "windows", "__pycache__", ".cache")]
                for f in files:
                    if exts and os.path.splitext(f)[1].lower().lstrip(".") not in exts:
                        continue
                    fp = os.path.join(dp, f)
                    try:
                        if os.path.getsize(fp) > 2_000_000:
                            continue
                        scanned += 1
                        with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                            for ln, line in enumerate(fh, 1):
                                if query.lower() in line.lower():
                                    hits.append(f"{fp}:{ln}: {line.strip()[:180]}")
                                    break
                    except Exception:
                        continue
                    if len(hits) >= limit or time.time() - t0 > 25:
                        break
                if len(hits) >= limit or time.time() - t0 > 25:
                    break
            return ("\n".join(hits) if hits else f"Text not found in {scanned} scanned files under {p}.")

        if a in ("duplicates", "dupes"):
            by_size = {}
            for dp, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d.lower() not in ("node_modules", ".git", "appdata", "windows")]
                for f in files:
                    fp = os.path.join(dp, f)
                    try:
                        s = os.path.getsize(fp)
                        if s > 0:
                            by_size.setdefault(s, []).append(fp)
                    except Exception:
                        continue
            groups = []
            for size, files in by_size.items():
                if len(files) < 2:
                    continue
                by_hash = {}
                for fp in files[:60]:
                    try:
                        h = hashlib.md5(open(fp, "rb").read(1024 * 1024)).hexdigest()
                        by_hash.setdefault(h, []).append(fp)
                    except Exception:
                        continue
                for h, same in by_hash.items():
                    if len(same) > 1:
                        groups.append(same)
            if not groups:
                return "No duplicate files found."
            out = [f"Found {len(groups)} duplicate group(s):"]
            for g in groups[:20]:
                out.append(f"- {core.human_bytes(os.path.getsize(g[0]))} each:")
                out.extend(f"    {x}" for x in g)
            return "\n".join(out)

        if a in ("disk", "drives"):
            if psutil is None:
                return "psutil is not available."
            out = []
            for part in psutil.disk_partitions(all=False):
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    out.append(f"{part.device} ({part.fstype}) free {core.human_bytes(u.free)} / "
                               f"{core.human_bytes(u.total)} ({u.percent}% used)")
                except Exception:
                    continue
            return "\n".join(out) if out else "No drives found."

        if a in ("recent", "recent_files"):
            cutoff = time.time() - max(1, int(days)) * 86400
            roots = [core.desktop(), os.path.join(os.path.expanduser("~"), "Documents"),
                     os.path.join(os.path.expanduser("~"), "Downloads")]
            hits = []
            for root in roots:
                if not os.path.isdir(root):
                    continue
                for dp, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for f in files:
                        fp = os.path.join(dp, f)
                        try:
                            mt = os.path.getmtime(fp)
                            if mt >= cutoff:
                                hits.append((mt, fp))
                        except Exception:
                            continue
            hits.sort(reverse=True)
            return "\n".join(f"{_fmt_time(mt)}  {fp}" for mt, fp in hits[:limit]) if hits else "No recent files."

        if a in ("download", "dl"):
            url = path
            if not url.startswith("http"):
                return "Give a full URL in path."
            dest = core.resolve_path(destination) if destination else os.path.join(
                core.desktop(), os.path.basename(urllib.parse.urlparse(url).path) or "download.bin")
            if requests is None:
                urllib.request.urlretrieve(url, dest)
            else:
                with requests.get(url, stream=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as r:
                    r.raise_for_status()
                    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(65536):
                            if chunk:
                                f.write(chunk)
            return f"Downloaded to: {dest} ({core.human_bytes(os.path.getsize(dest))})"

        if a == "open":
            return core.open_path(p)

        if a in ("read", "cat"):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()[:15000]
            except Exception as e:
                return f"Could not read: {e}"

        if a in ("write", "append"):
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "a" if a == "append" else "w", encoding="utf-8") as f:
                f.write(content)
            return f"Saved: {p} ({core.human_bytes(os.path.getsize(p))})"

        if a == "exists":
            return f"{p}: {'exists' if os.path.exists(p) else 'does not exist'}"

        if a == "tree":
            lines = [p]
            base_depth = p.rstrip("\\/").count(os.sep)

            def walk(folder, prefix="", depth=0):
                if depth > 2:
                    return
                try:
                    entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.lower()))
                except Exception:
                    return
                for i, e in enumerate(entries[:40]):
                    last = i == min(len(entries), 40) - 1
                    lines.append(f"{prefix}{'└── ' if last else '├── '}{e.name}")
                    if e.is_dir(follow_symlinks=False):
                        walk(e.path, prefix + ("    " if last else "│   "), depth + 1)

            walk(p)
            return "\n".join(lines[:200])

    except Exception as e:
        return f"File operation '{action}' failed: {e}"
    return f"Unknown file action '{action}'."


# --------------------------------------------------------------------------
# System
# --------------------------------------------------------------------------
_PROTECTED = ("system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
              "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
              "fontdrvhost.exe", "msmpeng.exe", "securityhealthservice.exe", "audiodg.exe",
              "python.exe", "jarvis", "vanguard", "vgc", "vgtray", "riotclientservices")


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _gpu_info() -> str:
    try:
        ps = ("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion "
              "| ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        return "; ".join(
            f"{d.get('Name','?')} ({core.human_bytes(d.get('AdapterRAM') or 0)}, driver {d.get('DriverVersion','?')})"
            for d in data if d.get("Name")) or "Unknown"
    except Exception:
        return "Unknown"


def system_info() -> str:
    """A full hardware/OS report."""
    lines = []
    try:
        lines.append(f"OS: {platform.platform()}")
        lines.append(f"Computer: {platform.node()}  User: {os.environ.get('USERNAME','?')}  "
                     f"Admin: {_is_admin()}")
        lines.append(f"CPU: {platform.processor() or '?'}  "
                     f"({psutil.cpu_count(logical=False) if psutil else '?'} cores / "
                     f"{psutil.cpu_count() if psutil else '?'} threads, "
                     f"{psutil.cpu_percent(interval=0.2) if psutil else '?'}% now)")
        if psutil:
            vm = psutil.virtual_memory()
            lines.append(f"RAM: {core.human_bytes(vm.used)} used / {core.human_bytes(vm.total)} "
                         f"({vm.percent}%)")
            try:
                bt = psutil.boot_time()
                up = time.time() - bt
                lines.append(f"Uptime: {int(up // 86400)}d {int(up % 86400 // 3600)}h "
                             f"{int(up % 3600 // 60)}m (booted {_fmt_time(bt)})")
            except Exception:
                pass
            for part in psutil.disk_partitions(all=False):
                try:
                    u = psutil.disk_usage(part.mountpoint)
                    lines.append(f"Disk {part.device}: {core.human_bytes(u.free)} free of "
                                 f"{core.human_bytes(u.total)} ({u.percent}% used)")
                except Exception:
                    continue
            b = psutil.sensors_battery()
            if b:
                lines.append(f"Battery: {int(b.percent)}% "
                             f"({'charging' if b.power_plugged else 'on battery'})")
        lines.append(f"GPU: {_gpu_info()}")
        lines.append(f"Local IP: {_local_ip()}")
    except Exception as e:
        lines.append(f"(partial report: {e})")
    return "\n".join(lines)


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "?"


def _set_volume(percent: int) -> str:
    p = max(0, min(100, int(percent)))
    try:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        vol = getattr(speakers, "EndpointVolume", None)
        if vol is None:
            vol = speakers.Activate(__import__("comtypes").interface, None)  # legacy fallback
        vol.SetMasterVolumeLevelScalar(p / 100.0, None)
        return f"Volume set to {p}%."
    except Exception:
        fn = core.G.get("set_volume_level")
        if fn:
            try:
                return fn(p)
            except Exception:
                pass
        return f"Could not set the volume precisely (tried {p}%)."


def _mute(mute: bool | None = None) -> str:
    try:
        from pycaw.pycaw import AudioUtilities
        vol = AudioUtilities.GetSpeakers().EndpointVolume
        if mute is None:
            mute = not bool(vol.GetMute())
        vol.SetMute(1 if mute else 0, None)
        return "Muted." if mute else "Unmuted."
    except Exception as e:
        return f"Could not change mute: {e}"


def _set_dark_mode(on: bool) -> str:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                             0, winreg.KEY_SET_VALUE)
        val = 0 if on else 1
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, val)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, val)
        winreg.CloseKey(key)
        return f"Dark mode {'on' if on else 'off'}."
    except Exception as e:
        return f"Could not change dark mode: {e}"


def _wifi_control(on: bool) -> str:
    try:
        r = subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi",
                            "admin=" + ("enable" if on else "disable")],
                           capture_output=True, text=True, timeout=20)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0:
            return f"Wi-Fi {'enabled' if on else 'disabled'}."
        return f"Could not change Wi-Fi (admin rights may be needed): {out[:200]}"
    except Exception as e:
        return f"Wi-Fi control failed: {e}"


def _installed_apps() -> str:
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    apps = {}
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        name = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, name) as app:
                            try:
                                disp = winreg.QueryValueEx(app, "DisplayName")[0]
                            except Exception:
                                continue
                            try:
                                ver = winreg.QueryValueEx(app, "DisplayVersion")[0]
                            except Exception:
                                ver = ""
                            if disp:
                                apps[str(disp)] = str(ver)
                    except Exception:
                        continue
        except Exception:
            continue
    if not apps:
        return "No installed applications could be read."
    return "\n".join(f"- {n} {v}".strip() for n, v in sorted(apps.items(), key=lambda x: x[0].lower())[:200])


def _startup_apps() -> str:
    import winreg
    rows = []
    for hive, label in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, val, _ = winreg.EnumValue(k, i)
                    rows.append(f"- {name} [{label}]: {val}")
        except Exception:
            continue
    for folder in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
                   os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                r"Microsoft\Windows\Start Menu\Programs\Startup")):
        try:
            if os.path.isdir(folder):
                for f in os.listdir(folder):
                    rows.append(f"- {f} [Startup folder]: {os.path.join(folder, f)}")
        except Exception:
            continue
    return "\n".join(rows) if rows else "No startup entries found."


def _process_rows(sort: str = "memory", limit: int = 25) -> str:
    if psutil is None:
        return "psutil is not available."
    rows = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            mi = p.info.get("memory_info")
            rows.append((p.info["pid"], p.info.get("name") or "?",
                         (mi.rss if mi else 0), p.info.get("cpu_percent") or 0.0))
        except Exception:
            continue
    if sort.lower() in ("cpu", "processor"):
        rows.sort(key=lambda r: -r[3])
        label = "CPU%"
    else:
        rows.sort(key=lambda r: -r[2])
        label = "RAM"
    out = [f"Top processes by {label}:"]
    for pid, name, rss, cpu in rows[: max(1, int(limit))]:
        out.append(f"- {name} (pid {pid})  {core.human_bytes(rss)}  CPU {cpu:.1f}%")
    return "\n".join(out)


def _kill_process(name_or_pid: str, confirmed: bool) -> str:
    target = (name_or_pid or "").strip()
    if not target:
        return "No process name or pid given."
    msg = core.guard("system_operation:kill", confirmed, f"Terminate process '{target}'.")
    if msg:
        return msg
    if psutil is None:
        return "psutil is not available."
    killed = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info.get("name") or "").lower()
            pid = str(p.info.get("pid"))
            if target.isdigit() and pid != target:
                continue
            if not target.isdigit() and target.lower() not in name:
                continue
            if any(prot in name for prot in _PROTECTED):
                continue
            p.terminate()
            killed.append(f"{name} ({pid})")
        except Exception:
            continue
    try:
        psutil.wait_procs([psutil.Process(int(target))], timeout=2) if target.isdigit() else None
    except Exception:
        pass
    return ("Terminated: " + ", ".join(killed)) if killed else f"No matching process for '{target}'."


def system_operation(action: str = "info", value: str = "", confirmed: bool = False,
                     limit: int = 25) -> str:
    """One tool for Windows system control.

    action:
      info            - CPU, RAM, disks, battery, GPU, uptime, IP
      processes       - top processes (value = 'cpu' or 'memory', limit)
      kill            - terminate a process (value = name or pid, confirmed=true)
      brightness      - set screen brightness (value = 0-100)
      volume          - set volume (value = 0-100)
      mute            - value on/off/toggle
      wifi            - value on/off (needs admin)
      dark_mode       - value on/off
      installed_apps  - list installed programs
      startup_apps    - list startup entries
      clean_temp      - delete temp files (confirmed=true)
      recycle_bin     - empty the Recycle Bin (confirmed=true)
      power           - value lock/sleep/restart/shutdown/cancel (confirmed=true for restart/shutdown)
      setting         - open a Windows Settings page (value = e.g. display, bluetooth, wifi)
      uptime          - how long Windows has been running
      gpu             - graphics card details
    """
    a = (action or "info").lower().strip().replace("-", "_")
    v = (value or "").strip()
    if a in ("info", "status", "report"):
        return system_info()
    if a in ("processes", "process", "tasks"):
        return _process_rows(v or "memory", limit)
    if a in ("kill", "terminate", "stop"):
        return _kill_process(v, confirmed)
    if a in ("brightness", "screen_brightness"):
        try:
            import screen_brightness_control as sbc
            p = max(0, min(100, int(float(v or 50))))
            sbc.set_brightness(p)
            return f"Brightness set to {p}%."
        except Exception as e:
            return f"Could not set brightness: {e}"
    if a in ("volume", "sound"):
        try:
            return _set_volume(int(float(v or 50)))
        except Exception:
            return "Give a volume percentage, e.g. value='50'."
    if a in ("mute", "unmute"):
        if v.lower() in ("toggle", "switch"):
            return _mute(None)
        return _mute(v.lower() not in ("off", "false", "0", "no", "unmute"))
    if a == "wifi":
        return _wifi_control(v.lower() not in ("off", "false", "0", "no", "disable"))
    if a in ("dark_mode", "theme"):
        return _set_dark_mode(v.lower() in ("on", "true", "1", "yes", "dark", "enable"))
    if a in ("installed_apps", "apps", "programs"):
        return _installed_apps()
    if a in ("startup_apps", "startup"):
        return _startup_apps()
    if a in ("clean_temp", "temp"):
        msg = core.guard("system_operation:clean_temp", confirmed, "Delete old temporary files.")
        if msg:
            return msg
        fn = core.G.get("_clean_temp")
        if fn:
            try:
                count, freed = fn()
                return f"Removed {count} old temp files, freed {core.human_bytes(freed)}."
            except Exception as e:
                return f"Cleanup failed: {e}"
        return "Cleanup is not available."
    if a in ("recycle_bin", "empty_recycle_bin"):
        msg = core.guard("system_operation:recycle_bin", confirmed, "Empty the Recycle Bin permanently.")
        if msg:
            return msg
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"],
                           capture_output=True, text=True, timeout=60)
            return "Recycle Bin emptied."
        except Exception as e:
            return f"Could not empty the Recycle Bin: {e}"
    if a in ("power", "shutdown", "restart", "sleep", "lock"):
        if a in ("shutdown", "restart", "sleep") and not v:
            v = a
        action_word = v.lower().strip() or "lock"
        if action_word in ("restart", "shutdown"):
            msg = core.guard("system_operation:power", confirmed, f"The PC will {action_word} in 30 seconds.")
            if msg:
                return msg
        fn = core.G.get("power_action")
        if fn:
            return fn(action_word)
        return f"Unknown power action '{action_word}'."
    if a in ("setting", "settings"):
        page = v or "home"
        mapping = {
            "display": "display", "sound": "sound", "bluetooth": "bluetooth", "wifi": "network-wifi",
            "network": "network", "apps": "appsfeatures", "update": "windowsupdate",
            "privacy": "privacy", "storage": "storagesense", "power": "powersleep",
            "about": "about", "home": "home",
        }
        try:
            os.startfile("ms-settings:" + mapping.get(page.lower(), page))
            return f"Opened Windows Settings: {page}."
        except Exception as e:
            return f"Could not open Settings: {e}"
    if a == "uptime":
        if psutil is None:
            return "psutil is not available."
        up = time.time() - psutil.boot_time()
        return f"Windows has been running for {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m."
    if a == "gpu":
        return _gpu_info()
    return f"Unknown system action '{action}'."


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def _public_ip() -> str:
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=6) if requests else None
        if r is not None:
            return r.json().get("ip", "?")
        return urllib.request.urlopen("https://api.ipify.org", timeout=6).read().decode()
    except Exception:
        return "?"


def _wifi_ssid() -> str:
    try:
        r = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                           timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", r.stdout or "", re.M)
        return m.group(1).strip() if m else "?"
    except Exception:
        return "?"


def network_operation(action: str = "info", target: str = "") -> str:
    """Network diagnostics and utilities.

    action:
      info        - local/public IP, gateway, DNS, Wi-Fi SSID
      ping        - ping target (default 8.8.8.8)
      dns         - resolve a hostname
      ports       - listening ports with owning process
      speed       - download speed test (about 10 MB)
      flush_dns   - clear the DNS cache
      wifi_profiles - saved Wi-Fi networks
      trace       - traceroute to target
      check_port  - test TCP connectivity (target = host:port)
      public_ip   - public IP only
    """
    a = (action or "info").lower().strip().replace("-", "_")
    t = (target or "").strip()
    if a == "info":
        return (f"Host: {platform.node()}\nLocal IP: {_local_ip()}\nPublic IP: {_public_ip()}\n"
                f"Wi-Fi: {_wifi_ssid()}\nGateway/DNS:\n" +
                (subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or "")[:1800])
    if a == "ping":
        host = t or "8.8.8.8"
        try:
            r = subprocess.run(["ping", "-n", "4", host], capture_output=True, text=True, timeout=30)
            return ((r.stdout or "") + (r.stderr or ""))[-1800:]
        except Exception as e:
            return f"Ping failed: {e}"
    if a in ("dns", "resolve"):
        try:
            return f"{t or 'google.com'} -> {socket.gethostbyname(t or 'google.com')}"
        except Exception as e:
            return f"DNS lookup failed: {e}"
    if a in ("ports", "listening"):
        if psutil is None:
            return "psutil is not available."
        rows = []
        try:
            for c in psutil.net_connections(kind="inet"):
                if c.status == psutil.CONN_LISTEN and c.laddr:
                    name = "?"
                    try:
                        name = psutil.Process(c.pid).name() if c.pid else "?"
                    except Exception:
                        pass
                    rows.append(f"- {c.laddr.ip}:{c.laddr.port}  {name} (pid {c.pid})")
        except Exception as e:
            return f"Could not list ports: {e}"
        return "\n".join(sorted(set(rows))[:60]) if rows else "No listening ports found."
    if a in ("speed", "speedtest"):
        if requests is None:
            return "requests is not available."
        try:
            t0 = time.time()
            r = requests.get("https://speed.cloudflare.com/__down?bytes=10000000", timeout=45, stream=True)
            total = 0
            for chunk in r.iter_content(65536):
                total += len(chunk)
                if time.time() - t0 > 20:
                    break
            secs = max(0.001, time.time() - t0)
            mbps = total * 8 / secs / 1_000_000
            return f"Download speed: about {mbps:.1f} Mbps ({core.human_bytes(total)} in {secs:.1f}s)."
        except Exception as e:
            return f"Speed test failed: {e}"
    if a in ("flush_dns", "flushdns"):
        try:
            r = subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, timeout=15)
            return ((r.stdout or "") + (r.stderr or "")).strip()[-600:] or "DNS cache flushed."
        except Exception as e:
            return f"Flush failed: {e}"
    if a in ("wifi_profiles", "wifi"):
        try:
            r = subprocess.run(["netsh", "wlan", "show", "profiles"], capture_output=True, text=True, timeout=10)
            return ((r.stdout or "") + (r.stderr or ""))[-1500:]
        except Exception as e:
            return f"Could not list Wi-Fi profiles: {e}"
    if a in ("trace", "traceroute"):
        host = t or "8.8.8.8"
        try:
            r = subprocess.run(["tracert", "-d", "-h", "12", host], capture_output=True, text=True, timeout=45)
            return ((r.stdout or "") + (r.stderr or ""))[-2000:]
        except Exception as e:
            return f"Traceroute failed: {e}"
    if a == "check_port":
        try:
            host, port = (t or "google.com:443").rsplit(":", 1)
            s = socket.create_connection((host, int(port)), timeout=5)
            s.close()
            return f"{host}:{port} is open."
        except Exception as e:
            return f"{t} is not reachable: {e}"
    if a == "public_ip":
        return _public_ip()
    return f"Unknown network action '{action}'."
