"""The sound track: voices + soft background music + small sound effects.

Music and effects are in harmis/assets/music and harmis/assets/sfx. They were
made by tools/make_sounds.py from scratch and are CC0 (public domain). The music
plays quietly under the story and gets a little softer while someone speaks.
An effect plays when a line mentions it (config.yaml -> audio: effects), for
example "उड़" (fly) -> whoosh, "छपाक" -> splash, "हा हा" -> laugh.
"""

import os
import subprocess
import wave

import imageio_ffmpeg
import numpy as np

from .config import CONFIG

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
RATE = 24000


def settings():
    return CONFIG.get("audio", {})


def read_audio(path, rate=RATE):
    """Any audio file -> mono float32 samples at `rate` (decoded by ffmpeg)."""
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", path, "-f", "s16le",
                          "-ac", "1", "-ar", str(rate), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def find_effects(segments):
    """[(time, effect name)]: at most one effect per line, when its words appear in the line."""
    rules = settings().get("effects", {})
    events = []
    for seg in segments:
        text = f" {seg['text']} {seg.get('english') or ''} ".lower()
        for name, words in rules.items():
            if any(word.lower() in text for word in words):
                if os.path.exists(os.path.join(ASSETS, "sfx", f"{name}.ogg")):
                    events.append((seg["start"] + 0.15, name))
                break
    return events


def music_bed(genre, length, speech):
    """Looped background music, softer while someone speaks (speech: 0/1 per sample)."""
    name = settings().get("music", {}).get(genre)
    path = os.path.join(ASSETS, "music", f"{name}.ogg") if name else None
    if not path or not os.path.exists(path):
        return None
    loop = read_audio(path)
    repeats = int(np.ceil(length / len(loop)))
    music = np.tile(loop, repeats)[:length]
    loud, soft = float(settings().get("music_volume", 0.14)), float(settings().get("music_under_voice", 0.07))
    gain = soft + (loud - soft) * (1 - speech)
    window = int(0.4 * RATE)  # smooth the ducking so the music never jumps
    gain = np.convolve(gain, np.ones(window) / window, mode="same")
    fade_in, fade_out = int(1.5 * RATE), int(3.0 * RATE)
    gain[:fade_in] *= np.linspace(0, 1, min(fade_in, length))
    gain[-fade_out:] *= np.linspace(1, 0, min(fade_out, length))
    return music * gain


def mix(segments, total, path, genre):
    """Voices + music + effects into one mono WAV. Returns the effects used, for the log."""
    length = int(total * RATE) + RATE
    voices = np.zeros(length, dtype=np.float32)
    speech = np.zeros(length, dtype=np.float32)
    cache = {}
    for seg in segments:
        if seg["audio"] not in cache:  # rhymes reuse the same clips
            cache[seg["audio"]] = read_audio(seg["audio"])
        samples = cache[seg["audio"]]
        start = int(seg["start"] * RATE)
        end = min(length, start + len(samples))
        voices[start:end] += samples[:end - start]
        speech[start:end] = 1
    peak = np.max(np.abs(voices)) or 1.0
    voices *= min(1.0, 0.9 / peak)  # voices as loud as possible without clipping
    track = voices
    music = music_bed(genre, length, speech)
    if music is not None:
        track = track + music
    effects = find_effects(segments)
    volume = float(settings().get("effects_volume", 0.35))
    for time, name in effects:
        sound = read_audio(os.path.join(ASSETS, "sfx", f"{name}.ogg")) * volume
        start = int(time * RATE)
        end = min(length, start + len(sound))
        track[start:end] += sound[:end - start]
    pcm = (np.clip(track, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(pcm.tobytes())
    return effects
