"""Upload queue: finished videos waiting in a GitHub Release named "queue".

    python -m harmis.upload_queue list
    python -m harmis.upload_queue add output/2026-10-16_kids_story_hindi.mp4
    python -m harmis.upload_queue publish --max 2          # upload the oldest ones to YouTube
    python -m harmis.upload_queue publish --max 2 --dry-run

bulk.yml makes many videos at once and adds each one here (the .mp4 plus its
.json captions and .story.json). daily.yml uploads up to 2 per run from here,
oldest first, mixing shorts and longs, and deletes them after a successful
upload. Needs GITHUB_TOKEN (set automatically inside GitHub Actions).
"""

import argparse
import datetime
import os
import re
import sys
import tempfile

import requests

from .config import CONFIG

TAG = "queue"
EXTENSIONS = (".story.json", ".json", ".mp4")  # longest first, so ".story.json" is not read as ".json"


class QueueError(Exception):
    pass


def split_name(name):
    for ext in EXTENSIONS:
        if name.endswith(ext):
            return name[: -len(ext)], ext
    return name, ""


def choose(items, count):
    """Oldest first, but mix formats: after a short, take the oldest long if there is one (and back)."""
    left, chosen = sorted(items, key=lambda item: item["created"]), []
    while left and len(chosen) < count:
        pick = left[0]
        if chosen:
            other = [item for item in left if item["format"] != chosen[-1]["format"]]
            pick = other[0] if other else pick
        chosen.append(pick)
        left.remove(pick)
    return chosen


class Queue:
    def __init__(self):
        from .publish_instagram import github_repo
        github = CONFIG["publish"]["github"]
        self.api, self.uploads = github["api"].rstrip("/"), github["uploads"].rstrip("/")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise QueueError("GITHUB_TOKEN is not set (it is set automatically inside GitHub Actions).")
        self.repo = github_repo()
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}
        self._release = None

    def _check(self, response, what):
        if response.status_code >= 300:
            raise QueueError(f"Could not {what}: HTTP {response.status_code} {response.text[:200]}")
        return response

    def release(self, create=False):
        """The "queue" release (made when create=True and it does not exist yet), or None."""
        if self._release:
            return self._release
        response = requests.get(f"{self.api}/repos/{self.repo}/releases/tags/{TAG}", headers=self.headers,
                                timeout=60)
        if response.status_code == 404:
            if not create:
                return None
            response = requests.post(f"{self.api}/repos/{self.repo}/releases", headers=self.headers, timeout=60,
                                     json={"tag_name": TAG, "name": "queue",
                                           "body": "HARMIS upload queue: videos made by the bulk workflow, "
                                                   "uploaded to YouTube a few a day by the daily workflow "
                                                   "and then deleted from here.",
                                           "draft": False, "prerelease": True})
        self._release = self._check(response, "read the queue release").json()
        return self._release

    def assets(self):
        release = self.release()
        if not release:
            return []
        found, page = [], 1
        while True:
            response = self._check(requests.get(f"{self.api}/repos/{self.repo}/releases/{release['id']}/assets",
                                                headers=self.headers, params={"per_page": 100, "page": page},
                                                timeout=60), "list the queue")
            found += response.json()
            if len(response.json()) < 100:
                return found
            page += 1

    def items(self):
        """Queued videos: [{"stem", "story", "format", "created", "assets": {ext: asset}}], oldest first."""
        groups = {}
        for asset in self.assets():
            stem, ext = split_name(asset["name"])
            if ext:
                groups.setdefault(stem, {})[ext] = asset
        items = []
        for stem, assets in groups.items():
            if ".mp4" not in assets:
                continue
            match = re.match(r"^\d{8}-\d{6}_(short|long)_(.+)$", stem)
            items.append({"stem": stem, "format": match.group(1) if match else "short",
                          "story": match.group(2) if match else stem,
                          "created": assets[".mp4"]["created_at"], "assets": assets})
        return sorted(items, key=lambda item: item["created"])

    def add(self, video):
        """Upload <video>.mp4 with its .json and .story.json. Returns the queue name."""
        import json
        base = os.path.splitext(video)[0]
        try:
            with open(base + ".story.json", encoding="utf-8") as file:
                meta = json.load(file)
        except (OSError, ValueError):
            raise QueueError(f"{base}.story.json is missing; make the video with `python -m harmis.main`.")
        story = re.sub(r"[^a-z0-9_]", "_", (meta.get("story_id") or "story").lower())
        stem = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%d-%H%M%S}_{meta.get('format', 'short')}_{story}"
        release = self.release(create=True)
        for ext, kind in ((".json", "application/json"), (".story.json", "application/json"),
                          (".mp4", "video/mp4")):  # the mp4 last: an item counts only when its mp4 is there
            if not os.path.exists(base + ext):
                continue
            with open(base + ext, "rb") as file:
                self._check(requests.post(f"{self.uploads}/repos/{self.repo}/releases/{release['id']}/assets",
                                          params={"name": stem + ext}, data=file, timeout=900,
                                          headers={**self.headers, "Content-Type": kind}), f"upload {ext}")
        print(f"[queue] Added {stem}")
        return stem

    def download(self, item, folder):
        """Save an item's files in folder; returns the local .mp4 path."""
        for ext, asset in item["assets"].items():
            response = self._check(requests.get(asset["url"], timeout=900, stream=True,
                                                headers={**self.headers, "Accept": "application/octet-stream"}),
                                   f"download {asset['name']}")
            with open(os.path.join(folder, item["stem"] + ext), "wb") as file:
                for chunk in response.iter_content(1024 * 1024):
                    file.write(chunk)
        return os.path.join(folder, item["stem"] + ".mp4")

    def remove(self, item):
        for asset in item["assets"].values():
            requests.delete(f"{self.api}/repos/{self.repo}/releases/assets/{asset['id']}", headers=self.headers,
                            timeout=60)
        print(f"[queue] Removed {item['stem']} from the queue")


def github_output(**values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            for key, value in values.items():
                file.write(f"{key}={value}\n")


def publish_from_queue(max_count, dry_run=False):
    """Upload up to max_count queued videos (within today's limit). Returns (queued, uploaded, failed)."""
    from . import daily
    from .publish import publish_video
    queue = Queue()
    items = queue.items()
    allowed = min(max_count, daily.budget())
    print(f"[queue] {len(items)} video(s) in the queue; uploading up to {allowed} now.")
    published = daily.published_stories()
    uploaded = failed = 0
    with tempfile.TemporaryDirectory(prefix="harmis_queue_") as folder:
        for item in choose(items, len(items)):
            if uploaded + failed >= allowed:
                break
            if item["story"] in published:
                print(f"[queue] {item['story']} is already on YouTube; removing the copy from the queue.")
                if not dry_run:
                    queue.remove(item)
                continue
            video = queue.download(item, folder)
            if publish_video(video, ["youtube"], dry_run=dry_run):
                failed += 1  # stays in the queue for the next run (often the quota is used up)
                break
            uploaded += 1
            published.add(item["story"])
            if not dry_run:
                queue.remove(item)
    return len(items), uploaded, failed


def main():
    parser = argparse.ArgumentParser(description="HARMIS upload queue (GitHub Release 'queue').")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show the queued videos")
    sub.add_parser("count", help="print how many videos are queued")
    add = sub.add_parser("add", help="add videos to the queue")
    add.add_argument("videos", nargs="+")
    pub = sub.add_parser("publish", help="upload the oldest queued videos to YouTube")
    pub.add_argument("--max", type=int, default=2)
    pub.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "list":
            items = Queue().items()
            for item in items:
                print(f"{item['created']}  {item['format']:<5}  {item['story']}")
            print(f"[queue] {len(items)} video(s) waiting.")
        elif args.command == "count":
            print(len(Queue().items()))
        elif args.command == "add":
            queue = Queue()
            for video in args.videos:
                queue.add(video)
        else:
            queued, uploaded, failed = publish_from_queue(args.max, args.dry_run)
            github_output(queued=queued, uploaded=uploaded, failed=failed)
            print(f"[queue] queued before: {queued}, uploaded: {uploaded}, failed: {failed}")
            sys.exit(1 if failed else 0)
    except QueueError as error:
        sys.exit(f"[queue] {error}")


if __name__ == "__main__":
    main()
