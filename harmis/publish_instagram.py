"""Post a short video as an Instagram Reel (Instagram Graph API, free).

    python -m harmis.publish_instagram --check           # is the token OK?
    python -m harmis.publish_instagram --refresh-token   # new 60-day token

Secrets (never commit them):
    IG_USER_ID       the Instagram professional account id
    IG_ACCESS_TOKEN  long-lived access token (lasts 60 days; refresh it before then)
    GITHUB_TOKEN     to put the video online for a moment (see below)
    META_APP_ID, META_APP_SECRET   only needed for --refresh-token

Instagram must download the video from a public web address. HARMIS uploads it
as a GitHub Release asset on this (public) repository, lets Instagram fetch it,
and deletes the release again straight after, even if something fails.
"""

import argparse
import os
import re
import subprocess
import sys
import time

import requests

from .config import CONFIG


class InstagramError(Exception):
    pass


def settings():
    return CONFIG["publish"]["instagram"], CONFIG["publish"]["github"]


def _need(name):
    value = os.environ.get(name)
    if not value:
        raise InstagramError(f"{name} is not set (see README: Instagram setup).")
    return value


def _graph_error(response):
    try:
        error = response.json().get("error", {})
        message = f"{error.get('message', response.text[:200])} (code {error.get('code')})"
        if error.get("code") == 190:
            message += " - the access token has expired: run --refresh-token or make a new one."
        return message
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"


def github_repo():
    """owner/name of this repository (GITHUB_REPOSITORY, or the git remote)."""
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True,
                             check=True).stdout.strip()
    except Exception:
        raise InstagramError("Cannot tell which GitHub repository to use: set GITHUB_REPOSITORY=owner/name.")
    match = re.search(r"github\.com[/:]([^/]+/[^/.]+?)(\.git)?$", url) or re.search(r"/git/([^/]+/[^/.]+)", url)
    if not match:
        raise InstagramError("Cannot tell which GitHub repository to use: set GITHUB_REPOSITORY=owner/name.")
    return match.group(1)


class TemporaryPublicLink:
    """Upload a file as a GitHub Release asset; delete the release (and tag) on exit."""

    def __init__(self, path):
        _, github = settings()
        self.path, self.api, self.uploads = path, github["api"].rstrip("/"), github["uploads"].rstrip("/")
        self.repo = github_repo()
        self.headers = {"Authorization": f"Bearer {_need('GITHUB_TOKEN')}",
                        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        self.release_id = self.tag = None

    def __enter__(self):
        self.tag = f"harmis-instagram-{int(time.time())}"
        response = requests.post(f"{self.api}/repos/{self.repo}/releases", headers=self.headers, timeout=60, json={
            "tag_name": self.tag, "name": "Temporary Instagram upload (deleted automatically)",
            "body": "Made by HARMIS so Instagram can fetch the video. Deleted right after posting.",
            "draft": False, "prerelease": True})
        if response.status_code >= 300:
            raise InstagramError(f"Could not create a GitHub release: HTTP {response.status_code} {response.text[:200]}")
        self.release_id = response.json()["id"]
        name = os.path.basename(self.path)
        with open(self.path, "rb") as file:
            upload = requests.post(f"{self.uploads}/repos/{self.repo}/releases/{self.release_id}/assets",
                                   params={"name": name}, data=file, timeout=600,
                                   headers={**self.headers, "Content-Type": "video/mp4"})
        if upload.status_code >= 300:
            raise InstagramError(f"Could not upload the video to GitHub: HTTP {upload.status_code} {upload.text[:200]}")
        url = upload.json()["browser_download_url"]
        print(f"[instagram] Video is online for a moment at {url}")
        return url

    def __exit__(self, *exc):
        if self.release_id:
            requests.delete(f"{self.api}/repos/{self.repo}/releases/{self.release_id}", headers=self.headers, timeout=60)
        if self.tag:
            requests.delete(f"{self.api}/repos/{self.repo}/git/refs/tags/{self.tag}", headers=self.headers, timeout=60)
        print("[instagram] Temporary GitHub release deleted.")
        return False


def publish_reel(video_path, caption, fmt, dry_run=False):
    """Post a short video as a Reel. Returns {"id", "url"}."""
    if fmt != "short":
        raise InstagramError("Instagram Reels are for short vertical videos only; this is a long video.")
    ig, _ = settings()
    graph = ig["graph_api"].rstrip("/")
    if dry_run:
        print(f"[instagram] DRY RUN - would post {video_path} as a Reel")
        print(f"[instagram]   1. upload it as a temporary GitHub Release asset on {github_repo()}")
        print(f"[instagram]   2. POST {graph}/<IG_USER_ID>/media  media_type=REELS, share_to_feed={ig.get('share_to_feed', True)}")
        print("[instagram]   3. wait until the container status is FINISHED, then media_publish")
        print("[instagram]   4. delete the temporary release")
        print(f"[instagram] caption ({len(caption)} characters):\n{caption}")
        return {"id": "", "url": "(dry run)"}

    user_id, token = _need("IG_USER_ID"), _need("IG_ACCESS_TOKEN")
    with TemporaryPublicLink(video_path) as video_url:
        response = requests.post(f"{graph}/{user_id}/media", timeout=60, data={
            "media_type": "REELS", "video_url": video_url, "caption": caption,
            "share_to_feed": str(ig.get("share_to_feed", True)).lower(), "access_token": token})
        if response.status_code >= 300:
            raise InstagramError("Could not create the Reel: " + _graph_error(response))
        container = response.json()["id"]
        print(f"[instagram] Instagram is processing the video (container {container}) ...")
        deadline = time.time() + float(ig.get("max_wait_seconds", 900))
        while True:
            status = requests.get(f"{graph}/{container}", timeout=60,
                                  params={"fields": "status_code,status", "access_token": token}).json()
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram could not process the video: {status.get('status', code)}")
            if time.time() > deadline:
                raise InstagramError("Instagram took too long to process the video; try again later.")
            time.sleep(float(ig.get("poll_seconds", 10)))
        response = requests.post(f"{graph}/{user_id}/media_publish", timeout=60,
                                 data={"creation_id": container, "access_token": token})
        if response.status_code >= 300:
            raise InstagramError("Could not publish the Reel: " + _graph_error(response))
    media_id = response.json()["id"]
    link = requests.get(f"{graph}/{media_id}", timeout=60,
                        params={"fields": "permalink", "access_token": token}).json().get("permalink", "")
    print(f"[instagram] Posted: {link or media_id}")
    return {"id": media_id, "url": link}


def check_token():
    ig, _ = settings()
    response = requests.get(f"{ig['graph_api'].rstrip('/')}/{_need('IG_USER_ID')}", timeout=60,
                            params={"fields": "username,name", "access_token": _need("IG_ACCESS_TOKEN")})
    if response.status_code >= 300:
        raise InstagramError(_graph_error(response))
    print(f"[instagram] Token OK for @{response.json().get('username')}")


def refresh_token():
    """Exchange the current long-lived token for a fresh 60-day one."""
    ig, _ = settings()
    response = requests.get(f"{ig['graph_api'].rstrip('/')}/oauth/access_token", timeout=60, params={
        "grant_type": "fb_exchange_token", "client_id": _need("META_APP_ID"),
        "client_secret": _need("META_APP_SECRET"), "fb_exchange_token": _need("IG_ACCESS_TOKEN")})
    if response.status_code >= 300:
        raise InstagramError(_graph_error(response))
    data = response.json()
    days = int(data.get("expires_in", 0)) // 86400
    print("New long-lived token (save it as IG_ACCESS_TOKEN, keep it private):\n\n" + data["access_token"]
          + (f"\n\nIt lasts about {days} days." if days else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram helper for HARMIS.")
    parser.add_argument("--check", action="store_true", help="check that IG_USER_ID / IG_ACCESS_TOKEN work")
    parser.add_argument("--refresh-token", action="store_true", help="get a fresh 60-day access token")
    args = parser.parse_args()
    try:
        if args.refresh_token:
            refresh_token()
        elif args.check:
            check_token()
        else:
            parser.print_help()
    except InstagramError as error:
        sys.exit(f"[instagram] {error}")
