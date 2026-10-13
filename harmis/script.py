"""Step 1: get a short script for a genre and language.

A script is a plain dict:

    {
        "title": "बीरबल की खिचड़ी",
        "genre": "kids_story",
        "lang": "hindi",
        "narrator": {"id": "narrator", "label": "कथावाचक", "gender": "f"},
        "characters": [                       # up to 2 (the narrator is not counted)
            {"id": "akbar", "name": "Akbar", "label": "अकबर", "gender": "m", "age": "adult"},
            ...
        ],
        "lines": [
            {"speaker": "Narrator", "text": "...", "scene": "village_pond_night"},
            {"speaker": "Akbar", "text": "...", "scene": "palace_court"},
        ],
    }

Characters come from the character library (harmis/assets/characters/), so the
same character always looks and sounds the same.

If the GEMINI_API_KEY environment variable is set we ask Google Gemini (free tier)
to write a new story. If that fails, or there is no key, we pick one of the
built-in sample scripts (harmis/samples.py) so the tool always works offline.
"""

import json
import os
import random

import requests

from .config import CONFIG
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


def character_entry(data, lang):
    """The bits of a character.yaml a script needs, with the on-screen name in the right language."""
    labels = data.get("label", {})
    label = labels.get("hindi") if lang == "hindi" else labels.get("english")
    return {"id": data["id"], "name": data["name"], "label": label or data["name"],
            "gender": data.get("gender", "m"), "age": data.get("age", "adult")}


def narrator_entry(genre, lang, library):
    """The narrator for this genre (picture and voice gender come from its character.yaml)."""
    data = library.find(CONFIG["genres"][genre].get("narrator", "narrator")) or {}
    return {"id": data.get("id"), "label": NARRATOR_LABEL[lang], "gender": data.get("gender", "f")}


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
def _gemini_prompt(genre, lang, library):
    """The instructions we send to Gemini."""
    known = ", ".join(sorted(library.scenes))
    cast = ", ".join(sorted({d["name"] for d in library.characters.values() if d["name"] != NARRATOR}))
    label_note = (
        'Give each character a "label": their name written in Devanagari. '
        if lang == "hindi" else 'Set "label" the same as "name". '
    )
    return (
        f"Write {GENRE_BRIEF[genre]}. It is for a 30 to 50 second vertical video. "
        f"{LANG_BRIEF[lang]} "
        "Use Indian names and Indian settings, festivals and foods. "
        "No copyrighted characters, brands or songs. "
        f"You may reuse these existing characters: {cast}. "
        "Use a Narrator and at most 2 other characters. "
        "Write 6 to 9 lines in total, about 60 to 90 words altogether. "
        'Each character needs a short Roman-letter "name", a "gender" ("m" or "f"), an '
        '"age" ("child", "adult" or "old") and a "look": one sentence describing their face, '
        "hair and clothes for an illustrator (kid-friendly). " + label_note +
        f'Give every line a "scene", chosen from: {known}. '
        "Reply with ONLY JSON in this exact shape, no other text:\n"
        '{"title": "...", "characters": [{"name": "Chintu", "label": "...", "gender": "m", '
        '"age": "child", "look": "..."}], "lines": [{"speaker": "Narrator", "text": "...", '
        '"scene": "gali"}, {"speaker": "Chintu", "text": "...", "scene": "gali"}]}'
    )


def _clean_script(data, genre, lang, library):
    """Check a script from Gemini and fix small problems. Raises ValueError if it is unusable."""
    scene = CONFIG["genres"][genre].get("default_scene")
    lines = []
    for line in data.get("lines", []):
        speaker = str(line.get("speaker", "")).strip() or NARRATOR
        text = str(line.get("text", "")).strip()
        if line.get("scene") in library.scenes:
            scene = line["scene"]  # unknown scenes keep the previous one
        if text:
            # Treat "narrator", "NARRATOR", "कथावाचक" etc. as the narrator.
            if speaker.lower() == "narrator" or speaker == NARRATOR_LABEL["hindi"]:
                speaker = NARRATOR
            lines.append({"speaker": speaker, "text": text, "scene": scene})
    if len(lines) < 3:
        raise ValueError("script has too few lines")

    speakers = []
    for line in lines:
        if line["speaker"] != NARRATOR and line["speaker"] not in speakers:
            speakers.append(line["speaker"])
    if len(speakers) > 2:
        raise ValueError("script has more than 2 characters")

    # Use the library character if we know them, otherwise add them to the library.
    info = {str(c.get("name", "")).strip(): c for c in data.get("characters", []) if isinstance(c, dict)}
    characters = []
    for name in speakers:
        known = library.find(name)
        if known is None:
            given = info.get(name, {})
            gender = "f" if str(given.get("gender", "")).lower().startswith("f") else "m"
            age = given.get("age") if given.get("age") in ("child", "adult", "old") else "adult"
            known = library.add_character(name, gender, age, str(given.get("look", "")),
                                          hindi_label=given.get("label") if lang == "hindi" else None)
        entry = character_entry(known, lang)
        for line in lines:  # scripts use the library's spelling of the name
            if line["speaker"] == name:
                line["speaker"] = entry["name"]
        characters.append(entry)

    return {
        "title": str(data.get("title", "")).strip() or genre.replace("_", " ").title(),
        "genre": genre,
        "lang": lang,
        "narrator": narrator_entry(genre, lang, library),
        "characters": characters,
        "lines": lines,
    }


def script_from_gemini(genre, lang, api_key, library):
    """Ask Gemini for a new script. Raises an exception on any problem."""
    response = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": api_key},  # header, so the key never shows up in error messages
        json={
            "contents": [{"parts": [{"text": _gemini_prompt(genre, lang, library)}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    # Sometimes models wrap JSON in ``` fences; strip them just in case.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return _clean_script(json.loads(text), genre, lang, library)


# ---------------------------------------------------------------------------
# Built-in samples
# ---------------------------------------------------------------------------
def build_sample(sample, genre, lang, library):
    """Turn one entry of SAMPLES into a script dict in the chosen language."""
    column = LANG_COLUMN[lang]
    scenes = sample.get("scenes", {})
    scene = CONFIG["genres"][genre].get("default_scene")
    lines = []
    for number, line in enumerate(sample["lines"]):
        scene = scenes.get(number, scene)
        lines.append({"speaker": line[0], "text": line[column], "scene": scene})
    return {
        "id": sample["id"],
        "title": sample["title"][lang],
        "genre": genre,
        "lang": lang,
        "narrator": narrator_entry(genre, lang, library),
        "characters": [character_entry(library.find(c), lang) for c in sample["characters"]],
        "lines": lines,
    }


def sample_scripts(genre, lang, library):
    """All built-in scripts for the genre, in random order."""
    scripts = [build_sample(s, genre, lang, library) for s in SAMPLES[genre]]
    random.shuffle(scripts)
    return scripts


def story_ids():
    """{story id: genre} for every built-in story."""
    return {s["id"]: genre for genre, samples in SAMPLES.items() for s in samples}


def get_script(genre, lang, library, use_ai=True, story=None):
    """Main entry point: return a script dict.

    story: id of a built-in story (for example "birbal_khichdi"); skips Gemini.
    """
    if lang not in LANGS:
        raise ValueError(f"Unknown language '{lang}'. Choose from: {', '.join(LANGS)}")
    if story:
        for sample in SAMPLES[genre]:
            if sample["id"] == story:
                print(f"[script] Using built-in story: {sample['title'][lang]}")
                return build_sample(sample, genre, lang, library)
        raise ValueError(f"No story '{story}' in genre {genre}")
    if genre not in GENRES:
        raise ValueError(f"Unknown genre '{genre}'. Choose from: {', '.join(GENRES)}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if use_ai and api_key:
        try:
            script = script_from_gemini(genre, lang, api_key, library)
            print(f"[script] Gemini wrote: {script['title']}")
            return script
        except Exception as error:  # network error, bad JSON, quota, ...
            print(f"[script] Gemini failed ({error}); using a built-in script instead.")

    script = sample_scripts(genre, lang, library)[0]
    print(f"[script] Using built-in script: {script['title']}")
    return script
