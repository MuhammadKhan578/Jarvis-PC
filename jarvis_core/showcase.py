"""Reel-inspired real-world capabilities for Jarvis PC.

The tools in this module deliberately separate *useful automation* from movie
magic.  ISS tracking and public analytics work without an account. Commerce and
phone-agent actions open/configure real services, but purchases and outbound
calls remain confirmation-gated and success is reported only from a real API.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

from . import core

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


ISS_API = "https://api.wheretheiss.at/v1/satellites/25544"
ISS_FILE = os.path.join(core.REPORTS_DIR, "ISS_Live_Tracker.html")
SHOPPING_FILE = os.path.join(core.DATA_DIR, "shopping_list.json")
MONITORS_FILE = os.path.join(core.DATA_DIR, "social_monitors.json")


def _http_json(method: str, url: str, *, headers: dict | None = None,
               json_body: dict | None = None, data: dict | None = None,
               timeout: int = 25):
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.request(method.upper(), url, headers=headers or {},
                                json=json_body, data=data, timeout=timeout)
    text = response.text or ""
    try:
        payload = response.json()
    except Exception:
        payload = {"text": text[:4000]}
    return response.status_code, payload, response.headers


# --------------------------------------------------------------------------- ISS
def _iss_data() -> dict:
    status, data, _ = _http_json("GET", ISS_API, timeout=15)
    if status != 200 or not isinstance(data, dict) or "latitude" not in data:
        raise RuntimeError(f"ISS service returned HTTP {status}: {core.truncate(data, 240)}")
    return data


def _iss_line(data: dict) -> str:
    lat = float(data.get("latitude") or 0)
    lon = float(data.get("longitude") or 0)
    altitude = float(data.get("altitude") or 0)
    velocity = float(data.get("velocity") or 0)
    visibility = str(data.get("visibility") or "unknown")
    footprint = float(data.get("footprint") or 0)
    return (f"ISS is at {lat:.4f}, {lon:.4f}; altitude {altitude:.1f} km; "
            f"speed {velocity:,.0f} km/h; visibility {visibility}; "
            f"ground footprint {footprint:,.0f} km.")


def _write_iss_tracker(initial: dict) -> str:
    os.makedirs(os.path.dirname(ISS_FILE), exist_ok=True)
    # A self-contained dark HUD. It maps longitude/latitude to an equirectangular
    # grid and refreshes from the public ISS endpoint every five seconds.
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>JARVIS ISS Tracker</title>
<style>
html,body{{margin:0;height:100%;background:#030712;color:#dffaff;font-family:Segoe UI,Arial;overflow:hidden}}
.hud{{position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,#0a2740,#030712 65%)}}
h1{{position:absolute;top:18px;left:28px;margin:0;color:#60eaff;letter-spacing:4px;font:700 22px Consolas}}
#map{{position:absolute;left:5%;right:5%;top:13%;bottom:14%;border:1px solid #1eb9d2;border-radius:18px;
background-color:#061526;background-image:linear-gradient(#0b3852 1px,transparent 1px),linear-gradient(90deg,#0b3852 1px,transparent 1px);
background-size:8.333% 16.666%;box-shadow:0 0 40px #00d9ff22 inset,0 0 30px #00d9ff22}}
#equator{{position:absolute;left:0;right:0;top:50%;height:1px;background:#f59e0b66}}
#iss{{position:absolute;width:24px;height:24px;margin:-12px;border-radius:50%;background:#fff;border:3px solid #ffb703;
box-shadow:0 0 12px #fff,0 0 32px #ffb703;transition:left 1s linear,top 1s linear}}
#trail{{position:absolute;inset:0;pointer-events:none}} .dot{{position:absolute;width:4px;height:4px;border-radius:50%;background:#38bdf888}}
#stats{{position:absolute;left:5%;right:5%;bottom:4%;display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}
.card{{border:1px solid #164e63;background:#071827cc;border-radius:10px;padding:10px 14px}}
.label{{font:10px Consolas;color:#6aa5b7;letter-spacing:2px}}.value{{font:700 17px Consolas;color:#e8fdff;margin-top:3px}}
#status{{position:absolute;right:30px;top:25px;color:#4ade80;font:12px Consolas}}
</style></head><body><div class="hud"><h1>J.A.R.V.I.S. // ISS LIVE ORBIT</h1><div id="status">● LIVE</div>
<div id="map"><div id="equator"></div><div id="trail"></div><div id="iss"></div></div><div id="stats">
<div class="card"><div class="label">LATITUDE</div><div id="lat" class="value"></div></div>
<div class="card"><div class="label">LONGITUDE</div><div id="lon" class="value"></div></div>
<div class="card"><div class="label">ALTITUDE</div><div id="alt" class="value"></div></div>
<div class="card"><div class="label">VELOCITY</div><div id="vel" class="value"></div></div>
<div class="card"><div class="label">VISIBILITY</div><div id="vis" class="value"></div></div></div></div>
<script>
const API={json.dumps(ISS_API)}, initial={json.dumps(initial)};const history=[];
function render(d){{const x=(+d.longitude+180)/360*100,y=(90-(+d.latitude))/180*100;
 const dot=document.getElementById('iss');dot.style.left=x+'%';dot.style.top=y+'%';history.push([x,y]);if(history.length>50)history.shift();
 document.getElementById('trail').innerHTML=history.map(p=>`<i class="dot" style="left:${{p[0]}}%;top:${{p[1]}}%"></i>`).join('');
 lat.textContent=(+d.latitude).toFixed(4)+'°';lon.textContent=(+d.longitude).toFixed(4)+'°';
 alt.textContent=(+d.altitude).toFixed(1)+' km';vel.textContent=Math.round(+d.velocity).toLocaleString()+' km/h';vis.textContent=d.visibility||'unknown';}}
async function tick(){{try{{const r=await fetch(API);if(!r.ok)throw Error(r.status);render(await r.json());status.textContent='● LIVE';status.style.color='#4ade80'}}catch(e){{status.textContent='● RETRYING';status.style.color='#fbbf24'}}}}
render(initial);setInterval(tick,5000);tick();
</script></body></html>"""
    with open(ISS_FILE, "w", encoding="utf-8") as handle:
        handle.write(page)
    return ISS_FILE


def iss_operation(action: str = "status", open_tracker: bool = False) -> str:
    """Track the International Space Station in real time.

    action: status (current coordinates), open/track (live HUD tracker), web
    (open NASA's tracker). No API key is required.
    """
    a = (action or "status").strip().lower()
    if a in ("web", "nasa"):
        return core.open_url("https://spotthestation.nasa.gov/tracking_map.cfm")
    try:
        data = _iss_data()
    except Exception as e:
        return f"ISS tracking failed: {e}"
    line = _iss_line(data)
    if a in ("open", "track", "tracker", "live") or open_tracker:
        path = _write_iss_tracker(data)
        opened = core.open_path(path)
        core.audit("iss_operation", "live tracker", path)
        return line + f" Live tracker: {path}. {opened}"
    return line


# ---------------------------------------------------------------- visual guide
def _locate_screen_target(target: str) -> dict:
    fn = core.G.get("_screen_ask")
    if not callable(fn):
        raise RuntimeError("screen vision is not available")
    prompt = (
        "Find this visible UI target on the current screen: " + json.dumps(target) + ". "
        "Reply ONLY JSON with x and y from 0 to 1000 at the target center, plus found and label: "
        '{"found":true,"x":500,"y":400,"label":"Export"}. Do not click anything.'
    )
    data = fn(prompt)
    if not isinstance(data, dict):
        data = core.parse_json_loose(data) or {}
    return data if isinstance(data, dict) else {}


def _overlay_at(x: int, y: int, label: str, seconds: float = 5.0):
    """Show a temporary click-through-style visual guide on the primary screen."""
    def run():
        try:
            import tkinter as tk
            import pyautogui
            sw, sh = pyautogui.size()
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            transparent = "#010203"
            root.configure(bg=transparent)
            try:
                root.wm_attributes("-transparentcolor", transparent)
            except Exception:
                root.attributes("-alpha", 0.93)
            root.geometry(f"{sw}x{sh}+0+0")
            canvas = tk.Canvas(root, width=sw, height=sh, bg=transparent,
                               highlightthickness=0, bd=0)
            canvas.pack()
            radius = max(38, min(sw, sh) // 18)
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                               outline="#a855f7", width=6)
            canvas.create_oval(x-radius-10, y-radius-10, x+radius+10, y+radius+10,
                               outline="#22d3ee", width=2)
            text = label or "Look here"
            box_x = min(sw-220, max(20, x + radius + 18))
            box_y = min(sh-80, max(20, y - 25))
            canvas.create_rectangle(box_x-10, box_y-9, box_x+205, box_y+40,
                                    fill="#111827", outline="#a855f7", width=2)
            canvas.create_text(box_x, box_y, anchor="nw", fill="#f5e9ff",
                               text=text[:80], font=("Segoe UI", 12, "bold"), width=190)
            root.after(int(max(1.0, min(30.0, seconds)) * 1000), root.destroy)
            root.mainloop()
        except Exception as e:
            core.log(f"visual guide overlay failed: {e}")
    threading.Thread(target=run, name="jarvis-visual-guide", daemon=True).start()


def visual_guide(action: str = "point", target: str = "", message: str = "",
                 seconds: float = 5.0) -> str:
    """Find a visible UI element and highlight it without clicking.

    Use for questions such as "how do I export this?". action=find returns the
    coordinates; point/highlight also draws a temporary purple/cyan overlay.
    """
    if not target.strip():
        return "What should I point out on the screen?"
    try:
        data = _locate_screen_target(target)
        if not data.get("found", True) or "x" not in data or "y" not in data:
            return f"I could not find '{target}' on the current screen."
        import pyautogui
        sw, sh = pyautogui.size()
        px = int(max(0, min(1000, float(data["x"]))) / 1000 * sw)
        py = int(max(0, min(1000, float(data["y"]))) / 1000 * sh)
        label = message.strip() or str(data.get("label") or target)
        if (action or "point").lower() in ("point", "highlight", "show", "guide"):
            _overlay_at(px, py, label, seconds)
            return f"Highlighted '{label}' at screen position {px}, {py} for {seconds:g} seconds."
        return json.dumps({"found": True, "x": px, "y": py, "label": label})
    except Exception as e:
        return f"Visual guidance failed: {e}"


# --------------------------------------------------------------------- commerce
_COMMERCE = {
    "foodpanda": "https://www.foodpanda.pk/restaurants/new?query={q}",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "ubereats": "https://www.ubereats.com/search?q={q}",
    "doordash": "https://www.doordash.com/search/store/{q}",
    "instacart": "https://www.instacart.com/store/s?k={q}",
    "amazon": "https://www.amazon.com/s?k={q}",
}


def _shopping() -> list[dict]:
    data = core.read_json(SHOPPING_FILE, []) or []
    return data if isinstance(data, list) else []


def commerce_operation(action: str = "search", query: str = "", service: str = "foodpanda",
                       item: str = "", quantity: int = 1, confirmed: bool = False) -> str:
    """Food/grocery search, local shopping list and guarded checkout hand-off.

    action: search/open_food/open_grocery, add/list/remove shopping-list items,
    checkout/order (opens the service after explicit confirmation; the website
    must confirm the cart/payment—Jarvis never invents an order).
    """
    a = (action or "search").strip().lower()
    if a in ("add", "add_item"):
        value = (item or query).strip()
        if not value:
            return "Which item should I add?"
        rows = _shopping()
        rows.append({"item": value, "quantity": max(1, int(quantity or 1)), "added": time.time()})
        core.write_json(SHOPPING_FILE, rows[-500:])
        return f"Added {max(1, int(quantity or 1))} x {value} to the local shopping list."
    if a in ("list", "shopping_list"):
        rows = _shopping()
        return ("Shopping list:\n" + "\n".join(
            f"- {r.get('quantity', 1)} x {r.get('item', '')}" for r in rows)) if rows else "Shopping list is empty."
    if a in ("remove", "delete"):
        msg = core.guard("commerce_operation:remove", confirmed,
                         f"Remove '{item or query}' from the shopping list.")
        if msg:
            return msg
        needle = (item or query).lower().strip()
        rows = _shopping(); kept = [r for r in rows if needle not in str(r.get("item", "")).lower()]
        core.write_json(SHOPPING_FILE, kept)
        return f"Removed {len(rows)-len(kept)} shopping-list item(s)."
    svc = (service or "foodpanda").strip().lower().replace(" ", "")
    template = _COMMERCE.get(svc)
    if not template:
        return "Supported services: " + ", ".join(sorted(_COMMERCE)) + "."
    q = (query or item or "food delivery").strip()
    url = template.format(q=urllib.parse.quote_plus(q))
    if a in ("checkout", "order", "buy", "purchase"):
        msg = core.guard("commerce_operation:order", confirmed,
                         f"Open {svc} to prepare an order for '{q}'. Final cart and payment still need verification.")
        if msg:
            return msg
    opened = core.open_url(url, core.G.get("PREFERRED_BROWSER") or "brave")
    core.audit("commerce_operation", f"{a} {svc} {q}", opened,
               risk="high" if a in ("checkout", "order", "buy", "purchase") else "normal")
    return (f"Opened {svc} search for '{q}'. {opened} "
            "No purchase is claimed until the service itself confirms checkout.")


# --------------------------------------------------------------- notifications
def _alert_cfg() -> dict:
    raw = core.config_get("remote_alerts", {}) or {}
    if not isinstance(raw, dict):
        return {}
    cfg = dict(raw)
    cfg["token"] = core.unprotect_secret(str(cfg.get("token") or ""))
    return cfg


def notification_operation(action: str = "status", title: str = "Jarvis", message: str = "",
                           server: str = "", topic: str = "", token: str = "",
                           priority: str = "high", click_url: str = "", confirmed: bool = False) -> str:
    """Send proactive desktop/mobile alerts through ntfy or a generic webhook.

    Configure once with server/topic/token. A phone can subscribe with the free
    ntfy app or Jarvis Mobile's Remote Alerts panel. Sending is confirmation-
    gated unless an already-approved monitor/routine invokes it internally.
    """
    a = (action or "status").strip().lower()
    if a in ("configure", "setup"):
        cfg = dict(_alert_cfg())
        cfg["server"] = (server or cfg.get("server") or "https://ntfy.sh").rstrip("/")
        cfg["topic"] = (topic or cfg.get("topic") or "").strip()
        if token:
            cfg["token"] = core.protect_secret(token.strip(), "jarvis-remote-alerts")
        elif cfg.get("token"):
            cfg["token"] = core.protect_secret(str(cfg["token"]), "jarvis-remote-alerts")
        if not cfg["topic"]:
            return "Give me an ntfy topic (use a long private random name)."
        core.save_config({"remote_alerts": cfg})
        return f"Remote alerts configured: {cfg['server']}/{cfg['topic']}. Token is protected locally."
    cfg = _alert_cfg()
    if a in ("status", "show"):
        return (f"Remote alerts: {cfg.get('server','not configured')}/{cfg.get('topic','')}"
                + (" (token protected)" if cfg.get("token") else ""))
    if a not in ("send", "alert", "notify", "test"):
        return "Alert actions: status, configure, send, test."
    body = (message or "Jarvis alert").strip()
    msg = core.guard("notification_operation:send", confirmed,
                     f"Send this remote notification: {core.truncate(body, 140)}")
    if msg:
        return msg
    endpoint = (server or cfg.get("server") or "").rstrip("/")
    alert_topic = (topic or cfg.get("topic") or "").strip()
    if not endpoint or not alert_topic:
        return "Remote alerts are not configured. Set server/topic first."
    headers = {"Title": title or "Jarvis", "Priority": priority or "high", "Tags": "robot"}
    secret = token or cfg.get("token") or ""
    if secret:
        headers["Authorization"] = "Bearer " + secret
    if click_url:
        headers["Click"] = click_url
    if requests is None:
        return "requests is not installed."
    try:
        response = requests.post(endpoint + "/" + urllib.parse.quote(alert_topic, safe=""),
                                 data=body.encode("utf-8"), headers=headers, timeout=20)
        if response.status_code not in (200, 201, 202):
            return f"Notification failed (HTTP {response.status_code}): {core.truncate(response.text, 240)}"
        core.audit("notification_operation", f"topic={alert_topic}", "sent", risk="high")
        return f"Remote notification sent to topic '{alert_topic}'."
    except Exception as e:
        return f"Notification failed: {e}"


# -------------------------------------------------------------- social metrics
def _metric_number(text: str, label: str) -> int | None:
    m = re.search(r"([\d,.]+)\s*([KMB])?\s+" + label, text or "", re.I)
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", ""))
        number *= {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get((m.group(2) or "").lower(), 1)
        return int(number)
    except Exception:
        return None


def _social_metrics(url: str) -> dict:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    response.raise_for_status()
    text = response.text
    description = ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        description = str(tag.get("content") or "") if tag else ""
        title_tag = soup.find("meta", attrs={"property": "og:title"})
        title = str(title_tag.get("content") or "") if title_tag else (soup.title.get_text(" ") if soup.title else url)
    except Exception:
        title = url
    haystack = description + " " + text[:500000]
    metrics = {
        "views": _metric_number(description, r"views?"),
        "likes": _metric_number(description, r"likes?"),
        "comments": _metric_number(description, r"comments?"),
    }
    if "youtu" in url.lower():
        for key, pattern in (
                ("views", r'"viewCount"\s*:\s*"?(\d+)'),
                ("likes", r'"likeCount"\s*:\s*"?(\d+)'),
                ("comments", r'"commentCount"\s*:\s*"?(\d+)')):
            m = re.search(pattern, haystack)
            if m:
                metrics[key] = int(m.group(1))
    return {"url": url, "title": core.truncate(title, 220), "description": core.truncate(description, 800),
            "metrics": {k: v for k, v in metrics.items() if v is not None}, "checked": time.time()}


def _monitors() -> dict:
    data = core.read_json(MONITORS_FILE, {}) or {}
    return data if isinstance(data, dict) else {}


def _monitor_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def analytics_operation(action: str = "check", url: str = "", monitor_id: str = "",
                        threshold: int = 0, notify: bool = False, confirmed: bool = False) -> str:
    """Check/monitor public Instagram or YouTube views, likes and comments.

    action: check, add/monitor, list, remove, check_all. Official/private account
    metrics still need the platform's API token; public-page metrics are best effort.
    """
    a = (action or "check").strip().lower()
    monitors = _monitors()
    if a in ("list", "status"):
        if not monitors:
            return "No social posts are monitored."
        return "Monitored posts:\n" + "\n".join(
            f"- {mid}: {row.get('title') or row.get('url')} | {row.get('last', {}).get('metrics', {})}"
            for mid, row in monitors.items())
    if a in ("remove", "delete"):
        msg = core.guard("analytics_operation:remove", confirmed, f"Remove analytics monitor {monitor_id}.")
        if msg:
            return msg
        removed = monitors.pop(monitor_id, None); core.write_json(MONITORS_FILE, monitors)
        return "Monitor removed." if removed else "Monitor not found."
    targets = []
    if a in ("check_all", "refresh_all"):
        targets = [(mid, row.get("url", "")) for mid, row in monitors.items()]
    else:
        target_url = (url or (monitors.get(monitor_id) or {}).get("url") or "").strip()
        if not target_url:
            return "Give me an Instagram/YouTube post URL."
        targets = [(monitor_id or _monitor_id(target_url), target_url)]
    outputs = []
    for mid, target_url in targets:
        try:
            current = _social_metrics(target_url)
        except Exception as e:
            outputs.append(f"{mid}: analytics failed: {e}")
            continue
        previous = (monitors.get(mid) or {}).get("last") or {}
        changes = {}
        for key, value in current["metrics"].items():
            old = (previous.get("metrics") or {}).get(key)
            if isinstance(old, int):
                changes[key] = value - old
        if a in ("add", "monitor", "watch") or mid in monitors or a == "check_all":
            monitors[mid] = {"url": target_url, "title": current["title"], "threshold": int(threshold or (monitors.get(mid) or {}).get("threshold") or 0),
                             "notify": bool(notify or (monitors.get(mid) or {}).get("notify")), "last": current}
        line = f"{current['title']}: " + ", ".join(f"{k} {v:,}" for k, v in current["metrics"].items())
        if changes:
            line += " | change: " + ", ".join(f"{k} {v:+,}" for k, v in changes.items())
        outputs.append(line)
        row = monitors.get(mid) or {}
        reached = row.get("threshold") and current["metrics"].get("views", 0) >= int(row["threshold"])
        if row.get("notify") and (reached or any(v > 0 for v in changes.values())):
            notification_operation("send", title="Jarvis analytics", message=line,
                                   priority="high", confirmed=True)
    core.write_json(MONITORS_FILE, monitors)
    return "\n".join(outputs)


# ------------------------------------------------------------------- telephony
def _phone_cfg() -> dict:
    raw = core.config_get("phone_agent", {}) or {}
    if not isinstance(raw, dict):
        return {}
    cfg = dict(raw); cfg["token"] = core.unprotect_secret(str(cfg.get("token") or ""))
    return cfg


def _adb_path() -> str:
    found = shutil.which("adb")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe")
    return candidate if os.path.exists(candidate) else ""


def phone_agent_operation(action: str = "status", phone: str = "", message: str = "",
                          endpoint: str = "", token: str = "", call_id: str = "",
                          confirmed: bool = False) -> str:
    """Dial a paired Android phone or call a configured conversational-phone API.

    configure saves a provider endpoint/token. place/call sends {to,message} to
    that real provider after confirmation; status/transcript reads its factual
    result. Without a provider, dial opens the number on an ADB-connected phone
    and the user presses Call—Jarvis never fakes an autonomous call.
    """
    a = (action or "status").strip().lower()
    if a in ("configure", "setup"):
        cfg = dict(_phone_cfg())
        if endpoint:
            cfg["endpoint"] = endpoint.rstrip("/")
        if token:
            cfg["token"] = core.protect_secret(token, "jarvis-phone-agent")
        if not cfg.get("endpoint"):
            return "Give me the HTTPS endpoint for your telephony/voice-agent provider."
        core.save_config({"phone_agent": cfg})
        return "Phone-agent provider configured. Token is protected locally."
    cfg = _phone_cfg()
    if a in ("status", "show") and not call_id:
        return ("Phone agent configured at " + cfg["endpoint"] if cfg.get("endpoint")
                else "No autonomous phone-agent provider configured. ADB dial is still available.")
    if a in ("dial", "open_dialer"):
        digits = re.sub(r"[^0-9+]", "", phone or "")
        if not digits:
            return "Give me a phone number to dial."
        adb = _adb_path()
        if not adb:
            return "ADB is not available; use Jarvis Mobile to open the dialer."
        try:
            result = subprocess.run([adb, "shell", "am", "start", "-a", "android.intent.action.DIAL",
                                     "-d", "tel:" + digits], capture_output=True, text=True, timeout=20)
            if result.returncode != 0:
                return "Could not open the paired phone dialer: " + core.truncate(result.stderr, 240)
            return f"Opened {digits} in the paired Android dialer. Tap Call on the phone."
        except Exception as e:
            return f"ADB dial failed: {e}"
    if a in ("call", "place", "message_call"):
        msg = core.guard("phone_agent_operation:call", confirmed,
                         f"Place an outbound AI-assisted call to {phone} and relay: {core.truncate(message, 140)}")
        if msg:
            return msg
        if not cfg.get("endpoint"):
            return "No phone-agent provider configured. I can only open the phone dialer."
        headers = {"Content-Type": "application/json"}
        if cfg.get("token"):
            headers["Authorization"] = "Bearer " + cfg["token"]
        try:
            status, data, _ = _http_json("POST", cfg["endpoint"], headers=headers,
                                         json_body={"to": phone, "message": message,
                                                    "assistant": "Jarvis", "request_transcript": True})
            if status not in (200, 201, 202):
                return f"Phone provider rejected the call (HTTP {status}): {core.truncate(data, 300)}"
            cid = str(data.get("id") or data.get("call_id") or "") if isinstance(data, dict) else ""
            core.audit("phone_agent_operation", f"to={phone}", f"accepted id={cid}", risk="high")
            return f"Phone provider accepted the call" + (f" (id {cid})" if cid else "") + ". Delivery is not claimed until status confirms it."
        except Exception as e:
            return f"Phone call failed: {e}"
    if a in ("call_status", "transcript", "result"):
        if not cfg.get("endpoint") or not call_id:
            return "Give me a call id and configure the provider first."
        headers = {"Authorization": "Bearer " + cfg["token"]} if cfg.get("token") else {}
        try:
            status, data, _ = _http_json("GET", cfg["endpoint"] + "/" + urllib.parse.quote(call_id),
                                         headers=headers)
            return json.dumps(data, ensure_ascii=False, indent=2)[:6000] if status < 400 else f"HTTP {status}: {data}"
        except Exception as e:
            return f"Could not read call status: {e}"
    return "Phone-agent actions: status, configure, dial, call, call_status, transcript."
