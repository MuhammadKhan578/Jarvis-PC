# Jarvis PC v2.4.5 release notes

Adds a **safe, guided Twilio setup** for the real SIM/phone-number line. No
credentials are bundled; everything is entered locally on the PC.

## New in v2.4.5

- **`phone_line_setup.ps1`** prompts for Account SID, Auth Token (masked input),
  Twilio voice number and your callback mobile. It configures Jarvis through
  `phone_line_operation("configure")`, protects the token with DPAPI, starts the
  local webhook on `127.0.0.1:8765` and checks `/voice/health`. The token is never
  printed, logged or sent to chat.
- **`phone_line_webhook.ps1 -TunnelUrl https://...`** reads the protected config,
  finds your Twilio number through the official REST API and sets its
  `VoiceUrl` to `<tunnel>/voice/inbound` with `VoiceMethod=POST`. No manual
  console clicking needed after the tunnel is running.
- **Free tunnel first:** Windows OpenSSH is already present, so
  `ssh -o StrictHostKeyChecking=accept-new -R 80:localhost:8765 ssh.localhost.run`
  gives a public HTTPS URL without installing anything. `cloudflared`/`ngrok`
  also work.
- **Trial-friendly flow:** any mobile can dial the Twilio number and give voice
  commands. `call me` → `confirm` makes Jarvis call back; in a Twilio trial,
  outgoing calls are limited to verified numbers, so it rings only your mobile.
- Docs updated: `README.md`, `docs/PHONE_LINE.md`, `docs/ASSISTANT.md`,
  `docs/FEATURE_MATRIX.md`.

## Honest limits

- Twilio free trial has **limited credit**; it is not free forever. Official
  pricing (Oct 2026): inbound voice from **$0.0085/min**, outbound from
  **$0.014/min** after trial credit. Exact credit is shown in your dashboard.
- A public HTTPS tunnel is required. Free tunnel URLs change on every restart;
  re-run `phone_line_webhook.ps1` with the new URL.
- No live Twilio call was placed here (no user credentials available). The
  official REST paths, local config, webhook routes, confirmation gate and
  scripts were verified offline; the first real call depends on your account.
- No incoming-call interception on Android, no Secret/Sex mode, no fixed
  latency claim.

## Verification

- `python -m compileall -q -f .` — exit 0.
- `python -m unittest discover -s tests -q` — **81 tests passed**.
- `python -m pip check` — no broken requirements.
- Both PowerShell scripts pass the PowerShell parser; embedded Python compiles.
