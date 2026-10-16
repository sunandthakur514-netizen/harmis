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
from .samples_long import LONG_SAMPLES

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

# Small line under the title on the long-video intro card (Gemini stories).
TAGLINE = {
    "kids_story": {"hindi": "बच्चों की एक कहानी", "hinglish": "Bachchon ki ek Kahani", "english": "A Story for Kids"},
    "kids_rhyme": {"hindi": "एक प्यारी कविता", "hinglish": "Ek Pyaari Kavita", "english": "A Happy Rhyme"},
    "comedy": {"hindi": "हँसी की एक कहानी", "hinglish": "Hansi ki ek Kahani", "english": "A Funny Story"},
    "horror": {"hindi": "एक रहस्यमयी कहानी (13+)", "hinglish": "Ek Rahasyamayi Kahani (13+)",
               "english": "A Mystery Story (13+)"},
}

# How many characters (besides the narrator) a story may have.
MAX_CHARACTERS = {"short": 2, "long": 3}

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
def _gemini_prompt(genre, lang, library, fmt="short"):
    """The instructions we send to Gemini."""
    known = ", ".join(sorted(library.scenes))
    cast = ", ".join(sorted({d["name"] for d in library.characters.values() if d["name"] != NARRATOR}))
    label_note = (
        'Give each character a "label": their name written in Devanagari. '
        if lang == "hindi" else 'Set "label" the same as "name". '
    )
    if fmt == "long":
        size = (
            "It is for a 5 to 7 minute video. Give it a clear beginning, a problem, a surprising "
            "twist and a happy ending" + (" with a narrator line giving a small moral" if genre.startswith("kids") else "") +
            ". The Narrator tells most of the story; the characters speak short lines in between. "
            "Use at most 3 characters besides the Narrator. Write 45 to 65 lines with 750 to 950 words "
            "of spoken text altogether (that is 5 to 7 minutes when read aloud). "
            "Split the story into 15 to 25 scenes; scenes may reuse the same place. "
        )
    else:
        size = (
            "It is for a 30 to 50 second vertical video. Use a Narrator and at most 2 other characters. "
            "Write 6 to 9 lines in total, about 60 to 90 words altogether. "
        )
    return (
        f"Write {GENRE_BRIEF[genre]}. {size}"
        f"{LANG_BRIEF[lang]} "
        "Use Indian names and Indian settings, festivals and foods. "
        "No copyrighted characters, brands or songs. "
        f"You may reuse these existing characters: {cast}. "
        'Each character needs a short Roman-letter "name", a "gender" ("m" or "f"), an '
        '"age" ("child", "adult" or "old") and a "look": one sentence describing their face, '
        "hair and clothes for an illustrator (kid-friendly). " + label_note +
        f'Give every line a "scene", chosen from: {known}. '
        "Reply with ONLY JSON in this exact shape, no other text:\n"
        '{"title": "...", "characters": [{"name": "Chintu", "label": "...", "gender": "m", '
        '"age": "child", "look": "..."}], "lines": [{"speaker": "Narrator", "text": "...", '
        '"scene": "gali"}, {"speaker": "Chintu", "text": "...", "scene": "gali"}]}'
    )


def _clean_script(data, genre, lang, library, fmt="short"):
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
            lines.append({"speaker": speaker, "text": text, "scene": scene, "cast": None})
    if len(lines) < 3:
        raise ValueError("script has too few lines")

    speakers = []
    for line in lines:
        if line["speaker"] != NARRATOR and line["speaker"] not in speakers:
            speakers.append(line["speaker"])
    if len(speakers) > MAX_CHARACTERS[fmt]:
        raise ValueError(f"script has more than {MAX_CHARACTERS[fmt]} characters")

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
        "tagline": TAGLINE[genre][lang],
        "genre": genre,
        "lang": lang,
        "format": fmt,
        "narrator": narrator_entry(genre, lang, library),
        "characters": characters,
        "lines": lines,
    }


def script_from_gemini(genre, lang, api_key, library, fmt="short"):
    """Ask Gemini for a new script. Raises an exception on any problem."""
    response = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": api_key},  # header, so the key never shows up in error messages
        json={
            "contents": [{"parts": [{"text": _gemini_prompt(genre, lang, library, fmt)}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
        },
        timeout=180 if fmt == "long" else 60,
    )
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    # Sometimes models wrap JSON in ``` fences; strip them just in case.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return _clean_script(json.loads(text), genre, lang, library, fmt)


# ---------------------------------------------------------------------------
# Built-in samples
# ---------------------------------------------------------------------------
def build_sample(sample, genre, lang, library, fmt="short"):
    """Turn one entry of SAMPLES / LONG_SAMPLES into a script dict in the chosen language.

    Scene markers are {line number: scene} or {line number: [scene, [character ids]]}.
    """
    by_id = {cid: library.find(cid) for cid in sample["characters"]}
    if lang != "hindi" and is_hindi_only(sample, fmt):
        print(f"[script] '{sample['id']}' is written in Hindi only, so this video will be in Hindi.")
        lang = "hindi"
    column = LANG_COLUMN[lang] if fmt == "short" else 1  # long stories are Hindi only
    scenes = sample.get("scenes", {})
    scene, cast = CONFIG["genres"][genre].get("default_scene"), None
    lines = []
    for number, line in enumerate(sample["lines"]):
        if number in scenes:
            marker = scenes[number]
            if isinstance(marker, str):
                scene, cast = marker, None
            else:
                scene, cast = marker[0], [by_id[cid]["name"] for cid in marker[1]]
        lines.append({"speaker": line[0], "text": line[column], "scene": scene, "cast": cast})
    return {
        "id": sample["id"],
        "source": sample.get("source", ""),
        "title": sample["title"][lang],
        "tagline": sample.get("tagline", TAGLINE[genre])[lang] if fmt == "long" else "",
        "genre": genre,
        "lang": lang,
        "format": fmt,
        "narrator": narrator_entry(genre, lang, library),
        "characters": [character_entry(by_id[c], lang) for c in sample["characters"]],
        "lines": lines,
    }


def is_hindi_only(sample, fmt="short"):
    """Long stories, and short ones whose lines are just (speaker, hindi)."""
    return fmt == "long" or all(len(line) == 2 for line in sample["lines"])


def samples_for(fmt):
    return SAMPLES if fmt == "short" else LONG_SAMPLES


def sample_scripts(genre, lang, library, fmt="short"):
    """All built-in scripts for the genre, in random order."""
    scripts = [build_sample(s, genre, lang, library, fmt) for s in samples_for(fmt).get(genre, [])
               if fmt == "long" or lang == "hindi" or not is_hindi_only(s)]  # random picks keep the language
    random.shuffle(scripts)
    return scripts


def story_ids():
    """{story id: (genre, format)} for every built-in story."""
    ids = {}
    for fmt in ("short", "long"):
        for genre, samples in samples_for(fmt).items():
            for sample in samples:
                ids[sample["id"]] = (genre, fmt)
    return ids


def get_script(genre, lang, library, use_ai=True, story=None, fmt="short"):
    """Main entry point: return a script dict.

    story: id of a built-in story (for example "birbal_khichdi"); skips Gemini.
    fmt:   "short" (30-60 s) or "long" (5-7 min).
    """
    if lang not in LANGS:
        raise ValueError(f"Unknown language '{lang}'. Choose from: {', '.join(LANGS)}")
    if genre not in GENRES:
        raise ValueError(f"Unknown genre '{genre}'. Choose from: {', '.join(GENRES)}")
    if fmt == "long" and lang != "hindi" and (story or not (use_ai and os.environ.get("GEMINI_API_KEY"))):
        print(f"[script] The built-in long stories are in Hindi only, so this video will be in Hindi. "
              f"(Set GEMINI_API_KEY for long {lang} stories.)")
        lang = "hindi"
    if story:
        for sample in samples_for(fmt).get(genre, []):
            if sample["id"] == story:
                print(f"[script] Using built-in story: {sample['title'].get(lang) or sample['title']['hindi']}")
                return build_sample(sample, genre, lang, library, fmt)
        raise ValueError(f"No {fmt} story '{story}' in genre {genre}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if use_ai and api_key:
        try:
            script = script_from_gemini(genre, lang, api_key, library, fmt)
            print(f"[script] Gemini wrote: {script['title']} ({len(script['lines'])} lines)")
            return script
        except Exception as error:  # network error, bad JSON, quota, ...
            print(f"[script] Gemini failed ({error}); using a built-in script instead.")

    scripts = sample_scripts(genre, lang, library, fmt)
    if not scripts:
        raise SystemExit(f"There is no built-in {fmt} story for '{genre}'. Set GEMINI_API_KEY so Gemini can "
                         f"write one, or use --genre kids_story (built-in long stories: "
                         f"{', '.join(i for i, (g, f) in story_ids().items() if f == fmt)}).")
    script = scripts[0]
    print(f"[script] Using built-in script: {script['title']}")
    return script
