# Jarvis PC v2.4.x — "All Yes" real-capability add-on

This add-on adds four **real** actions. Each one either does the actual work or
says plainly that it cannot. Nothing here fakes an order, a payment, a private
insight, a silent install, or a background removal.

| Capability | Function / action | What is real |
|---|---|---|
| Background removal | `media_tools.remove_background(action="remove", path=..., destination=...)` | Calls the installed `rembg` package, writes a new transparent PNG with alpha. |
| Food cart hand-off | `showcase.commerce_operation("cart_add", item=..., service=..., url=...)` | Drives the installed Edge through the existing DevTools browser path; final order/payment stays with the user. |
| Official insights | `showcase.analytics_operation("insights", platform=...)` | GETs Instagram Graph API / YouTube Data API with locally protected tokens. |
| Game download trigger | `games.game_operation("download", query=...)` | Public Steam storesearch resolves the appid; `steam://install/<appid>` is launched through `core.open_url`. |

All actions are confirmation-gated through `core.guard` where they can change
state. Every blocked action is audited locally in `jarvis_data/jarvis_audit.jsonl`.

## Setup requirements

1. **Background removal (`rembg`)**

   `rembg` is *not* in `requirements.txt` and Jarvis never installs it at
   runtime. Install it yourself in the same Python environment you use to run
   Jarvis:

   ```bat
   cd "C:\Users\Shahid\Desktop\Jarvis Github for PC"
   python -m pip install rembg
   ```

   If `rembg` is not importable, the tool returns exactly:
   `background removal ke liye rembg install karna hoga` and writes no file.
   Pillow (already in `requirements.txt`) is used to keep the RGBA alpha channel.

2. **Edge DevTools for `cart_add`**

   Edge is installed at
   `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`.
   The action calls the existing `browser.browser_operation` DevTools path with
   `text="edge"`, which starts/attaches an automation-enabled Edge on port 9222
   with the configured Jarvis browser profile. Log into Swiggy or Zomato once in
   that profile (`browser_profile_dir` config or `JARVIS_BROWSER_PROFILE`), and
   keep delivery address/CAPTCHA steps to yourself. If the browser cannot be
   started or the site shows a login page, the tool reports `login required` /
   `browser automation unavailable` honestly.

3. **Platform tokens for `insights`**

   Save the user's own official credentials; they are protected with the
   existing DPAPI helper (`core.protect_secret`) and stored in
   `jarvis_data/config.json`:

   ```text
   analytics_operation("configure_insights", platform="instagram", token="<Graph API access token>", account_id="<IG user id>")
   analytics_operation("configure_insights", platform="youtube", token="<Data API key>")
   ```

   Without a token the reply is `token chahiye / login required`, and **no**
   number is reported. Instagram uses
   `https://graph.facebook.com/<version>/<ig-user-id>/insights` with
   `impressions,reach,engagement` (`period=day`). YouTube uses
   `https://www.googleapis.com/youtube/v3/videos?part=statistics&id=...`.
   Only these official endpoints are called; private or logged-in pages are
   never scraped. HTTP 401/400 and missing fields are reported as errors, not
   filled in with guesses.

4. **Steam client for `download`**

   Steam must be installed and detectable (registry `SteamPath`/`InstallPath`,
   `%ProgramFiles(x86)%\Steam`, or `steam.exe` on PATH). The appid comes from the
   public `https://store.steampowered.com/api/storesearch/` endpoint via
   `urllib`. If the client is missing, the reply is `Steam installed nahi` and
   no URI is launched. `steam://install/<appid>` is opened with `core.open_url`;
   the exact reply `install request bheja; Steam client download karega` is
   returned **only** when that launch actually succeeded.

   For Epic there is no silent install. Without a configured legendary CLI token
   the tool returns an honest launcher hand-off. With one:

   ```text
   game_operation("configure_legendary", token="<legendary CLI token>")
   game_operation("download", platform="epic", query="<game>", confirmed=True)
   ```

   This prepares (prints/audits) the install command; it does not execute it.

## Exact commands

All commands are run from `C:\Users\Shahid\Desktop\Jarvis Github for PC`.

```text
# 1. remove a background (new file, source untouched)
media_tools.remove_background("remove", path="photo.jpg", destination="photo_nobg.png")
media_tools.remove_background("remove", path="photo.jpg", destination="photo_nobg.png", confirmed=True)  # only if output exists

# 2. attempt a real add-to-cart; user finishes order + payment
showcase.commerce_operation("cart_add", item="biryani", service="swiggy")            # default https://www.swiggy.com
showcase.commerce_operation("cart_add", item="pizza", service="zomato")              # https://www.zomato.com
showcase.commerce_operation("cart_add", item="biryani", url="https://www.swiggy.in") # explicit user URL
showcase.commerce_operation("cart_add", item="biryani", confirmed=True)              # opens cart/checkout for review only

# local shopping list (unchanged)
showcase.commerce_operation("add", item="eggs", quantity=2)
showcase.commerce_operation("list")

# 3. official insights
showcase.analytics_operation("insights", platform="youtube", url="https://www.youtube.com/watch?v=<id>")
showcase.analytics_operation("insights", platform="instagram")

# 4. real download trigger (scan actions are unchanged)
games.game_operation("download", query="Counter-Strike 2", confirmed=True)
games.game_operation("download", appid="730", confirmed=True)
games.game_operation("updates")   # existing local manifest scan
```

Offline verification:

```bat
python -m compileall -q -f jarvis_core/media_tools.py jarvis_core/showcase.py jarvis_core/games.py tests/test_all_yes_features.py
python -m unittest tests.test_all_yes_features -v
```

The tests use only mocks (fake `rembg` module, mocked browser calls, mocked
official API responses, mocked `urllib` and URI launch). No network request,
purchase, login or install is performed during the test run.

## Explicit limits

- **No payment automation.** `cart_add` never places an order, confirms a cart,
  enters payment details, or claims an order id. Final order and payment are
  always `needs_user_action`; opening the checkout page alone requires
  `confirmed=True` and still does not buy anything.
- **No private scraping.** `insights` only calls Instagram Graph / YouTube Data
  APIs with the user's own token. It does not read logged-in pages, DMs, or
  private profiles and never invents metrics when a token is absent or rejected.
- **No silent install.** Steam's client owns the install dialog and download;
  Jarvis only launches the real URI. Epic/legendary only prepares a command and
  never runs it in the background. Completion is claimed only from real client
  state.
- **No background removal without `rembg`.** If the dependency is missing, the
  honest dependency message is returned and no output file is created. Source
  images are never overwritten; an existing destination needs confirmation.
- Websites change their DOM and may show CAPTCHAs or sign-in walls. The cart
  action attempts real UI steps and reports failed clicks honestly; it does not
  claim success from a guessed selector.
