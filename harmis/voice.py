"""Step 2: turn each script line into speech, one audio file per line.

We use edge-tts (free Microsoft Edge voices, needs internet) with Indian voices:
hi-IN for Hindi, en-IN for Hinglish and English. Each speaker gets their own
voice, picked from their gender and age (children sound higher, Dadi slower).

If edge-tts cannot connect we fall back to espeak-ng (offline, robotic but works),
and if that is not installed either we write a silent clip so the video can
still be made.
"""

import asyncio
import os
import shutil
import subprocess
import wave

import edge_tts
from moviepy import AudioFileClip

from .config import CONFIG
from .script import NARRATOR

# edge-tts voices per language and gender.
# (Hinglish is written in Roman letters, which the en-IN voices read more naturally.)
EDGE_VOICES = {
    "hindi": {"m": "hi-IN-MadhurNeural", "f": "hi-IN-SwaraNeural"},
    "hinglish": {"m": "en-IN-PrabhatNeural", "f": "en-IN-NeerjaNeural"},
    "english": {"m": "en-IN-PrabhatNeural", "f": "en-IN-NeerjaNeural"},
}

# Speed (%) and pitch (Hz) changes by age, so a child and an adult sound different
# even with the same voice.
AGE_STYLE = {"child": (5, 25), "adult": (0, 0), "old": (-10, -8)}

# espeak-ng fallback: voice name per language.
ESPEAK_LANG = {"hindi": "hi", "hinglish": "en", "english": "en"}


def pick_voices(script):
    """Decide the voice for every speaker.

    Returns {speaker name: {"gender", "voice", "rate", "pitch", "age"}}.
    """
    lang, genre = script["lang"], script["genre"]
    # Narrator: gender from its character.yaml, speed/pitch from config.yaml.
    gender = script["narrator"]["gender"]
    style = CONFIG["genres"][genre].get("narrator_voice", {})
    rate, pitch = style.get("rate", 0), style.get("pitch", 0)
    voices = {NARRATOR: {"gender": gender, "voice": EDGE_VOICES[lang][gender],
                         "rate": rate, "pitch": pitch, "age": "adult"}}
    used = {(voices[NARRATOR]["voice"], pitch)}

    for character in script["characters"]:
        rate, pitch = AGE_STYLE[character["age"]]
        if genre == "horror":
            rate -= 5  # everyone talks a little slower in horror
        voice = EDGE_VOICES[lang][character["gender"]]
        # Same voice and pitch as someone else? Nudge the pitch until it is different.
        while (voice, pitch) in used:
            pitch += 12
        used.add((voice, pitch))
        voices[character["name"]] = {"gender": character["gender"], "voice": voice,
                                     "rate": rate, "pitch": pitch, "age": character["age"]}
    return voices


async def _edge_tts(text, style, path):
    # aiohttp does not read HTTPS_PROXY by itself, so pass it on if set.
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    communicate = edge_tts.Communicate(text, style["voice"], rate=f"{style['rate']:+d}%",
                                       pitch=f"{style['pitch']:+d}Hz", proxy=proxy)
    await communicate.save(path)


def speak_edge(text, style, path):
    """Make an mp3 with edge-tts. Raises an exception if it fails."""
    asyncio.run(_edge_tts(text, style, path))
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("edge-tts produced an empty file")


def speak_espeak(text, style, lang, path):
    """Make a wav with espeak-ng (offline). Raises an exception if it fails."""
    program = shutil.which("espeak-ng") or shutil.which("espeak")
    if not program:
        raise RuntimeError("espeak-ng is not installed")
    voice = ESPEAK_LANG[lang] + ("+f3" if style["gender"] == "f" else "+m3")
    pitch = {"child": 80, "adult": 50, "old": 35}[style["age"]] + style["pitch"] // 4
    speed = int(150 * (1 + style["rate"] / 100))
    subprocess.run([program, "-v", voice, "-p", str(max(0, min(99, pitch))), "-s", str(speed),
                    "-w", path, text], check=True, capture_output=True)


def write_silence(text, path, rate=22050):
    """Last resort: a silent wav that lasts about as long as reading the text."""
    seconds = max(1.5, 0.4 * len(text.split()))
    with wave.open(path, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"\x00\x00" * int(seconds * rate))


def make_voices(script, out_dir):
    """Create one audio file per line.

    Returns a list of dicts: {"speaker", "text", "audio", "duration"}.
    """
    os.makedirs(out_dir, exist_ok=True)
    voices = pick_voices(script)
    use_edge = True  # stop trying edge-tts after the first failure (saves time)
    results = []

    for number, line in enumerate(script["lines"]):
        style = voices[line["speaker"]]
        base = os.path.join(out_dir, f"line_{number:02d}")
        path = None

        if use_edge:
            try:
                path = base + ".mp3"
                speak_edge(line["text"], style, path)
            except Exception as error:
                print(f"[voice] edge-tts failed ({type(error).__name__}: {error}); "
                      "falling back to offline voices.")
                use_edge = False
                path = None

        if path is None:
            try:
                path = base + ".wav"
                speak_espeak(line["text"], style, script["lang"], path)
            except Exception as error:
                print(f"[voice] espeak-ng failed ({error}); using a silent clip.")
                write_silence(line["text"], path)

        # Measure how long the clip is so the animation can line up with it.
        with AudioFileClip(path) as clip:
            duration = clip.duration
        results.append({**line, "audio": path, "duration": duration})
        print(f"[voice] {line['speaker']:>10}: {duration:4.1f}s  {line['text'][:50]}")

    return results
