"""Step 1: get a short script for a genre and language.

A script is a plain dict:

    {
        "title": "गली क्रिकेट",
        "genre": "comedy",
        "lang": "hindi",
        "narrator_label": "कथावाचक",          # how the narrator is shown in subtitles
        "characters": [                       # up to 2 (the narrator is not counted)
            {"name": "Chintu", "label": "चिंटू", "gender": "m", "age": "child"},
            ...
        ],
        "lines": [
            {"speaker": "Narrator", "text": "..."},
            {"speaker": "Chintu", "text": "..."},
        ],
    }

If the GEMINI_API_KEY environment variable is set we ask Google Gemini (free tier)
to write a new story. If that fails, or there is no key, we pick one of the
built-in sample scripts (harmis/samples.py) so the tool always works offline.
"""

import json
import os
import random

import requests

from .samples import SAMPLES

GENRES = ["kids_story", "kids_rhyme", "comedy", "horror"]
LANGS = ["hindi", "hinglish", "english"]
NARRATOR = "Narrator"
NARRATOR_LABEL = {"hindi": "कथावाचक", "hinglish": "Narrator", "english": "Narrator"}

# Which column of a sample line holds each language: (speaker, hindi, hinglish, english)
LANG_COLUMN = {"hindi": 1, "hinglish": 2, "english": 3}

# Gemini model to use. Override with GEMINI_MODEL if Google renames models.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# What we tell Gemini about each genre.
GENRE_BRIEF = {
    "kids_story": (
        "a gentle story for children aged 4 to 10, retold from a public-domain Indian folk tale "
        "(Panchatantra, Jataka, Akbar-Birbal or Tenali Raman). End with a narrator line giving "
        "a small moral"
    ),
    "kids_rhyme": (
        "a brand new, original, cheerful rhyme for small children, with short rhyming lines "
        "about Indian everyday life (monsoon, mela, festivals, food, school). Do NOT use or "
        "copy any existing song or poem"
    ),
    "comedy": (
        "a light family comedy set in everyday Indian life (school, gali cricket, mohalla, "
        "village, festivals, food) with a funny twist at the end"
    ),
    "horror": (
        "a mildly spooky story for teenagers and adults set in India (old haveli, village, "
        "highway, monsoon night). Suspense only: no gore, no violence, no swearing"
    ),
}

LANG_BRIEF = {
    "hindi": "Write in simple Hindi using Devanagari script.",
    "hinglish": "Write in Hinglish (everyday Hindi mixed with English) using Roman (English) letters only.",
    "english": "Write in simple Indian English.",
}


def _gemini_prompt(genre, lang):
    """The instructions we send to Gemini."""
    label_note = (
        'Give each character a "label": their name written in Devanagari. '
        if lang == "hindi" else 'Set "label" the same as "name". '
    )
    return (
        f"Write {GENRE_BRIEF[genre]}. It is for a 30 to 50 second vertical video. "
        f"{LANG_BRIEF[lang]} "
        "Use Indian names (for example Chintu, Pinky, Dadi, Raju, Meera) and Indian settings, "
        "festivals and foods. No copyrighted characters, brands or songs. "
        "Use a Narrator and at most 2 other characters. "
        "Write 6 to 9 lines in total, about 60 to 90 words altogether. "
        'Each character needs a short Roman-letter "name", a "gender" ("m" or "f") and an '
        '"age" ("child", "adult" or "old"). ' + label_note +
        "Reply with ONLY JSON in this exact shape, no other text:\n"
        '{"title": "...", "characters": [{"name": "Chintu", "label": "...", "gender": "m", '
        '"age": "child"}], "lines": [{"speaker": "Narrator", "text": "..."}, '
        '{"speaker": "Chintu", "text": "..."}]}'
    )


def _clean_script(data, genre, lang):
    """Check a script from Gemini and fix small problems. Raises ValueError if it is unusable."""
    lines = []
    for line in data.get("lines", []):
        speaker = str(line.get("speaker", "")).strip() or NARRATOR
        text = str(line.get("text", "")).strip()
        if text:
            # Treat "narrator", "NARRATOR", "कथावाचक" etc. as the narrator.
            if speaker.lower() == "narrator" or speaker == NARRATOR_LABEL["hindi"]:
                speaker = NARRATOR
            lines.append({"speaker": speaker, "text": text})
    if len(lines) < 3:
        raise ValueError("script has too few lines")

    # Character info Gemini gave us, looked up by name.
    info = {str(c.get("name", "")).strip(): c for c in data.get("characters", []) if isinstance(c, dict)}

    # Characters = everyone who speaks except the narrator (max 2).
    characters = []
    for line in lines:
        name = line["speaker"]
        if name != NARRATOR and name not in [c["name"] for c in characters]:
            given = info.get(name, {})
            characters.append({
                "name": name,
                "label": str(given.get("label") or name).strip(),
                "gender": "f" if str(given.get("gender", "")).lower().startswith("f") else "m",
                "age": given.get("age") if given.get("age") in ("child", "adult", "old") else "adult",
            })
    if len(characters) > 2:
        raise ValueError("script has more than 2 characters")

    return {
        "title": str(data.get("title", "")).strip() or genre.replace("_", " ").title(),
        "genre": genre,
        "lang": lang,
        "narrator_label": NARRATOR_LABEL[lang],
        "characters": characters,
        "lines": lines,
    }


def script_from_gemini(genre, lang, api_key):
    """Ask Gemini for a new script. Raises an exception on any problem."""
    response = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": api_key},  # header, so the key never shows up in error messages
        json={
            "contents": [{"parts": [{"text": _gemini_prompt(genre, lang)}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    # Sometimes models wrap JSON in ``` fences; strip them just in case.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return _clean_script(json.loads(text), genre, lang)


def build_sample(sample, genre, lang):
    """Turn one entry of SAMPLES into a script dict in the chosen language."""
    column = LANG_COLUMN[lang]
    return {
        "title": sample["title"][lang],
        "genre": genre,
        "lang": lang,
        "narrator_label": NARRATOR_LABEL[lang],
        "characters": [
            {"name": c["name"], "label": c["hindi"] if lang == "hindi" else c["name"],
             "gender": c["gender"], "age": c["age"]}
            for c in sample["characters"]
        ],
        "lines": [{"speaker": line[0], "text": line[column]} for line in sample["lines"]],
    }


def sample_scripts(genre, lang):
    """All built-in scripts for the genre, in random order."""
    scripts = [build_sample(s, genre, lang) for s in SAMPLES[genre]]
    random.shuffle(scripts)
    return scripts


def get_script(genre, lang="hindi", use_ai=True):
    """Main entry point: return a script dict for the genre and language."""
    if genre not in GENRES:
        raise ValueError(f"Unknown genre '{genre}'. Choose from: {', '.join(GENRES)}")
    if lang not in LANGS:
        raise ValueError(f"Unknown language '{lang}'. Choose from: {', '.join(LANGS)}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if use_ai and api_key:
        try:
            script = script_from_gemini(genre, lang, api_key)
            print(f"[script] Gemini wrote: {script['title']}")
            return script
        except Exception as error:  # network error, bad JSON, quota, ...
            print(f"[script] Gemini failed ({error}); using a built-in script instead.")

    script = sample_scripts(genre, lang)[0]
    print(f"[script] Using built-in script: {script['title']}")
    return script
