from __future__ import annotations

import inspect
import http.server
import json
import os
import queue
import threading
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from jarvis_core import agent, browser, calendar_tools, computer, core, dictation, documents
from jarvis_core import integrations, mail, mcp, memory, privacy, research, smarthome, tools, workspace
import jarvis_config


class JarvisV230Tests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory(prefix="jarvis-v230-")
        self.tmp = Path(self.tmp_obj.name)
        self.old = {}
        for obj, name, value in (
            (core, "DATA_DIR", str(self.tmp / "data")),
            (core, "CONFIG_FILE", str(self.tmp / "config.json")),
            (core, "AUDIT_FILE", str(self.tmp / "audit.jsonl")),
            (core, "CONVERSATION_FILE", str(self.tmp / "conversation.jsonl")),
            (calendar_tools, "CAL_FILE", str(self.tmp / "calendar.json")),
            (agent, "SCHEDULE_FILE", str(self.tmp / "schedule.json")),
            (agent, "MISSIONS_FILE", str(self.tmp / "missions.json")),
            (memory, "MEMORY_FILE", str(self.tmp / "memory.json")),
            (memory, "LEGACY_FILE", str(self.tmp / "legacy.json")),
            (memory, "ARCHIVE_FILE", str(self.tmp / "archive.jsonl")),
            (memory, "BACKUP_DIR", str(self.tmp / "backups")),
        ):
            self.old[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        memory._CACHE = None
        memory._ARCHIVE_CACHE.update({"size": -1, "mtime": 0.0, "records": []})
        core._SAFETY["safe_mode"] = True
        core.save_config({
            "safe_mode": True,
            "memory_enabled": True,
            "archive_enabled": True,
            "auto_learn": True,
            "workspace": {},
            "mcp_servers": {},
        })

    def tearDown(self):
        for (obj, name), value in self.old.items():
            setattr(obj, name, value)
        memory._CACHE = None
        core._SAFETY["safe_mode"] = bool(core.load_config().get("safe_mode", True))
        self.tmp_obj.cleanup()

    def test_v240_versions_are_consistent(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('JARVIS_VERSION = "2.4.3"', (root / "jarvis.py").read_text(encoding="utf-8"))
        self.assertIn('VERSION = "2.4.3"', (root / "jarvis_app.py").read_text(encoding="utf-8"))
        self.assertEqual(mcp.SERVER_VERSION, "2.4.3")
        import jarvis_core
        self.assertEqual(jarvis_core.__version__, "3.3")
        self.assertIn("v2.4.3", (root / "README.md").read_text(encoding="utf-8"))

    def test_calendar_natural_dates_ranges_and_confirmed_invite(self):
        after = calendar_tools._parse_when("day after tomorrow 5 pm")
        self.assertIsNotNone(after)
        self.assertEqual((after.date() - datetime.now().date()).days, 2)
        clock = calendar_tools._parse_when("today 18:30")
        self.assertEqual((clock.hour, clock.minute), (18, 30))
        self.assertEqual(clock.date(), datetime.now().date())
        self.assertEqual(calendar_tools._clean_title("Project 2 review tomorrow 5 pm"),
                         "Project 2 review")
        self.assertEqual(calendar_tools._clean_title("Meeting today 18:30"), "Meeting")
        relative = calendar_tools._parse_when("2 ghante baad")
        self.assertTrue(110 <= (relative - datetime.now()).total_seconds() / 60 <= 121)
        self.assertEqual(calendar_tools._clean_title("2 ghante baad Project 2 review"),
                         "Project 2 review")
        made = calendar_tools.calendar_operation(
            "add", title="Long review tomorrow 5 pm", duration_minutes=60)
        self.assertIn("Event created", made)
        event_id = calendar_tools._load()[0]["id"]
        calendar_tools.calendar_operation("update", query=event_id, start="tomorrow 6 pm")
        self.assertEqual(calendar_tools._load()[0]["duration"], 60)

        now = datetime.now()
        calendar_tools._save([
            {"id": "a", "title": "Ten", "start": (now + timedelta(days=10)).isoformat(), "duration": 30},
            {"id": "b", "title": "Twenty", "start": (now + timedelta(days=20)).isoformat(), "duration": 30},
        ])
        upcoming = calendar_tools.upcoming(14)
        self.assertIn("Ten", upcoming)
        self.assertNotIn("Twenty", upcoming)

        calendar_tools._save([{
            "id": "invite", "title": "Review", "start": (now + timedelta(days=1)).isoformat(),
            "duration": 30, "attendees": ["a@example.com"], "location": "", "notes": "",
        }])
        with mock.patch("jarvis_core.integrations.send_email", return_value="Email sent") as send:
            result = calendar_tools.calendar_operation("invite", query="invite", confirmed=True)
        self.assertEqual(result, "Email sent")
        self.assertTrue(send.call_args.kwargs["confirmed"])
        invite_text = Path(send.call_args.kwargs["attachments"]).read_text(encoding="utf-8")
        self.assertIn("METHOD:REQUEST", invite_text)
        self.assertIn("RSVP=TRUE", invite_text)

    def test_recurring_routines_daypart_weekly_and_preapproval(self):
        morning = agent.parse_schedule_text("every morning summarize what changed overnight")
        self.assertEqual(morning["kind"], "daily")
        self.assertEqual(morning["time"], "08:00")
        weekly = agent.parse_schedule_text("every Friday at 5 pm run weekly review")
        self.assertEqual(weekly["kind"], "weekly")
        self.assertEqual(weekly["weekday"], 4)
        self.assertEqual(weekly["time"], "17:00")
        roman_weekly = agent.parse_schedule_text("har jumma 5 baje weekly review")
        self.assertEqual(roman_weekly["time"], "17:00")
        self.assertEqual(agent._extract_prompt(
            "every Friday review project 2 at 5 pm"), "review project 2")
        self.assertEqual(agent._extract_prompt(
            "har jumma 5 baje inbox organize karo"), "inbox organize karo")
        self.assertEqual(agent.parse_schedule_text(
            "every morning summarize project 2")["time"], "08:00")
        roman_once = agent.parse_schedule_text("2 ghante baad report yaad dilao")
        self.assertEqual(roman_once["kind"], "once")
        self.assertEqual(agent._extract_prompt(
            "2 ghante baad report yaad dilao"), "report yaad dilao")
        roman_interval = agent.parse_schedule_text("har 2 ghante system status check karo")
        self.assertEqual(roman_interval["kind"], "interval")
        self.assertEqual(agent._extract_prompt(
            "har 2 ghante system status check karo"), "system status check karo")

        import jarvis_core
        with mock.patch.object(core, "say_lang", return_value=None), \
                mock.patch.object(core, "audit", return_value=None):
            self.assertTrue(jarvis_core.command_hook(
                "every Friday at 5 pm run weekly review", {}))
        fast_job = next(iter(agent._load_schedule().values()))
        self.assertEqual((fast_job["kind"], fast_job["weekday"], fast_job["time"]),
                         ("weekly", 4, "17:00"))
        agent._save_schedule({})

        blocked = agent.schedule_operation(
            "add", text="every morning organize my inbox", confirmed=False)
        self.assertIn("CONFIRMATION REQUIRED", blocked)
        saved = agent.schedule_operation(
            "add", text="every morning organize my inbox", confirmed=True)
        self.assertIn("Scheduled", saved)
        job = next(iter(agent._load_schedule().values()))
        self.assertTrue(job["preapproved"])
        self.assertEqual(job["risk"], "high")

    def test_scheduler_dispatches_due_preapproved_job_once(self):
        q = queue.Queue()
        old_g = core.G
        core.G = {"command_queue": q}
        agent._STOP.clear()
        try:
            agent.add_schedule(time.time() - 1, "organize my inbox", preapproved=True, risk="high")

            def stop_after_tick(_seconds):
                agent._STOP.set()

            with mock.patch.object(core, "say_async", return_value=None), \
                    mock.patch.object(agent.time, "sleep", side_effect=stop_after_tick):
                agent._scheduler_loop()
            command = q.get_nowait()
            self.assertIn("PREAPPROVED SCHEDULED TASK", command)
            self.assertIn("organize my inbox", command)
            stored = next(iter(agent._load_schedule().values()))
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["runs"], 1)
        finally:
            agent._STOP.clear()
            core.G = old_g

    def test_mission_never_claims_blocked_step_complete(self):
        mission = agent._new_mission("Send an important update")
        mission["plan"] = [{"n": 1, "title": "Send update", "detail": "Send it",
                            "tools": ["email_operation"], "status": "pending", "result": ""}]
        agent._save_missions({mission["id"]: mission})

        class FakeChat:
            def send_message(self, _prompt):
                return type("Reply", (), {"text": "CONFIRMATION REQUIRED: Send the update. Nothing has been done yet."})()

        agent._STOP.clear()
        with mock.patch.object(agent, "_mission_chat", return_value=FakeChat()), \
                mock.patch.object(core, "say_async", return_value=None), \
                mock.patch.object(core, "save_report", return_value=("report.md", "report.html")), \
                mock.patch.object(core, "audit", return_value=None):
            agent._run_mission(mission["id"])
        saved = agent._load_missions()[mission["id"]]
        self.assertEqual(saved["plan"][0]["status"], "blocked")
        self.assertEqual(saved["status"], "partial")

    def test_credentials_are_protected_and_round_trip(self):
        github_token = "gh" + "p_" + "unit_test_value_1234567890"
        configured = workspace.workspace_operation(
            "configure", service="github", token=github_token, repo="owner/repo")
        self.assertIn("configured", configured)
        raw = core.read_json(core.CONFIG_FILE, {})["workspace"]["github"]["token"]
        self.assertNotEqual(raw, github_token)
        self.assertTrue(raw.startswith(("dpapi:", "b64:")))
        self.assertEqual(workspace._token("github"), github_token)

        mcp.mcp_operation("add_server", server="demo", url="https://example.test/mcp",
                          token="mcp_secret")
        raw_mcp = core.read_json(core.CONFIG_FILE, {})["mcp_servers"]["demo"]["token"]
        self.assertNotEqual(raw_mcp, "mcp_secret")
        self.assertEqual(core.unprotect_secret(raw_mcp), "mcp_secret")
        self.assertNotIn("mcp_secret", mcp.mcp_operation("status"))
        archive_token = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
        redacted = mail.redact_secrets("configure github token " + archive_token)
        self.assertNotIn(archive_token, redacted)
        self.assertIn("REDACTED", redacted)

    def test_gemini_key_is_dpapi_protected(self):
        key = "AIza" + "x" * 35
        old = os.environ.get(jarvis_config.CONFIG_ENV)
        old_key = os.environ.get("GEMINI_API_KEY")
        os.environ[jarvis_config.CONFIG_ENV] = str(self.tmp / "app-config")
        try:
            jarvis_config.save_api_key(key)
            raw = jarvis_config.load_config().get("gemini_api_key", "")
            self.assertNotEqual(raw, key)
            self.assertTrue(raw.startswith(("dpapi:", "b64:")))
            self.assertEqual(jarvis_config.get_saved_api_key(), key)
            jarvis_config.clear_api_key()
        finally:
            if old is None:
                os.environ.pop(jarvis_config.CONFIG_ENV, None)
            else:
                os.environ[jarvis_config.CONFIG_ENV] = old
            if old_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old_key

    def test_home_assistant_legacy_token_is_migrated(self):
        old = smarthome._CONFIG_FILE
        smarthome._CONFIG_FILE = str(self.tmp / "home.json")
        try:
            core.write_json(smarthome._CONFIG_FILE, {
                "enabled": True, "url": "http://home.local", "token": "legacy-home-token",
                "entities": {},
            })
            cfg = smarthome._load_config()
            self.assertEqual(cfg["token"], "legacy-home-token")
            raw = core.read_json(smarthome._CONFIG_FILE, {})["token"]
            self.assertNotEqual(raw, "legacy-home-token")
            self.assertTrue(raw.startswith(("dpapi:", "b64:")))
        finally:
            smarthome._CONFIG_FILE = old

    def test_mcp_exposes_read_only_connections(self):
        names = {x["name"] for x in mcp._SERVER_TOOLS}
        self.assertIn("jarvis_workspace_query", names)
        self.assertIn("jarvis_research_quick", names)
        with self.assertRaisesRegex(ValueError, "read-only"):
            mcp._server_call("jarvis_workspace_query", {
                "service": "slack", "action": "send", "query": "x",
            })

    def test_mcp_streamable_http_client_end_to_end(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                size = int(self.headers.get("Content-Length") or 0)
                message = json.loads(self.rfile.read(size) or b"{}")
                method = message.get("method")
                if method == "initialize":
                    result = {"protocolVersion": mcp.PROTOCOL_VERSION,
                              "serverInfo": {"name": "qa", "version": "1"},
                              "capabilities": {"tools": {}, "resources": {}}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "echo", "description": "Echo text"}]}
                elif method == "tools/call":
                    text = str((message.get("params") or {}).get("arguments", {}).get("text") or "")
                    result = {"content": [{"type": "text", "text": "echo:" + text}], "isError": False}
                elif method == "resources/list":
                    result = {"resources": [{"uri": "qa://one", "name": "One"}]}
                else:
                    result = {}
                body = json.dumps({"jsonrpc": "2.0", "id": message.get("id"),
                                   "result": result}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "qa-session")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/mcp"
            self.assertIn("saved", mcp.mcp_operation(
                "add_server", server="qa", url=url, token="local-token"))
            self.assertIn("echo", mcp.mcp_operation("list_tools", server="qa"))
            self.assertEqual(mcp.mcp_operation(
                "call", server="qa", tool="echo", arguments='{"text":"hello"}'), "echo:hello")
            self.assertIn("qa://one", mcp.mcp_operation("resources", server="qa"))
            self.assertIn("CONFIRMATION REQUIRED", mcp.mcp_operation(
                "call", server="qa", tool="send_message", arguments="{}"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_browser_selection_typing_and_safety(self):
        chrome = self.tmp / "chrome.exe"
        chrome.write_bytes(b"")
        paths = {"brave": [str(self.tmp / "missing-brave.exe")],
                 "chrome": [str(chrome)], "edge": []}
        with mock.patch.object(browser, "_BROWSER_PATHS", paths), \
                mock.patch.object(core, "G", {}):
            self.assertIsNone(browser._find_exe("brave", allow_fallback=False))
            self.assertEqual(browser._find_exe("brave", allow_fallback=True), str(chrome))

        tab = {"id": "1", "url": "https://example.test", "webSocketDebuggerUrl": "ws://x"}
        with mock.patch.object(browser, "_pick_tab", return_value=tab), \
                mock.patch.object(browser, "_click", return_value="CLICKED") as click:
            blocked = browser.browser_operation("click", text="Delete account")
            self.assertIn("CONFIRMATION REQUIRED", blocked)
            self.assertFalse(click.called)
            self.assertEqual(browser.browser_operation(
                "click", text="Delete account", confirmed=True), "CLICKED")
        self.assertIn("el.textContent", inspect.getsource(browser._type))

        with mock.patch.object(browser, "_pick_tab", return_value=tab), \
                mock.patch.object(browser, "_eval", return_value="ok") as evaluate:
            blocked = browser.browser_operation("eval", script="document.querySelector('button').click()")
            self.assertIn("CONFIRMATION REQUIRED", blocked)
            self.assertFalse(evaluate.called)

    def test_ui_safety_blocks_important_click_before_automation(self):
        self.assertEqual(computer._uia_key_sequence("ctrl+shift+s"), "^+s")
        self.assertEqual(computer._uia_key_sequence("enter"), "{ENTER}")
        old_g = core.G
        core.G = {"_find_and_click": lambda description: description == "Continue"}
        try:
            self.assertTrue(computer._vision_click("Continue"))
        finally:
            core.G = old_g
        with mock.patch.object(computer, "_uia_available", return_value=False):
            blocked = computer.ui_operation("click", window="Browser", control="Place order")
        self.assertIn("CONFIRMATION REQUIRED", blocked)

    def test_system_power_confirmation_is_forwarded_once(self):
        old_g = core.G
        power = mock.Mock(return_value="done")
        core.G = {"power_action": power}
        try:
            self.assertIn("CONFIRMATION REQUIRED",
                          computer.system_operation("power", value="restart"))
            self.assertEqual(computer.system_operation(
                "power", value="restart", confirmed=True), "done")
            power.assert_called_once_with("restart", confirmed=True)
        finally:
            core.G = old_g

    def test_file_delete_and_overwrite_confirmation_is_forwarded(self):
        target = self.tmp / "file.txt"
        target.write_text("old", encoding="utf-8")
        old_g = core.G
        deleter = mock.Mock(return_value="deleted")
        core.G = {"delete_to_recycle_bin": deleter}
        try:
            self.assertIn("CONFIRMATION REQUIRED",
                          computer.file_operation("delete", path=str(target)))
            self.assertEqual(computer.file_operation(
                "delete", path=str(target), confirmed=True), "deleted")
            deleter.assert_called_once_with(str(target), confirmed=True)
        finally:
            core.G = old_g
        self.assertIn("CONFIRMATION REQUIRED", computer.file_operation(
            "write", path=str(target), content="new"))
        self.assertIn("Saved:", computer.file_operation(
            "write", path=str(target), content="new", confirmed=True))
        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_one_slide_powerpoint_keeps_its_bullets(self):
        old_docs = core.DOCS_DIR
        core.DOCS_DIR = str(self.tmp / "documents")
        try:
            with mock.patch.object(core, "open_path", return_value="opened"):
                result = documents.create_powerpoint(
                    "single", json.dumps({"slides": [{"title": "QA", "bullets": ["First", "Second"]}]})
                )
            self.assertIn("PowerPoint created", result)
            path = next(Path(core.DOCS_DIR).glob("*.pptx"))
            text = documents.read_document(str(path))
            self.assertIn("First", text)
            self.assertIn("Second", text)
        finally:
            core.DOCS_DIR = old_docs

    def test_email_triage_summary_and_explicit_organization(self):
        rows = [
            {"sender": "Bank", "subject": "Security alert - verify", "snippet": "Action required", "unread": True},
            {"sender": "News", "subject": "Weekly newsletter", "snippet": "Unsubscribe", "unread": True},
        ]
        with mock.patch.object(integrations, "_load_mail_rows",
                               return_value=({}, "gmail", rows, {"url": "https://mail.google.com"})), \
                mock.patch.object(core, "llm_json", return_value=None):
            triage = integrations.email_operation("triage")
            self.assertIn("[URGENT]", triage)
            self.assertIn("[NEWSLETTER]", triage)
            blocked = integrations.email_operation("organize", confirmed=False)
            self.assertIn("CONFIRMATION REQUIRED", blocked)
            with mock.patch.object(integrations, "_mark_rows",
                                   return_value=(True, 1, "ok")) as mark:
                done = integrations.email_operation("organize", confirmed=True)
                self.assertIn("Marked 1 newsletter", done)
                self.assertEqual(len(mark.call_args.args[2]), 1)

        with mock.patch.object(integrations, "_load_mail_rows",
                               return_value=({}, "gmail", rows, {})), \
                mock.patch.object(core, "llm_text", return_value="Thread summary"):
            self.assertEqual(integrations.email_operation("summarize", query="project"),
                             "Thread summary")

    def test_inbox_listing_does_not_mark_read(self):
        data = {"ok": True, "messages": [{
            "sender": "A", "subject": "Hello", "snippet": "World", "unread": True,
        }], "url": "https://mail.google.com"}
        with mock.patch.object(integrations.gmail_web, "read_inbox", return_value=data), \
                mock.patch.object(integrations.gmail_web, "mark_inbox_read") as mark:
            text = integrations._gmail_web_inbox_text(mark_read=False)
        self.assertIn("Hello", text)
        self.assertFalse(mark.called)

    def test_github_summary_and_pull_requests_are_real_paths(self):
        issue = {"number": 12, "title": "Fix login", "state": "open",
                 "user": {"login": "dev"}, "comments": 1,
                 "html_url": "https://github.test/12", "body": "Details"}
        comments = [{"user": {"login": "reviewer"}, "body": "Please add a test"}]
        with mock.patch.object(workspace, "_cfg", return_value={"repo": "o/r", "token": "x"}), \
                mock.patch.object(workspace, "_token", return_value="x"), \
                mock.patch.object(workspace, "_http", side_effect=[
                    (200, json.dumps(issue), {}), (200, json.dumps(comments), {}),
                ]), \
                mock.patch.object(workspace, "_summarise", return_value="REAL SUMMARY") as summarize:
            result = workspace._github("summarize", "12", "", "", "", False)
        self.assertEqual(result, "REAL SUMMARY")
        self.assertIn("Please add a test", summarize.call_args.args[1])

        pulls = [{"number": 2, "title": "PR", "user": {"login": "dev"},
                  "head": {"ref": "feature"}, "base": {"ref": "main"}}]
        with mock.patch.object(workspace, "_cfg", return_value={"repo": "o/r", "token": "x"}), \
                mock.patch.object(workspace, "_token", return_value="x"), \
                mock.patch.object(workspace, "_http", return_value=(200, json.dumps(pulls), {})):
            self.assertIn("#2 PR", workspace._github("pull_requests", "", "", "", "", False))

    def test_notion_linear_and_jira_read_real_items(self):
        notion_data = {"results": [{
            "object": "page", "id": "a" * 32,
            "properties": {"title": {"title": [{"plain_text": "Q4 Plan"}]}},
        }]}
        with mock.patch.object(workspace, "_token", return_value="x"), \
                mock.patch.object(workspace, "_http", return_value=(200, json.dumps(notion_data), {})):
            result = workspace._notion("read", "Q4 plan", "", "", False)
        self.assertIn("Q4 Plan", result)
        self.assertEqual(workspace._notion_id("Q4 plan"), "")

        with mock.patch.object(workspace, "_token", return_value="x"), \
                mock.patch.object(workspace, "_linear_graphql", side_effect=[
                    (True, {"issueSearch": {"nodes": [{"id": "uuid", "identifier": "ENG-12"}]}}),
                    (True, {"issue": {"identifier": "ENG-12", "title": "Fix onboarding",
                                      "description": "Details", "url": "https://linear.test/eng-12",
                                      "state": {"name": "Open"}, "assignee": {"name": "Ali"},
                                      "comments": {"nodes": [{"body": "Please test",
                                                                "user": {"name": "Sara"}}]}}}),
                ]):
            linear = workspace._linear("read", "ENG-12", "", "", False)
        self.assertIn("Fix onboarding", linear)
        self.assertIn("Please test", linear)

        jira_data = {"fields": {
            "summary": "Login bug", "status": {"name": "Open"},
            "assignee": {"displayName": "Ali"}, "reporter": {"displayName": "Sara"},
            "updated": "2026-11-21", "description": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Description"}]}
            ]}, "comment": {"comments": [{"author": {"displayName": "Reviewer"},
                                              "body": {"content": [{"content": [
                                                  {"type": "text", "text": "Needs test"}
                                              ]}]}}]},
        }}
        with mock.patch.object(workspace, "_cfg", return_value={
                    "url": "https://jira.test", "email": "u@example.com", "token": "x"}), \
                mock.patch.object(workspace, "_token", return_value="x"), \
                mock.patch.object(workspace, "_http", return_value=(200, json.dumps(jira_data), {})):
            jira = workspace._jira("read", "ABC-12", "", "", False)
        self.assertIn("Login bug", jira)
        self.assertIn("Needs test", jira)

    def test_memory_privacy_controls_and_clear_guard(self):
        core.save_config({"archive_enabled": False})
        memory.archive_user("do not write this")
        self.assertFalse(os.path.exists(memory.ARCHIVE_FILE))
        core.save_config({"archive_enabled": True})
        memory.archive_user("write this")
        self.assertTrue(os.path.exists(memory.ARCHIVE_FILE))
        blocked = privacy.privacy_operation("clear_history")
        self.assertIn("CONFIRMATION REQUIRED", blocked)
        cleared = privacy.privacy_operation("clear_history", confirmed=True)
        self.assertIn("Cleared local conversation history", cleared)
        self.assertEqual(Path(memory.ARCHIVE_FILE).read_text(encoding="utf-8"), "")
        import jarvis_core
        spoken = []
        with mock.patch.object(core, "say_lang", side_effect=lambda a, b, c: spoken.append(a)):
            self.assertTrue(jarvis_core.command_hook("show privacy status", {}))
        self.assertTrue(spoken and "privacy status" in spoken[-1].lower())

    def test_persistent_memory_facts_pins_archive_context_and_backup(self):
        self.assertIn("Remembered", memory.save_fact(
            "user_name", "Shahid", "identity", 5))
        self.assertIn("Pinned permanently", memory.remember_exact(
            "Project Atlas deadline is Friday", tags="project"))
        memory.archive_user("We discussed Project Atlas milestones")
        memory.archive_assistant("I prepared the milestone summary")
        recall = memory.recall_all("Project Atlas", 10)
        self.assertIn("Project Atlas deadline is Friday", recall)
        self.assertIn("milestones", recall)
        context = memory.context_for("What is the Atlas deadline?")
        self.assertIn("LONG-TERM MEMORY", context)
        self.assertIn("Friday", context)
        backup = memory.backup_memory()
        self.assertIn("Memory backed up", backup)
        self.assertTrue(any(Path(memory.BACKUP_DIR).rglob("memory.json")))
        core.save_config({"memory_enabled": False})
        self.assertEqual(memory.context_for("Atlas"), "")

    def test_memory_forget_and_audit_clear_are_guarded(self):
        memory.save_fact("project", "Jarvis", "project", 4)
        self.assertIn("CONFIRMATION REQUIRED", memory.memory_operation("forget", key="project"))
        self.assertIn("Forgot", memory.memory_operation("forget", key="project", confirmed=True))
        core.audit("qa", "x", "ok")
        self.assertIn("CONFIRMATION REQUIRED", tools.audit_operation("clear"))
        self.assertIn("cleared", tools.audit_operation("clear", confirmed=True).lower())

    def test_research_rejects_http_errors(self):
        response = mock.Mock(status_code=404, url="https://example.test/nope", headers={"content-type": "text/html"})
        with mock.patch.object(research, "_get", return_value=response):
            result = research.fetch_page("https://example.test/nope")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "HTTP 404")

    def test_dictation_reports_measured_not_promised_latency(self):
        old = dict(dictation._STATE)
        try:
            dictation._STATE.update({
                "running": True, "started": time.time() - 2, "utterances": 2,
                "buffer": "hello", "last_latency_ms": 310,
                "latency_total_ms": 700, "latency_samples": 2,
            })
            status = dictation.status()
            self.assertIn("310 ms last / 350 ms average", status)
            self.assertNotIn("240 ms", status)
        finally:
            dictation._STATE.clear()
            dictation._STATE.update(old)

    def test_legacy_tools_have_confirmation_parameters(self):
        source = Path(__file__).resolve().parents[1] / "jarvis.py"
        text = source.read_text(encoding="utf-8")
        for signature in (
            "def youtube_subscribe(channel_name: str, confirmed: bool = False)",
            "def send_whatsapp_message(number_or_name: str, message: str,",
            "def send_whatsapp_voice(contact_name: str, text_urdu_script: str = \"\", text_english: str = \"\",",
            "def say_in_voice_chat(text_urdu_script: str = \"\", text_english: str = \"\",",
            "def press_keys(keys: str, confirmed: bool = False)",
            "def control_screen(task: str, max_steps: int = 12, confirmed: bool = False)",
            "def run_powershell(command: str, confirmed: bool = False)",
            "def run_python_code(code: str, confirmed: bool = False)",
            "def write_text_file(path: str, content: str, append: bool = False,",
            "def click_on_screen(description: str, double: bool = False,",
            "def forget(key: str, confirmed: bool = False)",
            "def close_window(title_part: str, confirmed: bool = False)",
            "def delete_to_recycle_bin(path: str, confirmed: bool = False)",
            "def power_action(action: str, confirmed: bool = False)",
        ):
            self.assertIn(signature, text)
        self.assertIn("def _safe_tool_call_text", text)
        self.assertIn('shown[key] = "<redacted>"', text)
        self.assertIn("completion is not confirmed", text)
        self.assertNotIn('return "Finished: " + "; ".join(history)', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
