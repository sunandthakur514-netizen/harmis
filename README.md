# HARMIS

Privacy Policy: [PRIVACY.md](PRIVACY.md) · Terms of Service: [TERMS.md](TERMS.md) · This app uses [YouTube API Services](https://www.youtube.com/t/terms) · [Google Privacy Policy](https://policies.google.com/privacy)

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
| 1 | `harmis/script.py` | Gets a story (a narrator + characters, each line has a scene). Uses Google Gemini if you have a free API key, otherwise a built-in story from `harmis/samples.py` / `harmis/samples_more.py` (short) or `harmis/samples_long.py` /
`harmis/samples_long_more.py` (long). The folk tales are softened for young
children: nobody is hurt, the villain runs away or says sorry. |
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
2. **local_sd**: SDXL Turbo on **your own CPU**. Free and unlimited,
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

### Video quality: voices, scene pictures, sound

**Voices** (`harmis/voice.py`, `voice:` in `config.yaml`):
1. **Gemini TTS** (`GEMINI_API_KEY`, free tier, model `gemini-2.5-flash-preview-tts` by
   default; put newer model names first in `voice: gemini: models`). Expressive Hindi,
   and a **different prebuilt voice** for the narrator and for every character, chosen by
   gender and age (or set `gemini_voice: Puck` in a `character.yaml`). Clips are cached
   in `cache/tts/`, so a retry never spends the free quota twice.
2. **edge-tts**, 3 tries per line with growing pauses.
3. espeak-ng / silence, **only on your own computer**. Inside GitHub Actions they are
   never used: if Gemini and edge-tts both fail, the run fails, so a robotic video is
   never published.

One story always uses one engine: if Gemini runs out of quota halfway, the whole story is
voiced again with edge-tts.

**Scene pictures** (`harmis/shots.py`): instead of pasting the same character cut-out on
every background, each part of the story gets **one full picture showing the characters
doing what happens there** (the tortoise holding the stick, flying with the swans, ...).
- A new picture starts when the scene changes, at each line with an `"actions"` entry in
  the story, and at least every 3 lines (short) / 4 lines (long).
- What each picture shows comes from the story's own `"actions"` (see
  `talkative_tortoise` in `harmis/samples.py`), else from **one Gemini request per story**
  that describes every shot, else from the English line, else "the characters together here".
- The characters keep the same fixed description, the same style words and the same seed
  in every picture. **Gemini image** also gets each character's own picture as a
  reference. If the key has no free image quota, Gemini is skipped for the run and
  **local_sd** makes the pictures (the log shows Google's exact answer, e.g.
  `quotaId=GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue=0`, which means
  the free tier has no image generation for that model; enabling billing on the Google
  Cloud project, or a newer free image model in `image_providers: gemini: model`, fixes it).
- Shots are cached in `cache/shots/<story>/` and not committed (each story is published
  once). If a shot cannot be made, a simple picture is put together from the background
  and the character pictures.

**Animation**: no mouth flaps and no pasted cut-outs any more. Each picture gets a slow,
smooth **Ken Burns** move (zoom and pan, a different direction for each picture) and a
soft **crossfade** into the next, with the title, subtitles and (long videos) the intro
and ending cards on top.

**Sound** (`harmis/sound.py`, `audio:` in `config.yaml`): soft **background music** at a
low volume that gets a little quieter while someone speaks (`lullaby` for stories,
`playful` for rhymes and comedy, none for horror), plus small **sound effects** when a
line mentions them: whoosh (उड़, flying), splash (छपाक), laugh (हा हा, हँसी), thud
(धम, गिरा), twinkle (जादू, सोने का), boing (उछल, कूद), pop. The words are listed in
`config.yaml`. The music and effects in `harmis/assets/music` and `harmis/assets/sfx`
were made from scratch by `tools/make_sounds.py` and are **CC0** (public domain).

**Try it:** **Actions → test-quality → Run workflow** makes one short (`talkative_tortoise`
by default) and attaches the mp4 and the scene pictures to the run. Nothing is uploaded.
Add the `GEMINI_API_KEY` repository secret first (free key at
<https://aistudio.google.com/apikey>); without it, voices use edge-tts and pictures local_sd.

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
   with `local_sd` (SDXL Turbo on the runner's CPU). The model and the
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
  stories and rhymes, privacy from `config.yaml` (default **public**) or `--privacy`.
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
| `GEMINI_API_KEY` | expressive voices, scene descriptions, pictures, captions (recommended) | <https://aistudio.google.com/apikey> |

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
  YouTube API audit form so later uploads keep the privacy you choose. For the
  audit, use [PRIVACY.md](PRIVACY.md) and [TERMS.md](TERMS.md) (their GitHub
  links) as the privacy policy and terms of service. `config.yaml` already asks
  for `privacy: public`, so after approval new uploads go public by themselves.
- **Quota:** the free quota is about 6 uploads a day.
- **Thumbnails:** custom thumbnails need a phone-verified channel (YouTube Studio >
  Settings > Channel > Feature eligibility).
- **Expired sign-in:** while the app is in "Testing", Google may ask you to sign in
  again after 7 days. Run `--auth` again and update `YT_TOKEN_JSON`.

### Daily automation – required secrets

`.github/workflows/daily.yml` makes and uploads a video **3 times a day**, with no
computer needed:

| Time (IST) | Cron (UTC) | Video |
|---|---|---|
| 06:30 | `0 1 * * *` | short (Hindi, 3d_cartoon) |
| 12:30 | `0 7 * * *` | long, 5–7 minutes (Hindi, 3d_cartoon) |
| 18:30 | `0 13 * * *` | short (Hindi, 3d_cartoon) |

Each run first looks at the **upload queue** (a GitHub Release named `queue`, filled
by `bulk.yml`, see below). If it has videos, it uploads up to 2 of them (oldest
first, shorts and longs mixed), deletes them from the queue and makes nothing new.
Only when the queue is empty does it make a new video: it picks the next story
that was **never published**, makes any missing pictures with `local_sd`, renders
it and uploads it. The mp4 is kept as a run artifact for 3 days so you can check it.
Start a test run any time from **Actions → daily → Run workflow** (untick "Upload
to YouTube" to only make the video).

- **Never twice:** every upload is logged in `output/published.csv` (time, video,
  YouTube id and url, story id, title), which the workflow commits back to the
  repo. Published stories and stories already in the queue are always skipped.
  When every built-in story is used, the run says so and makes nothing: add
  more stories to `harmis/samples*.py`.
- **Quota:** the free YouTube quota is 10,000 units a day and one upload costs
  1,600 (+50 for a thumbnail), so HARMIS uploads at most **5 videos per quota day**
  (midnight to midnight Pacific time), counted from `published.csv`. Change it with
  `daily: max_uploads_per_day` in `config.yaml`.
- **Kids only:** stories come from the genres in `daily: genres` (kids stories,
  rhymes and family comedy). The horror stories stay in the code but are never
  used for this made-for-kids channel.

### A new story every run: weekday themes (Gemini)

With the `GEMINI_API_KEY` secret, every daily (and bulk) video is a **brand-new original
Hindi story** written by Gemini for the day's theme (India time, `weekdays:` and
`themes:` in `config.yaml`, code in `harmis/storygen.py`):

| Day | Theme | Hashtags (examples) |
|---|---|---|
| Mon | Panchatantra / Jataka style moral fable | #MoralStory #PanchatantraStyle |
| Tue | Kids comedy with the recurring friends **Chintu & Golu** | #FunnyKidsStory #ChintuGolu |
| Wed | Mythology for kids (all shorts; 2 shorts every other day too, see below) | #KrishnaStory #HanumanStory #GaneshStory |
| Thu | Pari / magic fairy tale | #PariKiKahani #FairyTale |
| Fri | Little detective mystery (never scary) | #DetectiveStory #JasoosKahani |
| Sat | Science / space adventure (one real fact) | #ScienceForKids #SpaceStory |
| Sun | Rhyme / poem (shorts) and an Akbar-Birbal / Tenali riddle story (long) | #HindiRhymes #AkbarBirbal #Paheli |

- Gemini writes the story in the samples format: title, characters with **fixed visual
  descriptions**, scenes with a place, an **action** (what the picture shows) and dialogue,
  and a moral. Shorts are 45-55 s, long videos 5-7 minutes.
- Every story is checked: kid-safe words (and a second Gemini safety review), length,
  the theme's characters, valid speakers, and **not a repeat** of any title in
  `output/published.csv`. Up to 3 tries, each told what was wrong; if Gemini still fails
  (or there is no key) an unpublished built-in story that fits the theme is used.
- Recurring and sacred characters have fixed looks in `harmis/assets/characters/`
  (`chintu`, `golu`, `bal_krishna`, `bal_hanuman`, `bal_ganesha`, `pari`); other new
  characters live only for that video (`cache/characters/`).
- Titles, descriptions and hashtags follow the theme (`publish: hashtags: by_theme`).
  Mythology tags only name the deity who is in the story.
- **No horror** on this channel: no theme uses it, and the built-in horror stories are
  never picked automatically.

**Mythology for kids** (`mythology:` in `config.yaml`, `harmis/mythology.py`): every day
**2 of the 5 shorts** are mythology (the 2nd and 4th short of the day); on **Wednesday all
of them** are. The topics take turns so none comes twice in a row, and each topic's
episodes take turns too:

| Topic | Episodes (examples) | Ending line |
|---|---|---|
| Krishna leela | makhan chor, Kaliya naag, Govardhan | जय श्री कृष्ण! |
| Ganesha | modak, Mooshak the mouse, race around the world | गणपति बप्पा मोरया! |
| Hanuman | the sun as a mango, Sanjeevani | जय बजरंगबली! जय हनुमान! |
| Ramayana | Shabari's berries, the squirrel and Ram Setu, Bharat's paduka | जय श्री राम! |
| Mahabharata | Arjun and the bird's eye, Bhima's lesson, Ekalavya | जय श्री कृष्ण! |
| Shiva-Parvati & Kartikeya | Neelkanth, Kartikeya's peacock | हर हर महादेव! |
| Prahlad, Dhruv, Shravan Kumar, Nachiketa, Sudama-Krishna | one or two episodes each | matching line |

Gemini is told to retell the traditional story **faithfully and respectfully** for children
aged 4-10: simple Hindi, a clear moral, no jokes about deities, no changes to the core
events, no violence detail. Deities and heroes have fixed, respectful 3D-cartoon looks in
`harmis/assets/characters/` (Krishna: blue skin, peacock feather, flute; Ganesha: elephant
head, modak; Hanuman: monkey face, gada, orange; Shiva, Parvati, Ram, Sita, Lakshman,
Arjun, Prahlad, Dhruv and the others). After the moral the narrator says the deity's line
(जय श्री कृष्ण! ...). Titles look like **"बाल कृष्ण और माखन चोरी | Krishna Story for Kids"**,
with the topic's hashtags plus #MythologyForKids #HinduMythology #BhaktiKahani.
Try one: `python -m harmis.storygen --theme mythology --topic hanuman --format short`.

Try one by hand: `python -m harmis.storygen --theme mythology --format short --out cache/story.json`
then `python -m harmis.main --story-file cache/story.json`.

### Bulk videos and the upload queue (`bulk.yml`)

**Actions → bulk → Run workflow** makes many videos at once (default **15 shorts
and 7 longs**). It picks stories that were never published and are not queued,
makes one video per job, **5 jobs at a time**, and adds each `.mp4` with its
`.json` captions to the `queue` release (Releases page of the repo). New pictures
are committed at the end so later videos reuse them. Nothing is uploaded by
`bulk.yml`; `daily.yml` uploads the queued videos over the next days, within the
daily limit. See what is waiting with `python -m harmis.upload_queue list`
(needs `GITHUB_TOKEN`), or on the Releases page.

Add these under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `YT_CLIENT_SECRET_JSON` | the whole contents of your `client_secret.json` |
| `YT_TOKEN_JSON` | the token printed by `python -m harmis.publish_youtube --auth` |

The workflow writes them to `client_secret.json` and `~/.config/harmis/youtube_token.json`
only while it runs (never printed, deleted at the end). An expired access token
is refreshed automatically. **Important:** while your Google Cloud OAuth app is
in "Testing", Google ends the sign-in after 7 days and the uploads stop. Set it to
**In production** (Google Cloud → APIs & Services → OAuth consent screen →
Publish app), then run `--auth` once more and update `YT_TOKEN_JSON`.

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

Each of these is written in Hindi, Hinglish and English. These newer ones are in
**Hindi only** (`harmis/samples_more.py`; other `--lang` values fall back to Hindi):

| `--story` | Genre | Source |
|-----------|-------|--------|
| `pyasa_kauwa` | kids_story | folk tale (the thirsty crow) |
| `kabutar_jaal` | kids_story | Panchatantra (the doves and the net) |
| `bagula_kekda` | kids_story | Panchatantra (the crane and the crab) |
| `chuhe_hathi` | kids_story | Panchatantra (the mice who freed the elephants) |
| `bandar_mali` | kids_story | Jataka (the monkey gardeners) |
| `teetar_bado_ka_aadar` | kids_story | Jataka (the partridge, monkey and elephant) |
| `birbal_kaue_ginti` | kids_story | Akbar-Birbal (how many crows?) |
| `birbal_lakeer` | kids_story | Akbar-Birbal (the shorter line) |
| `birbal_kuan` | kids_story | Akbar-Birbal (the sold well) |
| `tenali_billi` | kids_story | Tenali Raman (the cat and the milk) |
| `tenali_kuan_shaadi` | kids_story | Tenali Raman (the wedding of the wells) |
| `tenali_hara_ghoda` | kids_story | Tenali Raman (the green horse) |
| `sooraj_dada`, `titli_rani`, `daant_chamkao`, `phalon_ki_tokri`, `ginti_ke_tare`, `indradhanush` | kids_rhyme | original rhymes |

Long stories (`--format long`, 5–7 minutes, Hindi):

| `--story` | Genre | Source |
|-----------|-------|--------|
| `sher_khargosh` | kids_story | Panchatantra (the lion and the clever rabbit) |
| `birbal_lakdi` | kids_story | Akbar-Birbal (the thief's magic stick) |
| `kauwa_saanp` | kids_story | Panchatantra (the crows and the greedy snake) |
| `chidiya_hathi` | kids_story | Panchatantra (the sparrow and the proud elephant) |
| `sone_ka_hans` | kids_story | Jataka (the golden swan) |
| `sone_ka_hiran` | kids_story | Jataka (the golden Ruru deer) |
| `birbal_mom_ka_sher` | kids_story | Akbar-Birbal (the wax lion) |
| `tenali_vidwan` | kids_story | Tenali Raman (the proud scholar) |

The folk tales are public domain and everything else is original. There are no
copyrighted characters or songs. To add your own story, copy an entry in
`harmis/samples.py` / `harmis/samples_more.py` (short) or `harmis/samples_long.py` /
`harmis/samples_long_more.py` (long). The folk tales are softened for young
children: nobody is hurt, the villain runs away or says sorry.

## Unlimited local pictures (`local_sd`)

`local_sd` makes pictures on your own computer with **SDXL Turbo**
(`stabilityai/sdxl-turbo`), using only the CPU, so there is no GPU, key or limit.
The model makes a 512x896 picture (tall or wide) in 4 steps, and HARMIS enlarges
it with Pillow (LANCZOS) to the size it needs. It needs about 10 GB of memory and
takes a few minutes per picture on a GitHub runner, so the workflows allow up to
5 hours.

**One kind of character per picture:** local models merge different animals into
hybrids (a swan with a tortoise shell), so a scene with two kinds of characters is
drawn as **close-ups**, one per character, and the video shows whoever is speaking
(narration takes turns). Set `shots: local_sd_mode: wide` for one wide picture with
each character in its own place instead. The negative prompt ("hybrid, merged
animals, extra heads, deformed, two animals fused") works because `guidance: 1.5`;
set `guidance: 0` for pictures twice as fast without it. The story's key **prop**
(the stick in the tortoise story) is put first in the prompt so it is drawn.
Gemini image, when the key has image quota, draws the whole scene together instead.

It is optional, because it is a bigger install: about 1 GB of packages, plus the
~7 GB model, which is downloaded **once** on the first picture and then cached
(normal Hugging Face cache, or `cache_dir` in `config.yaml`; in GitHub Actions the
cache key is `hf-sdxl-turbo-fp16-v1`).

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

**Licence:** SDXL Turbo comes with Stability AI's own model licence. Check it on the
model page (<https://huggingface.co/stabilityai/sdxl-turbo>) before you publish
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
