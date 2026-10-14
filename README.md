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
- The **speaking** character bounces gently, grows a little and glows. The others
  dim slightly and breathe (and blink if they have a `blink.png`).
- A round picture of the narrator appears while the narrator speaks.
- Big subtitles show the speaker's name. In short videos the title stays at the top.
- Characters or scenes without a picture are drawn in the simple shape style
  (shape characters' mouths move with the voice).

### Long videos (`--format long`)

- **1920x1080 (16:9)**, 5–7 minutes, 24 frames per second.
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
- Uploading to YouTube or Instagram is not part of this phase.
