"""Mythology for kids: which shorts are mythology, and which deity / epic comes next.

    python -m harmis.mythology next      # show the next topics without using them

Rules (config.yaml -> mythology):
  * 2 shorts a day are mythology - the 2nd and 4th short of the day (short_slots,
    India time); on Wednesday (all_day) every short is.
  * The topics (Krishna leela, Ganesha, Hanuman, Ramayana, Mahabharata, Shiva-Parvati,
    Prahlad, Dhruv, Shravan Kumar, Nachiketa, Sudama) take turns, so the same one
    never comes twice in a row; inside a topic the episodes take turns too.
The position is kept in state/daily.json, which the workflows commit.
"""

import datetime
import json
import os
import sys

from .config import CONFIG, PROJECT_DIR

STATE_FILE = os.path.join(PROJECT_DIR, "state", "daily.json")
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def settings():
    return CONFIG["mythology"]


def topics():
    return list(settings()["topics"])


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)
        file.write("\n")


def is_mythology_short(position, weekday):
    """Is the `position`-th short of a day (0 = first) a mythology short?"""
    return weekday in settings().get("all_day", [2]) or position in settings().get("short_slots", [1, 3])


def short_theme(weekday_theme, now=None, record=True):
    """Theme for the next short made today: mythology on its slots, else the weekday theme.

    Counts the shorts already made today (state/daily.json -> short_themes)."""
    now = (now or datetime.datetime.now(IST)).astimezone(IST)
    state = load_state()
    days = state.get("short_themes", {})
    today = now.date().isoformat()
    made = days.get(today, [])
    theme = "mythology" if is_mythology_short(len(made), now.weekday()) else weekday_theme
    if record:
        days[today] = made + [theme]
        state["short_themes"] = {d: v for d, v in sorted(days.items())[-7:]}  # keep a week
        save_state(state)
    return theme


def next_topics(count, record=True):
    """The next `count` (topic, episode) pairs, in turn, so no topic repeats back-to-back."""
    state = load_state()
    rotation = state.get("mythology", {})
    names = topics()
    index = int(rotation.get("index", -1))
    episodes = dict(rotation.get("episodes", {}))
    chosen = []
    for _ in range(count):
        index = (index + 1) % len(names)
        topic = names[index]
        options = settings()["topics"][topic]["episodes"]
        episode_index = (int(episodes.get(topic, -1)) + 1) % len(options)
        episodes[topic] = episode_index
        chosen.append((topic, options[episode_index]))
    if record:
        state["mythology"] = {"index": index, "episodes": episodes, "last": chosen[-1][0] if chosen else None}
        save_state(state)
    return chosen


def topic_for_story(characters):
    """Guess the topic of a story from its character ids (for built-in stories)."""
    for name, topic in settings()["topics"].items():
        if characters and characters[0] in topic["characters"]:
            return name
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "next":
        for topic, episode in next_topics(int(sys.argv[2]) if len(sys.argv) > 2 else 5, record=False):
            print(f"{topic:<14} {episode}")
    else:
        print(__doc__)
