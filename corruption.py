"""Visual and text corruption effects for ENTROPY.

Intensity contract:
  0.0  clean
  0.3  occasional artifacts
  0.7  heavily degraded
  1.0  collapse

Corruption is degradation, not attack. Effects favour replacement, fade,
and offset over inversion, flashing, or alarm.
"""
from __future__ import annotations

import random
from typing import Iterable

from rich.text import Text


GLYPHS = ["█", "▓", "▒", "░", "▚", "▞", "▙", "▜", "▖", "▗", "·", "."]
ZALGO_UP = ["̍", "̎", "̄", "̅", "̿", "̑"]
ZALGO_DOWN = ["̖", "̗", "̘", "̙", "̜", "̝"]


def corrupt_text(text: str, intensity: float, rng: random.Random | None = None) -> str:
    """Return a possibly degraded version of `text`. Intent: gentle drift, not noise."""
    if intensity < 0.08 or not text:
        return text
    rng = rng or random.Random()
    out_chars: list[str] = []
    # Per-char replacement probability. Cap at 12% so text remains legible.
    replace_p = min(0.12, intensity * 0.18)
    zalgo_p = max(0.0, intensity - 0.85) * 0.15

    for ch in text:
        if ch in (" ", "\n", "\t"):
            out_chars.append(ch)
            continue
        if rng.random() < replace_p:
            out_chars.append(rng.choice(GLYPHS))
            continue
        out_chars.append(ch)
        if zalgo_p > 0 and rng.random() < zalgo_p:
            if rng.random() < 0.5:
                out_chars.append(rng.choice(ZALGO_UP))
            else:
                out_chars.append(rng.choice(ZALGO_DOWN))
    return "".join(out_chars)


def glitch_line(line: str, intensity: float, rng: random.Random | None = None) -> list[str]:
    """Return one-or-more lines: a single line may be duplicated, offset, or split."""
    rng = rng or random.Random()
    if intensity <= 0.1 or not line:
        return [line]

    out = [line]
    if rng.random() < intensity * 0.25:
        # Duplicate with slight offset.
        offset = " " * rng.randint(1, max(2, int(intensity * 6)))
        out.append(offset + corrupt_text(line, intensity * 0.6, rng))
    if rng.random() < max(0.0, intensity - 0.5) * 0.4:
        # Split & re-emit a fragment.
        if len(line) > 8:
            cut = rng.randint(2, len(line) - 2)
            out.append(line[cut:])
    return out


def corrupt_block(text: str, intensity: float, rng: random.Random | None = None) -> str:
    """Apply corruption + glitching across a multi-line block."""
    if intensity <= 0.0:
        return text
    rng = rng or random.Random()
    lines = text.split("\n")
    result: list[str] = []
    for ln in lines:
        ct = corrupt_text(ln, intensity, rng)
        result.extend(glitch_line(ct, intensity, rng))
        # Occasional scanline drop.
        if intensity > 0.4 and rng.random() < (intensity - 0.3) * 0.15:
            result.append("")
    return "\n".join(result)


# --- styled rich.Text variants ----------------------------------------------

def style_for(intensity: float) -> str:
    """Pick the dominant colour for output, biased by corruption."""
    if intensity < 0.3:
        return "#00ff41"
    if intensity < 0.6:
        return "#3fdc6c"
    if intensity < 0.85:
        return "#d4a017"
    return "#a30000"


def render_corrupted(text: str, intensity: float, rng: random.Random | None = None) -> Text:
    """Return a rich.Text styled appropriately for current corruption level."""
    rng = rng or random.Random()
    style = style_for(intensity)
    block = corrupt_block(text, intensity, rng)
    t = Text(block, style=style)
    return t


def scanline_padding(intensity: float, width: int, rng: random.Random | None = None) -> list[str]:
    """Return a list of horizontal divider strings used to inject scanline-like rows."""
    if intensity < 0.5:
        return []
    rng = rng or random.Random()
    rows = max(0, int((intensity - 0.4) * 4))
    pad = []
    for _ in range(rows):
        char = rng.choice([" ", "·", "░", " ", " "])
        pad.append(char * max(1, width))
    return pad
