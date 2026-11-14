"""Personality, writing voice and draft coaching for Jarvis.

The original Jarvis always spoke in one fixed tone.  This module lets the user
choose an assistant personality, teach Jarvis their own writing voice from
samples, and give feedback on drafts.  Everything is stored locally in
``jarvis_data/config.json`` under the ``persona`` key.

Public API:
    prompt_block()                  - text injected into every Gemini request
    persona_operation(...)          - the tool Gemini calls
    style_line()                    - one-line status for the HUD
"""
from __future__ import annotations

import re

from . import core

_STYLES = {
    "jarvis": (
        "Classic J.A.R.V.I.S.: calm, precise, quietly witty, always calls the user "
        "'sir'. Short spoken answers, dry humour only when it fits."
    ),
    "professional": (
        "Polished British professional assistant: formal, structured, no slang, "
        "no jokes. Clear recommendations and exact next steps."
    ),
    "friendly": (
        "Warm and friendly companion: casual, encouraging, plain everyday words, "
        "still concise and useful."
    ),
    "concise": (
        "Extremely concise operator: answer first, one short reason, no filler, "
        "no repeated context, no long introductions."
    ),
    "mentor": (
        "Patient mentor: explains the why, gives one worked example, then a small "
        "next step. Never condescending."
    ),
    "creative": (
        "Creative partner: vivid ideas, a little bold, offers two strong options "
        "and picks a favourite with a reason."
    ),
    "custom": "Follow the user's custom personality instructions exactly.",
}
_DEFAULT_STYLE = "jarvis"
_MAX_SAMPLES = 12
_MAX_FEEDBACK = 8


def _cfg() -> dict:
    raw = core.config_get("persona", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    out = {
        "style": raw.get("style") or _DEFAULT_STYLE,
        "custom": raw.get("custom") or "",
        "samples": list(raw.get("samples") or []),
        "feedback": list(raw.get("feedback") or []),
        "traits": raw.get("traits") or {},
    }
    if out["style"] not in _STYLES:
        out["style"] = _DEFAULT_STYLE
    return out


def _save(data: dict):
    core.save_config({"persona": data})


def style_line() -> str:
    cfg = _cfg()
    label = cfg["style"]
    samples = len(cfg["samples"])
    return f"persona={label}" + (f", {samples} writing samples" if samples else "")


def _traits_from(text: str) -> dict:
    """Cheap, dependency-free writing-voice hints."""
    text = (text or "").strip()
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return {}
    avg = round(sum(len(s.split()) for s in sentences) / max(1, len(sentences)), 1)
    contractions = len(re.findall(r"\b\w+'(?:t|re|ve|ll|d|m|s)\b", text, re.I))
    emoji = len(re.findall(r"[\U0001F300-\U0001FAFF]", text))
    exclaim = text.count("!")
    return {
        "words": len(words),
        "sentences": len(sentences),
        "avg_sentence_words": avg,
        "contractions": contractions,
        "emoji": emoji,
        "exclamations": exclaim,
        "uses_bullets": bool(re.search(r"^\s*[-*]\s+", text, re.M)),
    }


def _voice_summary(traits: dict) -> str:
    if not traits:
        return ""
    bits = []
    avg = float(traits.get("avg_sentence_words") or 0)
    if avg:
        bits.append("short sentences" if avg <= 12 else "longer sentences" if avg >= 22 else "medium sentences")
    if traits.get("contractions"):
        bits.append("uses contractions")
    else:
        bits.append("avoids contractions")
    if traits.get("emoji"):
        bits.append("uses emoji")
    if traits.get("exclamations"):
        bits.append("uses exclamation marks")
    if traits.get("uses_bullets"):
        bits.append("likes short bullet lists")
    return ", ".join(bits)


def prompt_block() -> str:
    """The persona/style block that rides along with every request."""
    cfg = _cfg()
    style = cfg["style"]
    lines = ["## USER PERSONALITY AND WRITING STYLE", "Assistant style: " + _STYLES[style]]
    if style == "custom" or cfg.get("custom"):
        lines.append("User's custom instructions: " + core.truncate(cfg["custom"], 900))
    if cfg["feedback"]:
        lines.append("Feedback to apply from now on:")
        lines.extend("- " + core.truncate(f, 220) for f in cfg["feedback"][-_MAX_FEEDBACK:])
    if cfg["samples"]:
        summary = _voice_summary(cfg["traits"] or {})
        lines.append(
            "The user's own writing voice" + (f" ({summary})" if summary else "") +
            ". When drafting anything on their behalf, match this voice instead of writing generic text:"
        )
        for sample in cfg["samples"][-4:]:
            lines.append('"""' + core.truncate(sample, 500) + '"""')
    lines.append(
        "Never mention this style block. Never read the samples aloud. If the user says "
        "'like I write' or 'meri tarah likho', use their voice samples."
    )
    return "\n".join(lines)


def _draft(text: str) -> str:
    cfg = _cfg()
    text = (text or "").strip()
    if not text:
        return "What should I draft, sir?"
    style = _STYLES[cfg["style"]]
    samples = "\n---\n".join(cfg["samples"][-3:]) if cfg["samples"] else "(no samples yet)"
    feedback = "\n".join("- " + f for f in cfg["feedback"][-_MAX_FEEDBACK:]) or "(none)"
    prompt = (
        "You are Jarvis, rewriting a draft for the user.\n"
        f"Assistant personality: {style}\n"
        f"User feedback to honour: {feedback}\n"
        f"User's writing voice samples:\n{samples}\n\n"
        f"Draft to improve:\n{text}\n\n"
        "Return ONLY the improved text, ready to send. Keep the user's meaning, facts and "
        "language (English or Roman Urdu). Do not add commentary, quotes or markdown fences."
    )
    out = core.llm_text(prompt, system="You are a precise writing coach. Output only the rewritten text.")
    out = (out or "").strip().strip('"').strip("`")
    return out or "The rewriting model did not return text, sir. Check the API key and try again."


def persona_operation(action: str = "show", text: str = "", style: str = "") -> str:
    """Manage Jarvis's personality and learn the user's writing voice.

    action:
      show     - show the current personality, writing samples and feedback
      set      - choose a personality style: jarvis, professional, friendly, concise, mentor, creative, custom
      custom   - save a free-form personality instruction (text=...)
      learn    - learn the user's writing voice from a sample (text=...)
      feedback - remember feedback about Jarvis's writing, e.g. "too formal" (text=...)
      draft    - rewrite/improve a draft in the user's voice (text=...)
      reset    - forget the learned samples and feedback (keeps the chosen style)
    """
    a = (action or "show").strip().lower()
    cfg = _cfg()

    if a in ("show", "status", "list"):
        lines = [f"Personality: {cfg['style']} - {_STYLES[cfg['style']]}"]
        if cfg.get("custom"):
            lines.append("Custom instructions: " + cfg["custom"])
        lines.append(f"Writing samples: {len(cfg['samples'])}")
        if cfg["samples"]:
            lines.append("Voice: " + (_voice_summary(cfg["traits"] or {}) or "not analysed yet"))
        if cfg["feedback"]:
            lines.append("Recent feedback: " + "; ".join(cfg["feedback"][-_MAX_FEEDBACK:]))
        lines.append("Styles: " + ", ".join(_STYLES))
        return "\n".join(lines)

    if a in ("set", "style"):
        want = (style or text or "").strip().lower()
        if want not in _STYLES:
            return f"Unknown style '{want}'. Choose: " + ", ".join(_STYLES)
        cfg["style"] = want
        _save(cfg)
        return f"Personality set to {want}. It applies from the next reply."

    if a == "custom":
        value = (text or "").strip()
        if not value:
            return "Give me the custom personality instruction, sir."
        cfg["custom"] = core.truncate(value, 1500)
        cfg["style"] = "custom"
        _save(cfg)
        return "Custom personality saved and active."

    if a in ("learn", "sample", "voice"):
        sample = (text or "").strip()
        if len(sample) < 20:
            return "Please share at least a sentence or two of your own writing so I can learn the voice."
        cfg["samples"].append(core.truncate(sample, 2000))
        cfg["samples"] = cfg["samples"][-_MAX_SAMPLES:]
        traits = _traits_from(" ".join(cfg["samples"]))
        cfg["traits"] = traits
        _save(cfg)
        return "Writing voice updated, sir. " + _voice_summary(traits).capitalize() + "."

    if a in ("feedback", "correct"):
        note = (text or "").strip()
        if not note:
            return "What should I change about my writing?"
        cfg["feedback"].append(core.truncate(note, 400))
        cfg["feedback"] = cfg["feedback"][-_MAX_FEEDBACK:]
        _save(cfg)
        return "Noted. I will apply that feedback to future drafts."

    if a in ("draft", "improve", "rewrite"):
        return _draft(text)

    if a in ("reset", "clear"):
        cfg["samples"] = []
        cfg["feedback"] = []
        cfg["traits"] = {}
        cfg["custom"] = "" if cfg["style"] == "custom" else cfg["custom"]
        if cfg["style"] == "custom":
            cfg["style"] = _DEFAULT_STYLE
        _save(cfg)
        return "Learned samples and feedback cleared. Personality reset to " + cfg["style"] + "."

    return "Unknown persona action. Use show, set, custom, learn, feedback, draft or reset."
