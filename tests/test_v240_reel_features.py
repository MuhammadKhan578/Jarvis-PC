from __future__ import annotations

import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import jarvis_core
from jarvis_core import core, games, media_tools, showcase, tools


class JarvisReelFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-reels-")
        self.tmp = Path(self.tmp_obj.name)
        self.old = {}
        for obj, name, value in (
            (core, "CONFIG_FILE", str(self.tmp / "config.json")),
            (core, "AUDIT_FILE", str(self.tmp / "audit.jsonl")),
            (showcase, "ISS_FILE", str(self.tmp / "iss.html")),
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

    def test_iss_status_and_live_tracker(self):
        payload = {"latitude": 12.25, "longitude": 44.5, "altitude": 421.2,
                   "velocity": 27580.0, "visibility": "daylight", "footprint": 4520.0}
        with mock.patch.object(showcase, "_http_json", return_value=(200, payload, {})), \
                mock.patch.object(core, "open_path", return_value="opened"):
            status = showcase.iss_operation("status")
            opened = showcase.iss_operation("track")
        self.assertIn("12.2500", status)
        self.assertIn("27,580", status)
        self.assertIn("Live tracker", opened)
        html = Path(showcase.ISS_FILE).read_text(encoding="utf-8")
        self.assertIn("ISS LIVE ORBIT", html)
        self.assertIn(showcase.ISS_API, html)

    def test_visual_guide_finds_and_highlights_without_clicking(self):
        old_g = core.G
        core.G = {"_screen_ask": lambda prompt: {"found": True, "x": 500, "y": 250,
                                                   "label": "Export"}}
        try:
            with mock.patch.object(showcase, "_overlay_at") as overlay, \
                    mock.patch("pyautogui.size", return_value=(1920, 1080)):
                result = showcase.visual_guide("point", "Export button", seconds=3)
            self.assertIn("Highlighted", result)
            overlay.assert_called_once_with(960, 270, "Export", 3)
        finally:
            core.G = old_g

    def test_commerce_list_and_order_confirmation(self):
        self.assertIn("Added", showcase.commerce_operation(
            "add", item="eggs", quantity=2))
        self.assertIn("2 x eggs", showcase.commerce_operation("list"))
        blocked = showcase.commerce_operation(
            "order", query="biryani", service="foodpanda")
        self.assertIn("CONFIRMATION REQUIRED", blocked)
        with mock.patch.object(core, "open_url", return_value="Opened") as opened:
            result = showcase.commerce_operation(
                "order", query="biryani", service="foodpanda", confirmed=True)
        self.assertIn("No purchase is claimed", result)
        self.assertIn("biryani", opened.call_args.args[0])

    def test_remote_alert_config_protection_and_send(self):
        self.assertIn("configured", showcase.notification_operation(
            "configure", server="https://ntfy.example", topic="private-topic", token="token-value"))
        raw = core.read_json(core.CONFIG_FILE, {})["remote_alerts"]["token"]
        self.assertNotEqual(raw, "token-value")
        self.assertIn("CONFIRMATION REQUIRED", showcase.notification_operation(
            "send", message="Views crossed target"))
        response = mock.Mock(status_code=200, text="ok")
        with mock.patch.object(showcase.requests, "post", return_value=response) as post:
            result = showcase.notification_operation(
                "send", message="Views crossed target", confirmed=True)
        self.assertIn("sent", result)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer token-value")

    def test_public_analytics_monitor_and_change(self):
        descriptions = [
            '<meta name="description" content="3.8M views, 120K likes, 53K comments - creator">',
            '<meta name="description" content="4.0M views, 125K likes, 54K comments - creator">',
        ]
        responses = []
        for body in descriptions:
            r = mock.Mock(status_code=200, text='<html><head>' + body + '</head></html>')
            r.raise_for_status.return_value = None
            responses.append(r)
        with mock.patch.object(showcase.requests, "get", side_effect=responses):
            first = showcase.analytics_operation("add", url="https://instagram.example/p/x")
            second = showcase.analytics_operation("check", url="https://instagram.example/p/x")
        self.assertIn("views 3,800,000", first)
        self.assertIn("views +200,000", second)
        saved = core.read_json(showcase.MONITORS_FILE, {})
        self.assertEqual(len(saved), 1)

    def test_phone_agent_is_configured_and_confirmation_gated(self):
        self.assertIn("configured", showcase.phone_agent_operation(
            "configure", endpoint="https://calls.example/api/calls", token="phone-secret"))
        self.assertIn("CONFIRMATION REQUIRED", showcase.phone_agent_operation(
            "call", phone="+123", message="I will be late"))
        with mock.patch.object(showcase, "_http_json", return_value=(202, {"call_id": "c1"}, {})):
            result = showcase.phone_agent_operation(
                "call", phone="+123", message="I will be late", confirmed=True)
        self.assertIn("accepted", result)
        self.assertIn("c1", result)

    def test_steam_manifest_update_scan_and_guarded_install(self):
        steam = self.tmp / "Steam"
        apps = steam / "steamapps"
        apps.mkdir(parents=True)
        (apps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n}', encoding="utf-8")
        (apps / "appmanifest_730.acf").write_text(
            '"AppState"\n{\n"appid" "730"\n"name" "Counter-Strike 2"\n'
            '"StateFlags" "6"\n"BytesToDownload" "1048576"\n"installdir" "CS2"\n}',
            encoding="utf-8")
        with mock.patch.object(games, "_steam_root", return_value=str(steam)):
            rows = games.steam_games()
            updates = games.game_operation("updates")
            self.assertEqual(rows[0]["appid"], "730")
            self.assertTrue(rows[0]["update_pending"])
            self.assertIn("Counter-Strike 2", updates)
            self.assertIn("CONFIRMATION REQUIRED", games.game_operation(
                "install", query="CS2"))
            with mock.patch.object(games, "_steam_search", return_value=[
                    {"appid": "730", "name": "Counter-Strike 2", "price": 0}]), \
                    mock.patch.object(games, "_open_uri", return_value=True):
                result = games.game_operation("install", query="CS2", confirmed=True)
            self.assertIn("Steam install dialog opened", result)
            self.assertIn("Recommended library", result)

    def test_video_trim_and_keep_segments_create_real_outputs(self):
        ff = media_tools._ffmpeg()
        self.assertTrue(ff)
        source = self.tmp / "source.mp4"
        command = [ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                   "color=c=blue:s=320x240:d=3", "-f", "lavfi", "-i",
                   "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)]
        subprocess.run(command, check=True, timeout=120)
        trimmed = self.tmp / "trimmed.mp4"
        result = media_tools.video_operation(
            "trim", path=str(source), destination=str(trimmed), start="0.5", end="1.5")
        self.assertIn("Edited video created", result)
        self.assertTrue(trimmed.exists() and trimmed.stat().st_size > 1000)
        cut = self.tmp / "cut.mp4"
        result2 = media_tools.video_operation(
            "cut", path=str(source), destination=str(cut), segments="0-0.7, 2-2.8")
        self.assertIn("Edited video created", result2)
        self.assertTrue(cut.exists() and cut.stat().st_size > 1000)

    def test_image_edit_creates_real_output(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not installed")
        source = self.tmp / "source.png"
        Image.new("RGB", (120, 80), "#1d4ed8").save(source)
        result = media_tools.image_operation(
            "resize", path=str(source), destination=str(self.tmp / "small.png"),
            width=60)
        self.assertIn("Edited image created", result)
        with Image.open(self.tmp / "small.png") as image:
            self.assertEqual(image.size, (60, 40))
        result2 = media_tools.image_operation(
            "grayscale", path=str(self.tmp / "small.png"),
            destination=str(self.tmp / "gray.png"))
        self.assertIn("Edited image created", result2)
        with Image.open(self.tmp / "gray.png") as image:
            self.assertEqual(image.mode, "L")
        result3 = media_tools.image_operation(
            "resize", path=str(source), destination=str(self.tmp / "story.png"),
            preset="9:16", width=90)
        self.assertIn(" Edited image created", result3)
        with Image.open(self.tmp / "story.png") as image:
            self.assertEqual(image.size, (90, 160))

    def test_no_path_edit_picks_newest_local_media(self):
        ff = media_tools._ffmpeg()
        self.assertTrue(ff)
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not installed")
        folder = self.tmp / "Downloads"
        folder.mkdir()
        video = folder / "clip.mp4"
        subprocess.run(
            [ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=blue:s=160x120:d=2", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(video)],
            check=True, timeout=120)
        photo = folder / "picture.png"
        Image.new("RGB", (100, 80), "#123456").save(photo)
        old_folders = media_tools._MEDIA_FOLDERS
        media_tools._MEDIA_FOLDERS = [str(folder)]
        try:
            self.assertIn(str(video), media_tools.video_operation("info"))
            self.assertIn(str(photo), media_tools.image_operation("info"))
            edited = media_tools.video_operation("cut", segments="0-0.5")
            self.assertIn("Edited video created", edited)
            self.assertTrue((folder / "clip_edited.mp4").exists())
        finally:
            media_tools._MEDIA_FOLDERS = old_folders

    def test_natural_edit_this_video_and_photo_commands(self):
        with mock.patch.object(media_tools, "video_operation",
                               return_value="video edit ready") as video, \
                mock.patch.object(media_tools, "image_operation",
                                  return_value="photo edit ready") as image, \
                mock.patch.object(core, "say_lang") as say:
            self.assertTrue(jarvis_core.command_hook("edit this video"))
            self.assertTrue(jarvis_core.command_hook("edit this photo"))
        video.assert_called_once_with(action="auto_cut")
        image.assert_called_once_with(action="enhance")
        self.assertEqual(say.call_count, 2)

    def test_image_analysis_uses_visual_model_without_name_error(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not installed")
        source = self.tmp / "analyze.png"
        Image.new("RGB", (80, 60), "#dc2626").save(source)
        fake_types = types.SimpleNamespace(
            Part=types.SimpleNamespace(from_bytes=mock.Mock(return_value="image-part")))
        with mock.patch.object(core, "gen_types", return_value=fake_types), \
                mock.patch.object(core, "llm_text", return_value="A red rectangle.") as llm:
            result = media_tools.image_operation(
                "analyze", path=str(source), question="What is in this photo?")
        self.assertEqual(result, "A red rectangle.")
        llm.assert_called_once()
        self.assertEqual(llm.call_args.args[0][1], "What is in this photo?")

    def test_new_tools_are_registered(self):
        names = {getattr(fn, "__name__", "") for fn in tools.TOOL_FUNCTIONS}
        self.assertTrue({
            "iss_operation", "video_operation", "image_operation", "visual_guide",
            "commerce_operation", "analytics_operation", "notification_operation",
            "phone_agent_operation", "game_operation",
        }.issubset(names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
