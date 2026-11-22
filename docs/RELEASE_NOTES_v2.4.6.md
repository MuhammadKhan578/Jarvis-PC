# Jarvis PC v2.4.6 release notes

## New in v2.4.6

- **Optional one-person voice check after API-key setup.** The first-run HUD now
  asks, immediately after the Gemini key, whether spoken commands should be
  accepted only from one enrolled voice. The step is completely skippable.
  Two short recordings are reduced to a 13-value MFCC vector and stored in
  `jarvis_data/voiceprint.json` on this PC. No audio is uploaded, no account is
  needed, and the dialog says plainly that this is a convenience lock, not a
  biometric guarantee.
- **Voice lock controls.** HUD button `[ VOICE LOCK ]`, plus typed/voice commands
  `voice status`, `voice lock on`, `voice lock off`, `voice enroll`,
  `voice clear`, `confirm voice clear`. When the lock is on, a spoken phrase that
  does not match the enrolled vector is discarded before it reaches any command
  handler. Typed commands are never blocked. Windows hotkeys still work.
- **Natural greeting.** `Hello Jarvis, kaise ho` (and shorter variants such as
  `kaise ho`) is answered locally and instantly:
  `Kya hua sir? Main bilkul theek hoon, aap bataiye.` It does not wait for
  Gemini and works without an API key.

## Verification done here

- `python -m compileall -q -f .` — clean.
- `python -m unittest discover -s tests -p "test_*.py"` — **90/90 passed**.
  New tests cover MFCC enroll/verify, clear, skip persistence, no network code in
  the speaker module, and the local greeting reply.
- `python -m pip check` — no broken requirements.

## Honest limits

- A real microphone enrollment and a live spoken false-voice rejection were not
  performed in this environment. The verification tests use generated PCM and a
  temporary voiceprint file.
- The voice check is a speaker-similarity convenience lock. It is not a secure
  biometric identity system and can be fooled by a close voice, recording or
  loudspeaker. It is optional and off unless the user enables it.
- No fixed speech-to-first-word latency is claimed.

## Upgrade

Replace the source folder and start `Jarvis.bat`. Existing users who skip the
prompt once will not be asked again; open `[ VOICE LOCK ]` in the HUD any time.
