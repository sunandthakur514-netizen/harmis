"""HARMIS command line tool.

Usage:
    python -m harmis.main --genre kids_story
    python -m harmis.main --story birbal_khichdi --style 3d_cartoon
    python -m harmis.main --story sher_khargosh                 # a long (5-7 min) story
    python -m harmis.main --genre kids_story --format long
    python -m harmis.main --genre horror --providers none      # no AI pictures

Makes output/<date>_<genre>_<lang>.mp4 (short: 1080x1920, 30-60 s;
long: 1920x1080, 5-7 min). Settings not given here come from config.yaml.
"""

import argparse
import collections
import datetime
import os
import sys
import tempfile

from . import animate, script, voice
from .config import CONFIG
from .library import Library
from .providers import PROVIDERS, ImageChain

STYLES = ["storybook", "3d_cartoon", "anime"]
FORMATS = ["short", "long"]


def output_path(out_dir, genre, lang, fmt):
    """output/<date>_<genre>_<lang>[_long].mp4, adding _2, _3 ... so old videos are not overwritten."""
    date = datetime.date.today().isoformat()
    base = f"{date}_{genre}_{lang}" + ("_long" if fmt == "long" else "")
    path = os.path.join(out_dir, f"{base}.mp4")
    number = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{base}_{number}.mp4")
        number += 1
    return path


def save_story_meta(story, video_path, length, style):
    """Save what the video is about as <video>.story.json (for captions and publishing)."""
    import json
    narrator_lines = [line["text"] for line in story["lines"] if line["speaker"] == script.NARRATOR]
    moral = next((t for t in reversed(narrator_lines)
                  if t.lower().startswith(("सीख", "seekh", "moral"))), "")
    meta = {
        "title": story["title"], "story_id": story.get("id", ""), "genre": story["genre"],
        "lang": story["lang"], "format": story.get("format", "short"), "style": style,
        "source": story.get("source", ""), "tagline": story.get("tagline", ""),
        "characters": [c["label"] for c in story["characters"]],
        "summary": narrator_lines[0] if narrator_lines else story["lines"][0]["text"],
        "moral": moral, "duration": round(length, 1),
    }
    with open(os.path.splitext(video_path)[0] + ".story.json", "w", encoding="utf-8") as file:
        json.dump(meta, file, ensure_ascii=False, indent=2)
    return meta


def spoken_length(voiced_lines, fmt):
    """Length of the video if we use these voice clips."""
    return animate.build_timeline(voiced_lines, fmt)[1]


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


def add_common_options(parser):
    """Options shared by `harmis.main` and `harmis.prepare`."""
    stories = script.story_ids()
    parser.add_argument("--genre", choices=script.GENRES, help="story genre (needed unless --story is given)")
    parser.add_argument("--story", choices=sorted(stories), help="a specific built-in story")
    parser.add_argument("--format", choices=FORMATS, help="short (vertical, 30-60 s) or long (16:9, 5-7 min); "
                                                           "default: short, or the story's own format")
    parser.add_argument("--lang", choices=script.LANGS, default=CONFIG["defaults"]["lang"],
                        help=f"language (default: {CONFIG['defaults']['lang']})")
    parser.add_argument("--style", choices=STYLES, help="art style (default: from config.yaml for the genre)")
    parser.add_argument("--providers", help="image providers to try, e.g. 'pollinations,huggingface', "
                                            "or 'none' for the simple shape style (default: config.yaml)")
    parser.add_argument("--refresh-images", action="store_true", help="make new pictures even if cached ones exist")


def resolve_options(parser, args):
    """Fill in genre / format / style from --story and config.yaml."""
    stories = script.story_ids()
    if args.story:
        genre, story_format = stories[args.story]
        if args.format and args.format != story_format:
            parser.error(f"--story {args.story} is a {story_format} story")
        args.genre, args.format = genre, story_format
    elif not args.genre:
        parser.error("give --genre or --story")
    args.format = args.format or "short"
    args.style = args.style or CONFIG["genres"][args.genre].get("style") or CONFIG["defaults"]["style"]
    return args


def setup(args):
    """Image chain + library for these options."""
    chain = ImageChain(parse_providers(args.providers))
    library = Library(chain, args.style, args.genre, refresh=args.refresh_images, fmt=args.format)
    return chain, library


def main():
    parser = argparse.ArgumentParser(description="Make one video from a genre or a story.")
    add_common_options(parser)
    parser.add_argument("--out", default=CONFIG["defaults"]["output_dir"], help="folder for the finished video")
    parser.add_argument("--offline", action="store_true", help="do not call Gemini for the story")
    args = resolve_options(parser, parser.parse_args())
    fmt = args.format
    limits = CONFIG["formats"][fmt]
    min_length, max_length = float(limits["min_seconds"]), float(limits["max_seconds"])

    if args.genre == "horror":
        print("[main] Note: horror videos are mildly scary and meant for teens and adults (13+).")
    print(f"[main] genre={args.genre} lang={args.lang} style={args.style} format={fmt}")

    chain, library = setup(args)

    with tempfile.TemporaryDirectory(prefix="harmis_") as work_dir:
        # 1. Script
        story = script.get_script(args.genre, args.lang, library, use_ai=not args.offline,
                                  story=args.story, fmt=fmt)

        # 2. Voices
        voiced = voice.make_voices(story, os.path.join(work_dir, "audio0"), library=library)
        length = spoken_length(voiced, fmt)

        if fmt == "short" and length > max_length and not args.story:
            # Too long for a Short? Try the built-in scripts (shortest wins if none fit).
            best = (story, voiced)
            for attempt, other in enumerate(script.sample_scripts(args.genre, args.lang, library), start=1):
                if other["title"] == story["title"]:
                    continue
                print(f"[main] Story is longer than {max_length:.0f}s, trying: {other['title']}")
                other_voiced = voice.make_voices(other, os.path.join(work_dir, f"audio{attempt}"), library=library)
                if spoken_length(other_voiced, fmt) < spoken_length(best[1], fmt):
                    best = (other, other_voiced)
                if spoken_length(other_voiced, fmt) <= max_length:
                    break
            story, voiced = best
        elif fmt == "long" and not min_length <= length <= max_length:
            # Aim for 5-7 minutes: speak a little faster (up to +25%) or slower (down to -10%).
            speech = length - (len(voiced) - 1) * animate.GAP - animate.Layout(fmt).intro - animate.Layout(fmt).outro
            target = (max_length - 5) if length > max_length else (min_length + 5)
            change = round((speech / max(1.0, speech - (length - target)) - 1) * 100) + (2 if length > max_length else -2)
            change = max(-10, min(25, change))
            print(f"[main] Long video would be {length / 60:.1f} min; re-making voices {change:+d}% "
                  f"{'faster' if change > 0 else 'slower'} to fit {min_length / 60:.0f}-{max_length / 60:.0f} min.")
            voiced = voice.make_voices(story, os.path.join(work_dir, "audio_paced"), rate_change=change,
                                      library=library)
            length = spoken_length(voiced, fmt)
            if not min_length <= length <= max_length:
                print(f"[main] Note: this long video will be {length / 60:.1f} minutes "
                      f"(the target is {min_length / 60:.0f}-{max_length / 60:.0f} minutes).")

        # Short rhymes are sung twice, like children do (the same audio is reused).
        if fmt == "short" and args.genre == "kids_rhyme" and spoken_length(voiced + voiced, fmt) <= max_length:
            voiced = voiced + voiced

        # 3. Pictures (from the library cache, or made now by the image providers)
        visuals = library.load_visuals(story)
        used = collections.Counter(chain.used.values())
        if used:
            print("[main] Pictures needed this run: " + ", ".join(
                f"{n} drawn as simple shapes" if p == "shapes" else f"{n} made by {p}" for p, n in used.items()))

        # 4. Animation + final video
        path = output_path(args.out, args.genre, story["lang"], fmt)
        print(f"[main] Rendering video ({spoken_length(voiced, fmt):.1f}s) ...")
        path, length = animate.make_video(story, voiced, path, visuals, work_dir)

    # Story details + captions next to the video (used by `python -m harmis.publish`).
    save_story_meta(story, path, length, args.style)
    try:
        from . import captions
        captions.make_captions(path)
    except Exception as error:  # captions must never break making a video
        print(f"[main] Could not make captions ({type(error).__name__}: {error})")

    print(f"\nDone! Saved {path} ({length:.1f} seconds)")


if __name__ == "__main__":
    try:
        main()
    except voice.VoiceError as error:  # never publish a robotic or silent voice from GitHub Actions
        sys.exit(f"[voice] {error}")
