"""Titles, descriptions and hashtags for a finished video (Hindi + English mix).

    python -m harmis.captions output/2026-10-15_kids_story_hindi.mp4

Reads <video>.story.json (written by harmis.main), or the story title from an
existing <video>.json, and saves <video>.json:

    {
      "story_title": "...",           # the story's own title (always in the titles below)
      "title": "...",                 # <= 90 characters
      "description": "...",
      "hashtags": ["#hindikahani", ...],
      "youtube":   {"title": ..., "description": ..., "tags": [...]},
      "instagram": {"caption": ...}
    }

With GEMINI_API_KEY set, Gemini writes them; otherwise simple templates are filled
from the story (title, moral, characters, genre) and the hashtag lists in
config.yaml. Names of copyrighted characters / brands are always removed.
"""

import json
import os
import re
import sys

import requests

from .config import CONFIG
from .library import make_safe

TITLE_MAX = 90
REMOVED_TAGS = {"#harmis"}  # never used in public text (the channel tag is #KahaniKhazana)


class CaptionsError(Exception):
    """Not enough information to write captions. The message says what to do."""


def channel_name():
    return CONFIG["publish"].get("channel_name", "Kahani Khazana")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Small phrases for the templates: (Hindi, English)
GENRE_WORDS = {
    "kids_story": ("बच्चों की कहानी", "Moral Story for Kids"),
    "kids_rhyme": ("बच्चों की कविता", "Hindi Rhyme for Kids"),
    "comedy": ("मज़ेदार कहानी", "Funny Family Story"),
    "horror": ("रहस्यमयी कहानी", "Mystery Story (13+)"),
}
SOURCE_WORDS = {"Panchatantra": "पंचतंत्र", "Jataka": "जातक कथा", "Akbar-Birbal": "अकबर-बीरबल",
                "Tenali Raman": "तेनाली रामन"}


def story_meta(video_path):
    """The story details saved next to the video.

    Uses <video>.story.json, or else the story title in an existing <video>.json.
    Without either, it refuses instead of inventing a generic title.
    """
    stem = os.path.splitext(video_path)[0]
    if os.path.exists(stem + ".story.json"):
        with open(stem + ".story.json", encoding="utf-8") as file:
            return json.load(file)
    if os.path.exists(stem + ".json"):
        with open(stem + ".json", encoding="utf-8") as file:
            saved = json.load(file)
        title = saved.get("story_title") or str(saved.get("title", "")).split(" | ")[0].replace("#shorts", "").strip()
        if title:
            print(f"[captions] No {os.path.basename(stem)}.story.json; using the story title from "
                  f"{os.path.basename(stem)}.json: {title}")
            return {"title": title, "genre": saved.get("genre", "kids_story"), "lang": saved.get("lang", "hindi"),
                    "format": saved.get("format", "short"), "characters": [], "summary": "", "moral": "",
                    "source": saved.get("source", ""), "tagline": ""}
    raise CaptionsError(
        f"No story details for {video_path}: neither {os.path.basename(stem)}.story.json nor a "
        f"{os.path.basename(stem)}.json with a title exists. Make the video again with `python -m harmis.main` "
        f"(it saves both), or create {os.path.basename(stem)}.json yourself with at least "
        '{"story_title": "...", "genre": "kids_story", "format": "short"}.')


def clean(text):
    """Remove blocked (copyrighted) names and extra spaces."""
    return re.sub(r"[ \t]{2,}", " ", make_safe(str(text))).strip()


def fit(text, limit):
    """Shorten text to `limit` characters at a word boundary."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" |,-")
    return cut + "…"


# Mythology tags that only fit when that deity is in the story.
DEITY_TAGS = {"#krishnastory": ("कृष्ण", "krishna"), "#balkrishna": ("कृष्ण", "krishna"),
              "#hanumanstory": ("हनुमान", "hanuman"), "#ganeshastory": ("गणेश", "ganesh")}


def theme_tags(meta, tags_cfg):
    """Hashtags for the weekday theme (config.yaml -> publish: hashtags: by_theme); mythology
    stories get their topic's tags (#KrishnaStory ...) and the common mythology ones."""
    topic = CONFIG.get("mythology", {}).get("topics", {}).get(meta.get("topic") or "")
    if topic:
        return list(topic.get("hashtags", [])) + list(CONFIG["mythology"].get("hashtags", []))
    tags = list(tags_cfg.get("by_theme", {}).get(meta.get("theme") or "", []))
    about = " ".join([str(meta.get("title", ""))] + [str(c) for c in meta.get("characters", [])]).lower()
    return [t for t in tags if t.lower() not in DEITY_TAGS or any(w in about for w in DEITY_TAGS[t.lower()])]


def hashtags_for(meta, platform):
    tags_cfg = CONFIG["publish"]["hashtags"]
    by_source = list(tags_cfg.get("by_source", {}).get(meta.get("source") or "", []))
    by_theme = theme_tags(meta, tags_cfg)
    genre_tags = list(tags_cfg.get(meta["genre"], []))
    tags = by_theme[:3] + genre_tags[:2] + by_source + by_theme[3:] + genre_tags[2:] + list(tags_cfg.get("always", []))
    if platform == "youtube" and meta.get("format") == "short":
        tags = list(tags_cfg.get("shorts", [])) + tags
    if platform == "instagram":
        tags = list(tags_cfg.get("reels", [])) + tags
    seen, result = set(), []
    for tag in tags:
        tag = "#" + re.sub(r"[^\w]", "", clean(tag).lstrip("#"), flags=re.UNICODE)
        if len(tag) > 1 and tag.lower() not in seen and tag.lower() not in REMOVED_TAGS:
            seen.add(tag.lower())
            result.append(tag)
    return result[:15] if platform == "youtube" else result[:30]


# ---------------------------------------------------------------------------
# Templates (no internet needed)
# ---------------------------------------------------------------------------
def template_captions(meta):
    hindi_genre, english_genre = GENRE_WORDS.get(meta["genre"], GENRE_WORDS["kids_story"])
    theme = CONFIG.get("themes", {}).get(meta.get("theme") or "")
    if theme:  # a story written for a weekday theme: "परी और जादू की कहानी (Fairy Tale)"
        hindi_genre, english_genre = theme["label"]["hindi"], theme["label"]["english"]
    source = meta.get("source") or ""
    source_hi = SOURCE_WORDS.get(source, "")
    title = clean(meta["title"])
    second = source_hi or hindi_genre
    title_line = fit(" | ".join(p for p in (title, second if second != title else "", english_genre) if p), TITLE_MAX)

    parts = [f"{title} – {hindi_genre} ({english_genre})"]
    if meta.get("summary"):
        parts.append(clean(meta["summary"]))
    names = [clean(c) for c in meta.get("characters", []) if clean(c)]
    if names:
        parts.append("किरदार / Characters: " + ", ".join(names))
    if meta.get("moral"):
        moral = re.sub(r"^(सीख|seekh|moral)\s*[:：]\s*", "", clean(meta["moral"]), flags=re.IGNORECASE)
        parts.append(f"सीख (Moral): {moral}")
    if source:
        parts.append(f"यह कहानी {source_hi or source} की लोककथा पर आधारित है। Based on a public-domain {source} folk tale.")
    if meta["genre"] == "horror":
        parts.append("13+ | हल्की डरावनी कहानी, बच्चों के लिए नहीं। Mildly spooky, for teens and adults.")
    parts.append(f"कहानी पसंद आई? Like करें, Share करें और {channel_name()} को Subscribe करें! 🙏")
    description = "\n\n".join(parts)
    return {"title": title_line, "description": description}


# ---------------------------------------------------------------------------
# Gemini (optional)
# ---------------------------------------------------------------------------
def gemini_captions(meta, api_key):
    prompt = (
        f"Write YouTube/Instagram text for a short animated video on the channel '{channel_name()}' for Indian families. "
        f"The title MUST contain the story title exactly: {meta['title']}. "
        "Mix Hindi (Devanagari) and simple English, friendly and kid-safe. "
        f"Never mention copyrighted characters, brands or other channels. Story details: "
        f"{json.dumps({k: meta.get(k) for k in ('title', 'genre', 'theme', 'format', 'source', 'characters', 'summary', 'moral')}, ensure_ascii=False)}. "
        f"Reply with ONLY JSON: {{\"title\": \"max {TITLE_MAX} characters\", "
        "\"description\": \"3-6 short paragraphs, include the moral if there is one, end with a "
        "friendly like/share/subscribe line\", \"hashtags\": [\"#up to 10 relevant hashtags\"]}"
    )
    response = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL), headers={"x-goog-api-key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"}},
        timeout=60)
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    data = json.loads(text)
    if not data.get("title") or not data.get("description"):
        raise ValueError("Gemini returned no title/description")
    return {"title": fit(clean(data["title"]), TITLE_MAX), "description": clean(data["description"]),
            "extra_hashtags": [t for t in data.get("hashtags", []) if isinstance(t, str)]}


# ---------------------------------------------------------------------------
def make_captions(video_path, use_ai=True, save=True):
    """Build (and save as <video>.json) the captions for a video."""
    meta = story_meta(video_path)
    text, source = None, "templates"
    api_key = os.environ.get("GEMINI_API_KEY")
    if use_ai and api_key:
        try:
            text, source = gemini_captions(meta, api_key), "Gemini"
        except Exception as error:
            print(f"[captions] Gemini failed ({type(error).__name__}); using templates.")
    if text is None:
        text = template_captions(meta)

    youtube_tags = hashtags_for(meta, "youtube")
    instagram_tags = hashtags_for(meta, "instagram")
    for tag in text.get("extra_hashtags", []):  # Gemini's ideas, after ours
        tag = "#" + re.sub(r"[^\w]", "", clean(tag).lstrip("#"), flags=re.UNICODE)
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in instagram_tags} and tag.lower() not in REMOVED_TAGS:
            instagram_tags.append(tag)
    instagram_tags = instagram_tags[:30]

    story_title = clean(meta["title"])
    title = text["title"]
    if story_title and story_title not in title:  # the story title is always in the title
        title = fit(f"{story_title} | {title}", TITLE_MAX)
    if meta.get("title_en"):  # mythology: "बाल कृष्ण और माखन चोरी | Krishna Story for Kids"
        title = fit(f"{story_title} | {meta['title_en']}", TITLE_MAX)
    description = strip_removed_tags(text["description"])
    youtube_title = title
    if meta.get("format") == "short" and "#shorts" not in title.lower():
        youtube_title = fit(title, TITLE_MAX - 8) + " #shorts"
    caption = title + "\n\n" + description + "\n\n" + " ".join(instagram_tags)
    if story_title and story_title not in caption:
        caption = story_title + "\n\n" + caption
    captions = {
        "story_title": story_title,
        "title": title,
        "description": description,
        "hashtags": youtube_tags,
        "made_with": source,
        "format": meta.get("format", "short"),
        "genre": meta["genre"],
        "lang": meta.get("lang", "hindi"),
        "source": meta.get("source", ""),
        "theme": meta.get("theme", ""),
        "topic": meta.get("topic", ""),
        "youtube": {
            "title": youtube_title,
            "description": fit(description + "\n\n" + " ".join(youtube_tags), 4900),
            "tags": [t.lstrip("#") for t in youtube_tags] + [channel_name()],
        },
        "instagram": {"caption": fit(caption, 2150)},
    }
    if save:
        path = os.path.splitext(video_path)[0] + ".json"
        with open(path, "w", encoding="utf-8") as file:
            json.dump(captions, file, ensure_ascii=False, indent=2)
        print(f"[captions] Saved {path} ({source})")
    return captions


def strip_removed_tags(text):
    for tag in REMOVED_TAGS:
        text = re.sub(rf"\s*{re.escape(tag)}\b", "", text, flags=re.IGNORECASE)
    return text


def load_or_make(video_path):
    """Captions from <video>.json (cleaned of removed tags), or make them now."""
    path = os.path.splitext(video_path)[0] + ".json"
    if not os.path.exists(path):
        return make_captions(video_path)
    with open(path, encoding="utf-8") as file:
        caps = json.load(file)
    first = str(caps.get("title", "")).split(" | ")[0].strip()
    if not caps.get("story_title") and first in {hindi for hindi, _ in GENRE_WORDS.values()}:
        raise CaptionsError(
            f"{path} has only a generic title ('{first}'), not the story's title. Put the real title in it as "
            '"story_title": "..." and run with --remake-captions, or make the video again with `python -m harmis.main`.')
    removed = {t.lstrip("#") for t in REMOVED_TAGS}
    cleaned = json.loads(json.dumps(caps))
    cleaned["hashtags"] = [t for t in caps.get("hashtags", []) if t.lower() not in REMOVED_TAGS]
    cleaned["description"] = strip_removed_tags(caps.get("description", ""))
    if "youtube" in caps:
        cleaned["youtube"]["tags"] = [t for t in caps["youtube"].get("tags", []) if t.lower() not in removed]
        cleaned["youtube"]["description"] = strip_removed_tags(caps["youtube"].get("description", ""))
    if "instagram" in caps:
        cleaned["instagram"]["caption"] = strip_removed_tags(caps["instagram"].get("caption", ""))
    if cleaned != caps:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(cleaned, file, ensure_ascii=False, indent=2)
        print(f"[captions] Removed old tags from {path}")
    return cleaned


if __name__ == "__main__":
    for video in sys.argv[1:]:
        try:
            caps = make_captions(video)
        except CaptionsError as error:
            sys.exit(f"[captions] {error}")
        print(json.dumps(caps, ensure_ascii=False, indent=2))
