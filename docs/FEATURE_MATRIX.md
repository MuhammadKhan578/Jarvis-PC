# Jarvis PC v2.3.0 feature matrix

This maps the public assistant checklist to concrete code and verification.
“Implemented” does not mean a third-party account is magically available: live
GitHub/Slack/Notion/Linear/Jira/email actions still need the user's own login or
token and the service must be online.

| # | Capability | Implementation | Verification / boundary |
|---|---|---|---|
| 1 | Talk, type, listen, speak, personality, language | `jarvis.py`, `persona.py`, HUD chat/voice | English + Roman Urdu voice path and Urdu/English replies; natural-language Gemini routing. Mic/speaker devices are checked by diagnostics. |
| 2 | Dictate and write in Windows apps | `dictation.py` (`Ctrl+Alt+V`) | Voice-edit unit tests; real Windows typing/save tested through Notepad. Latency is measured and displayed—no fixed 240 ms guarantee. |
| 3 | Control Windows | `computer.py`, original launcher/screen tools | Real Notepad focus/type/`ctrl+s`/close smoke test; high-impact actions require confirmation. |
| 4 | Use a real browser | `browser.py` (Chromium DevTools) | Real isolated Brave test: open/read/find/input/contenteditable/click/safety. Dedicated persistent profile; experimental on changing sites. |
| 5 | Research and summarize | `research.py`, `integrations.py`, `documents.py` | Live multi-engine search + page extraction test; cited quick/deep paths and document summaries. |
| 6 | Persistent context | `memory.py`, `persona.py` | Facts, pins, episodes, archive, retrieval and backup tests. Memory/archive can be disabled independently. |
| 7 | Automatic routines | `agent.py` scheduler | One-off, interval, daily/day-part and weekly parsing; persisted due-job dispatch test; exact high-impact routines need preapproval. |
| 8 | Multi-app work | `agent.py` mission engine + tool set | Persistent plans, step results and reports. Blocked/failed steps now report partial instead of false completion. |
| 9 | Email and calendar | `integrations.py`, `mail.py`, `gmail_web.py`, `calendar_tools.py` | Draft/preview/confirm/send safety; read-only listing, triage, thread summary, conservative organization; calendar add/list/update/delete/REQUEST invitation/export tests. Live mail requires Gmail login or IMAP/SMTP credentials. |
| 10 | Slack, Notion, Linear, GitHub, Jira | `workspace.py` | Official API adapters; mocked response/guard tests for all services, GitHub PRs, Notion databases, Linear/Jira detail. Live calls require user tokens. |
| 11 | Help other AI tools | `mcp.py`, `jarvis_mcp_server.py` | Real stdio initialize/tools/resources/ping test. Memory/calendar/style plus read-only workspace queries and cited research. |
| 12 | Privacy and setup | `privacy.py`, `jarvis_config.py`, `core.py` | DPAPI for saved credentials, secret-log redaction, local data controls, no telemetry. Windows permission behavior is reported honestly. |
| 13 | Best-use cases | Combined capabilities above | Voice control, dictation, memory, research, routines and connected tools are available through natural language. |
| 14 | Important-action caution | `core.guard`, browser/UI/legacy tool guards | Send/delete/payment/purchase/account/overwrite/power/remote-write actions are blocked until confirmed; actions are audited locally. |

## Runtime reality

- Scheduled work needs Jarvis running and the PC awake. Overdue work is picked
  up after wake/start.
- Browser automation is affected by website redesigns, sign-in challenges,
  CAPTCHAs and service policy. Important outcomes must be verified.
- Exact speech latency and recognition accuracy depend on hardware, phrase
  length, network and the recognizer.
- Live third-party writes were not performed during release QA without the
  user's private credentials. Their adapters were tested with deterministic
  mocked official-API responses and confirmation guards.
