"""Step 2: turn each script line into speech, one audio file per line.

Voices, best first (config.yaml -> voice):
  1. Gemini TTS (needs GEMINI_API_KEY): expressive Hindi with a different
     prebuilt voice for the narrator and every character. Clips are cached in
     cache/tts/, so a retry or a re-run never spends the free quota twice.
  2. edge-tts (free Microsoft Edge voices, hi-IN / en-IN), 3 tries per line
     with growing pauses.
  3. espeak-ng (offline, robotic) and then silence - only on your own computer.
     Inside GitHub Actions these are never used: the run fails instead, so a
     robotic video is never published.

All lines of one story use the same engine: if Gemini stops halfway (quota), the
whole story is spoken again with edge-tts so the voices do not change mid-story.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import wave
import zlib

import edge_tts
import imageio_ffmpeg
import numpy as np
import requests
from moviepy import AudioFileClip

from .config import CONFIG, PROJECT_DIR
from .script import NARRATOR

# edge-tts voices per language and gender.
# (Hinglish is written in Roman letters, which the en-IN voices read more naturally.)
EDGE_VOICES = {
    "hindi": {"m": "hi-IN-MadhurNeural", "f": "hi-IN-SwaraNeural"},
    "hinglish": {"m": "en-IN-PrabhatNeural", "f": "en-IN-NeerjaNeural"},
    "english": {"m": "en-IN-PrabhatNeural", "f": "en-IN-NeerjaNeural"},
}

# Speed (%) and pitch (Hz) changes by age for edge-tts, so a child and an adult
# sound different even with the same voice.
AGE_STYLE = {"child": (5, 25), "adult": (0, 0), "old": (-10, -8)}

# Gemini prebuilt voices that suit each kind of character, picked in turn so
# nobody in a story shares a voice. A character.yaml can name its own: gemini_voice: Puck
GEMINI_POOLS = {
    ("f", "child"): ["Leda", "Zephyr", "Laomedeia", "Autonoe"],
    ("m", "child"): ["Puck", "Fenrir", "Sadachbia", "Zubenelgenubi"],
    ("f", "adult"): ["Kore", "Aoede", "Despina", "Erinome", "Callirrhoe", "Pulcherrima"],
    ("m", "adult"): ["Charon", "Orus", "Iapetus", "Alnilam", "Achird", "Algieba", "Umbriel"],
    ("f", "old"): ["Gacrux", "Vindemiatrix", "Achernar"],
    ("m", "old"): ["Algenib", "Sadaltager", "Rasalgethi", "Schedar"],
}

ESPEAK_LANG = {"hindi": "hi", "hinglish": "en", "english": "en"}
LANGUAGE_NAME = {"hindi": "Hindi", "hinglish": "Hinglish (Hindi with some English words)",
                 "english": "Indian English"}
CACHE_DIR = os.path.join(PROJECT_DIR, "cache", "tts")


class VoiceError(Exception):
    """No acceptable voice could be made (the run must fail, e.g. inside GitHub Actions)."""


class QuotaExhausted(Exception):
    """Gemini's free daily quota is used up: stop asking it in this run."""


def settings():
    return CONFIG.get("voice", {})


def in_ci():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def robotic_allowed():
    """espeak-ng / silence are allowed only on your own computer (never in GitHub Actions)."""
    return not in_ci() and settings().get("allow_espeak", True)


# ---------------------------------------------------------------------------
# Who sounds like what
# ---------------------------------------------------------------------------
def pick_voices(script, library=None):
    """Decide the voice for every speaker.

    Returns {speaker name: {"gender", "age", "voice", "rate", "pitch", "gemini", "direction"}}.
    """
    lang, genre = script["lang"], script["genre"]
    gemini_settings = settings().get("gemini", {})
    language = LANGUAGE_NAME[lang]
    rhyme = genre == "kids_rhyme"

    gender = script["narrator"]["gender"]
    style = CONFIG["genres"][genre].get("narrator_voice", {})
    narrator_voices = gemini_settings.get("narrator_voices", {})
    narrator_gemini = narrator_voices.get(genre) or ("Sulafat" if gender == "f" else "Achird")
    direction = gemini_settings.get("narrator_style", {}).get(genre) or (
        "Read this aloud like a warm, expressive storyteller for small children, with gentle "
        "emotion and natural pauses")
    voices = {NARRATOR: {"gender": gender, "age": "adult", "voice": EDGE_VOICES[lang][gender],
                         "rate": style.get("rate", 0), "pitch": style.get("pitch", 0),
                         "gemini": narrator_gemini,
                         "direction": f"{direction}. Speak in {language}"}}
    used_edge = {(voices[NARRATOR]["voice"], voices[NARRATOR]["pitch"])}
    used_gemini = {narrator_gemini}

    for character in script["characters"]:
        age, char_gender = character["age"], character["gender"]
        rate, pitch = AGE_STYLE[age]
        if genre == "horror":
            rate -= 5  # everyone talks a little slower in horror
        edge_voice = EDGE_VOICES[lang][char_gender]
        while (edge_voice, pitch) in used_edge:  # same voice as someone else? change the pitch
            pitch += 12
        used_edge.add((edge_voice, pitch))

        data = (library.characters.get(character["id"]) if library else None) or {}
        chosen = data.get("gemini_voice")
        if not chosen:
            pool = GEMINI_POOLS[(char_gender, age)]
            start = zlib.crc32(character["id"].encode()) % len(pool)
            ordered = pool[start:] + pool[:start]
            chosen = next((v for v in ordered if v not in used_gemini), ordered[0])
        used_gemini.add(chosen)
        look = " ".join(str(data.get("description", "")).split()[:14])
        kind = {"child": "young", "adult": "grown-up", "old": "old"}[age]
        line_style = ("in a cheerful, rhythmic, sing-song nursery rhyme style" if rhyme else
                      "with lively, natural emotion that fits the line, like a character in a cartoon")
        voices[character["name"]] = {
            "gender": char_gender, "age": age, "voice": edge_voice, "rate": rate, "pitch": pitch,
            "gemini": chosen,
            "direction": (f"Say this line as {character['label']}, a {kind} character in a children's story"
                          + (f" ({look})" if look else "") + f", {line_style}. Speak in {language}"),
        }
    if rhyme:
        voices[NARRATOR]["direction"] = (f"Sing-say this nursery rhyme line cheerfully and rhythmically for "
                                         f"small children. Speak in {language}")
    return voices


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------
def _write_wav(path, pcm, rate):
    with wave.open(path, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)


def trim_silence(path, threshold=0.012, keep=0.12):
    """Cut long silence at the start and end of a wav (Gemini sometimes adds some)."""
    with wave.open(path, "rb") as file:
        rate, width, channels = file.getframerate(), file.getsampwidth(), file.getnchannels()
        data = file.readframes(file.getnframes())
    if width != 2 or channels != 1:
        return
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
    loud = np.where(np.abs(samples) > threshold)[0]
    if len(loud) == 0:
        return
    start = max(0, loud[0] - int(keep * rate))
    end = min(len(samples), loud[-1] + int(keep * rate))
    _write_wav(path, (samples[start:end] * 32767).astype(np.int16).tobytes(), rate)


class GeminiTTS:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self):
        self.config = settings().get("gemini", {})
        self.models = list(self.config.get("models") or ["gemini-2.5-flash-preview-tts"])
        self.delay = float(self.config.get("delay_seconds", 7))
        self.tries = int(self.config.get("tries", 5))
        self.timeout = float(self.config.get("timeout", 120))
        self._last = 0.0

    @staticmethod
    def available():
        return bool(os.environ.get("GEMINI_API_KEY"))

    def cache_path(self, text, style):
        key = json.dumps([self.models[0], style["gemini"], style["direction"], text], ensure_ascii=False)
        return os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest()[:20] + ".wav")

    def _wait_turn(self):
        wait = self._last + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def speak(self, text, style, path):
        """Write a wav for one line (from the cache when possible)."""
        cached = self.cache_path(text, style)
        if os.path.exists(cached) and os.path.getsize(cached) > 1000:
            shutil.copyfile(cached, path)
            return "cache"
        body = {
            "contents": [{"parts": [{"text": f"{style['direction']}:\n{text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": style["gemini"]}}}},
        }
        last_error = None
        for model in list(self.models):
            for attempt in range(1, self.tries + 1):
                self._wait_turn()
                try:
                    response = requests.post(self.URL.format(model=model), json=body, timeout=self.timeout,
                                             headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
                except requests.RequestException as error:
                    last_error = f"{type(error).__name__}"
                    time.sleep(min(60, 5 * 2 ** (attempt - 1)))
                    continue
                if response.status_code == 200:
                    return self._save(response.json(), path, cached)
                text_body = response.text or ""
                last_error = f"HTTP {response.status_code} {' '.join(text_body.split())[:160]}"
                if response.status_code == 429:
                    if "PerDay" in text_body or "limit: 0" in text_body:
                        raise QuotaExhausted(last_error)
                    match = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', text_body)
                    wait = float(match.group(1)) + 1 if match else min(90, 10 * 2 ** (attempt - 1))
                    print(f"[voice]   Gemini busy (rate limit); waiting {wait:.0f}s ...")
                    time.sleep(wait)
                    continue
                if response.status_code in (500, 502, 503, 504):
                    time.sleep(min(60, 5 * 2 ** (attempt - 1)))
                    continue
                if response.status_code == 404:  # model name not available: try the next one
                    print(f"[voice]   Gemini TTS model {model} not found, trying the next one")
                    self.models.remove(model)
                break  # 400 / 403 / 404: retrying the same model will not help
        raise RuntimeError(f"Gemini TTS failed: {last_error}")

    def _save(self, data, path, cached):
        try:
            part = next(p for p in data["candidates"][0]["content"]["parts"] if "inlineData" in p)
        except (KeyError, IndexError, StopIteration):
            raise RuntimeError("Gemini TTS returned no audio")
        mime = part["inlineData"].get("mimeType", "")
        match = re.search(r"rate=(\d+)", mime)
        _write_wav(path, base64.b64decode(part["inlineData"]["data"]), int(match.group(1)) if match else 24000)
        trim_silence(path)
        os.makedirs(CACHE_DIR, exist_ok=True)
        shutil.copyfile(path, cached)
        return "gemini"


async def _edge_tts(text, style, path):
    # aiohttp does not read HTTPS_PROXY by itself, so pass it on if set.
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    communicate = edge_tts.Communicate(text, style["voice"], rate=f"{style['rate']:+d}%",
                                       pitch=f"{style['pitch']:+d}Hz", proxy=proxy)
    await communicate.save(path)


def speak_edge(text, style, path, tries=3):
    """Make an mp3 with edge-tts, up to `tries` attempts with growing pauses. Raises if all fail."""
    tries = int(settings().get("edge_tries", tries))
    for attempt in range(1, tries + 1):
        try:
            asyncio.run(_edge_tts(text, style, path))
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
            raise RuntimeError("edge-tts produced an empty file")
        except Exception as error:
            if attempt == tries:
                raise
            wait = 2 * 2 ** (attempt - 1)
            print(f"[voice]   edge-tts try {attempt}/{tries} failed ({type(error).__name__}); "
                  f"trying again in {wait}s ...")
            time.sleep(wait)


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
    _write_wav(path, b"\x00\x00" * int(seconds * rate), rate)


def change_speed(path, out_path, change):
    """Speed a clip up (+%) or down (-%) without changing its pitch (ffmpeg atempo)."""
    tempo = max(0.5, min(2.0, 1 + change / 100))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", path,
                    "-filter:a", f"atempo={tempo:.3f}", out_path], check=True)
    return out_path


# ---------------------------------------------------------------------------
# One story
# ---------------------------------------------------------------------------
def _speak_all(script, voices, out_dir, engine):
    """Every line with one engine. Returns [(path, source)]; raises if a line fails."""
    gemini = GeminiTTS() if engine == "gemini" else None
    results = []
    for number, line in enumerate(script["lines"]):
        style = voices[line["speaker"]]
        base = os.path.join(out_dir, f"{engine}_{number:02d}")
        if engine == "gemini":
            path = base + ".wav"
            results.append((path, gemini.speak(line["text"], style, path)))
        elif engine == "edge":
            path = base + ".mp3"
            speak_edge(line["text"], style, path)
            results.append((path, "edge"))
        elif engine == "espeak":
            path = base + ".wav"
            try:
                speak_espeak(line["text"], style, script["lang"], path)
                results.append((path, "espeak"))
            except Exception as error:
                print(f"[voice] espeak-ng failed ({error}); using a silent clip.")
                write_silence(line["text"], path)
                results.append((path, "silence"))
    return results


def engine_order():
    order = [e for e in settings().get("engines", ["gemini", "edge", "espeak"]) if e in ("gemini", "edge", "espeak")]
    if not robotic_allowed():
        order = [e for e in order if e != "espeak"]
    elif "espeak" not in order:
        order.append("espeak")  # on your own computer a video is always made
    return order


def make_voices(script, out_dir, rate_change=0, library=None):
    """Create one audio file per line. rate_change speeds every voice up (+) or down (-), in %.

    Returns a list of dicts: {"speaker", "text", ..., "audio", "duration"}.
    Raises VoiceError when no allowed engine works (always the case for espeak in CI).
    """
    os.makedirs(out_dir, exist_ok=True)
    voices = pick_voices(script, library)
    clips, errors = None, []
    for engine in engine_order():
        if engine == "gemini" and not GeminiTTS.available():
            errors.append("gemini: no GEMINI_API_KEY")
            continue
        try:
            clips = _speak_all(script, voices, out_dir, engine)
            break
        except Exception as error:
            kind = "free quota used up" if isinstance(error, QuotaExhausted) else type(error).__name__
            errors.append(f"{engine}: {kind}: {' '.join(str(error).split())[:160]}")
            print(f"[voice] {engine} could not voice the whole story ({kind}); trying the next voice engine.")
    if clips is None:
        where = " (GitHub Actions never uses espeak, so the run stops here)" if in_ci() else ""
        raise VoiceError("No voice engine worked" + where + ": " + " | ".join(errors))

    sources = sorted({source for _, source in clips})
    print(f"[voice] Voices made with: {', '.join(sources)}")
    results = []
    for number, (line, (path, source)) in enumerate(zip(script["lines"], clips)):
        if rate_change:  # e.g. +8 = 8% faster (used to fit long videos into 5-7 min)
            path = change_speed(path, os.path.join(out_dir, f"paced_{number:02d}.wav"), rate_change)
        with AudioFileClip(path) as clip:  # how long it is, so the animation lines up
            duration = clip.duration
        results.append({**line, "audio": path, "duration": duration, "voice_engine": source})
        who = voices[line["speaker"]]["gemini"] if source in ("gemini", "cache") else voices[line["speaker"]]["voice"]
        print(f"[voice] {line['speaker']:>10} ({who}): {duration:4.1f}s  {line['text'][:50]}")
    return results
