#!/usr/bin/env python3
"""Synthesize PicSong's original soundboard clips.

No recorded audio and no downloaded samples. From anywhere:

    python3 tools/generate_clips.py

Writes sounds/*.wav and sounds/manifest.json. Clip order in the manifest
is part of the picture-to-sound mapping.
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sounds"

AH = ((800, 5.0, 1.0), (1200, 5.0, 0.55), (2600, 4.0, 0.22))
OO = ((420, 5.0, 1.0), (780, 5.0, 0.38), (2400, 3.5, 0.1))
EE = ((340, 5.0, 0.4), (2200, 7.0, 1.0), (3100, 5.0, 0.32))
EH = ((560, 5.0, 1.0), (1750, 6.0, 0.62), (2550, 4.0, 0.22))
OH = ((520, 5.0, 1.0), (980, 5.0, 0.48), (2500, 4.0, 0.16))
NASAL = ((480, 5.0, 0.5), (1400, 7.0, 1.0), (2450, 4.0, 0.2))
QUACK = ((1080, 5.5, 0.7), (1680, 6.5, 1.0), (2550, 4.0, 0.28))


def rng_for(name: str) -> np.random.Generator:
    seed = 2166136261
    for ch in str(name):
        seed ^= ord(ch)
        seed = (seed * 16777619) & 0xFFFFFFFF
    return np.random.default_rng(seed)


def timebase(dur: float) -> np.ndarray:
    n = max(1, int(round(float(dur) * SR)))
    return np.arange(n, dtype=np.float64) / SR


def hold(t: np.ndarray, freq: float) -> np.ndarray:
    return np.full(len(t), float(freq), dtype=np.float64)


def glide_exp(t: np.ndarray, f0: float, f1: float) -> np.ndarray:
    if len(t) == 1 or t[-1] <= 0:
        return np.full(len(t), float(f0), dtype=np.float64)
    u = t / t[-1]
    if f0 <= 0 or f1 <= 0:
        return f0 + (f1 - f0) * u
    return float(f0) * (float(f1) / float(f0)) ** u


def gap(dur: float) -> np.ndarray:
    return np.zeros(max(0, int(round(dur * SR))), dtype=np.float64)


def join(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate([np.asarray(p, dtype=np.float64).reshape(-1) for p in parts])


def noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float64)


def unit(x: np.ndarray) -> np.ndarray:
    x = np.nan_to_num(np.asarray(x, dtype=np.float64))
    if x.size == 0:
        return x
    peak = float(np.max(np.abs(x)))
    if peak < 1e-8:
        return np.zeros_like(x)
    return x / peak


def rasp(x: np.ndarray, drive: float = 2.0) -> np.ndarray:
    return np.tanh(float(drive) * np.asarray(x, dtype=np.float64))


def saw(freq: np.ndarray, partials: int = 12) -> np.ndarray:
    f = np.asarray(freq, dtype=np.float64)
    peak = float(np.max(f)) if f.size else 0.0
    kmax = int(partials)
    if peak > 0:
        kmax = max(1, min(kmax, int((SR * 0.45) / peak)))
    phase = np.cumsum(f) / SR
    y = np.zeros_like(phase)
    twopi = 2.0 * math.pi
    for k in range(1, kmax + 1):
        y += np.sin(twopi * phase * k) / k
    return y


def square(freq: np.ndarray, partials: int = 8) -> np.ndarray:
    f = np.asarray(freq, dtype=np.float64)
    peak = float(np.max(f)) if f.size else 0.0
    phase = np.cumsum(f) / SR
    y = np.zeros_like(phase)
    twopi = 2.0 * math.pi
    k = 1
    made = 0
    while made < partials and (peak <= 0 or k * peak < SR * 0.45):
        y += np.sin(twopi * phase * k) / k
        k += 2
        made += 1
    return y


def tone(freq: np.ndarray) -> np.ndarray:
    f = np.asarray(freq, dtype=np.float64)
    return np.sin(2.0 * math.pi * np.cumsum(f) / SR)


def svf(x: np.ndarray, cutoff, q: float, mode: str = "band") -> np.ndarray:
    """Trapezoidal state-variable filter. cutoff may be a scalar or an array."""
    x = np.asarray(x, dtype=np.float64)
    n = int(x.shape[0])
    y = np.empty(n, dtype=np.float64)
    ic1 = 0.0
    ic2 = 0.0
    nyquist = SR * 0.45

    def coeffs(fc: float, qi: float):
        if fc < 30.0:
            fc = 30.0
        if fc > nyquist:
            fc = nyquist
        if qi < 0.5:
            qi = 0.5
        g = math.tan(math.pi * fc / SR)
        k = 1.0 / qi
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        return k, a1, a2, a3

    def step(v0: float, k: float, a1: float, a2: float, a3: float):
        nonlocal ic1, ic2
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        if mode == "low":
            return v2
        if mode == "high":
            return v0 - k * v1 - v2
        return v1

    if np.isscalar(cutoff):
        k, a1, a2, a3 = coeffs(float(cutoff), float(q))
        for i in range(n):
            y[i] = step(float(x[i]), k, a1, a2, a3)
        return y

    curve = np.asarray(cutoff, dtype=np.float64)
    if curve.shape[0] != n:
        raise ValueError("cutoff length does not match audio")
    qi = float(q)
    for i in range(n):
        k, a1, a2, a3 = coeffs(float(curve[i]), qi)
        y[i] = step(float(x[i]), k, a1, a2, a3)
    return y


def formant(src: np.ndarray, peaks) -> np.ndarray:
    y = np.zeros_like(src, dtype=np.float64)
    for freq, q, gain in peaks:
        y += float(gain) * unit(svf(src, freq, q, "band"))
    return y


def env_hump(t: np.ndarray, power: float = 1.0) -> np.ndarray:
    if len(t) == 0 or t[-1] <= 0:
        return np.ones_like(t)
    u = np.clip(t / t[-1], 0.0, 1.0)
    return np.sin(math.pi * u) ** power


def env_exp(t: np.ndarray, attack: float, tau: float) -> np.ndarray:
    env = np.exp(-t / tau)
    a = min(len(t) // 3, max(1, int(round(attack * SR))))
    if a > 1:
        env = env.copy()
        env[:a] *= np.linspace(0.0, 1.0, a, endpoint=False)
    return env


def edge_env(t: np.ndarray, attack: float, release: float) -> np.ndarray:
    n = len(t)
    env = np.ones(n, dtype=np.float64)
    a = min(n // 3, max(1, int(round(attack * SR))))
    r = min(n // 3, max(1, int(round(release * SR))))
    if a > 1:
        env[:a] = np.linspace(0.0, 1.0, a, endpoint=False)
    if r > 1:
        env[-r:] *= np.linspace(1.0, 0.0, r)
    return env


def dc_block(x: np.ndarray, r: float = 0.995) -> np.ndarray:
    y = np.empty_like(x)
    prev_x = 0.0
    prev_y = 0.0
    for i in range(x.shape[0]):
        xn = float(x[i])
        prev_y = xn - prev_x + r * prev_y
        prev_x = xn
        y[i] = prev_y
    return y


def apply_fade(x: np.ndarray, fin: float = 0.004, fout: float = 0.012) -> np.ndarray:
    n = len(x)
    y = np.array(x, dtype=np.float64, copy=True)
    fi = min(n // 3, max(1, int(round(fin * SR))))
    fo = min(n // 3, max(1, int(round(fout * SR))))
    if fi > 1:
        y[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False)
    else:
        y[0] = 0.0
    if fo > 1:
        y[-fo:] *= np.linspace(1.0, 0.0, fo)
    else:
        y[-1] = 0.0
    return y


def finish(x: np.ndarray) -> np.ndarray:
    y = np.nan_to_num(np.asarray(x, dtype=np.float64))
    if not np.all(np.isfinite(y)):
        raise RuntimeError("non-finite audio")
    y = dc_block(y)
    y = apply_fade(y)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak < 1e-6:
        raise RuntimeError("silent clip")
    return y * (0.9 / peak)


def pluck(freq: float, dur: float, half_life: float, brightness: float, seed: str) -> np.ndarray:
    n = int(round(dur * SR))
    period = max(2, int(round(SR / float(freq))))
    rng = rng_for(seed)
    buf = rng.uniform(-1.0, 1.0, period).astype(np.float64)
    stretch = 0.5 ** (1.0 / (float(freq) * float(half_life)))
    bright = float(np.clip(brightness, 0.0, 0.85))
    out = np.empty(n, dtype=np.float64)
    idx = 0
    prev = float(buf[-1])
    for i in range(n):
        sample = float(buf[idx])
        out[i] = sample
        avg = 0.5 * (sample + prev)
        nxt = (1.0 - bright) * avg + bright * sample
        prev = sample
        buf[idx] = stretch * nxt
        idx += 1
        if idx == period:
            idx = 0
    return out


def brass_wave(freq, t, partials, attack, release, cutoff, seed) -> np.ndarray:
    src = saw(freq, partials)
    y = unit(svf(src, cutoff, 0.707, "low"))
    chiff = unit(svf(noise(len(t), rng_for(seed)), 2200, 0.8, "band"))
    chiff *= np.exp(-t / 0.012)
    return y * edge_env(t, attack, release) + 0.28 * chiff


def quack_once(dur: float, f0: float, f1: float) -> np.ndarray:
    t = timebase(dur)
    f = glide_exp(t, f0, f1)
    src = rasp(unit(saw(f, 12)), 2.5)
    y = unit(formant(src, QUACK))
    env = env_hump(t, 0.4) * (1.0 - np.exp(-t / 0.004))
    return y * env


def quack() -> np.ndarray:
    return quack_once(0.18, 880, 410)


def double_quack() -> np.ndarray:
    return join(quack_once(0.15, 820, 450), gap(0.055), quack_once(0.17, 760, 380))


def moo() -> np.ndarray:
    t = timebase(0.86)
    f = glide_exp(t, 162, 108)
    f = f + (5.5 + 6.0 * (t / t[-1])) * np.sin(2 * math.pi * 5.15 * t)
    src = saw(f, 12)
    body = unit(svf(src, 340, 0.707, "low"))
    vow = unit(formant(src, OO) * 0.65 + formant(src, OH) * 0.35)
    return (0.58 * body + 0.42 * vow) * edge_env(t, 0.09, 0.16)


def meow() -> np.ndarray:
    t = timebase(0.5)
    u = np.clip(t / t[-1], 0.0, 1.0)
    arch = np.sin(math.pi * np.clip(u ** 0.55, 0.0, 1.0))
    f = 430 * (1 - 0.48 * u) + 380 * arch
    pure = unit(tone(f))
    src = rasp(unit(saw(f, 6)), 1.45)
    vow = (
        unit(formant(src, EH)) * np.clip(1.15 - u * 1.5, 0.0, 1.0)
        + unit(formant(src, EE)) * (np.sin(math.pi * u) ** 1.15)
        + unit(formant(src, OO)) * np.clip((u - 0.45) / 0.55, 0.0, 1.0)
    )
    return (0.64 * pure + 0.36 * unit(vow)) * env_hump(t, 0.5)


def bark_hit(dur: float, thump: float, seed: str, brightness: float) -> np.ndarray:
    t = timebase(dur)
    rng = rng_for(seed)
    puff = unit(svf(noise(len(t), rng), brightness, 1.3, "band"))
    puff += 0.55 * unit(svf(noise(len(t), rng), brightness * 1.7, 0.8, "band"))
    body = np.sin(2 * math.pi * thump * t) * np.exp(-t / 0.012)
    return unit(puff) * np.exp(-t / 0.02) + 0.85 * unit(body)


def bark() -> np.ndarray:
    return join(
        bark_hit(0.09, 125, "bark-a", 850),
        gap(0.1),
        bark_hit(0.07, 145, "bark-b", 980) * 0.75,
    )


def yip() -> np.ndarray:
    hits = []
    for i, freq in enumerate((480, 540, 430)):
        t = timebase(0.042)
        puff = unit(svf(noise(len(t), rng_for(f"yip-{i}")), 1700, 1.2, "band"))
        hit = puff * np.exp(-t / 0.009) + 0.35 * np.sin(2 * math.pi * freq * t) * np.exp(-t / 0.008)
        hits.append(hit)
        if i < 2:
            hits.append(gap(0.05))
    return join(*hits)


def ribbit() -> np.ndarray:
    def syl(f0, f1, dur, seed, wobble):
        t = timebase(dur)
        f = glide_exp(t, f0, f1)
        src = square(f, 6)
        y = unit(formant(src, AH))
        grit = unit(svf(noise(len(t), rng_for(seed)), 1500, 0.8, "band"))
        trem = 0.62 + 0.38 * np.sin(2 * math.pi * wobble * t)
        return (0.82 * y + 0.18 * grit) * trem * env_hump(t, 0.7)

    return join(syl(250, 170, 0.09, "rib", 42), gap(0.045), syl(145, 88, 0.18, "bit", 28))


def chirp() -> np.ndarray:
    bits = []
    specs = ((2300, 3900, 0.048), (2550, 4300, 0.042), (2200, 3600, 0.04), (2700, 4600, 0.05))
    for i, (f0, f1, dur) in enumerate(specs):
        t = timebase(dur)
        f = glide_exp(t, f0, f1)
        y = unit(tone(f)) + 0.22 * unit(tone(f * 2.0))
        bits.append(y * env_hump(t, 1.0))
        if i != len(specs) - 1:
            bits.append(gap(0.026))
    return join(*bits)


def baa() -> np.ndarray:
    t = timebase(0.72)
    f = glide_exp(t, 215, 168)
    f = f + 4.0 * np.sin(2 * math.pi * 4.8 * t)
    src = saw(f, 10)
    y = unit(formant(src, NASAL))
    trem = 0.22 + 0.78 * (0.5 + 0.5 * np.sin(2 * math.pi * 7.6 * t)) ** 1.35
    return y * trem * edge_env(t, 0.03, 0.08)


def oink() -> np.ndarray:
    t = timebase(0.3)
    u = np.clip(t / t[-1], 0.0, 1.0)
    f = np.interp(u, [0.0, 0.22, 0.55, 1.0], [390, 360, 175, 330])
    src = rasp(unit(saw(f, 8)), 1.7)
    grit = unit(svf(noise(len(t), rng_for("oink")), 900, 1.0, "band"))
    y = unit(formant(src, NASAL)) * 0.84 + grit * 0.16
    return y * env_hump(t, 0.55)


def cluck() -> np.ndarray:
    bits = []
    for i, f0 in enumerate((920, 760, 840)):
        t = timebase(0.05)
        f = glide_exp(t, f0, f0 * 0.42)
        src = rasp(unit(saw(f, 6)), 1.8)
        band = unit(svf(src, 1700, 1.4, "band"))
        tick = unit(svf(noise(len(t), rng_for(f"cluck-{i}")), 1400, 0.8, "band"))
        bits.append((0.75 * band + 0.25 * tick) * np.exp(-t / 0.011))
        if i < 2:
            bits.append(gap(0.068))
    return join(*bits)


def hoot_tone(freq: float, dur: float) -> np.ndarray:
    t = timebase(dur)
    y = unit(tone(hold(t, freq))) + 0.18 * unit(tone(hold(t, freq * 2)))
    breath = unit(svf(noise(len(t), rng_for(f"hoot-{freq}")), 650, 0.707, "low"))
    return (0.92 * y + 0.08 * breath) * (env_hump(t, 1.45))


def hoot() -> np.ndarray:
    return join(hoot_tone(425, 0.24), gap(0.09), hoot_tone(338, 0.32))


def neigh() -> np.ndarray:
    t = timebase(0.78)
    u = np.clip(t / t[-1], 0.0, 1.0)
    rising = 360 * (650 / 360) ** np.clip(u / 0.62, 0.0, 1.0)
    falling = 650 * (470 / 650) ** np.clip((u - 0.62) / 0.38, 0.0, 1.0)
    f = np.where(u < 0.62, rising, falling)
    f = f + (32 * np.clip(u / 0.18, 0.0, 1.0)) * np.sin(2 * math.pi * 22 * t)
    src = saw(f, 8)
    return unit(formant(src, EE)) * env_hump(t, 0.55)


def hiss() -> np.ndarray:
    t = timebase(0.62)
    center = 4600 + 700 * np.sin(2 * math.pi * 2.5 * t)
    y = unit(svf(noise(len(t), rng_for("hiss")), center, 0.9, "high"))
    trem = 0.82 + 0.18 * np.sin(2 * math.pi * 13 * t)
    return y * env_hump(t, 0.75) * trem


def buzz() -> np.ndarray:
    t = timebase(0.55)
    src = saw(hold(t, 198), 12)
    y = unit(svf(src, 1500, 0.707, "low"))
    wing = 0.2 + 0.8 * (0.5 + 0.5 * np.sin(2 * math.pi * 33 * t)) ** 2
    return y * wing * env_hump(t, 0.8)


def goose() -> np.ndarray:
    def honk(f0, dur):
        t = timebase(dur)
        f = glide_exp(t, f0, f0 * 0.8)
        src = rasp(unit(square(f, 8)), 1.6)
        return unit(formant(src, NASAL)) * env_hump(t, 0.45)

    return join(honk(445, 0.15), gap(0.05), honk(400, 0.2))


def howl() -> np.ndarray:
    t = timebase(0.88)
    u = np.clip(t / t[-1], 0.0, 1.0)
    f = 290 * (690 / 290) ** u
    f = f + (14 * np.clip((u - 0.4) / 0.25, 0.0, 1.0)) * np.sin(2 * math.pi * 5.4 * t)
    y = unit(tone(f)) + 0.28 * unit(tone(f * 2))
    rasp_bed = unit(svf(noise(len(t), rng_for("howl")), 1200, 0.707, "band"))
    return (0.94 * y + 0.06 * rasp_bed) * env_hump(t, 1.05)


def heehaw() -> np.ndarray:
    hee_t = timebase(0.32)
    f = hold(hee_t, 630) + 26 * np.sin(2 * math.pi * 15 * hee_t)
    hee = unit(formant(saw(f, 8), EE)) * env_hump(hee_t, 0.55)
    haw_t = timebase(0.4)
    fh = glide_exp(haw_t, 255, 175)
    haw = unit(formant(saw(fh, 8), AH)) * env_hump(haw_t, 0.7)
    return join(hee, gap(0.04), haw)


def trumpet(f0: float, dur: float, seed: str, cutoff: float) -> np.ndarray:
    t = timebase(dur)
    f = hold(t, f0) * (1.0 - 0.07 * np.exp(-t / 0.028))
    return brass_wave(f, t, 12, 0.01, 0.055, cutoff, seed)


def tuba_blurt() -> np.ndarray:
    t = timebase(0.42)
    f = glide_exp(t, 92, 78)
    return brass_wave(f, t, 6, 0.035, 0.12, 280, "tuba-blurt")


def trombone_slide() -> np.ndarray:
    t = timebase(0.46)
    f = glide_exp(t, 148, 268)
    return brass_wave(f, t, 10, 0.02, 0.08, 1500, "trombone-slide")


def horn_soft() -> np.ndarray:
    t = timebase(0.5)
    f = hold(t, 220) + 3.2 * np.sin(2 * math.pi * 4.2 * t)
    pure = unit(tone(f))
    buzz = unit(svf(saw(f, 4), 1000, 0.707, "low"))
    return (0.74 * pure + 0.26 * buzz) * env_hump(t, 1.2)


def kazoo() -> np.ndarray:
    t = timebase(0.32)
    f = hold(t, 470) * (1 + 0.012 * np.sin(2 * math.pi * 5.5 * t))
    buzz = rasp(unit(tone(f)), 4.2)
    y = 0.72 * unit(formant(buzz, AH)) + 0.28 * unit(buzz)
    return y * env_hump(t, 0.55)


def vuvuzela() -> np.ndarray:
    t = timebase(0.48)
    src = rasp(unit(saw(hold(t, 247), 16)), 2.6)
    y = unit(svf(src, 1550, 0.707, "low"))
    return y * edge_env(t, 0.015, 0.035)


def wah_mute() -> np.ndarray:
    t = timebase(0.34)
    f = hold(t, 368) * (1.0 - 0.05 * np.exp(-t / 0.03))
    src = saw(f, 10)
    center = 620 + 1550 * np.sin(math.pi * (t / t[-1])) ** 1.15
    y = unit(svf(src, center, 5.5, "band"))
    body = unit(svf(src, 900, 0.707, "low"))
    return (0.78 * y + 0.22 * body) * env_hump(t, 0.65)


def sax_honk() -> np.ndarray:
    t = timebase(0.22)
    f = hold(t, 262) * (1.0 - 0.05 * np.exp(-t / 0.02))
    f = f * (1.0 + 0.02 * np.sin(2 * math.pi * 23 * t))
    src = rasp(unit(saw(f, 10)), 1.7)
    breath = unit(svf(noise(len(t), rng_for("sax-honk")), 1700, 0.8, "band"))
    y = 0.8 * unit(formant(src, AH)) + 0.2 * breath
    return y * env_exp(t, 0.006, 0.07)


def harmonica() -> np.ndarray:
    t = timebase(0.36)
    a = unit(saw(hold(t, 388), 8))
    b = unit(saw(hold(t, 388 * 1.009), 8))
    reeds = unit(a + b)
    breath = unit(svf(noise(len(t), rng_for("harmonica")), 1500, 0.7, "band"))
    y = 0.84 * unit(formant(reeds, EH)) + 0.16 * breath
    return y * env_hump(t, 0.65)


def piano(f0: float, dur: float, seed: str) -> np.ndarray:
    t = timebase(dur)
    y = np.zeros(len(t), dtype=np.float64)
    stiffness = 0.0028
    for k in range(1, 7):
        fk = f0 * k * math.sqrt(1.0 + stiffness * k * k)
        if fk >= SR * 0.45:
            break
        y += (1.0 / k ** 1.35) * np.sin(2 * math.pi * fk * t) * np.exp(-t / (0.25 / k))
    tick = noise(len(t), rng_for(seed)) * np.exp(-t / 0.004) * 0.4
    return y + tick


def xylophone() -> np.ndarray:
    t = timebase(0.28)
    f0 = 746
    y = np.sin(2 * math.pi * f0 * t) * np.exp(-t / 0.09)
    y += 0.4 * np.sin(2 * math.pi * f0 * 3.07 * t) * np.exp(-t / 0.035)
    click = svf(noise(len(t), rng_for("xylophone")), 2200, 0.707, "high") * np.exp(-t / 0.004)
    return y + 0.3 * click


def glock() -> np.ndarray:
    t = timebase(0.7)
    f0 = 1488
    y = np.zeros(len(t), dtype=np.float64)
    for amp, ratio, tau in ((1.0, 1.0, 0.34), (0.55, 2.76, 0.2), (0.32, 5.4, 0.11), (0.16, 8.9, 0.06)):
        y += amp * np.sin(2 * math.pi * f0 * ratio * t) * np.exp(-t / tau)
    return y


def kalimba() -> np.ndarray:
    t = timebase(0.6)
    f0 = 214
    y = np.sin(2 * math.pi * f0 * t) * np.exp(-t / 0.26)
    y += 0.28 * np.sin(2 * math.pi * f0 * 4.8 * t) * np.exp(-t / 0.08)
    buzz = rasp(np.sin(2 * math.pi * f0 * t), 3.0) * np.exp(-t / 0.045) * 0.12
    return y + buzz


def music_box() -> np.ndarray:
    t = timebase(0.62)
    f0 = 1980
    y = np.zeros(len(t), dtype=np.float64)
    for i, ratio in enumerate((1.0, 2.97, 5.15, 6.8)):
        fk = f0 * ratio
        if fk >= SR * 0.45:
            continue
        y += (0.72 ** i) * np.sin(2 * math.pi * fk * t) * np.exp(-t / (0.28 / (i + 1)))
    return y


def marimba() -> np.ndarray:
    t = timebase(0.45)
    f0 = 168
    y = np.sin(2 * math.pi * f0 * t) * np.exp(-t / 0.18)
    y += 0.28 * np.sin(2 * math.pi * f0 * 4.05 * t) * np.exp(-t / 0.055)
    return y


def triangle() -> np.ndarray:
    t = timebase(0.55)
    y = np.sin(2 * math.pi * 2140 * t) * np.exp(-t / 0.24)
    y += 0.45 * np.sin(2 * math.pi * 4680 * t) * np.exp(-t / 0.11)
    y += 0.22 * np.sin(2 * math.pi * 6230 * t) * np.exp(-t / 0.07)
    return y


def wood_bonk() -> np.ndarray:
    t = timebase(0.12)
    y = np.sin(2 * math.pi * 186 * t) * np.exp(-t / 0.028)
    y += 0.45 * np.sin(2 * math.pi * 340 * t) * np.exp(-t / 0.016)
    tick = svf(noise(len(t), rng_for("wood-bonk")), 420, 1.4, "band") * np.exp(-t / 0.007)
    return y + 0.45 * tick


def pot_clang() -> np.ndarray:
    t = timebase(0.42)
    y = np.zeros(len(t), dtype=np.float64)
    for freq, amp, tau in ((312, 0.7, 0.16), (319, 0.45, 0.14), (628, 0.35, 0.09), (1010, 0.22, 0.06), (1544, 0.12, 0.04)):
        y += amp * np.sin(2 * math.pi * freq * t) * np.exp(-t / tau)
    return y


def spoon() -> np.ndarray:
    t = timebase(0.14)
    y = np.sin(2 * math.pi * 980 * t) * np.exp(-t / 0.028)
    y += 0.65 * np.sin(2 * math.pi * 1410 * t) * np.exp(-t / 0.018)
    y += 0.35 * np.sin(2 * math.pi * 2140 * t) * np.exp(-t / 0.012)
    return y


def knock() -> np.ndarray:
    def thump(seed):
        t = timebase(0.07)
        y = np.sin(2 * math.pi * 112 * t) * np.exp(-t / 0.014)
        nse = svf(noise(len(t), rng_for(seed)), 480, 0.9, "low") * np.exp(-t / 0.01)
        return y + 0.55 * nse

    return join(thump("knock-1"), gap(0.11), thump("knock-2"))


def glass_clink() -> np.ndarray:
    t = timebase(0.34)
    y = np.sin(2 * math.pi * 1680 * t) * np.exp(-t / 0.09)
    y += 0.7 * np.sin(2 * math.pi * 2230 * t) * np.exp(-t / 0.055)
    y += 0.25 * np.sin(2 * math.pi * 3410 * t) * np.exp(-t / 0.03)
    tick = noise(len(t), rng_for("glass-clink")) * np.exp(-t / 0.003) * 0.35
    return y + tick


def cowbell() -> np.ndarray:
    t = timebase(0.28)
    y = 0.6 * square(hold(t, 545), 8) + 0.4 * square(hold(t, 812), 8)
    return unit(svf(y, 3200, 0.707, "low")) * np.exp(-t / 0.065)


def temple_block() -> np.ndarray:
    t = timebase(0.09)
    f = glide_exp(t, 510, 230)
    y = unit(svf(tone(f), 900, 1.6, "band"))
    return y * np.exp(-t / 0.016)


def clown_horn() -> np.ndarray:
    t = timebase(0.3)
    a = unit(square(hold(t, 301), 7))
    b = unit(square(hold(t, 337), 7))
    y = unit(svf(0.55 * a + 0.45 * b, 1500, 0.707, "low"))
    return y * edge_env(t, 0.008, 0.04)


def bike_bell() -> np.ndarray:
    def ding():
        t = timebase(0.36)
        y = np.sin(2 * math.pi * 2520 * t) * np.exp(-t / 0.11)
        y += 0.65 * np.sin(2 * math.pi * 3180 * t) * np.exp(-t / 0.07)
        return y

    first = ding()
    second = ding() * 0.85
    n = len(first) + int(0.13 * SR)
    y = np.zeros(n, dtype=np.float64)
    y[: len(first)] += first
    i = int(0.13 * SR)
    y[i : i + len(second)] += second
    return y


def thud() -> np.ndarray:
    t = timebase(0.16)
    y = np.sin(2 * math.pi * 78 * t) * np.exp(-t / 0.04)
    nse = svf(noise(len(t), rng_for("thud")), 160, 0.707, "low") * np.exp(-t / 0.022)
    return y + 0.7 * nse


def cork_pop() -> np.ndarray:
    t = timebase(0.12)
    click = noise(len(t), rng_for("cork-pop")) * np.exp(-t / 0.0025)
    body = np.sin(2 * math.pi * 148 * t) * np.exp(-t / 0.018)
    air = svf(noise(len(t), rng_for("cork-air")), 1400, 0.707, "high") * np.exp(-t / 0.028)
    return click * 0.9 + body + 0.35 * air


def squeaky_toy() -> np.ndarray:
    t = timebase(0.34)
    squeeze = np.sin(math.pi * np.clip(t / t[-1], 0.0, 1.0))
    f = 680 + 210 * squeeze + 35 * np.sin(2 * math.pi * 17 * t)
    y = rasp(unit(tone(f)), 2.4)
    return y * squeeze


def party_horn() -> np.ndarray:
    t = timebase(0.38)
    f = glide_exp(t, 210, 780)
    src = rasp(unit(saw(f, 10)), 2.4)
    y = unit(svf(src, 2100, 0.707, "low"))
    return y * edge_env(t, 0.02, 0.03)


def water_drop() -> np.ndarray:
    t = timebase(0.09)
    f = glide_exp(t, 1680, 460)
    return tone(f) * np.exp(-t / 0.018)


def spring_raw(f0: float, f1: float, dur: float) -> np.ndarray:
    t = timebase(dur)
    f = f1 + (f0 - f1) * np.exp(-t / (dur * 0.22))
    wobble = 1.0 + 0.02 * np.sin(2 * math.pi * (7 + 6 * t / dur) * t) * (t / dur)
    f = f * wobble
    y = unit(tone(f)) + 0.28 * unit(tone(f * 2.35))
    return y * np.exp(-t / (dur * 0.5))


def spring() -> np.ndarray:
    return spring_raw(920, 130, 0.55)


def sproing() -> np.ndarray:
    return spring_raw(1680, 210, 0.26)


def slide_up() -> np.ndarray:
    t = timebase(0.4)
    f = glide_exp(t, 480, 2100)
    y = unit(tone(f)) + 0.12 * unit(tone(f * 2))
    breath = unit(svf(noise(len(t), rng_for("slide-up")), 2400, 0.707, "high"))
    return (0.95 * y + 0.05 * breath) * env_hump(t, 0.6)


def slide_down() -> np.ndarray:
    t = timebase(0.44)
    f = glide_exp(t, 1900, 280)
    y = unit(tone(f)) + 0.1 * unit(tone(f * 2))
    breath = unit(svf(noise(len(t), rng_for("slide-down")), 2000, 0.707, "high"))
    return (0.95 * y + 0.05 * breath) * env_hump(t, 0.55)


def jaw_harp() -> np.ndarray:
    t = timebase(0.52)
    drone = unit(tone(hold(t, 124)))
    flick = np.zeros(len(t), dtype=np.float64)
    for start, f0 in ((0.05, 740), (0.24, 620)):
        tt = timebase(0.13)
        tw = unit(tone(glide_exp(tt, f0, 150))) * np.exp(-tt / 0.045)
        i0 = int(start * SR)
        flick[i0 : i0 + len(tw)] += tw
    y = 0.62 * drone + 0.7 * unit(flick)
    return y * edge_env(t, 0.01, 0.06)


def ricochet() -> np.ndarray:
    y = spring_raw(1550, 190, 0.48)
    t = np.arange(len(y), dtype=np.float64) / SR
    pulses = np.clip(np.sin(2 * math.pi * 11.5 * t), 0.0, None) ** 1.7
    return y * (0.18 + 0.82 * pulses)


def clip(clip_id: str, tag: str, line: str, fn) -> dict:
    return {"id": clip_id, "tag": tag, "line": line, "fn": fn}


SPECS = [
    clip("quack", "animal", "A duck contributed.", quack),
    clip("double-quack", "animal", "The duck had a follow-up.", double_quack),
    clip("moo", "animal", "A cow explained itself.", moo),
    clip("meow", "animal", "A cat entered, uninvited.", meow),
    clip("bark", "animal", "Something barked at the picture.", bark),
    clip("yip", "animal", "A small dog has notes.", yip),
    clip("ribbit", "animal", "A frog called the meeting.", ribbit),
    clip("chirp", "animal", "A bird did not like that pixel.", chirp),
    clip("baa", "animal", "The sheep would like to speak.", baa),
    clip("oink", "animal", "A pig made it personal.", oink),
    clip("cluck", "animal", "A chicken took attendance.", cluck),
    clip("hoot", "animal", "An owl stayed up for this.", hoot),
    clip("neigh", "animal", "A horse has concerns.", neigh),
    clip("hiss", "animal", "Something without legs objected.", hiss),
    clip("buzz", "animal", "A bee filed a noise complaint.", buzz),
    clip("goose", "animal", "A goose is in charge now.", goose),
    clip("howl", "animal", "Something howled, professionally.", howl),
    clip("heehaw", "animal", "A donkey finished the thought.", heehaw),
    clip("trumpet-blat", "brass", "A trumpet blurted.", lambda: trumpet(311, 0.22, "trumpet-blat", 2500)),
    clip("trumpet-higher", "brass", "A smaller trumpet agreed.", lambda: trumpet(478, 0.18, "trumpet-higher", 2900)),
    clip("tuba-blurt", "brass", "The tuba moved furniture.", tuba_blurt),
    clip("trombone-slide", "brass", "A trombone went looking.", trombone_slide),
    clip("horn-soft", "brass", "A horn, from the next room.", horn_soft),
    clip("kazoo", "brass", "Kazoo. Unfortunately.", kazoo),
    clip("vuvuzela", "brass", "A plastic horn found the building.", vuvuzela),
    clip("wah-mute", "brass", "Muted brass, unmuted feelings.", wah_mute),
    clip("sax-honk", "brass", "A saxophone honked once and left.", sax_honk),
    clip("harmonica", "brass", "A harmonica in a pocket did its best.", harmonica),
    clip("piano-low", "plink", "A toy piano sat on a low key.", lambda: piano(98, 0.52, "piano-low")),
    clip("piano-high", "plink", "A toy piano apologizes.", lambda: piano(415, 0.42, "piano-high")),
    clip("xylophone", "plink", "Wood, struck with confidence.", xylophone),
    clip("glock", "plink", "A glockenspiel, briefly.", glock),
    clip("kalimba", "plink", "A thumb piano twanged.", kalimba),
    clip("music-box", "plink", "A music box remembered one tooth.", music_box),
    clip("ukulele", "plink", "Four strings, one opinion.", lambda: pluck(370, 0.5, 0.22, 0.08, "ukulele")),
    clip("banjo", "plink", "A banjo arrived too early.", lambda: pluck(307, 0.36, 0.1, 0.58, "banjo")),
    clip("marimba", "plink", "A soft mallet, a hard no.", marimba),
    clip("triangle", "plink", "The triangle. That is the whole statement.", triangle),
    clip("wood-bonk", "bonk", "Bonk.", wood_bonk),
    clip("pot-clang", "bonk", "A pot took the hit.", pot_clang),
    clip("spoon", "bonk", "Spoon.", spoon),
    clip("knock", "bonk", "Someone is at the pixel.", knock),
    clip("glass-clink", "bonk", "Glasses, no toast.", glass_clink),
    clip("cowbell", "bonk", "A cowbell got involved.", cowbell),
    clip("temple-block", "bonk", "A wooden block has spoken.", temple_block),
    clip("clown-horn", "bonk", "Honk.", clown_horn),
    clip("bike-bell", "bonk", "A bicycle, indoors.", bike_bell),
    clip("thud", "bonk", "That was the table.", thud),
    clip("cork-pop", "bonk", "Something left a bottle.", cork_pop),
    clip("squeaky-toy", "bonk", "A rubber toy is suffering.", squeaky_toy),
    clip("party-horn", "bonk", "A party horn unrolled itself.", party_horn),
    clip("water-drop", "bonk", "One drop. No rain.", water_drop),
    clip("spring", "boing", "Boing.", spring),
    clip("sproing", "boing", "Sproing, which is different.", sproing),
    clip("slide-up", "boing", "A whistle went up the stairs.", slide_up),
    clip("slide-down", "boing", "A whistle gave up.", slide_down),
    clip("jaw-harp", "boing", "A jaw harp did jaw harp things.", jaw_harp),
    clip("ricochet", "boing", "Cartoon physics, audio only.", ricochet),
]


def centroid(x: np.ndarray):
    if len(x) < 8:
        return None
    window = x * np.hanning(len(x))
    spec = np.abs(np.fft.rfft(window))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    total = float(np.sum(spec))
    if total < 1e-8:
        return None
    return float(np.sum(freqs * spec) / total)


def estimate_pitch(x: np.ndarray):
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 64:
        return None
    x = x - np.mean(x)
    energy = float(np.dot(x, x)) / len(x)
    if energy < 2e-5:
        return None
    n = len(x)
    nfft = 1 << (n * 2 - 1).bit_length()
    spec = np.fft.rfft(x, nfft)
    corr = np.fft.irfft(spec * np.conj(spec), nfft)
    min_lag = max(2, int(SR / 3500))
    max_lag = min(len(corr) - 2, n // 2, int(SR / 55))
    if max_lag <= min_lag + 2 or corr[0] <= 0:
        return None
    best_lag = None
    best = 0.0
    for lag in range(min_lag, max_lag):
        if corr[lag] >= corr[lag - 1] and corr[lag] >= corr[lag + 1] and corr[lag] > best:
            best = float(corr[lag])
            best_lag = lag
    if best_lag is None or best < 0.3 * float(corr[0]):
        return None
    return SR / best_lag


def pitch_at(x: np.ndarray, start: float, win: float = 0.04):
    i0 = max(0, int(start * SR))
    i1 = min(len(x), i0 + int(win * SR))
    if i1 <= i0:
        return None
    return estimate_pitch(x[i0:i1])


def write_wav(path: Path, x: np.ndarray) -> None:
    pcm = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(pcm.tobytes())


def main() -> None:
    tags = {"animal", "brass", "plink", "bonk", "boing"}
    ids = [spec["id"] for spec in SPECS]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate clip id")
    if not 40 <= len(SPECS) <= 60:
        raise SystemExit(f"expected 40-60 clips, got {len(SPECS)}")

    rendered = []
    failures = []
    for spec in SPECS:
        if spec["tag"] not in tags:
            failures.append(f"{spec['id']}: bad tag {spec['tag']}")
        audio = finish(spec["fn"]())
        dur = len(audio) / SR
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if not (0.05 < dur < 0.95):
            failures.append(f"{spec['id']}: duration {dur:.3f}s")
        if not (0.85 <= peak <= 0.93):
            failures.append(f"{spec['id']}: peak {peak:.3f}")
        if rms < 0.008:
            failures.append(f"{spec['id']}: rms {rms:.4f}")
        rendered.append((spec, audio, dur, peak, rms, centroid(audio)))

    shape_expect = {
        "quack": ("fall", 0.02, 0.12, 0.035),
        "moo": ("fall", 0.15, 0.62, 0.08),
        "meow": ("fall", 0.06, 0.38, 0.05),
        "spring": ("fall", 0.02, 0.4, 0.05),
        "sproing": ("fall", 0.015, 0.18, 0.04),
        "slide-up": ("rise", 0.05, 0.3, 0.05),
        "slide-down": ("fall", 0.05, 0.32, 0.05),
        "howl": ("rise", 0.1, 0.7, 0.08),
        "party-horn": ("rise", 0.05, 0.28, 0.05),
        "water-drop": ("fall", 0.0, 0.045, 0.025),
    }
    centroid_expect = {
        "hiss": ("gt", 1800),
        "chirp": ("gt", 1400),
        "thud": ("lt", 550),
        "tuba-blurt": ("lt", 750),
        "music-box": ("gt", 1000),
        "triangle": ("gt", 1400),
    }
    by_id = {spec["id"]: (audio, dur, cent) for spec, audio, dur, _peak, _rms, cent in rendered}

    print(f"{'id':<16} {'tag':<7} {'sec':>6} {'peak':>5} {'rms':>6} {'cent':>7} pitch")
    for spec, audio, dur, peak, rms, cent in rendered:
        p0 = pitch_at(audio, 0.03, 0.05)
        pitch = f"{p0:6.0f}" if p0 else "     -"
        cent_s = f"{cent:7.0f}" if cent else "      -"
        print(f"{spec['id']:<16} {spec['tag']:<7} {dur:6.3f} {peak:5.2f} {rms:6.3f} {cent_s} {pitch}")

    for clip_id, (kind, t0, t1, win) in shape_expect.items():
        audio = by_id[clip_id][0]
        a = pitch_at(audio, t0, win)
        b = pitch_at(audio, t1, win)
        if a is None or b is None:
            failures.append(f"{clip_id}: pitch unclear ({a}, {b})")
            continue
        ratio = b / a
        if kind == "fall" and ratio > 0.9:
            failures.append(f"{clip_id}: expected falling pitch, {a:.0f}->{b:.0f}")
        if kind == "rise" and ratio < 1.12:
            failures.append(f"{clip_id}: expected rising pitch, {a:.0f}->{b:.0f}")

    for clip_id, rule in centroid_expect.items():
        if rule is None or clip_id not in by_id:
            continue
        op, limit = rule
        cent = by_id[clip_id][2]
        if cent is None:
            failures.append(f"{clip_id}: no centroid")
        elif op == "gt" and cent <= limit:
            failures.append(f"{clip_id}: centroid {cent:.0f} <= {limit}")
        elif op == "lt" and cent >= limit:
            failures.append(f"{clip_id}: centroid {cent:.0f} >= {limit}")

    if by_id["bark"][1] > 0.45:
        failures.append("bark too long")
    if by_id["moo"][1] < 0.6:
        failures.append("moo too short")
    if by_id["howl"][1] < 0.6:
        failures.append("howl too short")

    counts = {}
    for spec, *_rest in rendered:
        counts[spec["tag"]] = counts.get(spec["tag"], 0) + 1
    print("counts", counts, "total", len(rendered))
    for tag, minimum in (("animal", 12), ("brass", 6), ("plink", 6), ("bonk", 6), ("boing", 4)):
        if counts.get(tag, 0) < minimum:
            failures.append(f"not enough {tag} clips")

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_clips = []
    for spec, audio, dur, _peak, _rms, _cent in rendered:
        filename = f"{spec['id']}.wav"
        write_wav(OUT / filename, audio)
        manifest_clips.append(
            {
                "id": spec["id"],
                "tag": spec["tag"],
                "file": filename,
                "seconds": round(dur, 5),
                "line": spec["line"],
            }
        )
    keep = {item["file"] for item in manifest_clips}
    for path in OUT.glob("*.wav"):
        if path.name not in keep:
            path.unlink()
    note = "Clip order is part of the picture-to-sound mapping. Do not reorder."
    payload = {"note": note, "clips": manifest_clips}
    (OUT / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(manifest_clips)} clips to {OUT}")
    if failures:
        print("FAILED")
        for item in failures:
            print(" -", item)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
