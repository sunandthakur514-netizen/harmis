"""Scene pictures ("shots"): one full picture per part of the story, showing the
characters DOING what happens there (the tortoise holding the stick, flying with
the swans, ...), instead of the same cut-out pasted on every background.

1. plan():    split the story into shots. A new shot starts when the scene changes,
              at every line that has an "action" in the story, and after
              `max_lines_per_shot` lines (so the picture changes regularly).
2. describe(): what each shot shows, in English, best first:
              the story's own "actions" -> Gemini (one request for the whole story,
              cached) -> the English line (built-in short stories) -> a simple
              "the characters together here".
3. prompts:   fixed character descriptions + the same style words and the same
              seed for every shot of a story, so the characters stay recognisable.
              Gemini image also gets each character's own picture as a reference.

Pictures are cached in cache/shots/<story>/ (not committed: every story is
published once).
"""

import hashlib
import json
import os
import re
import zlib

import requests

from .config import CONFIG, PROJECT_DIR
from .script import NARRATOR

SHOT_DIR = os.path.join(PROJECT_DIR, "cache", "shots")
TEXT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def settings():
    return CONFIG.get("shots", {})


def story_key(script):
    """Folder name for a story's shots."""
    key = script.get("id") or re.sub(r"[^a-z0-9]+", "_", script["title"].lower()).strip("_")
    return key or "story"


def story_seed(script):
    return zlib.crc32(story_key(script).encode()) % 100000


def action_fields(action):
    """A story's action is a sentence, or a dict with more detail for the pictures:
    {"action": "...", "prop": "a wooden stick held in the beak",
     "closeups": {character id: "what only this character is doing"},
     "wide": "small tortoise on a rock on the left, two swans flying far right in the sky"}"""
    if isinstance(action, dict):
        return {"action": action.get("action"), "prop": action.get("prop") or "",
                "closeups": dict(action.get("closeups") or {}), "wide": action.get("wide") or ""}
    return {"action": action, "prop": "", "closeups": {}, "wide": ""}


def plan(script, library):
    """Split the lines into shots. Sets line["shot"] and returns the shots:
    [{"index", "scene", "lines": [line numbers], "cast": [character ids], "action": None}]."""
    limit = int(settings().get("max_lines_per_shot", {}).get(script.get("format", "short"), 3))
    by_name = {c["name"]: c["id"] for c in script["characters"]}
    shots = []
    for number, line in enumerate(script["lines"]):
        cast_key = tuple(line["cast"]) if line.get("cast") is not None else None
        new = (not shots or line.get("scene") != shots[-1]["scene"] or cast_key != shots[-1]["cast_key"]
               or line.get("action") or len(shots[-1]["lines"]) >= limit)
        if new:
            shots.append({"index": len(shots), "scene": line.get("scene"), "cast_key": cast_key,
                          "lines": [], "cast": [], **action_fields(line.get("action"))})
        shots[-1]["lines"].append(number)
        line["shot"] = shots[-1]["index"]
    everyone = [c["id"] for c in script["characters"]]
    for shot in shots:
        if shot["cast_key"] is not None:  # long stories can say who is on screen
            shot["cast"] = [by_name[name] for name in shot["cast_key"] if name in by_name]
        else:
            speakers = [by_name[script["lines"][n]["speaker"]] for n in shot["lines"]
                        if script["lines"][n]["speaker"] in by_name]
            shot["cast"] = list(dict.fromkeys(speakers)) or everyone[:3]
            if script.get("format", "short") == "short":
                shot["cast"] = everyone  # short stories: the whole (small) cast
        del shot["cast_key"]
    return shots


# ---------------------------------------------------------------------------
# What each shot shows
# ---------------------------------------------------------------------------
def _gemini_actions(script, shots, library):
    """One Gemini text request for the whole story: [{"action", "characters"}] per shot."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    cast = "\n".join(f'- id "{c["id"]}", name {c["name"]}: {library.characters[c["id"]]["description"].strip()}'
                     for c in script["characters"])
    parts = []
    for shot in shots:
        place = library.scenes.get(shot["scene"], shot["scene"] or "")
        lines = "\n".join(f'  {script["lines"][n]["speaker"]}: {script["lines"][n]["text"]}' for n in shot["lines"])
        parts.append(f"Shot {shot['index']} (place: {place}; characters who may appear: "
                     f"{', '.join(shot['cast']) or 'none'}):\n{lines}")
    prompt = (
        "You are the art director of a cartoon for Indian children. For every shot below, write ONE "
        "English sentence (at most 30 words) describing exactly what the picture shows: which characters "
        "are visible, what they are DOING (pose, action, expression) and where. Be concrete and visual, "
        "show the key moment of the shot, keep it gentle and kid-friendly, no text or speech bubbles in "
        "the picture. Use the character names given. Also give: \"prop\": the one object the "
        "story needs to be visible in this shot (for example \"a wooden stick held in the beak\"), or \"\"; "
        "\"closeups\": for every visible character id, what ONLY that character is doing (do not "
        "mention the other characters); \"wide\": the same moment as one wide picture with each "
        "character's place (for example \"small tortoise on a rock on the left, two swans flying far "
        "right in the sky\").\n\n"
        f"Story: {script['title']}\nCharacters:\n{cast}\n\n" + "\n\n".join(parts) +
        '\n\nAnswer with JSON only: [{"shot": 0, "action": "...", "characters": ["id", ...], "prop": "...", '
        '"closeups": {"id": "..."}, "wide": "..."}, ...]'
    )
    model = settings().get("planner_model", "gemini-2.5-flash")
    response = requests.post(TEXT_URL.format(model=model), headers={"x-goog-api-key": key}, timeout=120,
                             json={"contents": [{"parts": [{"text": prompt}]}],
                                   "generationConfig": {"responseMimeType": "application/json",
                                                        "temperature": 0.6}})
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text)


def describe(script, shots, library):
    """Fill in shot["action"] (and maybe a better shot["cast"])."""
    folder = os.path.join(SHOT_DIR, story_key(script))
    content = json.dumps([[script["lines"][n]["text"] for n in s["lines"]] for s in shots], ensure_ascii=False)
    cache = os.path.join(folder, f"plan_{hashlib.sha1(content.encode()).hexdigest()[:12]}.json")
    planned = None
    if any(not s["action"] for s in shots):
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as file:
                planned = json.load(file)
        else:
            try:
                planned = _gemini_actions(script, shots, library)
                if planned:
                    os.makedirs(folder, exist_ok=True)
                    with open(cache, "w", encoding="utf-8") as file:
                        json.dump(planned, file, ensure_ascii=False, indent=1)
                    print(f"[shots] Gemini described {len(planned)} shots")
            except Exception as error:
                print(f"[shots] Gemini could not describe the shots ({type(error).__name__}); "
                      "using simpler descriptions")
    by_index = {int(item.get("shot", -1)): item for item in planned or [] if isinstance(item, dict)}
    known = {c["id"] for c in script["characters"]}
    names = {c["id"]: c["name"] for c in script["characters"]}
    for shot in shots:
        if shot["action"]:
            continue
        item = by_index.get(shot["index"])
        if item and item.get("action"):
            shot["action"] = str(item["action"]).strip()
            shot["prop"] = str(item.get("prop") or "").strip()
            shot["wide"] = str(item.get("wide") or "").strip()
            shot["closeups"] = {k: str(v) for k, v in (item.get("closeups") or {}).items() if k in known}
            cast = [c for c in item.get("characters", []) if c in known]
            if cast:
                shot["cast"] = cast
            continue
        english = [script["lines"][n].get("english") for n in shot["lines"]]
        english = [e for e in english if e]
        who = " and ".join(names[c] for c in shot["cast"])
        if english:
            shot["action"] = (f"{who}: " if who else "") + " ".join(english)[:220]
        else:
            shot["action"] = f"{who} together in this place, in the middle of a story" if who else \
                "the place where the story happens"
    return shots


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def species(data):
    """What kind of creature a character is: all people count as one kind (several people in
    one picture are fine); every animal character is its own kind unless it says `species:`."""
    if data.get("type", "human") != "animal":
        return "human"
    return data.get("species") or data["id"]


def species_groups(shot, library):
    """The shot's characters grouped by kind: [[ids of one kind], ...]."""
    groups = {}
    for char_id in shot["cast"]:
        if char_id in library.characters:
            groups.setdefault(species(library.characters[char_id]), []).append(char_id)
    return list(groups.values())


def prompts(shot, script, library, style_words, short_style, safe_core, mood, composition):
    """(full prompt, compact prompt for ~77-token models, [(name, character id)]).

    The full prompt is for models that can draw several different characters together
    (Gemini); the key prop of the story always comes first so it is not left out.
    """
    place = library.scenes.get(shot["scene"], "") if shot["scene"] else ""
    characters = [library.characters[c] for c in shot["cast"] if c in library.characters]
    looks = "; ".join(f"{d['name']}: {d['description'].strip()}" for d in characters)
    prop = shot.get("prop") or ""
    full = (
        (f"Key object that must be clearly visible: {prop}. " if prop else "")
        + f"{style_words}. A picture from an Indian children's cartoon story. {shot['action']}. "
        + (f"Setting: {place}. " if place else "") + (f"{mood}. " if mood else "")
        + (f"The characters always look exactly like this: {looks}. " if looks else "")
        + "Every character is a separate, complete creature (no hybrids, no merged animals). "
        + f"Full scene with background, characters acting naturally in it, {composition}, "
          "cinematic, expressive faces, no text, no speech bubbles, no captions. "
        + CONFIG["safety"]["always_add"]
    )
    short_looks = ", ".join(" ".join(d["description"].split()[:9]) for d in characters)
    compact = ((f"{prop}, " if prop else "") + f"{short_style}, {safe_core}, {shot['action']}, {short_looks}, "
               f"{' '.join(place.split()[:12])}")
    return full, compact, [(d["name"], d["id"]) for d in characters]


def mentions_prop(prop, text):
    """True if the text talks about the prop ("a long wooden stick" ... "holding a stick")."""
    words = [w for w in re.findall(r"[a-z]+", prop.lower()) if len(w) > 3 and w not in ("with", "held", "long")]
    return any(w in text.lower() for w in words)


def local_prompts(shot, library, short_style, safe_core):
    """Prompts for a local model, ONE kind of character per picture.

    Returns [(key, prompt)]: key "" for a single picture, or a character id for each
    close-up (config.yaml -> shots: local_sd_mode). Local models read only ~77 tokens,
    so the prop and the action come first and the style words after them.
    """
    place = " ".join((library.scenes.get(shot["scene"], "") if shot["scene"] else "").split()[:12])
    prop = shot.get("prop") or ""
    tail = f"{short_style}, {safe_core}, {place}"
    groups = species_groups(shot, library)
    if len(groups) <= 1:  # one kind of character (or none): the whole moment in one picture
        looks = ", ".join(" ".join(library.characters[c]["description"].split()[:10]) for c in (groups or [[]])[0])
        return [("", f"{prop + ', ' if prop else ''}{shot['action']}, {looks}, {tail}")]
    if settings().get("local_sd_mode", "closeups") == "wide":
        layout = shot.get("wide") or ", ".join(
            f"{' '.join(library.characters[g[0]]['description'].split()[:8])} on the {side}"
            for g, side in zip(groups, ("left", "right", "far back")))
        return [("", f"{prop + ', ' if prop else ''}wide shot, {layout}, separate characters, {tail}")]
    pictures = []
    for group in groups:  # one close-up per kind of character
        lead = library.characters[group[0]]
        doing = shot.get("closeups", {}).get(group[0]) or "reacting with a big expressive face"
        first = f"{prop}, " if prop and mentions_prop(prop, doing) else ""
        pictures.append((group[0], f"{first}close-up of {' '.join(lead['description'].split()[:12])}, {doing}, "
                                   f"no other animals, {tail}"))
    return pictures


def narrator_only(script, shot):
    return all(script["lines"][n]["speaker"] == NARRATOR for n in shot["lines"])
