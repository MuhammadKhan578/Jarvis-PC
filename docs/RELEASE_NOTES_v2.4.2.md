# Jarvis PC v2.4.2 release notes

This release turns the previously answered "no" items into **real, working paths**
wherever technology and the user's own accounts allow it. Nothing is faked.

## New in v2.4.2

- **Twilio phone line (`phone_line_*`):** real outbound calls ("call me"), a real
  inbound Twilio voice number with speech commands, spoken confirmation, consent
  before recording, local recording storage and an honest JSONL transcript log.
  Credentials are configured locally (DPAPI-protected token), never bundled.
  See `docs/PHONE_LINE.md` for setup (Twilio number + HTTPS webhook tunnel).
- **Background removal (`remove_background`):** real `rembg` output as a new PNG
  with alpha preserved; original is never overwritten. Reports honestly if the
  dependency is missing.
- **Food cart (`commerce_operation(action="cart_add")`):** real Edge DevTools
  add-to-cart attempt on a logged-in food site. Final order and payment always
  stay with the user; no order or payment is claimed.
- **Official insights (`analytics_operation(action="insights")`):** Instagram
  Graph API and YouTube Data API metrics with locally protected tokens. Without
  a token it says "token chahiye / login required"; no private-page scraping and
  no invented numbers.
- **Game download (`game_operation(action="download")`):** real Steam store
  lookup and a real `steam://install/<appid>` hand-off. This triggers Steam's own
  downloader; it is not a silent install and never claims completion.
- **Natural commands:** "call me", "phone line start/status/stop", "background
  remove karo", "insights", "<item> cart mein daalo", "download <game>".

## Still honestly limited

- No incoming-call interception on Android; the inbound voice line is a Twilio
  number. Android call recording/transcript is not implemented.
- No payment automation, no private Instagram/YouTube scraping, no silent game
  install, no Premiere project automation, no fixed latency guarantee.
- No Secret/Sex mode and no private JMF content in this repository.

## Verification

- `python -m compileall -q -f .`
- `python -m unittest discover -s tests -p "test_*.py" -v` — **57 tests passed**
  (25 original + 13 reel + 8 phone line + 11 all-yes add-on).
- `python -m pip check` — no broken requirements.
- Live Twilio calls, live platform APIs and live food-site carts were **not**
  executed during QA: those adapters are covered by mocked official-API tests and
  require the user's own credentials/logins to go live.
