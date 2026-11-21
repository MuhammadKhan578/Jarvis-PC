# Jarvis PC v2.4.5 feature matrix

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
| 15 | Live ISS position | `showcase.py` | Real Open Notify endpoint plus a refreshable local HTML map; no key. Endpoint failure is reported honestly. |
| 16 | Video understanding and cuts | `media_tools.py`, `imageio-ffmpeg` | Real FFprobe info, Gemini sampled-frame analysis, trim/cut/auto-cut FFmpeg tests with real generated MP4 outputs. Audio is not claimed for large videos. |
| 17 | Photo understanding and edits | `media_tools.py`, Pillow | Real Gemini image analysis plus resize/crop/preset/rotate/flip/enhance/grayscale/sepia/blur/text tests. Source is never overwritten. |
| 18 | Visual guide | `showcase.py` | Locates a UI target and draws a temporary highlight; does not click. |
| 19 | Food and groceries | `showcase.py` | Local grocery list and real service search hand-off; no purchase or payment is claimed. |
| 20 | Public social analytics | `showcase.py` | Best-effort public-page metrics and change monitoring; login-only insights require the user's account/API. |
| 21 | Remote alerts | `showcase.py` | ntfy-compatible POST with DPAPI-protected token and confirmation gate; real provider result reported. |
| 22 | Phone agent | `showcase.py` | ADB/provider dial hand-off with confirmation; call status/transcript only from a configured real provider. |
| 23 | Steam/Epic library | `games.py` | Real Steam manifest and Epic launcher metadata, update scan and disk-space check; install/update opens the real client only after confirmation. |
| 24 | Phone → PC Device Link | `device_link.py` | One-time code pairs the phone on the LAN; any file is staged with a 200 MB cap; Jarvis asks where to save it by voice; confirmed save verifies bytes and never overwrites silently. `/link/command` carries voice commands from the phone without a SIM number. |
| 25 | Free local voice line | `asterisk_line.py`, `asterisk/` | Asterisk (free) in WSL + SIP softphone: inbound speech commands on extension 1002 and opt-in outbound call to 1001 via AMI Originate. FastAGI records with consent, transcribes, runs the same guarded command hook, speaks the reply and logs a local transcript. No Twilio account or per-minute fee; real PSTN still needs a trunk/gateway. |

## Runtime reality

- Scheduled work needs Jarvis running and the PC awake. Overdue work is picked
  up after wake/start.
- Browser automation is affected by website redesigns, sign-in challenges,
  CAPTCHAs and service policy. Important outcomes must be verified.
- Exact speech latency and recognition accuracy depend on hardware, phrase
  length, network and the recognizer.
- FFmpeg is supplied by `imageio-ffmpeg` from `requirements.txt`; a system FFmpeg
  install is optional. Media edits create separate files and require
  confirmation before overwriting an output.
- Social metrics are whatever a public page exposes; Instagram/YouTube login-only
  insights need the user's account or official API. ISS, ntfy and provider call
  endpoints must be reachable. Steam/Epic and ADB hand-offs need those programs
  installed and accessible.
- Live third-party writes were not performed during release QA without the
  user's private credentials. Their adapters were tested with deterministic
  mocked official-API responses and confirmation guards. Local media, UI, STT,
  TTS and non-writing network reads were exercised directly.
