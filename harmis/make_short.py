"""Make ONE good short for a daily slot (used by .github/workflows/daily.yml).

    python -m harmis.make_short --out output

Each attempt: write or pick today's story (harmis/storygen.py: weekday theme plus
the 2-shorts-a-day mythology rule), make its pictures, render the video, and check
it before anything can be uploaded:
  * the video exists, is vertical-short length (20-75 s) and not tiny,
  * every scene picture was really made (no simple stand-in pictures),
  * the voices came from Gemini or edge-tts (never robotic or silent),
  * its story details and captions were saved.
If the check fails, it tries once more with a new story for the SAME theme and topic
(so the mythology rotation is not skipped). If that fails too, the slot is skipped:
nothing is uploaded and the run ends without an error.

Prints one JSON line and writes GITHUB_OUTPUT: made=true|false, video, story, theme.
"""

import argparse
import glob
import json
import os
import shlex
import subprocess
import sys

from .config import CONFIG


def run(args, capture=False):
    """Run a HARMIS step; its log goes straight to the workflow log (unless captured)."""
    print("[make_short] $ " + " ".join(args), flush=True)
    return subprocess.run([sys.executable, "-m"] + args, text=True,
                          stdout=subprocess.PIPE if capture else None)


def check(video):
    """Problems with a finished short ([] = good enough to upload)."""
    if not video or not os.path.exists(video):
        return ["no video was made"]
    problems = []
    base = os.path.splitext(video)[0]
    try:
        with open(base + ".story.json", encoding="utf-8") as file:
            meta = json.load(file)
    except (OSError, ValueError):
        return ["the story details (.story.json) are missing"]
    if not os.path.exists(base + ".json"):
        problems.append("the captions (.json) are missing")
    if meta.get("format") != "short":
        problems.append(f"it is a {meta.get('format')} video, not a short")
    if not 20 <= float(meta.get("duration", 0)) <= 75:
        problems.append(f"it is {meta.get('duration')} s long (a short must be 20-75 s)")
    if os.path.getsize(video) < 200_000:
        problems.append("the video file is suspiciously small")
    quality = meta.get("quality", {})
    if quality.get("simple_shots"):
        problems.append(f"{quality['simple_shots']} of {quality.get('shots')} scene pictures could not be made")
    bad_voices = set(quality.get("voices", [])) - {"gemini", "cache", "edge"}
    if bad_voices:
        problems.append(f"the voices came from {', '.join(sorted(bad_voices))}")
    return problems


def github_output(**values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            for key, value in values.items():
                file.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description="Make one checked short for a daily slot.")
    parser.add_argument("--out", default=CONFIG["defaults"].get("output_dir", "output"))
    parser.add_argument("--tries", type=int, default=2, help="attempts before the slot is skipped")
    args = parser.parse_args()
    daily = CONFIG.get("daily", {})
    common = ["--lang", daily.get("lang", "hindi"), "--style", daily.get("style", "3d_cartoon"),
              "--providers", "gemini,local_sd"]
    pinned = []  # the retry keeps the first attempt's theme and topic
    for attempt in range(1, args.tries + 1):
        print(f"[make_short] attempt {attempt}/{args.tries}", flush=True)
        for old in glob.glob(os.path.join(args.out, "*")):  # nothing half-made can be uploaded
            if not old.endswith("published.csv") and os.path.isfile(old):
                os.remove(old)
        picked = run(["harmis.storygen", "--slot", "short", "--out", "cache/story.json"] + pinned, capture=True)
        try:
            story = json.loads(picked.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            print("[make_short] could not get a story", flush=True)
            continue
        if not pinned:
            pinned = ["--theme", story["theme"]] + (
                ["--topic", story["topic"], "--episode", story.get("episode", "")] if story.get("topic") else [])
        if not story.get("args"):
            print("[make_short] no story available for this slot", flush=True)
            break
        story_args = shlex.split(story["args"])
        run(["harmis.prepare"] + story_args + common)  # a failed picture is retried by main
        made = run(["harmis.main"] + story_args + common + ["--offline", "--out", args.out])
        videos = sorted(glob.glob(os.path.join(args.out, "*.mp4")), key=os.path.getmtime)
        video = videos[-1] if made.returncode == 0 and videos else None
        problems = check(video)
        if not problems:
            result = {"made": "true", "video": video, "story": story["story"], "theme": story["theme"],
                      "topic": story.get("topic", ""), "attempt": attempt}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            github_output(**result)
            return
        print(f"[make_short] attempt {attempt} not good enough: {'; '.join(problems)}", flush=True)
    for old in glob.glob(os.path.join(args.out, "*")):  # leave nothing broken behind
        if not old.endswith("published.csv") and os.path.isfile(old):
            os.remove(old)
    print("::warning::No good short could be made for this slot; nothing will be uploaded.", flush=True)
    print(json.dumps({"made": "false"}), flush=True)
    github_output(made="false")


if __name__ == "__main__":
    main()
