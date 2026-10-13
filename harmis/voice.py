"""Step 2: turn each script line into speech, one audio file per line.

We use edge-tts (free Microsoft Edge voices, needs internet). Each speaker gets a
different voice. If edge-tts cannot connect we fall back to espeak-ng (offline,
robotic but works), and if that is not installed either we write a silent clip
so the video can still be made.
"""

import asyncio
import os
import shutil
import subprocess
import wave

import edge_tts
from moviepy import AudioFileClip

from .script import NARRATOR

# edge-tts voices: [narrator, character 1, character 2] for each genre.
EDGE_VOICES = {
    "comedy": ["en-US-ChristopherNeural", "en-US-GuyNeural", "en-US-JennyNeural"],
    "horror": ["en-GB-RyanNeural", "en-US-AnaNeural", "en-US-EricNeural"],
    "kids": ["en-US-JennyNeural", "en-US-AnaNeural", "en-GB-RyanNeural"],
}

# Extra tweaks per genre (slower and deeper for horror, a bit faster for comedy).
EDGE_STYLE = {
    "comedy": {"rate": "+5%", "pitch": "+0Hz"},
    "horror": {"rate": "-10%", "pitch": "-5Hz"},
    "kids": {"rate": "+0%", "pitch": "+5Hz"},
}

# espeak-ng fallback voices: (voice, pitch 0-99) for narrator, char 1, char 2.
ESPEAK_VOICES = [("en-us+m3", 40), ("en-gb+m1", 60), ("en-us+f3", 70)]


def speaker_index(script, speaker):
    """0 for the narrator, 1 or 2 for the characters."""
    if speaker == NARRATOR:
        return 0
    return 1 + script["characters"].index(speaker)


async def _edge_tts(text, voice, rate, pitch, path):
    # aiohttp does not read HTTPS_PROXY by itself, so pass it on if set.
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, proxy=proxy)
    await communicate.save(path)


def speak_edge(text, index, genre, path):
    """Make an mp3 with edge-tts. Raises an exception if it fails."""
    style = EDGE_STYLE[genre]
    asyncio.run(_edge_tts(text, EDGE_VOICES[genre][index], style["rate"], style["pitch"], path))
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("edge-tts produced an empty file")


def speak_espeak(text, index, path):
    """Make a wav with espeak-ng (offline). Raises an exception if it fails."""
    program = shutil.which("espeak-ng") or shutil.which("espeak")
    if not program:
        raise RuntimeError("espeak-ng is not installed")
    voice, pitch = ESPEAK_VOICES[index]
    subprocess.run([program, "-v", voice, "-p", str(pitch), "-s", "155", "-w", path, text],
                   check=True, capture_output=True)


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
    genre = script["genre"]
    use_edge = True  # stop trying edge-tts after the first failure (saves time)
    results = []

    for number, line in enumerate(script["lines"]):
        index = speaker_index(script, line["speaker"])
        base = os.path.join(out_dir, f"line_{number:02d}")
        path = None

        if use_edge:
            try:
                path = base + ".mp3"
                speak_edge(line["text"], index, genre, path)
            except Exception as error:
                print(f"[voice] edge-tts failed ({type(error).__name__}: {error}); "
                      "falling back to offline voices.")
                use_edge = False
                path = None

        if path is None:
            try:
                path = base + ".wav"
                speak_espeak(line["text"], index, path)
            except Exception as error:
                print(f"[voice] espeak-ng failed ({error}); using a silent clip.")
                write_silence(line["text"], path)

        # Measure how long the clip is so the animation can line up with it.
        with AudioFileClip(path) as clip:
            duration = clip.duration
        results.append({**line, "audio": path, "duration": duration})
        print(f"[voice] {line['speaker']:>10}: {duration:4.1f}s  {line['text'][:50]}")

    return results
