# Jarvis PC v2.4.3 release notes

Adds a direct Mobile Jarvis ↔ PC Jarvis link over the local network.

## New in v2.4.3

- **Device Link server (`device_link_*`):** pair the phone with a one-time 6-digit
  code; receive any file (photo, zip, video, document) into a staging folder;
  ask the user by voice where to save it; then write the real file to the chosen
  path with size verification and overwrite confirmation. Commands: "device link
  start/status/stop/code", "mobile se file aayi", "save it to <path>" /
  "<path> mein save karo".
- **Voice channel from the phone:** `/link/command` routes spoken commands from
  the paired mobile app through Jarvis PC and returns the spoken reply. This is
  a Wi-Fi intercom inside the app — **no SIM number and no phone call needed**.
  A real telephone call still requires the separately documented Twilio line.
- **Security:** token required for every endpoint, pairing code expires after
  10 minutes with an attempt cap, files stay on the local network, nothing is
  saved to a final path until the user supplies a destination.

## Honest limits

- Same Wi-Fi or phone hotspot is required; there is no cloud relay.
- No automatic save without a destination; no fake "saved" message.
- A real phone call to Jarvis needs Twilio credentials (see `docs/PHONE_LINE.md`).
- No Secret/Sex mode, no private JMF, no fixed latency guarantee.

## Verification

- `python -m compileall -q -f .`
- `python -m unittest discover -s tests -p "test_*.py" -v` — **69 tests passed**
  (25 original + 13 reel + 8 phone line + 11 all-yes + 12 device link).
- Real local HTTP proof: pair (wrong code rejected) → upload → destination
  question → save with byte verification → `/link/command` voice reply.
- Integration bug fixed during QA: the Android `file_id` key and explicit
  `confirm` flag are both accepted by `/link/save`; overwrite never happens
  without a clear confirmation.
- `python -m pip check` — no broken requirements.
- End-to-end local HTTP flow (pair → upload → destination prompt → save → voice
  command) was exercised with a real local server and a real multipart client.
