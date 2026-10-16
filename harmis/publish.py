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
import json
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


LOG_FIELDS = ["time", "video", "platform", "id", "url", "privacy", "story_id", "title", "format"]


def log_path():
    return os.path.join(CONFIG["defaults"].get("output_dir", "output"), "published.csv")


def read_log():
    """Every row of output/published.csv (older files without the newer columns work too)."""
    try:
        with open(log_path(), newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))
    except OSError:
        return []


def log_post(video, platform, result, privacy="", caps=None):
    """Add one real post to output/published.csv (committed by the daily workflow)."""
    path = log_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = read_log()
    caps = caps or {}
    rows.append({"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                 "video": os.path.basename(video), "platform": platform, "id": result.get("id", ""),
                 "url": result.get("url", ""), "privacy": privacy, "story_id": caps.get("story_id", ""),
                 "title": caps.get("story_title", ""), "format": caps.get("format", "")})
    with open(path, "w", newline="", encoding="utf-8") as file:  # rewritten so old files get the new columns
        writer = csv.DictWriter(file, fieldnames=LOG_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[publish] Logged in {path}")


def story_id_of(video):
    """The built-in story id saved next to the video (<video>.story.json), or ""."""
    try:
        with open(os.path.splitext(video)[0] + ".story.json", encoding="utf-8") as file:
            return json.load(file).get("story_id", "")
    except (OSError, ValueError):
        return ""


def publish_video(video, targets, privacy=None, dry_run=False, remake_captions=False):
    """Post one video. Returns the number of platforms that failed."""
    try:
        caps = (captions_module.make_captions(video) if remake_captions
                else captions_module.load_or_make(video))
    except captions_module.CaptionsError as error:
        print(f"[publish] {error}")
        return len(targets)
    caps = {**caps, "story_id": caps.get("story_id") or story_id_of(video)}
    fmt, genre = caps.get("format", "short"), caps.get("genre", "kids_story")
    print(f"[publish] {video}: {fmt} {genre} video, title: {caps['title']}")

    failed = 0
    for target in targets:
        try:
            if target == "youtube":
                from . import publish_youtube
                result = publish_youtube.upload(video, caps, genre, fmt, privacy, dry_run)
            else:
                from . import publish_instagram
                if fmt != "short":
                    print("[publish] Skipping Instagram: Reels are for short vertical videos only.")
                    continue
                result = publish_instagram.publish_reel(video, caps["instagram"]["caption"], fmt, dry_run)
            if not dry_run:
                log_post(video, target, result, result.get("privacy", ""), caps)
        except Exception as error:
            failed += 1
            print(f"[publish] {target} FAILED: {error}")
    return failed


def main():
    parser = argparse.ArgumentParser(description="Publish a HARMIS video to YouTube / Instagram.")
    parser.add_argument("--video", help="the mp4 to publish, or a folder (default: the newest video "
                                         "with a matching .json in the output folder)")
    parser.add_argument("--to", default="youtube", help="youtube, instagram or youtube,instagram")
    parser.add_argument("--dry-run", action="store_true", help="print everything, post nothing")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"],
                        help="YouTube privacy (default: config.yaml, normally public)")
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

    failed = publish_video(args.video, targets, args.privacy, args.dry_run, args.remake_captions)
    if args.dry_run:
        print("[publish] Dry run finished: nothing was posted.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
