# Privacy Policy – HARMIS

**App name:** HARMIS
**Owner:** Anand
**YouTube channel:** Kahani Khazana
**Contact:** sunandthakur912@gmail.com
**Effective date:** 15 October 2026

## 1. What HARMIS is

HARMIS is a personal tool used **only by its owner, Anand**. It makes original
animated Hindi story videos for children and uploads them to the owner's own
YouTube channel ("Kahani Khazana") and the owner's own Instagram account.
It is not offered to the public, and no other person signs in to it.

## 2. Google / YouTube data

- HARMIS asks Google for **only one permission (OAuth scope)**:
  `https://www.googleapis.com/auth/youtube.upload`. This is used to upload
  the owner's own videos (with their title, description, tags and an optional
  thumbnail) to the owner's own channel.
- HARMIS does **not** read, collect or store any other YouTube or Google data:
  no viewer data, comments, subscribers, analytics, contacts, emails or files.
- HARMIS collects **no data from any other person**. Only the channel owner
  ever signs in.

## 3. How access tokens are stored

- The OAuth client secret and the access/refresh token are stored only as
  **private GitHub / GitHub Codespaces secrets** of the owner's account.
- When the owner signs in with `python -m harmis.publish_youtube --auth`, the
  token is also saved in a private file (`~/.config/harmis/youtube_token.json`,
  readable only by the owner) inside the owner's own Codespace or computer.
- Tokens and secrets are **never** committed to the code repository, never
  published, and never sent anywhere except to Google to upload videos.

## 4. Sharing and selling

HARMIS does **not** sell, rent, share or transfer any data to anyone. It shows
no ads, uses no analytics or tracking, and sets no cookies.

## 5. Instagram

For Instagram, HARMIS uses the owner's own Instagram professional account
through Meta's Instagram Graph API, only to post the owner's own short videos.
The access token is stored as a private secret in the same way. To let
Instagram download a video, the video file is put online for a few minutes as a
GitHub Release asset on the owner's public repository and then deleted
automatically.

## 6. Removing access and deleting data

- The owner can revoke HARMIS's access to the Google account at any time at
  <https://myaccount.google.com/permissions>.
- Deleting the GitHub / Codespaces secrets and the local token file removes all
  stored tokens. HARMIS keeps no other copy.
- Uploaded videos can be removed at any time in YouTube Studio or the Instagram app.

## 7. Policies HARMIS follows

HARMIS complies with:

- the [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service)
- the [Google Privacy Policy](https://policies.google.com/privacy)
- the [YouTube Terms of Service](https://www.youtube.com/t/terms)

By using HARMIS to upload to YouTube, the owner agrees to the YouTube Terms of
Service, and Google's handling of data is described in the Google Privacy Policy.

## 8. Changes

If this policy changes, the new version will be published in this file
(`PRIVACY.md`) in the HARMIS repository, with a new effective date.

## 9. Contact

Questions about this policy: **sunandthakur912@gmail.com**
