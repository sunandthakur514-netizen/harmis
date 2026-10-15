"""Upload a video to YouTube (YouTube Data API v3, free quota).

One-time sign-in (makes a token you can keep as a secret):
    python -m harmis.publish_youtube --auth

Secrets (never commit them):
    YT_CLIENT_SECRET_JSON  contents of client_secret.json (or put the file at the
                           path in YT_CLIENT_SECRET_FILE, default ./client_secret.json)
    YT_TOKEN_JSON          contents of the token printed by --auth (or the file
                           ~/.config/harmis/youtube_token.json, written by --auth)

Short videos become Shorts automatically (vertical, under 3 minutes, "#shorts" in
the title). Needs the optional packages in requirements-publish.txt.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse

from .config import CONFIG

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = os.path.expanduser("~/.config/harmis/youtube_token.json")
KIDS_GENRES = {"kids_story", "kids_rhyme"}

LOCK_MESSAGE = (
    "[youtube] NOTE: YouTube keeps videos uploaded through a NEW (unverified) Google Cloud "
    "project locked as PRIVATE, even if you asked for public or unlisted. Your video is "
    "safe; you can watch it in YouTube Studio. To publish it: make it public by hand in YouTube "
    "Studio, or ask Google for an API audit (Google Cloud > YouTube Data API > 'API audit' form) "
    "so future uploads keep the privacy you choose."
)


class YouTubeSetupError(Exception):
    """Missing packages / client secret / token. The message says what to do."""


def _client_config():
    text = os.environ.get("YT_CLIENT_SECRET_JSON")
    if not text:
        path = os.environ.get("YT_CLIENT_SECRET_FILE", "client_secret.json")
        if not os.path.exists(path):
            raise YouTubeSetupError("No YouTube client secret: set YT_CLIENT_SECRET_JSON or put "
                                    "client_secret.json in the project folder (see README).")
        with open(path, encoding="utf-8") as file:
            text = file.read()
    return json.loads(text)


def _imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise YouTubeSetupError("YouTube packages are not installed: pip install -r requirements-publish.txt")
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


def credentials():
    """Saved OAuth token (refreshed automatically when it expires)."""
    Request, Credentials, *_ = _imports()
    text = os.environ.get("YT_TOKEN_JSON")
    if not text and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as file:
            text = file.read()
    if not text:
        raise YouTubeSetupError("No YouTube token: run `python -m harmis.publish_youtube --auth` once "
                                "and save the token as YT_TOKEN_JSON (see README).")
    creds = Credentials.from_authorized_user_info(json.loads(text), SCOPES)
    if not creds.valid:
        if creds.refresh_token:
            creds.refresh(Request())
        else:
            raise YouTubeSetupError("The YouTube token has expired and cannot be refreshed: run --auth again.")
    return creds


def authorize():
    """One-time sign-in. Works on a laptop and in a browser Codespace (copy-paste the address)."""
    *_, InstalledAppFlow, _build, _err, _media = _imports()
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES, redirect_uri="http://localhost:8080/")
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    print("1. Open this address and sign in with the Google account of your YouTube channel:\n\n   "
          + url + "\n")
    print("2. Allow access. Your browser then goes to an address starting with http://localhost:8080/ "
          "(it is fine if the page does not load).")
    answer = input("3. Copy that WHOLE address from the browser's address bar and paste it here: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(answer).query).get("code", [answer])[0]
    flow.fetch_token(code=code)
    token = flow.credentials.to_json()
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as file:
        file.write(token)
    os.chmod(TOKEN_FILE, 0o600)
    print(f"\nSaved {TOKEN_FILE}.\nFor GitHub Actions / Codespaces, add a secret named YT_TOKEN_JSON "
          "with this value (keep it private!):\n\n" + token)


def privacy_status(override=None):
    """--privacy, else config.yaml (publish.youtube.privacy, or privacyStatus), default private."""
    settings = CONFIG["publish"]["youtube"]
    value = str(override or settings.get("privacyStatus") or settings.get("privacy") or "private").lower()
    if value not in ("private", "unlisted", "public"):
        raise ValueError(f"YouTube privacy must be private, unlisted or public (config.yaml says '{value}')")
    return value


def build_request_body(captions, genre, privacy=None):
    """The video details sent to YouTube."""
    settings = CONFIG["publish"]["youtube"]
    yt = captions["youtube"]
    tags, total = [], 0
    for tag in yt["tags"]:  # YouTube allows about 500 characters of tags in total
        if total + len(tag) + 2 > 480:
            break
        tags.append(tag)
        total += len(tag) + 2
    return {
        "snippet": {
            "title": yt["title"][:100],
            "description": yt["description"][:5000],
            "tags": tags,
            "categoryId": str(settings.get("category_id", "27")),
            "defaultLanguage": settings.get("language", "hi"),
            "defaultAudioLanguage": settings.get("language", "hi"),
        },
        "status": {
            "privacyStatus": privacy_status(privacy),
            "selfDeclaredMadeForKids": genre in KIDS_GENRES,
            "embeddable": True,
        },
    }


def make_thumbnail(video_path, at_seconds=2.0):
    """Title card of a long video as a 1280x720 JPEG (YouTube's thumbnail size)."""
    import imageio_ffmpeg
    path = os.path.join(tempfile.mkdtemp(prefix="harmis_thumb_"), "thumbnail.jpg")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(at_seconds),
                    "-i", video_path, "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "3", path], check=True)
    return path


def upload(video_path, captions, genre, fmt, privacy=None, dry_run=False):
    """Upload the video. Returns {"id", "url", "privacy"} (or the plan when dry_run)."""
    body = build_request_body(captions, genre, privacy)
    want_thumbnail = fmt == "long" and CONFIG["publish"]["youtube"].get("thumbnail_for_long", True)
    if dry_run:
        print("[youtube] DRY RUN - would upload:", video_path)
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"[youtube] as a {'Short' if fmt == 'short' else 'normal video'}"
              + ("; would also set a custom thumbnail from the title card" if want_thumbnail else ""))
        return {"id": "", "url": "(dry run)", "privacy": body["status"]["privacyStatus"]}

    *_, build, HttpError, MediaFileUpload = _imports()
    youtube = build("youtube", "v3", credentials=credentials(), cache_discovery=False)
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    print(f"[youtube] Uploading {os.path.basename(video_path)} ...")
    try:
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[youtube]   {int(status.progress() * 100)}%")
    except HttpError as error:
        reason = ""
        try:
            reason = json.loads(error.content)["error"]["errors"][0].get("reason", "")
        except Exception:
            pass
        hints = {"quotaExceeded": "the daily free API quota is used up; try again tomorrow",
                 "uploadLimitExceeded": "the channel reached YouTube's upload limit for today",
                 "youtubeSignupRequired": "this Google account has no YouTube channel yet"}
        raise RuntimeError(f"YouTube upload failed (HTTP {error.resp.status} {reason}): "
                           f"{hints.get(reason, 'see the message above')}") from None

    video_id = response["id"]
    got_privacy = response.get("status", {}).get("privacyStatus", body["status"]["privacyStatus"])
    url = f"https://youtube.com/shorts/{video_id}" if fmt == "short" else f"https://youtu.be/{video_id}"
    print(f"[youtube] Uploaded: {url} (privacy: {got_privacy})")
    if body["status"]["privacyStatus"] != "private":
        print(LOCK_MESSAGE)

    if want_thumbnail:
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(make_thumbnail(video_path),
                                                                                 mimetype="image/jpeg")).execute()
            print("[youtube] Custom thumbnail set.")
        except HttpError as error:
            print(f"[youtube] Could not set the thumbnail (HTTP {error.resp.status}). Custom thumbnails need "
                  "a verified channel (YouTube Studio > Settings > Channel > Feature eligibility).")
    return {"id": video_id, "url": url, "privacy": got_privacy}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube helper for HARMIS.")
    parser.add_argument("--auth", action="store_true", help="sign in once and save a token")
    if parser.parse_args().auth:
        try:
            authorize()
        except YouTubeSetupError as error:
            sys.exit(str(error))
    else:
        parser.print_help()
