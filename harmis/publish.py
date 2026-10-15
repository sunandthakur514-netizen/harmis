"""Publish a finished video to YouTube and/or Instagram.

    python -m harmis.publish --video output/2026-10-15_kids_story_hindi.mp4 --to youtube,instagram
    python -m harmis.publish --video output/....mp4 --to youtube --dry-run   # show everything, post nothing
    python -m harmis.publish --to youtube --dry-run      # newest video in output/ that has its .json

Captions (title, description, hashtags) come from <video>.json, which is made
automatically if it is missing (see harmis/captions.py). Every real post is
logged in output/published.csv.
"""

import argparse
import csv
import datetime
import os
import sys

from . import captions as captions_module
from .config import CONFIG

PLATFORMS = ("youtube", "instagram")


def newest_video(folder):
    """The newest .mp4 in a folder that has a matching <video>.json (its captions)."""
    videos = [os.path.join(folder, name) for name in os.listdir(folder) if name.endswith(".mp4")]
    videos = [v for v in videos if os.path.exists(os.path.splitext(v)[0] + ".json")]
    if not videos:
        sys.exit(f"[publish] No video with a matching .json in {folder}. Make one with `python -m harmis.main`, "
                 "or give --video <file>.mp4.")
    return max(videos, key=os.path.getmtime)


def log_post(video, platform, result, privacy=""):
    path = os.path.join(CONFIG["defaults"].get("output_dir", "output"), "published.csv")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if new:
            writer.writerow(["time", "video", "platform", "id", "url", "privacy"])
        writer.writerow([datetime.datetime.now().isoformat(timespec="seconds"), video, platform,
                         result.get("id", ""), result.get("url", ""), privacy])
    print(f"[publish] Logged in {path}")


def main():
    parser = argparse.ArgumentParser(description="Publish a HARMIS video to YouTube / Instagram.")
    parser.add_argument("--video", help="the mp4 to publish, or a folder (default: the newest video "
                                         "with a matching .json in the output folder)")
    parser.add_argument("--to", default="youtube", help="youtube, instagram or youtube,instagram")
    parser.add_argument("--dry-run", action="store_true", help="print everything, post nothing")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"],
                        help="YouTube privacy (default: config.yaml, normally private)")
    parser.add_argument("--remake-captions", action="store_true", help="make <video>.json again")
    args = parser.parse_args()

    output_dir = CONFIG["defaults"].get("output_dir", "output")
    if args.video is None or os.path.isdir(args.video):
        folder = args.video or output_dir
        if not os.path.isdir(folder):
            sys.exit(f"[publish] Folder {folder} does not exist; give --video <file>.mp4.")
        args.video = newest_video(folder)
        print(f"[publish] Picked the newest video: {args.video}")
    if not os.path.exists(args.video):
        sys.exit(f"[publish] {args.video} does not exist")
    targets = [t.strip().lower() for t in args.to.split(",") if t.strip()]
    for target in targets:
        if target not in PLATFORMS:
            sys.exit(f"[publish] Unknown platform '{target}'. Choose from: {', '.join(PLATFORMS)}")

    try:
        caps = (captions_module.make_captions(args.video) if args.remake_captions
                else captions_module.load_or_make(args.video))
    except captions_module.CaptionsError as error:
        sys.exit(f"[publish] {error}")
    fmt, genre = caps.get("format", "short"), caps.get("genre", "kids_story")
    print(f"[publish] {args.video}: {fmt} {genre} video, title: {caps['title']}")

    failed = 0
    for target in targets:
        try:
            if target == "youtube":
                from . import publish_youtube
                result = publish_youtube.upload(args.video, caps, genre, fmt, args.privacy, args.dry_run)
            else:
                from . import publish_instagram
                if fmt != "short":
                    print("[publish] Skipping Instagram: Reels are for short vertical videos only.")
                    continue
                result = publish_instagram.publish_reel(args.video, caps["instagram"]["caption"], fmt, args.dry_run)
            if not args.dry_run:
                log_post(args.video, target, result, result.get("privacy", ""))
        except Exception as error:
            failed += 1
            print(f"[publish] {target} FAILED: {error}")
    if args.dry_run:
        print("[publish] Dry run finished: nothing was posted.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
