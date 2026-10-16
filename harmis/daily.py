"""Story choice and upload limits for the automation workflows (daily.yml, bulk.yml).

    python -m harmis.daily next --slot auto        # prints: <story id> <format>   (or: none <format>)
    python -m harmis.daily done --slot long --story sher_khargosh
    python -m harmis.daily budget                  # uploads still allowed today
    python -m harmis.daily plan --shorts 15 --longs 7   # JSON list of stories for bulk.yml
    python -m harmis.daily published               # every story already on YouTube

A story is never used twice: published stories (output/published.csv, plus the
older state/daily.json) and stories waiting in the upload queue are skipped.
Only the genres in config.yaml (daily: genres) are used, so the horror stories
stay out of this made-for-kids channel.
"""

import argparse
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

from . import script
from .config import CONFIG, PROJECT_DIR

STATE_FILE = os.path.join(PROJECT_DIR, "state", "daily.json")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
QUOTA_DAY = ZoneInfo("America/Los_Angeles")  # the YouTube API quota resets at midnight Pacific time


def settings():
    return CONFIG.get("daily", {})


def candidates(slot):
    """Built-in stories for a slot (short / long), genres taken in turns: story, rhyme, story, ..."""
    genres = settings().get("genres", ["kids_story", "kids_rhyme"])
    skip = set(settings().get("exclude_stories", []))
    by_genre = [[s["id"] for s in script.samples_for(slot).get(genre, []) if s["id"] not in skip]
                for genre in genres]
    ordered = []
    for turn in range(max((len(ids) for ids in by_genre), default=0)):
        ordered += [ids[turn] for ids in by_genre if turn < len(ids)]
    return ordered


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def youtube_rows():
    from .publish import read_log
    return [row for row in read_log() if row.get("platform") == "youtube"]


def published_stories():
    """Story ids already uploaded to YouTube."""
    done = {row.get("story_id") for row in youtube_rows()}
    for slot in load_state().values():  # uploads made before published.csv was committed
        done |= set(slot.get("published", [])) | {slot.get("story")}
    done.discard(None)
    done.discard("")
    return done


def queued_stories():
    """Story ids waiting in the upload queue (needs GITHUB_TOKEN; empty without it)."""
    try:
        from .upload_queue import Queue
        return {item["story"] for item in Queue().items()}
    except Exception as error:
        print(f"[daily] Could not read the upload queue ({error}); assuming it is empty.", file=sys.stderr)
        return set()


def used_stories(with_queue=True):
    return published_stories() | (queued_stories() if with_queue else set())


def uploads_today(now=None):
    """YouTube uploads since midnight Pacific time (when the free quota resets)."""
    today = (now or datetime.datetime.now(QUOTA_DAY)).astimezone(QUOTA_DAY).date()
    count = 0
    for row in youtube_rows():
        try:
            when = datetime.datetime.fromisoformat(row["time"])
        except (KeyError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        count += when.astimezone(QUOTA_DAY).date() == today
    return count


def budget(now=None):
    return max(0, int(settings().get("max_uploads_per_day", 5)) - uploads_today(now))


def auto_slot(now=None):
    """Afternoon run (11:00-16:59 IST) = long video; morning and evening = short."""
    hour = (now or datetime.datetime.now(IST)).astimezone(IST).hour
    return "long" if 11 <= hour < 17 else "short"


def next_story(slot, used=None):
    used = used_stories() if used is None else used
    return next((story for story in candidates(slot) if story not in used), None)


def plan(shorts, longs, used=None):
    """Stories for a bulk run: [{"story": id, "format": short|long}, ...], none used before."""
    used = used_stories() if used is None else used
    jobs = []
    for slot, count in (("short", shorts), ("long", longs)):
        free = [s for s in candidates(slot) if s not in used]
        if len(free) < count:
            print(f"[daily] Only {len(free)} unused {slot} stories left (asked for {count}).", file=sys.stderr)
        jobs += [{"story": story, "format": slot} for story in free[:count]]
    return jobs


def mark_done(slot, story):
    state = load_state()
    entry = state.get(slot, {})
    published = sorted(set(entry.get("published", [])) | {story})
    state[slot] = {"story": story, "date": datetime.datetime.now(IST).isoformat(timespec="minutes"),
                   "published": published}
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)
        file.write("\n")
    print(f"[daily] {slot}: {story} done; next time: {next_story(slot, published_stories()) or 'none left'}")


def main():
    parser = argparse.ArgumentParser(description="Story choice for the automation workflows.")
    parser.add_argument("command", choices=["next", "done", "budget", "plan", "published"])
    parser.add_argument("--slot", default="auto", choices=["auto", "short", "long"])
    parser.add_argument("--story", help="for done: the story that was uploaded")
    parser.add_argument("--shorts", type=int, default=15, help="for plan")
    parser.add_argument("--longs", type=int, default=7, help="for plan")
    args = parser.parse_args()
    slot = auto_slot() if args.slot == "auto" else args.slot
    if args.command == "next":
        print(next_story(slot) or "none", slot)
    elif args.command == "done":
        if not args.story:
            parser.error("done needs --story")
        mark_done(slot, args.story)
    elif args.command == "budget":
        print(budget())
    elif args.command == "plan":
        print(json.dumps(plan(args.shorts, args.longs)))
    else:
        print("\n".join(sorted(published_stories())))


if __name__ == "__main__":
    main()
