#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compose Happy Bot's bundled WAVs. Run this script after editing a voice or score."""
from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path


SOUNDS = Path(__file__).resolve().parents[1] / "plasmoid/io.github.dragonswithin.happybot/contents/sounds"
RATE = 24000


@dataclass(frozen=True)
class Voice:
    root_hz: float
    # Each partial has a frequency multiple, starting level, and decay per second.
    partials: tuple[tuple[float, float, float], ...]
    bend: float = 0.0  # semitones above or below the note at its onset
    attack: float = .009
    flutter_hz: float = 0.0
    flutter_depth: float = 0.0
    echo_ms: int = 0
    echo_level: float = 0.0


VOICES = {
    # Pip's original greeting swoops gently between two round electronic vowels.
    "pip": Voice(587, ((1, 1, 3), (2, .24, 10), (3, .13, 13)), bend=-3.4),
    # A short hammer strike on Rivet's metal body.
    "rivet": Voice(349, ((1, .87, 6), (2.38, .48, 19), (3.79, .41, 30), (5.43, .21, 43)), attack=.004),
    # Two slowly beating voices overlap like Orbit's rings.
    "orbit": Voice(440, ((1, 1, 2), (1.013, .61, 3), (2, .12, 7)), bend=-1.4,
                   attack=.018, echo_ms=48, echo_level=.19),
    # Watt's beacon flickers with a quick electric buzz.
    "watt": Voice(494, ((1, 1, 4), (2, .39, 7), (4, .30, 17), (6, .14, 28)), bend=2.1,
                  attack=.005, flutter_hz=38, flutter_depth=.31),
    # Pixel's pulse wave is built from soft, band-limited odd harmonics.
    "pixel": Voice(523, ((1, 1, 1), (3, .30, 2), (5, .16, 4), (7, .08, 5)), attack=.004),
    # Sprig's airy reed rises into each note, with a little breath vibrato.
    "sprig": Voice(659, ((1, 1, 1.6), (2, .07, 3), (3, .26, 4)), bend=-1.9,
                   attack=.022, flutter_hz=6, flutter_depth=.13),
    # A low, softly detuned tube hum for Nixie.
    "nixie": Voice(294, ((1, 1, 2), (1.007, .18, 2), (2, .54, 6), (3, .22, 9)), bend=-.35,
                   attack=.014, flutter_hz=14, flutter_depth=.08),
    # Sprocket's escapement gives each short metallic note a ratcheting edge.
    "sprocket": Voice(392, ((1, 1, 5), (2.95, .54, 14), (4.1, .25, 24)), attack=.004,
                      flutter_hz=23, flutter_depth=.56, echo_ms=32, echo_level=.26),
    # Sonar sends out a clear ping followed by a soft reflection.
    "sonar": Voice(698, ((1, 1, 9), (2, .07, 16)), attack=.006, echo_ms=76, echo_level=.33),
    # The descending pitch and hollow overtones give Dotty a springy bubble pop.
    "dotty": Voice(415, ((1, 1, 5), (2, .32, 9), (3, .09, 15)), bend=6.5, attack=.007),
}


@dataclass(frozen=True)
class Score:
    # Event RMS target, then notes as (start ms, duration ms, semitones from voice's root, relative level).
    rms: float
    notes: tuple[tuple[int, int, int, float], ...]


SCORES = {
    "open": Score(.106, ((0, 88, 0, .78), (112, 142, 5, 1))),
    "error": Score(.117, ((0, 125, 2, 1), (156, 89, 1, .76), (257, 190, -4, .86))),
    "complete": Score(.118, ((0, 84, 0, .70), (94, 72, 4, .80), (171, 87, 7, .86), (269, 205, 12, 1))),
    "alarm": Score(.157, ((0, 122, 4, 1), (151, 143, 11, .98), (324, 112, 4, .91),
                          (619, 122, 4, 1), (770, 143, 11, .98), (943, 212, 4, .91))),
    "reminder": Score(.111, ((0, 156, 7, .88), (180, 285, 0, 1), (201, 265, 4, .30))),
    "attention": Score(.107, ((0, 84, 0, .78), (117, 85, 3, .8), (247, 190, 9, 1))),
    "mic_ready": Score(.081, ((0, 38, 0, .78), (42, 62, 7, 1))),
    "mic_done": Score(.078, ((0, 45, 7, .84), (54, 76, 0, .88))),
    "background": Score(.094, ((0, 108, -5, .70), (142, 102, 2, .77),
                               (273, 230, 0, 1), (283, 216, 4, .48))),
    "nudge": Score(.075, ((0, 61, 2, .63), (176, 108, 5, .94))),
}


# Wand uses short, fixed-pitch desktop cues with a soft bell attack.
WAND_VOICE = Voice(392, ((1, 1, 6), (2, .14, 14), (3.98, .08, 27)), attack=.012)
WAND_SCORES = {
    "open": Score(.066, ((0, 210, 7, 1),)),
    "error": Score(.095, ((0, 112, 0, .9), (134, 190, -3, 1))),
    "complete": Score(.081, ((0, 138, 4, .82), (150, 248, 9, 1))),
    "alarm": Score(.14, ((0, 170, 5, 1), (233, 170, 5, .94), (610, 245, 5, 1))),
    "reminder": Score(.08, ((0, 175, 2, 1), (205, 224, 2, .65))),
    "attention": Score(.085, ((0, 124, 9, 1), (160, 173, 5, .82))),
    "mic_ready": Score(.058, ((0, 85, 12, 1),)),
    "mic_done": Score(.057, ((0, 105, 2, 1),)),
    "background": Score(.069, ((0, 215, 0, 1), (22, 190, 7, .36))),
    "nudge": Score(.06, ((0, 158, 4, 1),)),
}


def render_note(voice: Voice, pitch: int, length: int) -> list[float]:
    hz = voice.root_hz * 2 ** (pitch / 12)
    duration = length / RATE
    attack = min(voice.attack, duration * .30)
    release = min(.055, duration * .36)
    phase = 0.0
    output = []
    for i in range(length):
        t = i / RATE
        # Integrate frequency so a pitch bend never jumps between oscillator phases.
        phase += math.tau * hz * 2 ** (voice.bend * math.exp(-t / .033) / 12) / RATE
        tone = sum(level * math.exp(-decay * t) * math.sin(multiple * phase)
                   for multiple, level, decay in voice.partials)
        flutter = 1 - voice.flutter_depth * (.5 - .5 * math.cos(math.tau * voice.flutter_hz * t))
        fade = min(1.0, t / attack, (length - 1 - i) / (RATE * release))
        envelope = fade * fade * (3 - 2 * fade)
        output.append(tone * envelope * flutter)
    return output


def write_cue(path: Path, voice: Voice, event: str, score: Score) -> None:
    length_ms = max(start + duration for start, duration, _, _ in score.notes)
    samples = [0.0] * (length_ms * RATE // 1000)
    for start, duration, pitch, level in score.notes:
        offset = start * RATE // 1000
        note = render_note(voice, pitch, duration * RATE // 1000)
        for i, sample in enumerate(note, start=offset):
            samples[i] += sample * level
    if voice.echo_ms:
        # The microphone-ready sound must finish before recording starts.
        delay_ms = min(voice.echo_ms, 32) if event == "mic_ready" else voice.echo_ms
        delay = delay_ms * RATE // 1000
        dry = samples.copy()
        samples.extend([0.0] * delay)
        for i, sample in enumerate(dry, start=delay):
            samples[i] += sample * voice.echo_level

    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    gain = min(score.rms / rms, .53 / max(map(abs, samples)))
    integers = [round(x * gain * 32767) for x in samples]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(struct.pack(f"<{len(integers)}h", *integers))


if __name__ == "__main__":
    for name, voice in VOICES.items():
        for event, score in SCORES.items():
            write_cue(SOUNDS / name / f"{event}.wav", voice, event, score)
    for event, score in WAND_SCORES.items():
        write_cue(SOUNDS / "wand" / f"{event}.wav", WAND_VOICE, event, score)
