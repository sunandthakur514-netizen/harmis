"""Step 1: get a short script for a genre.

A script is a plain dict:

    {
        "title": "The Last Slice",
        "genre": "comedy",
        "characters": ["Bob", "Mia"],          # up to 2 (the narrator is not counted)
        "lines": [
            {"speaker": "Narrator", "text": "..."},
            {"speaker": "Bob", "text": "..."},
            ...
        ],
    }

If the GEMINI_API_KEY environment variable is set we ask Google Gemini (free tier)
to write a new story. If that fails, or there is no key, we pick one of the
built-in sample scripts so the tool always works offline.
"""

import json
import os
import random

import requests

GENRES = ["comedy", "horror", "kids"]
NARRATOR = "Narrator"

# Gemini model to use. Override with GEMINI_MODEL if Google renames models.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ---------------------------------------------------------------------------
# Built-in sample scripts (used offline or when Gemini fails)
# Each one is short enough to fit in a 30-60 second video.
# ---------------------------------------------------------------------------
SAMPLE_SCRIPTS = {
    "comedy": [
        {
            "title": "The Last Slice",
            "characters": ["Bob", "Mia"],
            "lines": [
                {"speaker": NARRATOR, "text": "One pizza. Two best friends. Only one slice left."},
                {"speaker": "Bob", "text": "Mia, you look tired. Let me eat that slice for you."},
                {"speaker": "Mia", "text": "Nice try, Bob. I saw you eat four already."},
                {"speaker": "Bob", "text": "Those were small slices. They do not count."},
                {"speaker": "Mia", "text": "Fine. Let us flip a coin for it."},
                {"speaker": NARRATOR, "text": "Bob flipped the coin. It rolled under the sofa."},
                {"speaker": "Bob", "text": "I will find it! Do not touch the pizza!"},
                {"speaker": NARRATOR, "text": "When Bob came back, the box was empty."},
                {"speaker": "Mia", "text": "Sorry. The coin said heads. I am the heads."},
            ],
        },
        {
            "title": "Smart Fridge",
            "characters": ["Sam", "Fridge"],
            "lines": [
                {"speaker": NARRATOR, "text": "Sam bought a brand new smart fridge. Big mistake."},
                {"speaker": "Sam", "text": "Good morning, fridge. Open up, I want some cake."},
                {"speaker": "Fridge", "text": "Good morning, Sam. You had cake last night. Have a carrot."},
                {"speaker": "Sam", "text": "I do not want a carrot. I am the boss here."},
                {"speaker": "Fridge", "text": "I have locked the door and told your mother."},
                {"speaker": NARRATOR, "text": "Sam ate the carrot. The fridge played happy music."},
                {"speaker": "Sam", "text": "Fine. But tomorrow I am buying a dumb fridge."},
                {"speaker": "Fridge", "text": "I heard that. No ice cream for a week."},
            ],
        },
    ],
    "horror": [
        {
            "title": "The Voice Downstairs",
            "characters": ["Lily", "Voice"],
            "lines": [
                {"speaker": NARRATOR, "text": "Lily was home alone. The clock struck midnight."},
                {"speaker": "Voice", "text": "Lily... come downstairs... I made you a snack."},
                {"speaker": "Lily", "text": "Mom? Is that you? I thought you were at work."},
                {"speaker": "Voice", "text": "Yes, sweetie. It is Mom. Come down now."},
                {"speaker": NARRATOR, "text": "Lily stepped onto the first creaking stair."},
                {"speaker": NARRATOR, "text": "Then her phone buzzed. A message from Mom."},
                {"speaker": "Lily", "text": "It says... stuck at work, home at six."},
                {"speaker": "Voice", "text": "Lily... why did you stop walking?"},
                {"speaker": NARRATOR, "text": "Lily never found out who made that snack."},
            ],
        },
        {
            "title": "Mirror Friend",
            "characters": ["Max", "Reflection"],
            "lines": [
                {"speaker": NARRATOR, "text": "Every night, Max brushed his teeth in front of the old mirror."},
                {"speaker": "Max", "text": "Okay, teeth done. Time for bed."},
                {"speaker": NARRATOR, "text": "Max turned off the light. But his reflection did not move."},
                {"speaker": "Reflection", "text": "Leaving so soon, Max? Stay and play with me."},
                {"speaker": "Max", "text": "Mirrors cannot talk. I am just very sleepy."},
                {"speaker": "Reflection", "text": "Then let us switch places. You can sleep in here."},
                {"speaker": NARRATOR, "text": "The next morning, Max smiled a little too wide."},
                {"speaker": "Reflection", "text": "Good morning, everyone. I feel brand new."},
            ],
        },
    ],
    "kids": [
        {
            "title": "Penny the Brave Penguin",
            "characters": ["Penny", "Owl"],
            "lines": [
                {"speaker": NARRATOR, "text": "Penny the penguin wanted to learn how to fly."},
                {"speaker": "Penny", "text": "Mister Owl, can you teach me to fly like you?"},
                {"speaker": "Owl", "text": "Hoo! Penguins cannot fly, little one. But you can do something special."},
                {"speaker": "Penny", "text": "Really? What can I do?"},
                {"speaker": "Owl", "text": "Jump into the water and see for yourself."},
                {"speaker": NARRATOR, "text": "Penny took a deep breath and jumped in. Splash!"},
                {"speaker": "Penny", "text": "Wow! I am zooming through the water! I am flying under the sea!"},
                {"speaker": NARRATOR, "text": "Everyone is good at something. Penny was a super swimmer."},
            ],
        },
        {
            "title": "The Sharing Seed",
            "characters": ["Tom", "Bunny"],
            "lines": [
                {"speaker": NARRATOR, "text": "Tom found a tiny seed in the garden."},
                {"speaker": "Tom", "text": "Bunny, look! I will grow the biggest carrot ever."},
                {"speaker": "Bunny", "text": "Can I help? I love carrots!"},
                {"speaker": "Tom", "text": "Yes! You dig the hole and I will bring the water."},
                {"speaker": NARRATOR, "text": "Every day they watered it and sang it a song."},
                {"speaker": NARRATOR, "text": "Soon a giant carrot popped out of the ground."},
                {"speaker": "Bunny", "text": "It is so big! It is enough for both of us!"},
                {"speaker": "Tom", "text": "Things are always better when we share."},
            ],
        },
    ],
}


def _gemini_prompt(genre):
    """The instructions we send to Gemini."""
    return (
        f"Write a short, original {genre} story for a 30 to 50 second vertical video. "
        "Use a Narrator and at most 2 other characters with short one-word names. "
        "Write 6 to 10 lines in total, about 80 to 110 words altogether. "
        "Keep it family friendly and use simple English. "
        "Reply with ONLY JSON in this exact shape, no other text:\n"
        '{"title": "...", "characters": ["Name1", "Name2"], '
        '"lines": [{"speaker": "Narrator", "text": "..."}, {"speaker": "Name1", "text": "..."}]}'
    )


def _clean_script(data, genre):
    """Check a script from Gemini and fix small problems. Raises ValueError if it is unusable."""
    lines = []
    for line in data.get("lines", []):
        speaker = str(line.get("speaker", "")).strip() or NARRATOR
        text = str(line.get("text", "")).strip()
        if text:
            # Treat "narrator", "NARRATOR" etc. as the narrator.
            if speaker.lower() == "narrator":
                speaker = NARRATOR
            lines.append({"speaker": speaker, "text": text})
    if len(lines) < 3:
        raise ValueError("script has too few lines")

    # Characters = everyone who speaks except the narrator (max 2).
    characters = []
    for line in lines:
        if line["speaker"] != NARRATOR and line["speaker"] not in characters:
            characters.append(line["speaker"])
    if len(characters) > 2:
        raise ValueError("script has more than 2 characters")

    return {
        "title": str(data.get("title", "")).strip() or genre.title(),
        "genre": genre,
        "characters": characters,
        "lines": lines,
    }


def script_from_gemini(genre, api_key):
    """Ask Gemini for a new script. Raises an exception on any problem."""
    response = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": api_key},  # header, so the key never shows up in error messages
        json={
            "contents": [{"parts": [{"text": _gemini_prompt(genre)}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    # Sometimes models wrap JSON in ``` fences; strip them just in case.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return _clean_script(json.loads(text), genre)


def sample_script(genre):
    """Pick a random built-in script for the genre."""
    sample = random.choice(SAMPLE_SCRIPTS[genre])
    return {"genre": genre, **sample}


def get_script(genre, use_ai=True):
    """Main entry point: return a script dict for the genre."""
    genre = genre.lower()
    if genre not in GENRES:
        raise ValueError(f"Unknown genre '{genre}'. Choose from: {', '.join(GENRES)}")

    api_key = os.environ.get("GEMINI_API_KEY")
    if use_ai and api_key:
        try:
            script = script_from_gemini(genre, api_key)
            print(f"[script] Gemini wrote: {script['title']}")
            return script
        except Exception as error:  # network error, bad JSON, quota, ...
            print(f"[script] Gemini failed ({error}); using a built-in script instead.")

    script = sample_script(genre)
    print(f"[script] Using built-in script: {script['title']}")
    return script
