"""New original stories from Gemini, one theme per weekday (config.yaml -> weekdays, themes).

    python -m harmis.storygen --slot auto --out cache/story.json      # today's theme
    python -m harmis.storygen --theme mythology --format short --out cache/story.json
    python -m harmis.main --story-file cache/story.json                # make the video

Each run asks Gemini (GEMINI_API_KEY) for a NEW Hindi story in the samples format:
title, characters with fixed visual descriptions, scenes with a place, an action
(what the picture shows) and dialogue, and a moral. The story is checked before it
is used:
  * kid-safe: no unsafe words (config.yaml -> storygen: unsafe_words) and, if
    `review` is on, a second Gemini request that double-checks it,
  * the right length (45-55 s for a short, 5-7 min for a long video),
  * the theme's own characters (Chintu & Golu on Tuesdays, ...) and valid speakers,
  * not a repeat of any title already published (output/published.csv).
Up to `tries` attempts; each new attempt is told what was wrong. If Gemini still
fails (or there is no key), an unpublished built-in story is used instead.

The CLI prints one JSON line for the workflows:
    {"args": "--story-file cache/story.json", "story": "ai_...", "theme": "...",
     "slot": "short", "source": "gemini" | "built-in" | "none"}
"""

import argparse
import datetime
import json
import os
import re
import sys
import zlib

import requests

from .config import CONFIG, PROJECT_DIR

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
NARRATOR = "Narrator"
MAX_CHARACTERS = {"short": 3, "long": 4}
TEMP_CHARACTER_DIR = os.path.join(PROJECT_DIR, "cache", "characters")


def settings():
    return CONFIG.get("storygen", {})


def theme_for(slot, now=None):
    """Today's theme (India time) for a short or long video."""
    day = (now or datetime.datetime.now(IST)).astimezone(IST).weekday()
    return CONFIG["weekdays"][day][slot]


def norm_title(title):
    return re.sub(r"[\W_]+", "", str(title).lower())


def published_titles():
    from .publish import read_log
    return {norm_title(row["title"]) for row in read_log() if row.get("title")}


def hindi_words(text):
    return len(re.findall(r"\S+", text))


# ---------------------------------------------------------------------------
# Asking Gemini
# ---------------------------------------------------------------------------
def _ask(prompt, temperature=1.0):
    model = settings().get("model", "gemini-2.5-flash")
    response = requests.post(URL.format(model=model), headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                             timeout=240, json={"contents": [{"parts": [{"text": prompt}]}],
                                                "generationConfig": {"temperature": temperature,
                                                                     "responseMimeType": "application/json"}})
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))


def story_prompt(theme_name, fmt, library, avoid, feedback=""):
    theme = CONFIG["themes"][theme_name]
    words, lines, scenes = (settings()[k][fmt] for k in ("words", "lines", "scenes"))
    must = [library.characters[c] for c in theme.get("characters", []) if c in library.characters]
    may = [library.characters[c] for c in theme.get("allowed", []) if c in library.characters]
    cast = "\n".join(f'- {d["name"]} ({d["label"]["hindi"]}): {" ".join(d["description"].split())}'
                     for d in must + may)
    rhyme = theme["genre"] == "kids_rhyme"
    length = (f"It is for a {'45 to 55 second vertical video' if fmt == 'short' else '5 to 7 minute video'}: "
              f"{lines[0]}-{lines[1]} lines in {scenes[0]}-{scenes[1]} scenes, {words[0]}-{words[1]} Hindi words "
              "of spoken text altogether. ")
    if fmt == "long":
        length += ("Give it a clear beginning, a problem, a surprising twist and a happy ending. The Narrator "
                   "tells most of it; characters speak short lines in between. Keep each scene to 3-5 lines. ")
    return (
        f"You write for 'Kahani Khazana', a made-for-kids Hindi YouTube channel (children aged 4-10). "
        f"Write {theme['brief']}. {length}"
        "Language: simple, warm spoken Hindi in Devanagari script; short sentences children understand. "
        "Indian names, places, food and festivals. Original: do not copy any existing book, film, cartoon, "
        "brand, song or copyrighted character. Strictly kid-safe: no violence, no weapons, no death, no "
        "scary or horror content, no bad words, nobody is mocked for their looks; kind and positive.\n"
        + (f"These characters MUST appear: {', '.join(d['name'] for d in must)}.\n" if must else "")
        + (f"Existing characters you may use (keep their exact names; their looks are fixed):\n{cast}\n" if cast else "")
        + f"At most {MAX_CHARACTERS[fmt]} characters besides the Narrator. A new character needs a Roman-letter "
          '"name", a Devanagari "label", "gender" (m/f), "age" (child/adult/old), "type" (human/animal) and a '
          '"look": ONE English sentence fixing exactly how they look (species, face, hair, clothes, colours) '
          "so an illustrator draws them the same in every picture.\n"
          'Every scene has a "place" (English, the location only, no people or animals in it), an "action" '
          "(English, what the picture shows: which characters are there and what they are DOING, pose and "
          'expression) and its "lines" (speaker "Narrator" or a character name, text in Hindi).\n'
        + ("It is a song: every line rhymes with the next one and one catchy line repeats.\n" if rhyme else
           'The very last line is the Narrator giving the moral, starting with "सीख:".\n')
        + (f"Do NOT reuse any of these titles or their plots: {', '.join(sorted(avoid)[:60])}.\n" if avoid else "")
        + (f"Your previous answer had these problems, fix them: {feedback}\n" if feedback else "")
        + 'Reply with ONLY JSON: {"id": "short_english_slug", "title": "Hindi title", "moral": "Hindi moral", '
          '"characters": [{"name": "...", "label": "...", "gender": "m", "age": "child", "type": "human", '
          '"look": "..."}], "scenes": [{"place": "...", "action": "...", "lines": [{"speaker": "Narrator", '
          '"text": "..."}]}]}'
    )


def problems(data, theme_name, fmt, library, avoid):
    """What is wrong with a story from Gemini ([] = it can be used)."""
    found = []
    theme = CONFIG["themes"][theme_name]
    if not isinstance(data, dict):
        return ["the answer is not a JSON object"]
    title = str(data.get("title", "")).strip()
    if not re.search(r"[ऀ-ॿ]", title):
        found.append("the title must be in Hindi (Devanagari)")
    if norm_title(title) in avoid:
        found.append(f"the title '{title}' was already published; write a different story")
    scenes = [s for s in data.get("scenes", []) if isinstance(s, dict)]
    lines = [l for s in scenes for l in s.get("lines", []) if isinstance(l, dict) and str(l.get("text", "")).strip()]
    low, high = settings()["scenes"][fmt]
    if not low <= len(scenes) <= high + 2:
        found.append(f"use {low}-{high} scenes (you used {len(scenes)})")
    low, high = settings()["lines"][fmt]
    if not low <= len(lines) <= high + 4:
        found.append(f"use {low}-{high} lines (you used {len(lines)})")
    words = sum(hindi_words(str(l["text"])) for l in lines)
    low, high = settings()["words"][fmt]
    if not low * 0.9 <= words <= high * 1.1:
        found.append(f"the spoken text must be {low}-{high} Hindi words (it was {words})")
    names = {str(c.get("name", "")).strip().lower() for c in data.get("characters", []) if isinstance(c, dict)}
    speakers = {str(l.get("speaker", "")).strip() for l in lines} - {NARRATOR, "narrator", "कथावाचक"}
    unknown = [s for s in speakers if s.lower() not in names and library.find(s) is None]
    if unknown:
        found.append(f"these speakers are not in the characters list: {', '.join(unknown)}")
    if len(speakers) > MAX_CHARACTERS[fmt]:
        found.append(f"at most {MAX_CHARACTERS[fmt]} speaking characters besides the Narrator")
    for char_id in theme.get("characters", []):
        name = library.characters[char_id]["name"]
        if name.lower() not in {s.lower() for s in speakers}:
            found.append(f"{name} must be one of the speaking characters")
    hindi = sum(len(re.findall(r"[ऀ-ॿ]", str(l["text"]))) for l in lines)
    if lines and hindi < 0.5 * sum(len(str(l["text"])) for l in lines):
        found.append("write the lines in Hindi (Devanagari)")
    if theme["genre"] != "kids_rhyme" and lines and not str(lines[-1]["text"]).strip().startswith("सीख"):
        found.append('the last line must be the Narrator saying "सीख: ..."')
    if any(not str(s.get("place", "")).strip() or not str(s.get("action", "")).strip() for s in scenes):
        found.append("every scene needs a place and an action")
    everything = json.dumps(data, ensure_ascii=False).lower()
    bad = [w for w in settings().get("unsafe_words", []) + CONFIG["safety"].get("blocked_words", [])
           if str(w).lower() in everything]
    if bad:
        found.append(f"remove these words, this is a kids channel: {', '.join(bad)}")
    return found


def review(sample):
    """A second Gemini opinion: is it really kid-safe? Returns (ok, reason)."""
    text = "\n".join(f"{speaker}: {line}" for speaker, line in sample["lines"])
    verdict = _ask(
        "You check stories for a Hindi YouTube channel for children aged 4-10 (made for kids). Is this story "
        "completely safe and suitable: no violence, no scary or horror content, no death, no weapons, no "
        "unkind mocking, nothing disrespectful to any religion or deity, no copyrighted characters? "
        'Answer JSON only: {"safe": true or false, "reason": "short reason"}\n\n'
        f"Title: {sample['title']['hindi']}\n{text}", temperature=0.0)
    return bool(verdict.get("safe")), str(verdict.get("reason", ""))


# ---------------------------------------------------------------------------
# Gemini answer -> samples format (like harmis/samples_long.py, Hindi only)
# ---------------------------------------------------------------------------
def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")[:30] or "story"


def to_sample(data, theme_name, fmt, library):
    theme = CONFIG["themes"][theme_name]
    title = str(data["title"]).strip()
    story_id = f"ai_{slug(data.get('id') or title)}_{zlib.crc32(title.encode()) % 10000:04d}"
    given = {str(c.get("name", "")).strip().lower(): c for c in data.get("characters", []) if isinstance(c, dict)}
    names, new_characters = {}, []  # speaker as written -> library name

    def character_for(speaker):
        if speaker.lower() in names:
            return names[speaker.lower()]
        known = library.find(speaker)
        if known is not None:
            names[speaker.lower()] = (known["id"], known["name"])
        else:
            info = given.get(speaker.lower(), {})
            char_id = f"{story_id}_{slug(speaker)}"
            new_characters.append({
                "id": char_id, "name": speaker, "label": str(info.get("label") or speaker),
                "gender": "f" if str(info.get("gender", "")).lower().startswith("f") else "m",
                "age": info.get("age") if info.get("age") in ("child", "adult", "old") else "adult",
                "type": "animal" if str(info.get("type", "")).lower() == "animal" else "human",
                "description": " ".join(str(info.get("look") or f"a friendly Indian {speaker}").split())})
            names[speaker.lower()] = (char_id, speaker)
        return names[speaker.lower()]

    lines, scene_marks, actions, new_scenes, cast = [], {}, {}, {}, []
    for number, scene in enumerate(s for s in data["scenes"] if isinstance(s, dict)):
        scene_name = f"{story_id}_s{number:02d}"
        new_scenes[scene_name] = " ".join(str(scene["place"]).split())
        scene_marks[len(lines)] = scene_name
        actions[len(lines)] = " ".join(str(scene["action"]).split())
        for line in scene.get("lines", []):
            text = " ".join(str(line.get("text", "")).split())
            if not text:
                continue
            speaker = str(line.get("speaker", "")).strip()
            if speaker.lower() in ("narrator", "कथावाचक", ""):
                speaker = NARRATOR
            else:
                char_id, speaker = character_for(speaker)
                if char_id not in cast:
                    cast.append(char_id)
            lines.append((speaker, text))
    return {
        "id": story_id, "title": {"hindi": title}, "tagline": {"hindi": theme["label"]["hindi"]},
        "source": "", "theme": theme_name, "genre": theme["genre"], "format": fmt, "mood": theme.get("mood", ""),
        "moral": str(data.get("moral", "")).strip(), "characters": cast, "scenes": scene_marks,
        "actions": actions, "lines": lines, "new_characters": new_characters, "new_scenes": new_scenes,
        "made_by": "gemini",
    }


def register(sample, library):
    """Make a generated story's own characters and places known to the library (this run only)."""
    for info in sample.get("new_characters", []):
        if info["id"] not in library.characters:
            data = {key: info[key] for key in ("name", "gender", "age", "type", "description")}
            data.update({"id": info["id"], "label": {"hindi": info["label"], "english": info["name"]},
                         "seed": zlib.crc32(info["id"].encode()) % 100000,
                         "folder": os.path.join(TEMP_CHARACTER_DIR, info["id"])})
            os.makedirs(data["folder"], exist_ok=True)
            library.characters[info["id"]] = data
    library.scenes.update(sample.get("new_scenes", {}))


def load_story_file(path, library):
    with open(path, encoding="utf-8") as file:
        sample = json.load(file)
    sample["lines"] = [tuple(line) for line in sample["lines"]]
    sample["scenes"] = {int(k): v for k, v in sample["scenes"].items()}
    sample["actions"] = {int(k): v for k, v in sample.get("actions", {}).items()}
    register(sample, library)
    return sample


def generate(theme_name, fmt, library, tries=None):
    """A checked, new story from Gemini in the samples format, or None."""
    if not os.environ.get("GEMINI_API_KEY"):
        print("[storygen] No GEMINI_API_KEY: cannot write a new story.", file=sys.stderr)
        return None
    avoid = published_titles()
    feedback = ""
    for attempt in range(1, int(tries or settings().get("tries", 3)) + 1):
        try:
            data = _ask(story_prompt(theme_name, fmt, library, avoid, feedback))
        except Exception as error:
            print(f"[storygen] try {attempt}: Gemini failed ({type(error).__name__}: "
                  f"{' '.join(str(error).split())[:120]})", file=sys.stderr)
            feedback = ""
            continue
        found = problems(data, theme_name, fmt, library, avoid)
        if not found:
            sample = to_sample(data, theme_name, fmt, library)
            if settings().get("review", True):
                try:
                    ok, reason = review(sample)
                except Exception as error:
                    ok, reason = False, f"the safety check could not run ({type(error).__name__})"
                if not ok:
                    found = [f"a safety review rejected it: {reason}"]
            if not found:
                words = sum(hindi_words(text) for _, text in sample["lines"])
                print(f"[storygen] try {attempt}: '{sample['title']['hindi']}' ({len(sample['lines'])} lines, "
                      f"{words} words) is OK", file=sys.stderr)
                return sample
        print(f"[storygen] try {attempt} rejected: {'; '.join(found)}", file=sys.stderr)
        feedback = "; ".join(found)
    return None


def fallback_story(theme_name, fmt):
    """An unpublished built-in story that fits the theme (or any unpublished one), or None."""
    from . import daily, script
    theme = CONFIG["themes"][theme_name]
    used = daily.used_stories()
    candidates = [s for s in daily.candidates(fmt) if s not in used]
    sources = theme.get("fallback_sources", [])
    by_id = {s["id"]: (genre, s) for genre, samples in script.samples_for(fmt).items() for s in samples}
    fitting = [s for s in candidates if by_id[s][0] == theme["genre"] and (not sources or by_id[s][1].get("source") in sources)]
    return (fitting or candidates or [None])[0]


def main():
    parser = argparse.ArgumentParser(description="Write today's new story with Gemini (or pick a built-in one).")
    parser.add_argument("--slot", "--format", dest="slot", default="auto", choices=["auto", "short", "long"])
    parser.add_argument("--theme", choices=sorted(CONFIG["themes"]), help="default: today's theme (weekday, IST)")
    parser.add_argument("--out", default=os.path.join(PROJECT_DIR, "cache", "story.json"))
    parser.add_argument("--no-gemini", action="store_true", help="only use built-in stories")
    args = parser.parse_args()
    from . import daily
    from .library import Library
    from .providers import ImageChain
    slot = daily.auto_slot() if args.slot == "auto" else args.slot
    theme_name = args.theme or theme_for(slot)
    theme = CONFIG["themes"][theme_name]
    print(f"[storygen] {slot} video, theme {theme_name} ({theme['label']['english']})", file=sys.stderr)
    library = Library(ImageChain([]), CONFIG["defaults"]["style"], theme["genre"], fmt=slot)
    sample = None if args.no_gemini else generate(theme_name, slot, library)
    if sample is not None:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as file:
            json.dump(sample, file, ensure_ascii=False, indent=1)
        result = {"args": f"--story-file {args.out}", "story": sample["id"], "source": "gemini"}
    else:
        story = fallback_story(theme_name, slot)
        result = ({"args": f"--story {story} --format {slot}", "story": story, "source": "built-in"} if story
                  else {"args": "", "story": "none", "source": "none"})
        print(f"[storygen] Using {result['source']} story: {story}", file=sys.stderr)
    print(json.dumps({**result, "theme": theme_name, "slot": slot}, ensure_ascii=False))


if __name__ == "__main__":
    main()
