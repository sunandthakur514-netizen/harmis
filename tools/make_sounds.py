"""Make HARMIS's background music and sound effects from scratch (no samples, no downloads).

    python tools/make_sounds.py

Everything is synthesised here with numpy/scipy from sine waves and noise, so
the files are original works, released under CC0 1.0 (public domain) - see
harmis/assets/music/LICENSE.md. Output (Ogg Vorbis, mono, 24 kHz):

    harmis/assets/music/lullaby.ogg   soft music box + pad, 72 BPM (stories)
    harmis/assets/music/playful.ogg   bouncy marimba + bass + shaker, 108 BPM (rhymes, comedy)
    harmis/assets/sfx/<name>.ogg      whoosh, splash, laugh, thud, twinkle, boing, pop

The same seed always gives the same files.
"""

import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from scipy import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import imageio_ffmpeg  # noqa: E402

RATE = 24000
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "harmis", "assets")
rng = np.random.default_rng(2026)


def note(name):
    """'C4' -> frequency in Hz."""
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = names[name[0]] + (1 if "#" in name else 0)
    return 440.0 * 2 ** ((semis + 12 * (int(name[-1]) - 4)) / 12)


def t_axis(seconds):
    return np.arange(int(seconds * RATE)) / RATE


def bell(freq, seconds=1.6, decay=3.0):
    """Music-box / bell tone: sine plus soft overtones with an exponential decay."""
    t = t_axis(seconds)
    env = np.exp(-t * decay) * np.minimum(1, t / 0.004)
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t * 4) \
        + 0.12 * np.sin(2 * np.pi * 3.01 * freq * t) * np.exp(-t * 8)
    return tone * env


def marimba(freq, seconds=0.6):
    t = t_axis(seconds)
    env = np.exp(-t * 9) * np.minimum(1, t / 0.002)
    return (np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 4 * freq * t) * np.exp(-t * 30)) * env


def pad(freqs, seconds):
    """Soft sustained chord with slow attack and release."""
    t = t_axis(seconds)
    env = np.minimum(1, t / 0.6) * np.minimum(1, (seconds - t) / 0.8)
    tone = sum(np.sin(2 * np.pi * f * t) + 0.2 * np.sin(2 * np.pi * 2 * f * t + 0.3) for f in freqs)
    return tone * env / len(freqs)


def add(track, sound, at):
    start = int(at * RATE)
    end = min(len(track), start + len(sound))
    if end > start:
        track[start:end] += sound[:end - start]


def reverb(track, amount=0.25):
    """A small room: a few feedback-free echoes, slightly darker each time."""
    out = track.copy()
    for delay, gain in ((0.031, 0.5), (0.053, 0.4), (0.089, 0.3), (0.137, 0.22), (0.211, 0.15)):
        shift = int(delay * RATE)
        echo = np.zeros_like(track)
        echo[shift:] = track[:-shift]
        b, a = signal.butter(1, 3500 / (RATE / 2))
        out += amount * gain * signal.lfilter(b, a, echo)
    return out


def normalise(track, peak=0.5):
    return track / (np.max(np.abs(track)) + 1e-9) * peak


CHORDS = {"C": ["C4", "E4", "G4"], "Am": ["A3", "C4", "E4"], "F": ["F3", "A3", "C4"], "G": ["G3", "B3", "D4"],
          "Dm": ["D4", "F4", "A4"], "Em": ["E4", "G4", "B4"]}
MELODY_NOTES = {"C": ["C5", "E5", "G5", "A5", "D5"], "Am": ["A4", "C5", "E5", "G5", "D5"],
                "F": ["F5", "A5", "C5", "D5", "G5"], "G": ["G5", "B4", "D5", "E5", "A5"],
                "Dm": ["D5", "F5", "A5", "C5", "E5"], "Em": ["E5", "G5", "B4", "D5", "A5"]}


def lullaby():
    beat = 60 / 72  # 72 BPM
    progression = ["C", "Am", "F", "G", "C", "Am", "Dm", "G", "F", "C", "Am", "G", "F", "G", "C", "C"]
    track = np.zeros(int(len(progression) * 4 * beat * RATE) + RATE * 2)
    for bar, chord in enumerate(progression):
        t0 = bar * 4 * beat
        add(track, 0.5 * pad([note(n) for n in CHORDS[chord]], 4 * beat + 0.6), t0)
        add(track, 0.35 * bell(note(CHORDS[chord][0][0] + "3"), 2.5, 1.6), t0)  # soft low root
        # Music-box melody: mostly eighth notes, a few rests, ending on the root.
        for step in range(8):
            if rng.random() < 0.28 and step not in (0, 4):
                continue
            pick = MELODY_NOTES[chord][0] if step == 0 else rng.choice(MELODY_NOTES[chord])
            add(track, 0.45 * bell(note(pick), 1.4, 3.2), t0 + step * beat / 2)
    track = reverb(track, 0.35)
    return normalise(track[: int(len(progression) * 4 * beat * RATE)], 0.5)


def playful():
    beat = 60 / 108  # 108 BPM
    progression = ["C", "G", "Am", "F"] * 3 + ["C", "F", "G", "C"]
    length = len(progression) * 4 * beat
    track = np.zeros(int(length * RATE) + RATE)
    pattern = [0, None, 2, 1, None, 3, 2, None]  # bouncy eighth notes (index into chord melody notes)
    for bar, chord in enumerate(progression):
        t0 = bar * 4 * beat
        root = note(CHORDS[chord][0][0] + "2")
        for k, mult in enumerate((1, 1.5, 1, 1.5)):  # root - fifth bass on every beat
            add(track, 0.55 * marimba(root * mult, 0.5), t0 + k * beat)
        for step, index in enumerate(pattern):
            if index is not None:
                add(track, 0.4 * marimba(note(MELODY_NOTES[chord][index]), 0.45), t0 + step * beat / 2)
        for step in range(8):  # soft shaker on the off-beats
            if step % 2:
                noise = rng.normal(0, 1, int(0.05 * RATE)) * np.exp(-t_axis(0.05) * 70)
                b, a = signal.butter(2, 5000 / (RATE / 2), "high")
                add(track, 0.12 * signal.lfilter(b, a, noise), t0 + step * beat / 2)
    track = reverb(track, 0.18)
    return normalise(track[: int(length * RATE)], 0.5)


# ----------------------------------------------------------------------------- effects
def sweep_filter(noise, cutoffs, btype="low"):
    """Noise through a filter whose cutoff changes over time (in blocks)."""
    out = np.zeros_like(noise)
    block = 256
    zi = None
    for start in range(0, len(noise), block):
        frac = start / len(noise)
        fc = np.interp(frac, np.linspace(0, 1, len(cutoffs)), cutoffs)
        b, a = signal.butter(2, min(0.99, fc / (RATE / 2)), btype)
        if zi is None:
            zi = signal.lfilter_zi(b, a) * 0
        out[start:start + block], zi = signal.lfilter(b, a, noise[start:start + block], zi=zi)
    return out


def whoosh():
    t = t_axis(0.8)
    noise = rng.normal(0, 1, len(t))
    sound = sweep_filter(noise, [300, 2500, 4500, 1200, 300])
    return normalise(sound * np.sin(np.pi * t / t[-1]) ** 2, 0.8)


def splash():
    t = t_axis(0.9)
    noise = rng.normal(0, 1, len(t))
    body = sweep_filter(noise, [6000, 3000, 1500, 800]) * np.exp(-t * 6) * np.minimum(1, t / 0.005)
    sound = body
    for _ in range(9):  # little bubbles
        start = rng.uniform(0.05, 0.6)
        f0 = rng.uniform(500, 1100)
        bt = t_axis(0.06)
        bubble = np.sin(2 * np.pi * (f0 * bt + 4000 * bt ** 2)) * np.exp(-bt * 60)
        add(sound, 0.35 * bubble, start)
    return normalise(sound, 0.8)


def resonator(x, freq, bandwidth):
    r = np.exp(-np.pi * bandwidth / RATE)
    theta = 2 * np.pi * freq / RATE
    return signal.lfilter([1 - r], [1, -2 * r * np.cos(theta), r * r], x)


def laugh():
    """A cartoon 'hee-hee-hee' giggle: short voiced syllables through vowel formants."""
    track = np.zeros(int(1.2 * RATE))
    for k in range(5):
        dur = 0.13
        t = t_axis(dur)
        f0 = 430 - 18 * k + 40 * np.sin(np.pi * t / dur)
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        pulses = signal.sawtooth(phase) + 0.25 * rng.normal(0, 1, len(t))  # a little breath
        voiced = resonator(pulses, 350, 120) + 0.6 * resonator(pulses, 2300, 200) + 0.3 * resonator(pulses, 3000, 300)
        env = np.sin(np.pi * t / dur) ** 1.5
        add(track, voiced * env, 0.05 + k * 0.19)
    return normalise(track, 0.7)


def thud():
    t = t_axis(0.45)
    freq = 90 * np.exp(-t * 4) + 40
    body = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 9)
    click = rng.normal(0, 1, len(t)) * np.exp(-t * 120)
    b, a = signal.butter(2, 900 / (RATE / 2))
    return normalise(body + 0.4 * signal.lfilter(b, a, click), 0.9)


def twinkle():
    track = np.zeros(int(1.4 * RATE))
    for k, name in enumerate(["C6", "E6", "G6", "C7", "E7"]):
        add(track, bell(note(name), 1.0, 5.0), k * 0.07)
    return normalise(reverb(track, 0.4), 0.6)


def boing():
    t = t_axis(0.7)
    freq = 180 + 220 * (1 - np.exp(-t * 6)) + 30 * np.sin(2 * np.pi * 14 * t) * np.exp(-t * 3)
    sound = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 4.5) * np.minimum(1, t / 0.004)
    return normalise(sound, 0.7)


def pop():
    t = t_axis(0.09)
    freq = 900 * np.exp(-t * 30) + 200
    sound = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 45)
    return normalise(sound, 0.7)


def save(samples, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        with wave.open(tmp.name, "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(RATE)
            file.writeframes(pcm.tobytes())
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", tmp.name,
                    "-c:a", "libvorbis", "-q:a", "4", "-map_metadata", "-1", path], check=True)
    os.remove(tmp.name)
    print(f"{path}: {len(samples) / RATE:.1f}s")


if __name__ == "__main__":
    save(lullaby(), os.path.join(ROOT, "music", "lullaby.ogg"))
    save(playful(), os.path.join(ROOT, "music", "playful.ogg"))
    for make in (whoosh, splash, laugh, thud, twinkle, boing, pop):
        save(make(), os.path.join(ROOT, "sfx", f"{make.__name__}.ogg"))
