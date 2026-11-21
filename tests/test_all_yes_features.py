"""Offline, mock-only tests for the four real v2.4.x add-on capabilities."""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from jarvis_core import core, games, media_tools, showcase


class AllYesFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-all-yes-")
        self.tmp = Path(self.tmp_obj.name)
        self.old = {}
        for obj, name, value in (
            (core, "CONFIG_FILE", str(self.tmp / "config.json")),
            (core, "AUDIT_FILE", str(self.tmp / "audit.jsonl")),
            (showcase, "SHOPPING_FILE", str(self.tmp / "shopping.json")),
            (showcase, "MONITORS_FILE", str(self.tmp / "monitors.json")),
        ):
            self.old[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        core._SAFETY["safe_mode"] = True
        core.save_config({"safe_mode": True})

    def tearDown(self):
        for (obj, name), value in self.old.items():
            setattr(obj, name, value)
        core._SAFETY["safe_mode"] = True
        self.tmp_obj.cleanup()

    # ------------------------------------------------------------ 1. rembg
    def test_remove_background_missing_dependency_is_honest(self):
        source = self.tmp / "photo.png"
        Image.new("RGB", (12, 12), "red").save(source)
        destination = self.tmp / "nobg.png"
        with mock.patch.dict(sys.modules, {"rembg": None}):
            result = media_tools.remove_background(
                "remove", path=str(source), destination=str(destination))
        self.assertIn("rembg install karna hoga", result)
        self.assertFalse(destination.exists())

    def test_remove_background_fake_dependency_writes_real_png(self):
        source = self.tmp / "photo.png"
        Image.new("RGB", (12, 12), "red").save(source)
        original_bytes = source.read_bytes()
        destination = self.tmp / "nobg.png"

        fake_rembg = types.ModuleType("rembg")

        def fake_remove(image):
            out = image.copy().convert("RGBA")
            out.putalpha(Image.new("L", out.size, 137))
            return out

        fake_rembg.remove = fake_remove
        with mock.patch.dict(sys.modules, {"rembg": fake_rembg}):
            result = media_tools.remove_background(
                "remove", path=str(source), destination=str(destination))
            self.assertTrue(destination.is_file())
            blocked = media_tools.remove_background(
                "remove", path=str(source), destination=str(destination))
            self.assertIn("CONFIRMATION REQUIRED", blocked)
            overwritten = media_tools.remove_background(
                "remove", path=str(source), destination=str(destination), confirmed=True)

        self.assertIn(str(destination), result)
        self.assertGreater(destination.stat().st_size, 0)
        self.assertIn(str(destination), overwritten)
        with Image.open(destination) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 137)
        self.assertEqual(source.read_bytes(), original_bytes)

    # -------------------------------------------------------- 2. cart_add
    @staticmethod
    def _fake_browser(calls):
        def browser_op(action, **kwargs):
            calls.append((action, kwargs))
            if action == "open":
                url = kwargs.get("url", "")
                if "checkout" in url or url.endswith("/cart"):
                    return f"Opened {url}"
                return f"Edge started with automation enabled. Opened: {url}"
            if action == "read":
                reads = [c for c in calls if c[0] == "read"]
                return ("Your cart: 1 item, biryani" if len(reads) > 1
                        else "Swiggy search — biryani results")
            if action == "type":
                return "TYPED search = " + kwargs.get("text", "")
            if action == "wait":
                return "Waited"
            if action == "find":
                return "- <button> Add biryani to cart"
            if action == "click":
                return "CLICKED BUTTON Add to cart" if kwargs.get("text") == "ADD TO CART" else "NOT_FOUND"
            return ""
        return browser_op

    def test_cart_add_needs_user_action_no_purchase_and_checkout_confirmation(self):
        calls = []
        with mock.patch.object(showcase.browser, "browser_operation",
                               side_effect=self._fake_browser(calls)):
            result = showcase.commerce_operation(
                "cart_add", item="biryani", service="swiggy")
        self.assertIn("needs_user_action", result)
        for claim in ("order placed", "order confirmed", "purchase complete",
                      "payment complete", "order id"):
            self.assertNotIn(claim, result.lower())
        self.assertIn("CONFIRMATION REQUIRED", result)
        self.assertFalse(any(c[0] == "open" and "checkout" in c[1].get("url", "")
                             for c in calls))
        self.assertTrue(any(c[0] == "click" for c in calls))

        checkout_calls = []
        with mock.patch.object(showcase.browser, "browser_operation",
                               side_effect=self._fake_browser(checkout_calls)):
            confirmed = showcase.commerce_operation(
                "cart_add", item="biryani", service="swiggy", confirmed=True)
        self.assertTrue(any(c[0] == "open" and "checkout" in c[1].get("url", "")
                            for c in checkout_calls))
        self.assertIn("needs_user_action", confirmed)
        self.assertNotIn("order placed", confirmed.lower())

    def test_cart_add_honest_when_login_or_browser_unavailable(self):
        with mock.patch.object(showcase.browser, "browser_operation",
                               side_effect=lambda action, **kw: (
                                   "Edge ready" if action == "open" else "Please log in to continue")):
            login = showcase.commerce_operation("cart_add", item="biryani", service="swiggy")
        self.assertIn("login required", login)
        self.assertIn("needs_user_action", login)
        with mock.patch.object(showcase.browser, "browser_operation",
                               return_value="I could not find the requested Edge browser on this PC."):
            unavailable = showcase.commerce_operation("cart_add", item="biryani")
        self.assertIn("automation available nahi", unavailable)
        self.assertIn("needs_user_action", unavailable)

    def test_local_shopping_list_still_works(self):
        self.assertIn("Added", showcase.commerce_operation("add", item="eggs", quantity=2))
        self.assertIn("2 x eggs", showcase.commerce_operation("list"))

    # --------------------------------------------------------- 3. insights
    def test_insights_requires_token_and_never_scrapes(self):
        with mock.patch.object(showcase, "_social_metrics",
                               side_effect=AssertionError("private-page scrape attempted")):
            youtube = showcase.analytics_operation(
                "insights", platform="youtube", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            instagram = showcase.analytics_operation("insights", platform="instagram")
        self.assertIn("token chahiye", youtube)
        self.assertIn("login required", instagram)
        self.assertNotIn("views", youtube)

    def test_insights_youtube_official_response_and_401(self):
        configured = showcase.analytics_operation(
            "configure_insights", platform="youtube", token="yt-secret")
        self.assertIn("protected", configured)
        raw = core.read_json(core.CONFIG_FILE, {})["youtube_data"]["token"]
        self.assertNotEqual(raw, "yt-secret")
        payload = {"items": [{"statistics": {"viewCount": "12345", "likeCount": "678",
                                              "commentCount": "90"}}]}
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        with mock.patch.object(showcase, "_http_json", return_value=(200, payload, {})) as get, \
                mock.patch.object(showcase, "_social_metrics",
                                  side_effect=AssertionError("scrape attempted")):
            result = showcase.analytics_operation("insights", platform="youtube", url=url)
        self.assertIn("12,345", result)
        self.assertIn("678", result)
        self.assertEqual(get.call_args.args[0], "GET")
        self.assertIn("www.googleapis.com/youtube/v3/videos", get.call_args.args[1])
        self.assertIn("key=yt-secret", get.call_args.args[1])

        with mock.patch.object(showcase, "_http_json",
                               return_value=(401, {"error": {"message": "Invalid key"}}, {})):
            denied = showcase.analytics_operation("insights", platform="youtube", url=url)
        self.assertIn("HTTP 401", denied)
        self.assertNotIn("12,345", denied)

    def test_insights_instagram_official_response(self):
        showcase.analytics_operation(
            "configure_insights", platform="instagram", token="ig-secret",
            account_id="17841400000000000")
        payload = {"data": [
            {"name": "impressions", "values": [{"value": 4321}]},
            {"name": "reach", "values": [{"value": 3210}]},
            {"name": "engagement", "values": [{"value": 210}]},
        ]}
        with mock.patch.object(showcase, "_http_json", return_value=(200, payload, {})) as get, \
                mock.patch.object(showcase, "_social_metrics",
                                  side_effect=AssertionError("scrape attempted")):
            result = showcase.analytics_operation("insights", platform="instagram")
        self.assertIn("4,321", result)
        self.assertIn("3,210", result)
        self.assertIn("graph.facebook.com", get.call_args.args[1])
        self.assertIn("access_token=ig-secret", get.call_args.args[1])

        with mock.patch.object(showcase, "_http_json",
                               return_value=(401, {"error": {"message": "bad token"}}, {})):
            denied = showcase.analytics_operation("insights", platform="instagram")
        self.assertIn("HTTP 401", denied)
        self.assertNotIn("4,321", denied)

    # ------------------------------------------------------------ 4. games
    def test_storesearch_uses_public_urllib_endpoint(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"items": [{"id": 730, "name": "Counter-Strike 2"}]}).encode("utf-8")

        with mock.patch.object(games.urllib.request, "urlopen", return_value=Response()) as urlopen:
            result = games._steam_store_search("CS2")
        self.assertEqual(result, {"appid": "730", "name": "Counter-Strike 2"})
        self.assertIn("storesearch", urlopen.call_args.args[0].full_url)

    def test_game_download_launches_real_steam_uri_only_when_launched(self):
        with mock.patch.object(games, "_steam_store_search",
                               return_value={"appid": "730", "name": "Counter-Strike 2"}) as search, \
                mock.patch.object(games, "_steam_client_path",
                                  return_value=r"C:\Program Files (x86)\Steam\steam.exe"), \
                mock.patch.object(core, "open_url",
                                  return_value="Opened steam://install/730") as open_url:
            result = games.game_operation("download", query="CS2", confirmed=True)
        self.assertIn("install request bheja; Steam client download karega", result)
        search.assert_called_once_with("CS2")
        open_url.assert_called_once_with("steam://install/730")

        with mock.patch.object(games, "_steam_store_search",
                               return_value={"appid": "730", "name": "Counter-Strike 2"}), \
                mock.patch.object(games, "_steam_client_path", return_value=""), \
                mock.patch.object(core, "open_url") as open_url:
            missing = games.game_operation("download", query="CS2", confirmed=True)
        self.assertIn("Steam installed nahi", missing)
        open_url.assert_not_called()

        with mock.patch.object(games, "_steam_store_search",
                               return_value={"appid": "730", "name": "Counter-Strike 2"}), \
                mock.patch.object(games, "_steam_client_path", return_value="steam.exe"), \
                mock.patch.object(core, "open_url",
                                  return_value="Could not open browser: no handler"):
            failed = games.game_operation("download", query="CS2", confirmed=True)
        self.assertIn("URI launch failed", failed)
        self.assertNotIn("download karega", failed)

    def test_game_download_epic_handoff_is_honest(self):
        result = games.game_operation("download", platform="epic", query="Fortnite", confirmed=True)
        self.assertIn("legendary CLI token configured nahi", result)
        self.assertIn("silent install nahi", result)


if __name__ == "__main__":
    unittest.main()
