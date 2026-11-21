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

from . import browser, core

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


_CART_SITES = {
    "swiggy": "https://www.swiggy.com",
    "swiggy.in": "https://www.swiggy.com",
    "zomato": "https://www.zomato.com",
}
_CART_CHECKOUT = {
    "https://www.swiggy.com": "https://www.swiggy.com/checkout",
    "https://www.zomato.com": "https://www.zomato.com/cart",
}
_LOGIN_MARKERS = re.compile(r"\b(?:log\s*in|sign\s*in|login|signin|captcha|verify\s+(?:your\s+)?account)\b", re.I)


def _cart_log(steps: list[str], label: str, detail: str) -> None:
    line = f"{label}: {core.truncate(detail, 260)}"
    steps.append(line)
    core.log("commerce cart_add | " + line)


def _cart_add(site: str, item: str, confirmed: bool, steps: list[str]) -> str:
    """Drive the real Edge DevTools browser to attempt an add-to-cart.

    Every step is logged. The final order/payment always stays with the user;
    the checkout tab opens only after explicit confirmation. No purchase,
    order id or payment result is ever claimed here.
    """
    item = (item or "").strip()
    if not item:
        return "needs_user_action: Cart me kya daalun? Item ka naam batao. Koi order/payment nahi kiya."
    _cart_log(steps, "target", f"site={site} item={item}")
    # browser_operation is the existing DevTools path; text="edge" asks for the
    # installed Edge at C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
    try:
        opened = browser.browser_operation("open", url=site, text="edge")
    except Exception as e:
        opened = f"Browser automation unavailable: {e}"
    _cart_log(steps, "open_edge", opened)
    if any(x in opened.lower() for x in ("could not", "did not", "not the requested", "unavailable", "close ")):
        return ("needs_user_action: Edge DevTools automation available nahi hai — " + opened +
                " Mainne item cart me nahi daala; order/payment nahi kiya.")
    body = browser.browser_operation("read")
    _cart_log(steps, "page_read", body[:500])
    if _LOGIN_MARKERS.search(body or ""):
        return ("needs_user_action: login required — Edge profile me is site par sign in karo, "
                "phir dobara try karo. Cart/order/payment nahi kiya.")
    typed = browser.browser_operation("type", text=item, submit=True)
    _cart_log(steps, "search_type", typed)
    if "not_found" in typed.lower() or "failed" in typed.lower():
        return ("needs_user_action: Search box nahi mila — " + typed +
                " Cart/order/payment nahi kiya.")
    browser.browser_operation("wait", text="2")
    found = browser.browser_operation("find", text=item)
    _cart_log(steps, "find_item", found)
    if found.lower().startswith(("no elements", "find failed")):
        return (f"needs_user_action: '{item}' search results me nahi mila. "
                "Cart/order/payment nahi kiya.")
    clicked = ""
    for label in ("ADD TO CART", "Add to cart", "Add", "ADD"):
        clicked = browser.browser_operation("click", text=label)
        _cart_log(steps, "click_" + label.replace(" ", "_"), clicked)
        if clicked.upper().startswith("CLICKED"):
            break
    else:
        return ("needs_user_action: Add-to-cart button click nahi ho paya. "
                "Cart/order/payment nahi kiya.")
    cart_text = browser.browser_operation("read")
    _cart_log(steps, "cart_read", cart_text[:500])
    verified = bool(re.search(r"\b(?:cart|basket|bag)\b", cart_text or "", re.I))
    note = ("Item add karne ka UI step chal gaya" if verified else
            "Add-to-cart click gaya, par site ne cart confirmation nahi dikhaya")
    checkout = _CART_CHECKOUT.get(site, site.rstrip("/") + "/checkout")
    if confirmed:
        chk = browser.browser_operation("open", url=checkout, text="edge")
        _cart_log(steps, "open_checkout", chk)
    else:
        msg = core.guard("commerce_operation:cart_checkout", False,
                         f"Open {checkout} to review the cart.")
        _cart_log(steps, "checkout_guard", msg)
    core.audit("commerce_operation", f"cart_add site={site} item={item}",
               "needs_user_action; no order/payment", risk="high")
    return ("needs_user_action: " + note + ". Final order aur payment AAP karein — "
            "maine order nahi diya aur payment nahi kiya. Cart review ke liye checkout tab "
            "kholne ke liye confirmed=true do. Steps:\n- " + "\n- ".join(steps))


def commerce_operation(action: str = "search", query: str = "", service: str = "foodpanda",
                       item: str = "", quantity: int = 1, confirmed: bool = False,
                       url: str = "") -> str:
    """Food/grocery search, local shopping list and guarded checkout hand-off.

    action: search/open_food/open_grocery, add/list/remove shopping-list items,
    cart_add (real Edge DevTools add-to-cart attempt; user finishes order/payment),
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
    if a in ("cart_add", "add_to_cart"):
        site = str(url or "").strip()
        if site and not re.match(r"^https?://", site, re.I):
            site = "https://" + site
        site = site or _CART_SITES.get(svc, "https://www.swiggy.com")
        return _cart_add(site, (item or query).strip(), confirmed, [])
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


# Official API adapters only. Nothing here scrapes a private or logged-in page.
_INSIGHTS_CFG = {
    "instagram": "instagram_graph", "ig": "instagram_graph",
    "youtube": "youtube_data", "yt": "youtube_data",
}


def _insights_cfg(platform: str) -> tuple[dict, str]:
    key = _INSIGHTS_CFG.get((platform or "").strip().lower(), "")
    raw = core.config_get(key, {}) if key else {}
    cfg = dict(raw) if isinstance(raw, dict) else {}
    cfg["token"] = core.unprotect_secret(str(cfg.get("token") or ""))
    return cfg, key


def _official_get(url: str, headers: dict | None = None) -> tuple[int, object]:
    """Real GET to an official API via requests, with a urllib fallback."""
    if requests is not None:
        return _http_json("GET", url, headers=headers, timeout=25)[:2]
    import urllib.request
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
        return int(response.status), payload


def _youtube_video_id(value: str) -> str:
    text = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    match = re.search(r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", text)
    return match.group(1) if match else ""


def _instagram_insights(cfg: dict, account_id: str) -> str:
    token = str(cfg.get("token") or "").strip()
    if not token:
        return ("token chahiye / login required: Instagram Graph API access token nahi mila. "
                "analytics_operation('configure_insights', platform='instagram', token='...') se "
                "protected token save karo. Koi koi number nahi bataya ja raha.")
    account_id = (account_id or str(cfg.get("account_id") or "")).strip()
    if not account_id:
        return "Instagram Graph insights ke liye account_id (IG user id) do. Token save hai."
    version = str(cfg.get("version") or "v19.0").strip() or "v19.0"
    url = (f"https://graph.facebook.com/{urllib.parse.quote(version, safe='.')}/"
           f"{urllib.parse.quote(account_id, safe='')}/insights")
    params = urllib.parse.urlencode({
        "metric": "impressions,reach,engagement", "period": "day", "access_token": token})
    try:
        status, payload = _official_get(url + "?" + params)
    except Exception as e:
        return f"Instagram Graph API call failed: {core.truncate(e, 240)}. Koi koi number nahi bataya ja raha."
    if status != 200 or not isinstance(payload, dict) or "error" in payload:
        return (f"Instagram Graph API error (HTTP {status}): {core.truncate(payload, 300)}. "
                "Koi koi number nahi bataya ja raha.")
    metrics = {}
    for row in (payload.get("data") or []):
        name = str((row or {}).get("name") or "")
        points = (row or {}).get("values") or []
        value = points[-1].get("value") if points and isinstance(points[-1], dict) else None
        if name and isinstance(value, (int, float)):
            metrics[name] = value
    if not metrics:
        return "Instagram Graph API ne koi metric nahi diya. Koi koi number nahi bataya ja raha."
    line = "Instagram Graph API (official): " + ", ".join(
        f"{k.replace('_', ' ')} {v:,}" for k, v in metrics.items())
    core.audit("analytics_operation", "insights instagram", line, risk="normal")
    return line


def _youtube_insights(cfg: dict, video_id: str, video_url: str) -> str:
    api_key = str(cfg.get("token") or "").strip()
    if not api_key:
        return ("token chahiye / login required: YouTube Data API key/token nahi mila. "
                "analytics_operation('configure_insights', platform='youtube', token='...') se "
                "protected token save karo. Koi koi number nahi bataya ja raha.")
    video_id = _youtube_video_id(video_id or video_url)
    if not video_id:
        return "YouTube insights ke liye video id ya watch URL do. Token save hai."
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
        {"part": "statistics", "id": video_id, "key": api_key})
    try:
        status, payload = _official_get(url)
    except Exception as e:
        return f"YouTube Data API call failed: {core.truncate(e, 240)}. Koi koi number nahi bataya ja raha."
    if status != 200 or not isinstance(payload, dict) or "error" in payload:
        return (f"YouTube Data API error (HTTP {status}): {core.truncate(payload, 300)}. "
                "Koi koi number nahi bataya ja raha.")
    items = payload.get("items") or []
    stats = (items[0].get("statistics") or {}) if items and isinstance(items[0], dict) else {}
    metrics = {}
    for key in ("viewCount", "likeCount", "commentCount", "favoriteCount"):
        value = stats.get(key)
        if str(value).isdigit():
            metrics[key] = int(value)
    if not metrics:
        return f"YouTube Data API ne video {video_id} ke liye statistics nahi diya. Koi koi number nahi bataya ja raha."
    line = f"YouTube Data API (official) video {video_id}: " + ", ".join(
        f"{k} {v:,}" for k, v in metrics.items())
    core.audit("analytics_operation", "insights youtube", line, risk="normal")
    return line


def analytics_operation(action: str = "check", url: str = "", monitor_id: str = "",
                        threshold: int = 0, notify: bool = False, confirmed: bool = False,
                        platform: str = "", token: str = "", account_id: str = "",
                        video_id: str = "") -> str:
    """Check/monitor public Instagram or YouTube views, likes and comments.

    action: check, add/monitor, list, remove, check_all. Official/private account
    metrics still need the platform's API token; public-page metrics are best effort.
    insights/configure_insights use only official Instagram Graph / YouTube Data
    APIs with locally protected tokens—no private-page scraping, no invented data.
    """
    a = (action or "check").strip().lower()
    if a in ("configure_insights", "insights_configure"):
        cfg, key = _insights_cfg(platform)
        if not key:
            return "insights configure ke liye platform='instagram' ya 'youtube' do."
        if not token.strip():
            return "Token do; main use DPAPI se locally protect karke save karunga."
        cfg["token"] = core.protect_secret(token.strip(), f"jarvis-{key}")
        if account_id:
            cfg["account_id"] = account_id.strip()
        core.save_config({key: cfg})
        return f"{key} token locally protected ho gaya. Koi API call nahi kiya."
    if a == "insights":
        plat = (platform or "").strip().lower()
        if not plat:
            plat = "youtube" if "youtu" in (url or "").lower() else (
                "instagram" if "instagram" in (url or "").lower() else "")
        if plat not in _INSIGHTS_CFG:
            return "insights ke liye platform='instagram' ya 'youtube' do."
        cfg, _key = _insights_cfg(plat)
        if plat in ("instagram", "ig"):
            return _instagram_insights(cfg, account_id)
        return _youtube_insights(cfg, video_id, url)
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
