# Jarvis PC Device Link (phone → PC files, local network only)

Device Link is a **real** local-network channel between Jarvis on this PC and a
paired Android phone. The phone sends a file over your Wi-Fi / hotspot, Jarvis
on the PC speaks up and **asks where to save it**, and only after you give a
real destination is the file written there. There is no cloud, no internet and
no phone number involved. The Twilio voice line (`docs/PHONE_LINE.md`) is a
**separate** feature for real telephony; Device Link does not use it.

## Requirements

- PC and phone on the **same Wi-Fi network** (or the PC's mobile hotspot).
- Port **8766** reachable on the LAN (allow Jarvis / Python through Windows
  Firewall for private networks if Windows asks).
- No internet connection is needed. Nothing is uploaded anywhere.

## Exact steps

1. **Start the listener on the PC.** Say to Jarvis (or call the tool):

   `device link start`

   You should hear that Device Link started with a LAN IP such as
   `http://192.168.1.23:8766`.

2. **Get the one-time code.** Say:

   `device link code`

   Jarvis speaks a 6-digit code (for example `482913`) and repeats the LAN IP
   and port. The code is valid for **10 minutes** and works **once**. If you say
   it again, the old code and any old pairing are cancelled. You can say
   `device link status` any time to hear the IP, port, pairing state and how many
   files are waiting.

3. **Pair from the phone.** In the Jarvis Android companion's **Device Link**
   screen (or any local HTTP client on the phone), enter:

   - **IP:** the LAN IP from step 1/2 (e.g. `192.168.1.23`)
   - **Port:** `8766`
   - **Code:** the 6 digits from step 2

   The phone calls `POST /link/pair` with `{"code":"482913"}` and receives
   `{"ok":true,"token":"..."}`. A wrong or expired code returns `ok:false` with
   an honest error; after 5 wrong tries a new code is required. The phone must
   keep the returned token: every later request sends it in the
   `X-Jarvis-Token` header.

4. **Send any file from the phone.** The app posts `multipart/form-data` to
   `/link/upload` with the token header. Files up to **200 MB** are accepted.

5. **Hear PC Jarvis ask for the destination.** The PC immediately speaks:

   > File received: photo.jpg. Where should I save it on this PC? Tell me a
   > path such as Downloads or D:\backup.

   (Also in Urdu/Roman Urdu: "File mil gayi: photo.jpg. PC par kaha save karna
   hai? Paths batao jaise Downloads ya D:\backup.")

   At this point the file is **only staged** in
   `jarvis_data/device_link/incoming/`. Nothing has been saved to a final place,
   and the phone is told `status: "need_destination"` — no fake success.

6. **Say where to save it.** Reply to Jarvis on the PC with either form:

   - `save it to Downloads`
   - `D:\backup\photo.jpg mein save karo`

   You can give a folder (`Downloads`, `D:\backup`) or a full file path
   (`D:\backup\photo.jpg`). Relative names resolve against the Desktop, matching
   Jarvis's normal path rules.

7. **File saved and path spoken.** Jarvis creates any missing parent folders,
   copies the real bytes, verifies the size, removes the staged copy and says
   the **actual final path** out loud, e.g. "File saved to
   D:\backup\photo.jpg. Size 184320 bytes." The phone can call
   `POST /link/save` with `{"id":"...","destination":"...","confirmed":true}`
   and gets `{"ok":true,"path":"D:\\backup\\photo.jpg","size":184320}`.

   If that target already exists, Jarvis refuses to overwrite until you
   confirm: the response contains `CONFIRMATION REQUIRED` and no bytes are
   touched. Say `confirm save` / `haan` on the phone, or send
   `{"id":"...","confirm":true}` (the remembered destination is reused). Only
   that explicit confirmed request proceeds. The key `file_id` is also accepted
   for compatibility with the Android client.

You can also **talk to PC Jarvis from the phone**: `POST /link/command` with
`{"text":"what time is it"}` and the token header routes the text through the
same `command_hook` used by voice and returns the captured spoken reply as JSON.
`/link/call` is an alias. Risky commands (delete, send, payment, etc.) stay
blocked without confirmation, exactly as on the PC.

## Privacy and limits

- **Local only:** the server binds `0.0.0.0:8766` on your LAN. No relay, no
  cloud storage, no telemetry, no internet dependency.
- **Token required:** uploading, saving and commanding all require the random
  token from pairing, sent in `X-Jarvis-Token`. The token is stored protected
  via `core.protect_secret` (DPAPI where available) under the gitignored
  `jarvis_data/device_link/` folder; only the protected form is on disk.
- **One-time code:** codes expire after 10 minutes, allow 5 wrong attempts, and
  generating a new code invalidates the old token. Pair again if you lose it.
- **No auto-save:** every upload waits for an explicit destination; there is no
  default final folder and no claim of success before verification.
- **No phone number / no Twilio:** this channel is not telephony. Phone calls
  and SMS remain a separate, optional Twilio feature described in
  `docs/PHONE_LINE.md`.
- **200 MB per file** cap; larger uploads are rejected before staging.
- PC Jarvis's voice stays male; there is no secret/sex mode and no special
  timing claim. High-risk actions keep their confirmation gates.

## Troubleshooting

- `device link status` says `stopped` → run `device link start`.
- Phone cannot connect → check both devices are on the same network, the IP is
  the PC's LAN address (not `127.0.0.1`), and the Windows Firewall allows port
  8766 on private networks.
- "No pairing code is active" → run `device link code` again on the PC.
- "Wrong pairing code" → the 6 digits must be typed exactly; after 5 errors ask
  for a new code.
- "There is no pending file from the phone" → send/upload a file first, then
  give the destination.
- `CONFIRMATION REQUIRED` → repeat the save with confirmation as Jarvis asks.
