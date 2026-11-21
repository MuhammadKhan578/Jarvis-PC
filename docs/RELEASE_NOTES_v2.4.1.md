# Jarvis PC v2.4.1 release notes

Patch on top of v2.4.0: the reel-style *"edit this video"* flow now works
without typing a file path.

- `video_operation` and `image_operation` pick the newest ordinary video or
  image from `Downloads`/`Desktop` when no path is supplied.
- Deterministic local commands: *"edit this video"*, *"trim this clip"* and
  *"clean this footage"* run a real `auto_cut`; *"edit this photo"* and
  *"enhance this image"* save a real enhanced copy.
- Originals are still never overwritten, and an existing output still needs
  confirmation.
- Added two regression tests: no-path media picking and natural edit commands.

This is a real FFmpeg/Pillow file edit, not Adobe Premiere Pro project
automation. Premiere does not need to be installed. No fixed latency is
promised.

## Verification

- `python -m compileall -q -f .`
- `python -m unittest discover -s tests -p "test_*.py" -v` — 38 tests passed.
- `python -m pip check` — no broken requirements.
- A generated 6-second MP4 was cut into a real shorter MP4 and a generated PNG
  was centre-cropped into a real 9:16 PNG through the shipped tools.
