"""HARMIS command line tool.

Usage:
    python -m harmis.main --genre horror

Makes output/<date>_<genre>.mp4 (a 1080x1920 vertical video, 30-60 seconds).
"""

import argparse
import datetime
import os
import tempfile

from . import animate, script, voice

MAX_LENGTH = 60.0  # seconds


def output_path(out_dir, genre):
    """output/<date>_<genre>.mp4, adding _2, _3 ... so old videos are not overwritten."""
    date = datetime.date.today().isoformat()
    path = os.path.join(out_dir, f"{date}_{genre}.mp4")
    number = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{date}_{genre}_{number}.mp4")
        number += 1
    return path


def spoken_length(voiced_lines):
    """Length of the video if we use these voice clips."""
    return animate.build_timeline(voiced_lines)[1]


def main():
    parser = argparse.ArgumentParser(description="Make one short vertical video from a genre.")
    parser.add_argument("--genre", required=True, choices=script.GENRES, help="story genre")
    parser.add_argument("--out", default="output", help="folder for the finished video (default: output)")
    parser.add_argument("--offline", action="store_true", help="do not call Gemini, use built-in scripts")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="harmis_") as work_dir:
        # 1. Script
        story = script.get_script(args.genre, use_ai=not args.offline)

        # 2. Voices
        voiced = voice.make_voices(story, os.path.join(work_dir, "audio"))

        # An AI story might come out too long; built-in ones always fit.
        if spoken_length(voiced) > MAX_LENGTH:
            print(f"[main] Story is longer than {MAX_LENGTH:.0f}s, switching to a built-in script.")
            story = script.sample_script(args.genre)
            voiced = voice.make_voices(story, os.path.join(work_dir, "audio2"))

        # 3. Animation + final video
        path = output_path(args.out, args.genre)
        print(f"[main] Rendering video ({spoken_length(voiced):.1f}s) ...")
        path, length = animate.make_video(story, voiced, path, work_dir)

    print(f"\nDone! Saved {path} ({length:.1f} seconds)")


if __name__ == "__main__":
    main()
