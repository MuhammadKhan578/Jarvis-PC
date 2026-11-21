# Jarvis PC — real Twilio voice phone line

This is a **real Twilio number**, not a hack into the Android phone's calls. Jarvis
places outbound calls through the Twilio REST API and answers inbound calls on a
Twilio phone number through a local webhook. No call is ever claimed successful
unless Twilio returns a real call SID.

Credentials are **never bundled in this repository**. They are saved only in
`jarvis_data/config.json` on this PC (already gitignored). The auth token is
stored through Jarvis's `core.protect_secret()` helper, which uses Windows DPAPI
when available (with a portable base64 fallback when pywin32 is missing), and is
read back with `core.unprotect_secret()` only at request time. Do not paste the
token into chat, logs or screenshots.

## 1. Create the Twilio account and number

1. Sign up at <https://www.twilio.com/> and verify the personal phone that will
   receive the test call.
2. In **Console → Phone Numbers → Manage → Buy a number**, buy a number with
   **Voice** capability. Note it in E.164 format, e.g. `+15551234567`.
3. In **Console → Account**, copy the **Account SID** and **Auth Token**. Treat
   the Auth Token like a password.

## 2. Save the configuration through the tool (once, on the PC)

Use the Jarvis tool (or a local Python call); all values are optional except the
three Twilio fields, so you can update one at a time:

```python
from jarvis_core import phone_line

phone_line.phone_line_operation(
    action="configure",
    account_sid="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # your SID
    auth_token="your_real_auth_token",                # protected locally
    from_number="+15551234567",                       # your Twilio number
    to_number="+15557654321",                         # your callback number for "call me"
    enabled=True,
)
```

Equivalent tool call: `phone_line_operation(action="configure", ...)`.
Check with `phone_line_operation("status")` — it shows a masked SID and never
prints the token. To change the callback number later, pass only `to_number`.

## 3. Start the local webhook

```python
phone_line.phone_line_operation(action="start", port=8765)
# or, in the foreground:
phone_line.phone_line_webhook(port=8765)
```

It binds **127.0.0.1 only**. Verify locally:

```
GET http://127.0.0.1:8765/voice/health
```

Stop it with `phone_line_operation(action="stop")`. `jarvis line status`,
`phone line status`, `phone line start` and `phone line stop` also work as spoken
commands. `jarvis line setup` opens this guide.

## 4. Expose the webhook over HTTPS

Twilio needs a public HTTPS URL. From this PC, run one of:

```
cloudflared tunnel --url http://localhost:8765
ngrok http 8765
```

Copy the generated `https://<subdomain>...` URL. It changes on free tunnels;
update Twilio whenever it changes. Do not expose port 8765 directly to the
internet — the server intentionally listens only on localhost.

## 5. Point Twilio at the webhook

1. **Console → Phone Numbers → Active Numbers → your number → Voice & Fax**.
2. Under **A call comes in**, choose **Webhook**, HTTP **POST**, and set the URL
   to `https://<your-tunnel>/voice/inbound`. Save.
3. Call your Twilio number. After the greeting, say a command such as
   `phone line status`, `what time is it`, `last transcript` or
   `record this call`.

To test only the recording endpoint, temporarily set the "A call comes in"
webhook to `https://<your-tunnel>/voice/record`. It announces the consent line
before it starts `<Record>`.

## 6. Outbound calls and confirmation

`call me <message>` uses the configured `to_number` as the destination. Because
placing a real call costs money and reaches a person, it is high-risk: the first
attempt returns `CONFIRMATION REQUIRED` and places **no** call. On the voice line,
say `confirm` when prompted; in chat, call again with `confirmed=True`:

```python
phone_line.phone_line_call(to_number="+15557654321",
                           message="Sir, Jarvis is calling as requested.",
                           confirmed=True)
```

Only a response containing a Twilio `sid` such as `CA...` counts as accepted;
the exact status reported by Twilio is printed too. HTTP/network errors are
returned verbatim (truncated for safety), never replaced with a success claim.

## 7. Recordings and transcripts

- `/voice/record` says, **before** recording:
  *"Ye call recording ki ja rahi hai / This call is being recorded."*
- On the recording callback, Jarvis downloads the audio from the Twilio URL with
  HTTP Basic auth (SID + token) and saves it under
  `jarvis_data/phone_line_recordings/`.
- A JSONL log at `jarvis_data/phone_line_transcripts.jsonl` records timestamp,
  `from`, `sid`, `speech_result` and the local audio path.
- `speech_result` is the spoken command captured by the earlier `<Gather>`. If
  there was no gathered speech, it is written honestly as
  **`transcript unavailable`** — there is no automatic audio-to-text service in
  this feature and none is claimed.

## Legal consent note

Recording laws differ by country and US state (one-party vs all-party consent).
Announce the recording exactly as implemented, only record when your local law
allows it, and get any additional permission required for the people on the
line. Do not use this to secretly record calls. You are responsible for the
number you buy and for Twilio usage charges.

## What works / what does not

**Works**

- Real outbound voice calls through Twilio REST, with confirmation gate and real
  SID/status/error reporting.
- Inbound voice commands on the **Twilio number**, routed through Jarvis's
  command hook with spoken replies read back through TwiML.
- Small safe dispatcher for phone line status, last transcript, health, time and
  date; high-risk PC commands are refused from the phone line.
- Spoken `confirm` second step for confirmation-required commands.
- Consent-announced recording, local audio save and honest JSONL transcript log.
- Male TwiML voice (`voice="man"`) throughout; no female voice switching.

**Does not work / is not claimed**

- **No inbound call interception on Android.** This cannot hear or join calls on
  your carrier SIM or mobile dialer; it only handles calls to the Twilio number.
- No automatic speech-to-text of the recording. Audio without a Gather result is
  logged as `transcript unavailable`.
- No call delivery guarantee: "accepted" means Twilio returned a SID, not that
  the human answered.
- No operation while the PC is off, the webhook is stopped, the HTTPS tunnel is
  down, or Twilio is unconfigured.
- No emergency (911/112) calling, no bypass of Twilio trial restrictions, and no
  "240ms" response-time claim.
