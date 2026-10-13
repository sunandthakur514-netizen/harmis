"""HARMIS command line tool.

Usage:
    python -m harmis.main --genre kids_story
    python -m harmis.main --genre comedy --lang hinglish

Makes output/<date>_<genre>_<lang>.mp4 (a 1080x1920 vertical video, 30-60 seconds).
"""

import argparse
import datetime
import os
import tempfile

from . import animate, script, voice

MAX_LENGTH = 60.0  # seconds


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


def main():
    parser = argparse.ArgumentParser(description="Make one short vertical video from a genre.")
    parser.add_argument("--genre", required=True, choices=script.GENRES, help="story genre")
    parser.add_argument("--lang", default="hindi", choices=script.LANGS, help="language (default: hindi)")
    parser.add_argument("--out", default="output", help="folder for the finished video (default: output)")
    parser.add_argument("--offline", action="store_true", help="do not call Gemini, use built-in scripts")
    args = parser.parse_args()

    if args.genre == "horror":
        print("[main] Note: horror videos are mildly scary and meant for teens and adults (13+).")

    with tempfile.TemporaryDirectory(prefix="harmis_") as work_dir:
        # 1. Script
        story = script.get_script(args.genre, args.lang, use_ai=not args.offline)

        # 2. Voices
        voiced = voice.make_voices(story, os.path.join(work_dir, "audio0"))

        # Too long? Try the built-in scripts (shortest wins if none fit).
        if spoken_length(voiced) > MAX_LENGTH:
            best = (story, voiced)
            for attempt, other in enumerate(script.sample_scripts(args.genre, args.lang), start=1):
                if other["title"] == story["title"]:
                    continue
                print(f"[main] Story is longer than {MAX_LENGTH:.0f}s, trying: {other['title']}")
                other_voiced = voice.make_voices(other, os.path.join(work_dir, f"audio{attempt}"))
                if spoken_length(other_voiced) < spoken_length(best[1]):
                    best = (other, other_voiced)
                if spoken_length(other_voiced) <= MAX_LENGTH:
                    break
            story, voiced = best

        # Short rhymes are sung twice, like children do (the same audio is reused).
        if args.genre == "kids_rhyme" and spoken_length(voiced + voiced) <= MAX_LENGTH:
            voiced = voiced + voiced

        # 3. Animation + final video
        path = output_path(args.out, args.genre, args.lang)
        print(f"[main] Rendering video ({spoken_length(voiced):.1f}s) ...")
        path, length = animate.make_video(story, voiced, path, work_dir)

    print(f"\nDone! Saved {path} ({length:.1f} seconds)")


if __name__ == "__main__":
    main()
