"""Video understanding and safe, deterministic FFmpeg editing for Jarvis PC."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import core


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or ""


def _source(path: str) -> str:
    p = core.resolve_path(path)
    return p if os.path.isfile(p) else ""


def _output(source: str, destination: str, suffix: str) -> str:
    if destination:
        p = core.resolve_path(destination)
    else:
        stem, ext = os.path.splitext(source)
        p = stem + suffix + (ext if ext.lower() in (".mp4", ".mov", ".mkv", ".webm") else ".mp4")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    return p


def _duration(ff: str, source: str) -> float:
    result = subprocess.run([ff, "-i", source], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if not m:
        return 0.0
    return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))


def _parse_time(value) -> float:
    text = str(value or "0").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0])*60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
    except Exception:
        pass
    raise ValueError("Use seconds or HH:MM:SS")


def _segments(text: str, duration: float = 0) -> list[tuple[float, float]]:
    out = []
    for piece in re.split(r"[,;\n]+", text or ""):
        m = re.match(r"\s*([^\s-]+)\s*(?:-|to|until)\s*([^\s]+)\s*$", piece, re.I)
        if not m:
            continue
        start, end = _parse_time(m.group(1)), _parse_time(m.group(2))
        if duration:
            end = min(end, duration)
        if end > start >= 0:
            out.append((start, end))
    return out


def _run(command: list[str], timeout: int = 900) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        return result.returncode == 0, detail[-5000:]
    except Exception as e:
        return False, str(e)


def _concat(ff: str, source: str, segments: list[tuple[float, float]], output: str) -> str:
    if not segments:
        return "No valid keep-segments were given. Example: 0-5, 12-20."
    work = Path(tempfile.mkdtemp(prefix="jarvis-video-"))
    pieces = []
    try:
        for index, (start, end) in enumerate(segments):
            part = work / f"part_{index:03d}.mp4"
            ok, detail = _run([
                ff, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", source,
                "-map", "0:v:0?", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(part)
            ])
            if not ok or not part.exists():
                return f"Video segment {start:g}-{end:g} failed: {core.truncate(detail, 500)}"
            pieces.append(part)
        listing = work / "concat.txt"
        listing.write_text("\n".join("file '" + str(p).replace("'", "'\\''") + "'" for p in pieces),
                           encoding="utf-8")
        ok, detail = _run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                           "-c", "copy", "-movflags", "+faststart", output])
        if not ok:
            return "Video join failed: " + core.truncate(detail, 700)
        return output
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _auto_segments(ff: str, source: str, threshold: float, minimum: float) -> tuple[list[tuple[float, float]], str]:
    duration = _duration(ff, source)
    if duration <= 0:
        return [], "Could not read video duration."
    ok, detail = _run([ff, "-hide_banner", "-i", source, "-af",
                       f"silencedetect=noise={threshold:g}dB:d={minimum:g}", "-f", "null", "-"], timeout=300)
    # ffmpeg exits successfully for the null analysis. Parse either way because
    # builds occasionally return 1 after decoding a damaged tail frame.
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", detail)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", detail)]
    silences = []
    end_index = 0
    for start in starts:
        while end_index < len(ends) and ends[end_index] <= start:
            end_index += 1
        end = ends[end_index] if end_index < len(ends) else duration
        end_index += 1
        silences.append((max(0, start), min(duration, end)))
    if not silences:
        return [(0, duration)], "No long silences detected; the output would be unchanged."
    keep = []
    cursor = 0.0
    padding = 0.12
    for start, end in silences:
        cut_at = max(cursor, start + padding)
        if cut_at - cursor >= 0.25:
            keep.append((cursor, cut_at))
        cursor = max(cursor, end - padding)
    if duration - cursor >= 0.25:
        keep.append((cursor, duration))
    return keep, f"Detected {len(silences)} silence(s); keeping {len(keep)} speaking segment(s)."


def _analyze_video(source: str, question: str) -> str:
    types_mod = core.gen_types()
    if types_mod is None:
        return "Gemini video analysis is unavailable."
    size = os.path.getsize(source)
    prompt = ((question or "").strip() or
              "Explain this video, then list every action, object, visible instruction, decision and important quote. "
              "Distinguish what is visibly demonstrated from marketing claims. Use timestamps when possible.")
    try:
        if size <= 18 * 1024 * 1024:
            with open(source, "rb") as handle:
                part = types_mod.Part.from_bytes(data=handle.read(), mime_type="video/mp4")
            return core.llm_text([part, prompt], system="You are a precise video analyst. Never invent unseen actions.",
                                 smart=True, max_tokens=3500)
        ff = _ffmpeg()
        if not ff:
            return "The video is too large for direct analysis and FFmpeg is unavailable."
        duration = max(1.0, _duration(ff, source))
        folder = Path(tempfile.mkdtemp(prefix="jarvis-video-frames-"))
        try:
            parts = []
            count = min(12, max(4, int(duration // 20) + 1))
            for index in range(count):
                at = duration * index / max(1, count - 1)
                frame = folder / f"frame_{index:02d}.jpg"
                ok, _ = _run([ff, "-y", "-ss", f"{at:.3f}", "-i", source, "-frames:v", "1",
                              "-q:v", "3", str(frame)], timeout=60)
                if ok and frame.exists():
                    parts.append(types_mod.Part(text=f"[Frame at {at:.1f}s]"))
                    parts.append(types_mod.Part.from_bytes(data=frame.read_bytes(), mime_type="image/jpeg"))
            parts.append(types_mod.Part(text=prompt))
            return core.llm_text(parts, system="You are a precise sampled-video analyst. State that audio was not inspected.",
                                 smart=True, max_tokens=3000)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    except Exception as e:
        return f"Video analysis failed: {e}"


def video_operation(action: str = "analyze", path: str = "", destination: str = "",
                    segments: str = "", start: str = "0", end: str = "",
                    question: str = "", silence_db: float = -35.0,
                    silence_seconds: float = 0.7, confirmed: bool = False) -> str:
    """Understand or edit a real local video.

    action:
      analyze/summarize - multimodal video explanation
      info              - duration, size and path
      trim              - keep start..end
      cut/keep          - concatenate keep-segments such as "0-5, 12-20"
      auto_cut          - remove long silent gaps and create a new MP4
      open              - open the video

    Source files are never overwritten silently. Editing requires FFmpeg
    (installed through imageio-ffmpeg) and always creates a separate output.
    """
    source = _source(path)
    if not source:
        return f"Video file not found: {core.resolve_path(path)}"
    a = (action or "analyze").strip().lower()
    if a in ("open", "play"):
        return core.open_path(source)
    ff = _ffmpeg()
    duration = _duration(ff, source) if ff else 0
    if a in ("info", "status"):
        return (f"Video: {source}\nDuration: {duration:.2f}s\nSize: {core.human_bytes(os.path.getsize(source))}\n"
                f"FFmpeg: {ff or 'not available'}")
    if a in ("analyze", "summarize", "summary", "explain", "understand"):
        return _analyze_video(source, question)
    if not ff:
        return "FFmpeg is not available. Install imageio-ffmpeg and try again."
    suffix = "_edited"
    output = _output(source, destination, suffix)
    if os.path.abspath(output).lower() == os.path.abspath(source).lower():
        return "Refusing to overwrite the source video. Choose a different destination."
    if os.path.exists(output):
        msg = core.guard("video_operation:overwrite", confirmed, f"Overwrite existing edited video '{output}'.")
        if msg:
            return msg
    if a in ("trim", "clip"):
        try:
            first = _parse_time(start)
            last = _parse_time(end) if str(end or "").strip() else duration
        except Exception as e:
            return f"Invalid trim time: {e}"
        keep = [(first, last)] if last > first else []
        result = _concat(ff, source, keep, output)
        note = f"Trimmed {first:g}s to {last:g}s."
    elif a in ("cut", "keep", "edit", "simple_cut"):
        keep = _segments(segments, duration)
        result = _concat(ff, source, keep, output)
        note = "Kept segments: " + ", ".join(f"{s:g}-{e:g}" for s, e in keep)
    elif a in ("auto_cut", "remove_silence", "silence_cut"):
        keep, note = _auto_segments(ff, source, float(silence_db), max(0.2, float(silence_seconds)))
        if not keep:
            return note
        result = _concat(ff, source, keep, output)
    else:
        return "Video actions: analyze, info, trim, cut, auto_cut, open."
    if result != output or not os.path.isfile(output):
        return result
    core.audit("video_operation", f"{a} {source}", output)
    return f"{note} Edited video created: {output} ({core.human_bytes(os.path.getsize(output))})."


# --------------------------------------------------------------------- photos
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif",
    ".tif": "image/tiff", ".tiff": "image/tiff",
}


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
        return Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
    except Exception:
        return None


def _image_source(path: str) -> str:
    source = _source(path)
    if not source:
        return ""
    return source if os.path.splitext(source)[1].lower() in _IMAGE_EXTENSIONS else ""


def _image_output(source: str, destination: str) -> str:
    if destination:
        output = core.resolve_path(destination)
    else:
        stem, ext = os.path.splitext(source)
        ext = ext.lower() if ext.lower() in _IMAGE_EXTENSIONS else ".png"
        output = stem + "_edited" + ext
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    return output


def _save_image(image, output: str) -> None:
    ext = os.path.splitext(output)[1].lower()
    image = image.convert("RGB") if ext in (".jpg", ".jpeg") else image
    if ext in (".jpg", ".jpeg"):
        image.save(output, quality=92, subsampling=0)
    elif ext == ".webp":
        image.save(output, quality=90, method=5)
    else:
        image.save(output)


def _crop_box(value, image) -> tuple[int, int, int, int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = [p for p in re.split(r"[,\s;]+", text) if p]
    if len(parts) != 4:
        raise ValueError("crop needs x,y,width,height")
    try:
        x, y, width, height = (int(round(float(p))) for p in parts)
    except Exception as e:
        raise ValueError("crop values must be numbers") from e
    image_width, image_height = image.size
    x = min(max(0, x), max(0, image_width - 1))
    y = min(max(0, y), max(0, image_height - 1))
    width = min(max(1, width), image_width - x)
    height = min(max(1, height), image_height - y)
    return x, y, x + width, y + height


def _analyze_image(source: str, question: str) -> str:
    types_mod = core.gen_types()
    if types_mod is None:
        return "Gemini image analysis is unavailable."
    try:
        pil = _pil()
        Image, ImageOps = pil[0], pil[5]
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original)
            if max(image.size) > 1400:
                image.thumbnail((1400, 1400))
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
            payload = buffer.getvalue()
        part = types_mod.Part.from_bytes(data=payload, mime_type="image/jpeg")
        prompt = (question or "").strip() or (
            "Describe this image precisely. List visible objects, people, text, setting, "
            "actions and any likely context. Distinguish observations from guesses."
        )
        return core.llm_text(
            [part, prompt],
            system="You are a careful image analyst. Never invent text or details that are not visible.",
            smart=True, max_tokens=2200)
    except Exception as e:
        return f"Image analysis failed: {e}"


def image_operation(action: str = "info", path: str = "", destination: str = "",
                    width: int = 0, height: int = 0, crop: str = "", degrees: float = 0,
                    flip: str = "", brightness: float = 1.0, contrast: float = 1.0,
                    saturation: float = 1.0, sharpness: float = 1.0, blur: float = 0.0,
                    mode: str = "", text: str = "", question: str = "",
                    preset: str = "", confirmed: bool = False) -> str:
    """Understand or edit a real local photo/image.

    action:
      info      - dimensions, format and size
      analyze   - multimodal image description/answer (question is optional)
      open      - open the image in the default viewer
      resize    - width/height in pixels; 0 keeps the aspect ratio
      crop      - x,y,width,height in source pixels
      preset    - center-crop to 9:16, 1:1, 16:9, 4:3 or 3:2 before editing
      rotate    - rotate by degrees
      flip      - horizontal or vertical
      enhance   - brightness/contrast/saturation/sharpness multipliers
      grayscale - convert to black and white
      sepia     - warm vintage tone
      blur      - Gaussian blur radius (0..20)
      text      - draw text on the image

    Every edit creates a separate file; the original is never overwritten.
    An existing output file needs confirmation.
    """
    source = _image_source(path)
    if not source:
        return f"Image file not found or unsupported: {core.resolve_path(path)}"
    a = (action or "info").strip().lower()
    if a in ("open", "view"):
        return core.open_path(source)
    if a in ("info", "status"):
        try:
            pil = _pil()
            with pil[0].open(source) as img:
                return (f"Image: {source}\nDimensions: {img.width}x{img.height}\n"
                        f"Format: {img.format}\nMode: {img.mode}\n"
                        f"Size: {core.human_bytes(os.path.getsize(source))}")
        except Exception as e:
            return f"Could not read image: {e}"
    if a in ("analyze", "summarize", "describe", "explain", "understand"):
        return _analyze_image(source, question)
    pil = _pil()
    if pil is None:
        return "Pillow is not installed; install requirements.txt to edit images."
    Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps = pil
    output = _image_output(source, destination)
    if os.path.abspath(output).lower() == os.path.abspath(source).lower():
        return "Refusing to overwrite the source image. Choose a different destination."
    if os.path.exists(output):
        msg = core.guard("image_operation:overwrite", confirmed,
                         f"Overwrite existing edited image '{output}'.")
        if msg:
            return msg
    try:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).copy()
        notes = []
        ratios = {"9:16": 9 / 16, "1:1": 1.0, "16:9": 16 / 9,
                  "4:3": 4 / 3, "3:2": 3 / 2}
        target = ratios.get((preset or "").strip().lower())
        if target and not _crop_box(crop, image):
            old_width, old_height = image.size
            if old_width / old_height > target:
                new_width = max(1, int(old_height * target))
                crop = f"{(old_width - new_width) // 2},0,{new_width},{old_height}"
            else:
                new_height = max(1, int(old_width / target))
                crop = f"0,{(old_height - new_height) // 2},{old_width},{new_height}"
        box = _crop_box(crop, image)
        if box:
            image = image.crop(box)
            notes.append(f"cropped {box}")
        if width or height:
            old_width, old_height = image.size
            new_width = int(width) if width else int(old_width * height / old_height)
            new_height = int(height) if height else int(old_height * width / old_width)
            new_width, new_height = max(1, min(8000, new_width)), max(1, min(8000, new_height))
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            notes.append(f"resized {old_width}x{old_height} to {new_width}x{new_height}")
        if degrees:
            image = image.rotate(float(degrees), expand=True)
            notes.append(f"rotated {float(degrees):g} degrees")
        flip_value = (flip or "").strip().lower()
        if flip_value in ("horizontal", "h", "left-right", "mirror"):
            image = ImageOps.mirror(image)
            notes.append("flipped horizontally")
        elif flip_value in ("vertical", "v", "top-bottom"):
            image = ImageOps.flip(image)
            notes.append("flipped vertically")
        if a in ("grayscale", "grey", "black_and_white", "bw"):
            image = ImageOps.grayscale(image)
            notes.append("converted to grayscale")
        elif a in ("sepia",):
            image = ImageOps.colorize(ImageOps.grayscale(image), "#704214", "#fff0d0")
            notes.append("applied sepia")
        elif blur:
            image = image.filter(ImageFilter.GaussianBlur(radius=max(0.1, min(20.0, float(blur)))))
            notes.append(f"blurred radius {float(blur):g}")
        elif text.strip():
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("arial.ttf", max(12, min(200, int(max(image.size) / 18))))
            except Exception:
                font = ImageFont.load_default()
            padding = 12
            draw.text((padding, padding), mem_clean_safe(text)[:160], fill="white",
                      stroke_width=2, stroke_fill="black", font=font)
            notes.append("added text")
        else:
            changed = False
            image = ImageEnhance.Brightness(image).enhance(_factor(brightness))
            image = ImageEnhance.Contrast(image).enhance(_factor(contrast))
            image = ImageEnhance.Color(image).enhance(_factor(saturation))
            image = ImageEnhance.Sharpness(image).enhance(_factor(sharpness))
            changed = changed or any(abs(float(x) - 1.0) > 0.001 for x in
                                     (brightness, contrast, saturation, sharpness))
            if mode.strip().lower() in ("auto", "autocontrast"):
                image = ImageOps.autocontrast(image)
                notes.append("auto-enhanced")
            elif changed:
                notes.append("adjusted brightness/contrast/saturation/sharpness")
            else:
                notes.append("copied image without changes")
        _save_image(image, output)
    except Exception as e:
        return f"Image edit failed: {e}"
    core.audit("image_operation", f"{a} {source} {crop} {width}x{height}", output)
    return (", ".join(notes) + f". Edited image created: {output} "
            f"({core.human_bytes(os.path.getsize(output))}).")


def _factor(value) -> float:
    try:
        return max(0.0, min(5.0, float(value if value not in (None, "") else 1.0)))
    except Exception:
        return 1.0


def mem_clean_safe(text) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", str(text or "")).strip()
