"""HARMIS command line tool.

Usage:
    python -m harmis.main --genre kids_story
    python -m harmis.main --story birbal_khichdi --style 3d_cartoon
    python -m harmis.main --genre comedy --lang hinglish --style anime
    python -m harmis.main --genre horror --providers none      # no AI pictures

Makes output/<date>_<genre>_<lang>.mp4 (a 1080x1920 vertical video, 30-60 seconds).
Settings that are not given on the command line come from config.yaml.
"""

import argparse
import collections
import datetime
import os
import tempfile

from . import animate, script, voice
from .config import CONFIG
from .library import Library
from .providers import PROVIDERS, ImageChain

STYLES = ["storybook", "3d_cartoon", "anime"]


def output_path(out_dir, genre, lang):
    """output/<date>_<genre>_<lang>.mp4, adding _2, _3 ... so old videos are not overwritten."""
    date = datetime.date.today().isoformat()
    path = os.path.join(out_dir, f"{date}_{genre}_{lang}.mp4")
    number = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{date}_{genre}_{lang}_{number}.mp4")
        number += 1
    return path


def spoken_length(voiced_lines):
    """Length of the video if we use these voice clips."""
    return animate.build_timeline(voiced_lines)[1]


def parse_providers(text):
    """'pollinations,gemini' -> list; 'none' -> [] (no AI pictures); None -> use config.yaml."""
    if text is None:
        return None
    if text.strip().lower() in ("none", "off", ""):
        return []
    names = [name.strip() for name in text.split(",")]
    for name in names:
        if name not in PROVIDERS:
            raise SystemExit(f"Unknown provider '{name}'. Choose from: {', '.join(PROVIDERS)} or none")
    return names


def main():
    stories = script.story_ids()
    parser = argparse.ArgumentParser(description="Make one short vertical video from a genre.")
    parser.add_argument("--genre", choices=script.GENRES, help="story genre (needed unless --story is given)")
    parser.add_argument("--story", choices=sorted(stories), help="a specific built-in story")
    parser.add_argument("--lang", choices=script.LANGS, default=CONFIG["defaults"]["lang"],
                        help=f"language (default: {CONFIG['defaults']['lang']})")
    parser.add_argument("--style", choices=STYLES, help="art style (default: from config.yaml for the genre)")
    parser.add_argument("--providers", help="image providers to try, e.g. 'pollinations,huggingface', "
                                            "or 'none' for the simple shape style (default: config.yaml)")
    parser.add_argument("--refresh-images", action="store_true", help="make new pictures even if cached ones exist")
    parser.add_argument("--out", default=CONFIG["defaults"]["output_dir"], help="folder for the finished video")
    parser.add_argument("--offline", action="store_true", help="do not call Gemini for the story")
    args = parser.parse_args()

    if args.story:
        args.genre = stories[args.story]
    elif not args.genre:
        parser.error("give --genre or --story")
    style = args.style or CONFIG["genres"][args.genre].get("style") or CONFIG["defaults"]["style"]
    max_length = float(CONFIG["video"]["max_seconds"])

    if args.genre == "horror":
        print("[main] Note: horror videos are mildly scary and meant for teens and adults (13+).")
    print(f"[main] genre={args.genre} lang={args.lang} style={style}")

    chain = ImageChain(parse_providers(args.providers))
    library = Library(chain, style, args.genre, refresh=args.refresh_images)

    with tempfile.TemporaryDirectory(prefix="harmis_") as work_dir:
        # 1. Script
        story = script.get_script(args.genre, args.lang, library, use_ai=not args.offline, story=args.story)

        # 2. Voices
        voiced = voice.make_voices(story, os.path.join(work_dir, "audio0"))

        # Too long? Try the built-in scripts (shortest wins if none fit).
        if spoken_length(voiced) > max_length and not args.story:
            best = (story, voiced)
            for attempt, other in enumerate(script.sample_scripts(args.genre, args.lang, library), start=1):
                if other["title"] == story["title"]:
                    continue
                print(f"[main] Story is longer than {max_length:.0f}s, trying: {other['title']}")
                other_voiced = voice.make_voices(other, os.path.join(work_dir, f"audio{attempt}"))
                if spoken_length(other_voiced) < spoken_length(best[1]):
                    best = (other, other_voiced)
                if spoken_length(other_voiced) <= max_length:
                    break
            story, voiced = best

        # Short rhymes are sung twice, like children do (the same audio is reused).
        if args.genre == "kids_rhyme" and spoken_length(voiced + voiced) <= max_length:
            voiced = voiced + voiced

        # 3. Pictures (from the library cache, or made now by the image providers)
        visuals = library.load_visuals(story)
        used = collections.Counter(chain.used.values())
        if used:
            print("[main] Pictures needed this run: " + ", ".join(
                f"{n} drawn as simple shapes" if p == "shapes" else f"{n} made by {p}" for p, n in used.items()))

        # 4. Animation + final video
        path = output_path(args.out, args.genre, args.lang)
        print(f"[main] Rendering video ({spoken_length(voiced):.1f}s) ...")
        path, length = animate.make_video(story, voiced, path, visuals, work_dir)

    print(f"\nDone! Saved {path} ({length:.1f} seconds)")


if __name__ == "__main__":
    main()
