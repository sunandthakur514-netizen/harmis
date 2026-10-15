"""Pick the next story for the daily automation (.github/workflows/daily.yml).

    python -m harmis.daily next --slot auto        # prints: <story id> <format>
    python -m harmis.daily done --slot long --story sher_khargosh

Each slot (short / long) walks through its own list in config.yaml (daily:)
one story at a time, so stories do not repeat until the whole list has been
used. The position is kept in state/daily.json, which the workflow commits back
to the repo after a successful upload ("done").
"""

import argparse
import datetime
import json
import os
import sys

from . import script
from .config import CONFIG, PROJECT_DIR

STATE_FILE = os.path.join(PROJECT_DIR, "state", "daily.json")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def rotation(slot):
    """The story list for a slot, checked against the built-in stories."""
    stories = script.story_ids()
    ids = CONFIG.get("daily", {}).get(slot) or [s for s, (_, fmt) in stories.items() if fmt == slot]
    for story in ids:
        if story not in stories or stories[story][1] != slot:
            sys.exit(f"[daily] '{story}' in config.yaml daily.{slot} is not a built-in {slot} story")
    return ids


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def auto_slot(now=None):
    """Afternoon run (11:00-16:59 IST) = long video; morning and evening = short."""
    hour = (now or datetime.datetime.now(IST)).astimezone(IST).hour
    return "long" if 11 <= hour < 17 else "short"


def next_story(slot):
    ids = rotation(slot)
    last = load_state().get(slot, {}).get("index", -1)
    return ids[(last + 1) % len(ids)]


def mark_done(slot, story):
    ids = rotation(slot)
    state = load_state()
    state[slot] = {"index": ids.index(story), "story": story,
                   "date": datetime.datetime.now(IST).isoformat(timespec="minutes")}
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)
        file.write("\n")
    print(f"[daily] {slot}: {story} done; next time: {ids[(ids.index(story) + 1) % len(ids)]}")


def main():
    parser = argparse.ArgumentParser(description="Story rotation for the daily automation.")
    parser.add_argument("command", choices=["next", "done"])
    parser.add_argument("--slot", default="auto", choices=["auto", "short", "long"])
    parser.add_argument("--story", help="for done: the story that was uploaded")
    args = parser.parse_args()
    slot = auto_slot() if args.slot == "auto" else args.slot
    if args.command == "next":
        print(next_story(slot), slot)
    else:
        if not args.story:
            parser.error("done needs --story")
        mark_done(slot, args.story)


if __name__ == "__main__":
    main()
