"""Titles, descriptions and hashtags for a finished video (Hindi + English mix).

    python -m harmis.captions output/2026-10-15_kids_story_hindi.mp4

Reads <video>.story.json (written by harmis.main) and saves <video>.json:

    {
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
    """The story details saved next to the video, or a guess from the file name."""
    meta_path = os.path.splitext(video_path)[0] + ".story.json"
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as file:
            return json.load(file)
    # Older videos: output/<date>_<genre>_<lang>[_long][_2].mp4
    name = os.path.basename(os.path.splitext(video_path)[0])
    genre = next((g for g in GENRE_WORDS if f"_{g}_" in f"_{name}_"), "kids_story")
    lang = next((l for l in ("hindi", "hinglish", "english") if f"_{l}" in name), "hindi")
    print(f"[captions] No {os.path.basename(meta_path)}; guessing from the file name ({genre}, {lang}).")
    return {"title": GENRE_WORDS[genre][0], "genre": genre, "lang": lang,
            "format": "long" if "_long" in name else "short", "characters": [], "summary": "", "moral": "",
            "source": "", "tagline": ""}


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


def hashtags_for(meta, platform):
    tags_cfg = CONFIG["publish"]["hashtags"]
    by_source = list(tags_cfg.get("by_source", {}).get(meta.get("source") or "", []))
    genre_tags = list(tags_cfg.get(meta["genre"], []))
    tags = genre_tags[:2] + by_source + genre_tags[2:] + list(tags_cfg.get("always", []))
    if platform == "youtube" and meta.get("format") == "short":
        tags = list(tags_cfg.get("shorts", [])) + tags
    if platform == "instagram":
        tags = list(tags_cfg.get("reels", [])) + tags
    seen, result = set(), []
    for tag in tags:
        tag = "#" + re.sub(r"[^\w]", "", clean(tag).lstrip("#"), flags=re.UNICODE)
        if len(tag) > 1 and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result[:15] if platform == "youtube" else result[:30]


# ---------------------------------------------------------------------------
# Templates (no internet needed)
# ---------------------------------------------------------------------------
def template_captions(meta):
    hindi_genre, english_genre = GENRE_WORDS.get(meta["genre"], GENRE_WORDS["kids_story"])
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
    parts.append("कहानी पसंद आई? Like करें, Share करें और Subscribe करें! 🙏")
    description = "\n\n".join(parts)
    return {"title": title_line, "description": description}


# ---------------------------------------------------------------------------
# Gemini (optional)
# ---------------------------------------------------------------------------
def gemini_captions(meta, api_key):
    prompt = (
        "Write YouTube/Instagram text for a short animated video for Indian families. "
        "Mix Hindi (Devanagari) and simple English, friendly and kid-safe. "
        f"Never mention copyrighted characters, brands or other channels. Story details: "
        f"{json.dumps({k: meta.get(k) for k in ('title', 'genre', 'format', 'source', 'characters', 'summary', 'moral')}, ensure_ascii=False)}. "
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
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in instagram_tags}:
            instagram_tags.append(tag)
    instagram_tags = instagram_tags[:30]

    title = text["title"]
    description = text["description"]
    youtube_title = title
    if meta.get("format") == "short" and "#shorts" not in title.lower():
        youtube_title = fit(title, TITLE_MAX - 8) + " #shorts"
    captions = {
        "title": title,
        "description": description,
        "hashtags": youtube_tags,
        "made_with": source,
        "format": meta.get("format", "short"),
        "genre": meta["genre"],
        "youtube": {
            "title": youtube_title,
            "description": fit(description + "\n\n" + " ".join(youtube_tags), 4900),
            "tags": [t.lstrip("#") for t in youtube_tags],
        },
        "instagram": {"caption": fit(title + "\n\n" + description + "\n\n" + " ".join(instagram_tags), 2150)},
    }
    if save:
        path = os.path.splitext(video_path)[0] + ".json"
        with open(path, "w", encoding="utf-8") as file:
            json.dump(captions, file, ensure_ascii=False, indent=2)
        print(f"[captions] Saved {path} ({source})")
    return captions


def load_or_make(video_path):
    path = os.path.splitext(video_path)[0] + ".json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    return make_captions(video_path)


if __name__ == "__main__":
    for video in sys.argv[1:]:
        caps = make_captions(video)
        print(json.dumps(caps, ensure_ascii=False, indent=2))
