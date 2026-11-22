"""Optional on-device speaker check for PC Jarvis.

Enrolment keeps a small MFCC vector in jarvis_data/voiceprint.json. Nothing is
uploaded and no account is needed. Verification is a convenience lock, not a
biometric guarantee; the setup dialog says so and the step is skippable.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

_DATA = Path(__file__).resolve().parents[1] / "jarvis_data" / "voiceprint.json"
_RATE = 16000
_NFFT = 512
_HOP = 160
_COEFS = 13
_FILTERS = 26


def _mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _hz(mel: float) -> float:
    return 700.0 * (np.power(10.0, mel / 2595.0) - 1.0)


def _bank() -> np.ndarray:
    bins = _NFFT // 2 + 1
    maximum = _mel(_RATE / 2.0)
    bank = np.zeros((_FILTERS, bins), dtype=np.float64)
    for m in range(_FILTERS):
        lo = int(np.floor(_hz(maximum * m / (_FILTERS + 1.0)) / (_RATE / 2.0) * (bins - 1)))
        hi = int(np.ceil(_hz(maximum * (m + 2.0) / (_FILTERS + 1.0)) / (_RATE / 2.0) * (bins - 1)))
        hi = max(hi, lo + 1)
        hi = min(hi, bins)
        for k in range(lo, hi):
            bank[m, k] = (k - lo + 1.0) / (hi - lo + 1.0)
    return bank


_BANK = _bank()


class VoiceID:
    def __init__(self, path: Path | str = _DATA):
        self.path = Path(path)
        self.vector: np.ndarray | None = None
        self.enabled = False
        self.skipped = False
        self.score = -1.0
        self.load()

    # ------------------------------------------------------------ persistence
    def load(self) -> None:
        self.vector = None
        self.enabled = False
        self.skipped = False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            v = np.asarray(raw.get("vector", []), dtype=np.float64)
            if v.shape == (_COEFS,):
                self.vector = v
                self.enabled = bool(raw.get("enabled", False))
            self.skipped = bool(raw.get("skipped", False))
        except Exception:
            pass

    def save(self) -> None:
        if self.vector is None and not self.skipped:
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled": bool(self.enabled),
            "skipped": bool(self.skipped),
        }
        if self.vector is not None:
            payload["vector"] = [float(x) for x in self.vector]
        try:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass

    def setup_done(self) -> bool:
        return self.vector is not None or self.skipped

    def mark_skipped(self) -> None:
        self.skipped = True
        self.save()

    def has_enrollment(self) -> bool:
        return self.vector is not None

    def set_enabled(self, on: bool) -> bool:
        if on and self.vector is None:
            return False
        self.enabled = bool(on)
        self.save()
        return self.enabled

    def clear(self) -> None:
        self.vector = None
        self.enabled = False
        self.score = -1.0
        self.save()

    # --------------------------------------------------------------- features
    @staticmethod
    def _samples(pcm, rate: int) -> np.ndarray | None:
        if pcm is None:
            return None
        if isinstance(pcm, (bytes, bytearray)):
            x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
        else:
            x = np.asarray(pcm, dtype=np.float64)
            if np.nanmax(np.abs(x)) > 1.5:
                x = x / 32768.0
        if x.size < 1600:
            return None
        if rate != _RATE:
            n = int(round(x.size * _RATE / float(rate)))
            x = np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x)
        return x

    @staticmethod
    def features(pcm, rate: int = _RATE) -> np.ndarray | None:
        x = VoiceID._samples(pcm, rate)
        if x is None:
            return None
        x = np.concatenate(([x[0]], x[1:] - 0.97 * x[:-1]))
        count = (x.size - _NFFT) // _HOP + 1
        if count < 2:
            return None
        window = np.hamming(_NFFT)
        acc = np.zeros(_COEFS, dtype=np.float64)
        used = 0
        for i in range(count):
            frame = x[i * _HOP:i * _HOP + _NFFT] * window
            energy = float(np.sum(frame * frame))
            if energy < 1e-7:
                continue
            power = np.abs(np.fft.rfft(frame, _NFFT)) ** 2
            log_e = np.log(np.maximum(_BANK @ power, 1e-10))
            dct = np.cos(np.pi * np.arange(1, _COEFS + 1)[:, None] *
                         (np.arange(_FILTERS) + 0.5)[None, :] / _FILTERS)
            acc += dct @ log_e
            used += 1
        if used == 0:
            return None
        v = acc / used
        norm = float(np.linalg.norm(v))
        if norm < 1e-12:
            return None
        return v / norm

    # --------------------------------------------------------------- identity
    def enroll(self, pcm, rate: int = _RATE) -> bool:
        v = self.features(pcm, rate)
        if v is None:
            return False
        if self.vector is not None:
            v = 0.5 * self.vector + 0.5 * v
            v = v / max(float(np.linalg.norm(v)), 1e-12)
        self.vector = v
        self.score = 1.0
        self.enabled = True
        self.save()
        return True

    def verify(self, pcm, rate: int = _RATE) -> bool:
        self.score = -1.0
        if self.vector is None:
            return True
        v = self.features(pcm, rate)
        if v is None:
            return False
        self.score = float(np.dot(self.vector, v))
        return self.score >= 0.80


voice_id = VoiceID()
