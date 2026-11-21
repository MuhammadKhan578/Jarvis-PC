# Jarvis PC v2.4.0 release notes

## New reel feature pack

- **ISS** — real Open Notify position plus a refreshable local HUD map.
- **Video** — Gemini sampled-frame understanding, FFprobe info, and real
  trim/cut/keep/auto-cut MP4 outputs using the FFmpeg binary from
  `imageio-ffmpeg`. Source files are never overwritten.
- **Photos** — Gemini image questions and real Pillow edits: resize, centre-crop
  with 9:16/1:1/16:9/4:3/3:2 presets, rotate, flip, enhance, grayscale, sepia,
  blur and text.
- **Visual guide** — temporary highlight over a located UI element, without
  clicking.
- **Commerce** — local grocery list and real food/grocery hand-offs. No purchase
  or payment is claimed.
- **Analytics** — best-effort public views/likes/comments monitoring; login-only
  insights are not scraped.
- **Alerts** — ntfy-compatible remote alerts with DPAPI-protected tokens and an
  explicit confirmation gate.
- **Phone agent** — ADB/provider dial hand-off with confirmation; call status and
  transcripts come only from a configured real provider.
- **Games** — real Steam/Epic library and update scans with disk-space checks and
  confirmation-gated client hand-offs.

## Privacy and safety

- New local runtime files: `jarvis_data/shopping_list.json`,
  `jarvis_data/social_monitors.json`, and
  `Jarvis_Reports/ISS_Live_Tracker.html`.
- ntfy and phone-provider tokens use the existing Windows DPAPI credential store.
- High-impact actions remain confirmation-gated and audited locally.
- No fixed 240 ms latency claim. Measured latency is reported by the app.

## Verification

- `python -m compileall -q -f .`
- `python -m unittest discover -s tests -p "test_*.py" -v` — 36 tests passed.
- `python -m pip check` — no broken requirements.
- FFmpeg edits were validated with a generated source MP4. Photo edits and
  mocked multimodal analysis were validated with generated images.
