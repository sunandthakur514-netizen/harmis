# HARMIS

Automated 2D video maker for YouTube and Instagram, made for **Indian kids and families**.

Give it a genre (or a story), a language and an art style. It makes **one video**
with a story, Indian voices, illustrated characters on illustrated backgrounds,
and big subtitles:

| `--format` | Size | Length | For |
|------------|------|--------|-----|
| `short` (default) | 1080x1920 vertical | 30–60 seconds | YouTube Shorts, Instagram Reels |
| `long` | 1920x1080 horizontal (16:9) | 5–7 minutes | normal YouTube videos |

It uses only free tools, and **always** produces a video, even fully offline.

## Genres

| Genre | What it is | Who it is for |
|-------|------------|---------------|
| `kids_story` | Gentle folk tales with a small moral (Panchatantra, Jataka, Akbar-Birbal, Tenali Raman) | Kids |
| `kids_rhyme` | Original rhymes about monsoon, mela, Diwali and food, with a soft dholak-style beat | Kids |
| `comedy` | Family comedy: gali cricket, Dadi's smartphone, mohalla life | Everyone |
| `horror` | Mildly spooky stories (old haveli, last bus). No gore. Shows a **13+** badge | Teens and adults only |

## Languages

| `--lang` | Subtitles | Voices |
|----------|-----------|--------|
| `hindi` (default) | Hindi in Devanagari (bundled Noto Sans Devanagari font) | edge-tts `hi-IN` (Swara, Madhur) |
| `hinglish` | Hindi + English in Roman letters | edge-tts `en-IN` (Neerja, Prabhat) |
| `english` | Simple Indian English | edge-tts `en-IN` (Neerja, Prabhat) |

## Art styles

| `--style` | Look |
|-----------|------|
| `3d_cartoon` | 3D animated-movie look (default for kids and comedy) |
| `storybook` | Soft watercolour picture-book look (default for horror) |
| `anime` | Clean anime line art |

The style is added to every picture prompt. Each style has its own pictures.

## How it works

| Step | File | What it does |
|------|------|--------------|
| 1 | `harmis/script.py` | Gets a story (a narrator + characters, each line has a scene). Uses Google Gemini if you have a free API key, otherwise a built-in story from `harmis/samples.py` (short) or `harmis/samples_long.py` (long). |
| 2 | `harmis/voice.py` | Turns every line into speech with **edge-tts** Indian voices. |
| 3 | `harmis/library.py` + `harmis/providers.py` | Gets a picture for every character and scene, from the cache or from a free AI image service. |
| 4 | `harmis/animate.py` | Layers the characters over the backgrounds and builds the video with **Pillow** + **MoviePy**. |
| 5 | `harmis/main.py` | The command you run. All settings live in `config.yaml`. |
| – | `harmis/prepare.py` | Makes and caches all pictures for a story in advance, slowly, without making a video. |

### Pictures: free providers with fallback

Every picture is requested from these providers, in this order (change it in `config.yaml`):

1. **Pollinations.ai**: free, no key needed. Its free tier can stop after a
   picture or two with *HTTP 402 Payment Required*. HARMIS then skips it for the
   rest of the run straight away.
2. **local_sd**: Stable Diffusion Turbo on **your own CPU**. Free and unlimited,
   but optional (see [Unlimited local pictures](#unlimited-local-pictures-local_sd)).
   Skipped with a log line if its packages are not installed.
3. **Gemini image generation**: only if `GEMINI_API_KEY` is set
4. **Hugging Face free inference**: only if `HF_TOKEN` is set (free account at huggingface.co)
5. **Simple shape style**: drawn by HARMIS itself, always works

Every picture's log line says which provider made it and how long it took, for
example `character birbal: made by local_sd in 41.3s`.

Free services limit how fast you may ask, so HARMIS is patient:

- **One request at a time**, with a pause between requests (`delay_seconds`,
  15 s for Pollinations).
- **Timeout of 120 s** per picture, because free pictures can be slow.
- On a **rate limit (HTTP 429), a timeout or a busy server (502/503/504)** it
  waits and tries again with growing pauses (up to 4 tries for Pollinations).
  A `Retry-After` header from the server is respected.
- **Rate limits never switch a provider off.** Only repeated real errors do:
  3 pictures in a row that failed with real errors.
- Every failed try is logged with its HTTP status code and error text.
- **Optional:** set `POLLINATIONS_TOKEN` (a free token from <https://pollinations.ai>)
  for higher Pollinations limits. It is sent as a header.

Example log:

```
[images] scene palace_court: pollinations try 1/4 failed (rate limited): HTTP 429 Too Many Requests {"error":"..."}
[images]   waiting 20s, then trying again ...
[images] scene palace_court: made by pollinations
[images]   waiting 15s before the next pollinations request ...
[images] character birbal: made by pollinations
[main] Pictures needed this run: 5 made by pollinations
```

### Prepare pictures in advance (recommended)

Making all the pictures for a story can take a few minutes because of the
pauses. Do it once, separately, then make videos as often as you like:

```bash
python -m harmis.prepare --story birbal_khichdi --style 3d_cartoon
python -m harmis.prepare --story sher_khargosh --style 3d_cartoon --format long
```

It makes every character and scene picture the story needs, one at a time, and
caches them. At the end it lists which pictures are ready and which are missing.
Run it again later to retry only the missing ones. Then
`python -m harmis.main --story birbal_khichdi` uses the cached pictures straight away.

### Character library (same look in every video)

Every character is defined once in `harmis/assets/characters/<name>/character.yaml`:
on-screen name in Hindi and English, gender and age (for the voice), and a fixed
visual description. The first time a character is needed, HARMIS:

1. asks a provider for a full-body picture on a white background,
2. removes the background with **rembg** (free, runs on your CPU), and
3. saves it as `<style>.png` (transparent), which every later video reuses.

Included: Akbar, Birbal, Tenali, Kamala, the monkey, the crocodile, the tortoise,
the swan, Chintu, Pinky, Dadi, Sharma Uncle, Meera, Rohan, Vikram, the bus conductor,
and three narrators (kids, comedy, horror). New characters invented by Gemini are
added to the library automatically.

**Use your own picture:** save it as `harmis/assets/characters/<name>/custom.png`.
It always wins over generated pictures. A transparent PNG is best. If it has a
plain background, HARMIS removes it. To make your character blink, add an
eyes-closed version as `blink.png` in the same folder.

### Scenes (backgrounds)

Scenes are listed in `harmis/assets/backgrounds/scenes.yaml` (palace court,
village, gali, school, living room, Diwali mela, monsoon village, haveli at night, and more).
Stories say which scene each line happens in. Backgrounds are generated once per
style and cached as `harmis/assets/backgrounds/<scene>__<style>.png` (vertical,
short videos) or `<scene>__<style>__wide.png` (16:9, long videos).

**Use your own background:** save it as `harmis/assets/backgrounds/<scene>.png`.
It is used for both formats (cropped to fit).

To make new pictures instead of the cached ones, add `--refresh-images`.
Generated pictures **are committed** to git, so they are made once and reused
forever (also by the GitHub Actions workflows below), and so are your own
`custom.png` and `<scene>.png` files.

### Animation

- The background moves slowly (Ken Burns zoom and pan) and **crossfades** when the scene changes.
- The **speaking** character bounces gently, grows a little and glows, and its
  **mouth flaps** with the voice (see below). The others dim slightly and breathe.
- Everyone **blinks** every 3–5 seconds.
- A round picture of the narrator appears while the narrator speaks.
- Subtitles sit in a small, see-through box with the speaker's name. In short
  videos the title stays at the top.
- Characters or scenes without a picture are drawn in the simple shape style
  (shape characters' mouths move with the voice).

### Lip movement (mouth flaps) and blinking

Every character picture gets three extra versions, made once and cached next to it:
`<picture>_mouth_half.png`, `<picture>_mouth_open.png` and `<picture>_blink.png`.
They are made with **local_sd**, which repaints only a small area around the mouth
or the eyes (same seed and description, plus "mouth open, talking" / "eyes
closed"), so the rest of the character stays exactly the same.

While a character speaks, HARMIS checks how loud the voice is every ~80 ms and
shows the closed, half-open or open mouth, smoothed so it does not flicker.

**Where is the mouth?** `character.yaml` has `mouth_box` and `eyes_box`
(`[x, y, width, height]` as fractions of the picture). If they are missing,
HARMIS finds them itself (face detection, or the shape of the head in the cut-out
picture, or a default for a `type: human` / `type: animal`). It writes the result
into `character.yaml` so you can correct the numbers. After editing, delete that
character's `*_mouth_*.png`, `*_blink.png` and `*_variants.json` to remake them.

**Fallback:** if local_sd is not installed, or repainting fails, a simple cartoon
mouth (a dark oval in a darker skin colour) is drawn over `mouth_box` and opens
with the voice. Blinking then only happens if you add your own `blink.png`.

`python -m harmis.prepare` (and the `prepare-pictures` workflow) make these
versions together with the character pictures.

### Long videos (`--format long`)

- **1920x1080 (16:9)**, 5–7 minutes, 24 frames per second. If a story comes out
  longer than 7 minutes, the voices are made again a little faster (up to +25%);
  if shorter than 5 minutes, a little slower (down to -10%).
- **Intro title card** (title and a small tagline), then the story, then an
  **ending card** ("कहानी पसंद आई? लाइक करें • शेयर करें • सब्सक्राइब करें",
  text only, no logos).
- **15–25 scenes** with a beginning, a problem, a twist and an ending (and a moral
  for kids). The narrator tells most of the story and the characters speak in between.
- Characters stand **side by side** (up to 3 per scene) and subtitles sit at the
  bottom. Each scene shows only the characters who are in it.
- **Few picture requests:** scenes reuse the same backgrounds. For example,
  *Sher aur Chatur Khargosh* has 16 scenes but only 7 background pictures, plus 3 characters and the narrator.
- **Memory-safe:** frames are drawn one at a time, all voices are mixed into one
  audio file first, and the video is rendered in 60-second pieces that ffmpeg
  joins at the end (`chunk_seconds` in `config.yaml`).
- **Stories:** Gemini (if `GEMINI_API_KEY` is set) writes long stories in Hindi,
  Hinglish or English for any genre. Without Gemini, two built-in long **Hindi**
  stories are used (see below). Other languages then switch to Hindi, with a note in the log.

### Kid safety

Every picture prompt gets kid-safe words added (kid-friendly, wholesome,
non-violent, no gore, no weapons, original character design, no text). Names of
copyrighted characters and studios are removed from every prompt. Edit both lists
under `safety:` in `config.yaml`. Horror stays mild and is marked 13+.

## Setup

1. Install **Python 3.10 or newer**.
2. Install **ffmpeg** (MoviePy needs it):
   - Windows: `winget install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
3. Install the Python packages:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

   The first time a background is removed, rembg downloads its model (about 170 MB) once.

4. *(Optional)* Unlimited pictures on your own CPU: see
   [Unlimited local pictures](#unlimited-local-pictures-local_sd).

5. *(Optional)* Free API keys for more picture providers and AI-written stories:

   ```bash
   export GEMINI_API_KEY="your-key"   # https://aistudio.google.com/apikey  (stories + pictures)
   export HF_TOKEN="your-token"       # https://huggingface.co/settings/tokens (pictures)
   export POLLINATIONS_TOKEN="token"  # free token from https://pollinations.ai (higher limits)
   ```

   On Windows use `set NAME=value`. Without keys the tool still works: it uses
   Pollinations (no key needed) and built-in stories.

## Run it

```bash
python -m harmis.main --genre kids_story                          # Hindi, 3d_cartoon
python -m harmis.main --story birbal_khichdi --style 3d_cartoon   # one specific story
python -m harmis.main --genre comedy --lang hinglish --style anime
python -m harmis.main --genre horror --lang english
python -m harmis.main --genre kids_rhyme --providers none         # no AI pictures, shape style only

# Long 5-7 minute videos (16:9)
python -m harmis.prepare --story sher_khargosh --format long      # pictures first (optional)
python -m harmis.main --story sher_khargosh                       # built-in long Hindi story
python -m harmis.main --genre kids_story --format long            # Gemini story if GEMINI_API_KEY is set
```

The video is saved as `output/<date>_<genre>_<lang>.mp4` (long videos end in
`_long.mp4`). If that file already exists, `_2`, `_3`, … is added so old videos are kept.

Options:

- `--genre kids_story|kids_rhyme|comedy|horror`: the type of story
- `--story ID`: a specific built-in story (the genre and format are picked automatically)
- `--format short|long`: vertical 30–60 s (default) or 16:9 5–7 minutes
- `--lang hindi|hinglish|english`: the language (default from `config.yaml`: `hindi`)
- `--style storybook|3d_cartoon|anime`: the art style (default from `config.yaml` per genre)
- `--providers pollinations,local_sd,gemini,huggingface`: which picture providers to try, in order;
  `--providers none` turns AI pictures off
- `--refresh-images`: make new pictures even if cached ones exist
- `--offline`: do not call Gemini for the story
- `--out FOLDER`: save the video somewhere other than `output/`

The first video with new characters takes longer, because the pictures are
generated first (or use `harmis.prepare` beforehand). After that, a short video
takes about a minute. A long video takes roughly 10–20 minutes, depending on your computer.

## Run it on GitHub Actions (free, no computer needed)

The repository is public, so GitHub's standard runners (4 CPU cores, 16 GB) are
free. Two workflows do the heavy work there. Start them from the **Actions** tab
of the repository: pick the workflow on the left, click **Run workflow**, choose
the options, and click the green **Run workflow** button.

### `prepare-pictures`: make and commit a story's pictures

Options: **story**, **style** (`auto` = the genre's style) and **format** (`auto` = the story's own format).

1. **list**: finds which scene and character pictures the story still needs.
2. **generate**: makes each missing picture in its own job, up to 5 at a time,
   with `local_sd` (Stable Diffusion Turbo on the runner's CPU). The model and the
   pip packages are cached, so only the very first run downloads them.
3. **commit**: collects the new pictures and commits them to `harmis/assets/`.

Pictures that already exist are skipped, so you can run it again to fill in any
that failed. Locally, the same steps are:
`python -m harmis.prepare --story <id> --list-file missing.json` and
`python -m harmis.prepare --story <id> --providers local_sd --only scene:palace_court`.

After it has committed, run `git pull` to get the pictures on your own computer too.

### `make-video`: render a video and download it

Options: **story**, **lang**, **style**, **format**, and **make missing pictures**.

It installs HARMIS, ffmpeg and espeak-ng, renders the video with the pictures in
`harmis/assets/`, and attaches the mp4 to the run. Open the finished run, scroll to
**Artifacts**, and download `harmis-video-<story>-<lang>` (a zip with the mp4;
kept for 30 days). Real edge-tts voices work there, because the runners have internet.

Run `prepare-pictures` first for a new story. Otherwise missing pictures are drawn
in the shape style. Ticking **make missing pictures** makes them with `local_sd`
during the video run instead, which is slower, and those pictures are **not** committed.

Both workflows use **Python 3.12** and install the small CPU-only torch from the
PyTorch index.

## Publishing to YouTube and Instagram

Every video gets captions automatically: `harmis.main` saves `<video>.story.json`
(what the story is about) and `<video>.json` with a title (max 90 characters), a
description and hashtags in Hindi and English. Gemini writes them if
`GEMINI_API_KEY` is set; otherwise templates use the story's title, moral,
characters and genre plus the hashtag lists under `publish: hashtags:` (channel tag `#KahaniKhazana`, channel name under `publish: channel_name:`) in
`config.yaml`. Shorts get `#shorts`, Reels get `#reels`, and copyrighted names
are always removed. You can make them again with `python -m harmis.captions <video>.mp4`.

**Publish a video:**

```bash
python -m harmis.publish --video output/2026-10-15_kids_story_hindi.mp4 --to youtube,instagram --dry-run
python -m harmis.publish --video output/2026-10-15_kids_story_hindi.mp4 --to youtube,instagram
```

- `--dry-run` shows exactly what would be posted and posts nothing. Always try it first.
- Short videos go to YouTube as **Shorts** and to Instagram as **Reels**. Long
  videos go to YouTube as normal videos; Instagram skips them.
- YouTube: category Education, language Hindi, "made for kids" on for kids
  stories and rhymes, privacy from `config.yaml` (default **private**) or `--privacy`.
  Long videos also get the title card as their thumbnail.
- Each real post is added to `output/published.csv` (time, video, platform, link). Leave out `--video` (or give a folder) to publish the newest video that has its `.json`.

### Secrets: what to set

Secrets are **never** committed (`.gitignore` blocks `client_secret*.json` and
`*token*.json`). Put them in **Codespaces secrets** (GitHub > your profile >
Settings > Codespaces > Secrets) or **repository secrets** (repository >
Settings > Secrets and variables > Actions).

| Secret | Used for | Where it comes from |
|--------|----------|---------------------|
| `YT_CLIENT_SECRET_JSON` | YouTube | the whole content of `client_secret.json` (step 4 below) |
| `YT_TOKEN_JSON` | YouTube | printed by `python -m harmis.publish_youtube --auth` (step 7) |
| `IG_USER_ID` | Instagram | your Instagram professional account id (Instagram step 7) |
| `IG_ACCESS_TOKEN` | Instagram | long-lived token (Instagram step 6) |
| `META_APP_ID`, `META_APP_SECRET` | Instagram token refresh | Meta app > App settings > Basic |
| `GITHUB_TOKEN` | Instagram (temporary video link) | already there in GitHub Actions; in Codespaces it is set automatically, or make a fine-grained token with "Contents: read and write" for this repository |
| `GEMINI_API_KEY` | better captions (optional) | <https://aistudio.google.com/apikey> |

Install the YouTube packages once: `pip install -r requirements-publish.txt`.

### YouTube setup (one time, about 15 minutes)

1. Go to <https://console.cloud.google.com/> and sign in with the Google account
   that owns your YouTube channel. Click the project menu at the top, then
   **New project**. Name it, for example "harmis", and click **Create**.
2. Open **APIs & Services > Library**, search for **YouTube Data API v3**, and
   click **Enable**.
3. Open **APIs & Services > OAuth consent screen** (also called **Google Auth Platform**):
   - User type: **External**. Fill in the app name, your email, and the developer email.
   - **Audience / Test users**: add your own Gmail address. Leave the app in **Testing**.
4. Open **APIs & Services > Credentials > Create credentials > OAuth client ID**:
   - Application type: **Desktop app**. Click **Create**, then **Download JSON**.
   - Save it as `client_secret.json` in the project folder (it is git-ignored),
     or paste its content into the secret `YT_CLIENT_SECRET_JSON`.
5. `pip install -r requirements-publish.txt`
6. Run `python -m harmis.publish_youtube --auth`.
7. Open the link it prints and sign in. The app is unverified, so Google warns you:
   click **Advanced > Go to harmis (unsafe)** (it is your own app), then **Allow**.
   The browser then goes to an address starting with `http://localhost:8080/`; the
   page may not load, which is fine. Copy the **whole address** and paste it into
   the terminal. HARMIS saves the token and prints it: save it as the secret `YT_TOKEN_JSON`.
8. Test: `python -m harmis.publish --video output/<file>.mp4 --to youtube --dry-run`, then without `--dry-run`.

**Good to know:**
- **Private lock:** YouTube locks videos uploaded through a new, unverified
  project as **private**, even if you ask for public. HARMIS tells you when this
  can happen. Make the video public by hand in YouTube Studio, or fill in Google's
  YouTube API audit form so later uploads keep the privacy you choose.
- **Quota:** the free quota is about 6 uploads a day.
- **Thumbnails:** custom thumbnails need a phone-verified channel (YouTube Studio >
  Settings > Channel > Feature eligibility).
- **Expired sign-in:** while the app is in "Testing", Google may ask you to sign in
  again after 7 days. Run `--auth` again and update `YT_TOKEN_JSON`.

### Instagram setup (one time, about 20 minutes)

1. In the Instagram app: **Settings > Account type and tools > Switch to professional
   account**, and choose **Creator** (or Business).
2. Create a **Facebook Page** (facebook.com > Pages > Create new Page), if you do not have one.
3. Link them: Instagram **Settings > Accounts Center**, add your Facebook account,
   and connect the Instagram account to the Page (or do it from the Page:
   Settings > Linked accounts > Instagram).
4. Go to <https://developers.facebook.com/>, click **My Apps > Create app**, choose
   the use case for managing Instagram content / **Business** type, and create it.
   In the app, add the **Instagram** product (Instagram API with Facebook Login).
5. Open **Tools > Graph API Explorer**, select your app, and click **Generate Access Token**
   with these permissions: `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `business_management`. Allow access
   for your Page and Instagram account.
6. Make the token **long-lived** (60 days): open **Tools > Access Token Debugger**,
   paste the token, and click **Extend Access Token**. Save the new token as
   `IG_ACCESS_TOKEN`.
7. Find your **IG_USER_ID**: in the Graph API Explorer, request
   `me/accounts?fields=instagram_business_account{id,username}`. The `id` inside
   `instagram_business_account` is your `IG_USER_ID`.
8. Check: `python -m harmis.publish_instagram --check` should print your username.
9. Test: `python -m harmis.publish --video output/<short file>.mp4 --to instagram --dry-run`,
   then without `--dry-run`.

**Good to know:**
- **Temporary public link:** Instagram must download the video from a public
  address. HARMIS uploads it for a moment as a GitHub Release asset on this public
  repository and deletes it right after posting, even if posting fails.
- **Token renewal:** the token lasts 60 days. Renew it before then with
  `python -m harmis.publish_instagram --refresh-token` (needs `META_APP_ID` and
  `META_APP_SECRET`) and save the new token as `IG_ACCESS_TOKEN`.
- **Limits:** about 50 posts per day through the API.

## Settings: `config.yaml`

Change these without touching the code:

- `defaults`: language, style, output folder
- `video`: crossfade time, size of the pieces long videos are rendered in
- `formats`: size, frames per second, minimum and maximum length for `short` and
  `long`, plus the long-video intro and ending card times
- `image_providers`: provider order, and per provider: timeout, tries, pause
  between requests, first wait after a rate limit, model
- `styles`: the words each art style adds to prompts
- `safety`: kid-safe words added to prompts, words that are removed, negative prompt
- `genres`: per genre: art style, narrator character, narrator voice, default scene and mood
- `publish`: YouTube privacy, category and language; Instagram API settings; hashtag lists

## Built-in stories

| `--story` | Genre | Source |
|-----------|-------|--------|
| `monkey_crocodile` | kids_story | Panchatantra |
| `birbal_khichdi` | kids_story | Akbar-Birbal |
| `tenali_thieves` | kids_story | Tenali Raman |
| `talkative_tortoise` | kids_story | Jataka |
| `chham_chham_baarish` | kids_rhyme | original rhyme (monsoon) |
| `diwali_mela` | kids_rhyme | original rhyme (Diwali) |
| `gali_cricket` | comedy | original |
| `dadi_smartphone` | comedy | original |
| `haveli_paayal` | horror | original |
| `aakhri_bus` | horror | original |

Each story is written in Hindi, Hinglish and English.

Long stories (`--format long`, 5–7 minutes, Hindi):

| `--story` | Genre | Source | Scenes / background pictures |
|-----------|-------|--------|------------------------------|
| `sher_khargosh` | kids_story | Panchatantra (the lion and the clever rabbit) | 16 / 7 |
| `birbal_lakdi` | kids_story | Akbar-Birbal (the thief's magic stick) | 15 / 7 |

The folk tales are public domain and everything else is original. There are no
copyrighted characters or songs. To add your own story, copy an entry in
`harmis/samples.py` (short) or `harmis/samples_long.py` (long).

## Unlimited local pictures (`local_sd`)

`local_sd` makes pictures on your own computer with **Stable Diffusion Turbo**
(`stabilityai/sd-turbo`), using only the CPU, so there is no GPU, key or limit.
The model makes a 512 px picture (512x768 for tall or wide ones) in 1–4 steps,
and HARMIS enlarges it with Pillow (LANCZOS) to the size it needs.

It is optional, because it is a bigger install: about 1 GB of packages, plus the
2.5 GB model, which is downloaded **once** on the first picture and then cached
(normal Hugging Face cache, or `cache_dir` in `config.yaml`).

**Install** (after the normal `pip install -r requirements.txt`):

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu   # small CPU-only torch
pip install -r requirements-local-sd.txt
python -c "import torch; print(torch.__version__)"   # should end in +cpu
```

The first line matters on Linux (and Codespaces): without it pip installs the
CUDA build of torch, which pulls in several GB of GPU libraries you do not need.

**Python 3.14 (Codespaces):** torch publishes Python 3.14 wheels (torch 2.11 and
newer), so this should work directly. If pip says *"No matching distribution
found for torch"*, use Python 3.12 in a separate virtual environment:

```bash
sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv   # or: uv python install 3.12
python3.12 -m venv .venv312
source .venv312/bin/activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-local-sd.txt
```

**Speed:** on a CPU, expect roughly 10–60 seconds per picture, depending on the
machine (a 2-core Codespace is at the slow end). The first picture also loads the
model (and downloads it the first time). Making the pictures in advance is easiest:

```bash
python -m harmis.prepare --story birbal_khichdi --style 3d_cartoon
```

To use **only** the local model (no internet services): `--providers local_sd`.
Settings (`steps`, `size`, `threads`, `cache_dir`) are under `local_sd:` in `config.yaml`.

**Licence:** SD-Turbo comes with Stability AI's own model licence. Check it on the
model page (<https://huggingface.co/stabilityai/sd-turbo>) before you publish
videos made with it commercially (for example monetised YouTube).

## Good to know

- **edge-tts needs internet.** If it cannot connect, the tool switches to
  `espeak-ng` (offline, robotic voice) if it is installed
  (`sudo apt install espeak-ng`, `brew install espeak-ng`). If neither works,
  the video is still made, just without sound.
- **Hindi letters** need Pillow with "raqm" support. The normal `pip install Pillow`
  has it. If Hindi letters look broken, run `pip install --force-reinstall "Pillow<12"`.
- If a picture provider is slow or down, the next one is tried. If all are down,
  you still get a video in the shape style.
- If a short story comes out longer than 60 seconds, the tool tries a built-in story
  instead. Short rhymes are sung twice. If a long story is outside 5–7 minutes,
  the log says so (the video is still made).
- The font is **Noto Sans Devanagari** (SIL Open Font License, see `harmis/fonts/OFL.txt`).
