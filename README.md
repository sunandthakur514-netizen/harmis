# HARMIS

Automated 2D video maker for YouTube and Instagram, made for **Indian kids and families**.

Give it a genre (or a story), a language and an art style. It makes **one short
vertical video** (1080x1920, 30–60 seconds) with a story, Indian voices,
illustrated characters on illustrated backgrounds, and big subtitles.
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
| 1 | `harmis/script.py` | Gets a short story (a narrator + up to 2 characters, each line has a scene). Uses Google Gemini if you have a free API key, otherwise a built-in story from `harmis/samples.py`. |
| 2 | `harmis/voice.py` | Turns every line into speech with **edge-tts** Indian voices. |
| 3 | `harmis/library.py` + `harmis/providers.py` | Gets a picture for every character and scene, from the cache or from a free AI image service. |
| 4 | `harmis/animate.py` | Layers the characters over the backgrounds and builds the video with **Pillow** + **MoviePy**. |
| 5 | `harmis/main.py` | The command you run. All settings live in `config.yaml`. |

### Pictures: free providers with fallback

Every picture is requested from these providers, in this order (change it in `config.yaml`):

1. **Pollinations.ai**: free, no key needed
2. **Gemini image generation**: only if `GEMINI_API_KEY` is set
3. **Hugging Face free inference**: only if `HF_TOKEN` is set (free account at huggingface.co)
4. **Simple shape style**: drawn by HARMIS itself, always works

Each provider has a timeout and retries. A provider that keeps failing is skipped
for the rest of the run. The log shows which provider made each picture, for example:

```
[images] scene palace_court: made by pollinations
[images] character birbal: pollinations failed (HTTP 503)
[images] character birbal: made by huggingface
[main] Pictures needed this run: 4 made by pollinations, 1 made by huggingface
```

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
style and cached as `harmis/assets/backgrounds/<scene>__<style>.png`.

**Use your own background:** save it as `harmis/assets/backgrounds/<scene>.png`.

To make new pictures instead of the cached ones, add `--refresh-images`.
Generated pictures are not committed to git (see `.gitignore`); your own
`custom.png` and `<scene>.png` files are.

### Animation

- The background moves slowly (Ken Burns zoom and pan) and **crossfades** when the scene changes.
- The **speaking** character bounces gently, grows a little and glows. The others
  dim slightly and breathe (and blink if they have a `blink.png`).
- A round picture of the narrator appears while the narrator speaks.
- Big subtitles show the speaker's name. The title stays at the top.
- Characters or scenes without a picture are drawn in the simple shape style
  (shape characters' mouths move with the voice).

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

4. *(Optional)* Free API keys for more picture providers and AI-written stories:

   ```bash
   export GEMINI_API_KEY="your-key"   # https://aistudio.google.com/apikey  (stories + pictures)
   export HF_TOKEN="your-token"       # https://huggingface.co/settings/tokens (pictures)
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
```

The video is saved as `output/<date>_<genre>_<lang>.mp4`. If that file already
exists, `_2`, `_3`, … is added so old videos are kept.

Options:

- `--genre kids_story|kids_rhyme|comedy|horror`: the type of story
- `--story ID`: a specific built-in story (the genre is picked automatically)
- `--lang hindi|hinglish|english`: the language (default from `config.yaml`: `hindi`)
- `--style storybook|3d_cartoon|anime`: the art style (default from `config.yaml` per genre)
- `--providers pollinations,gemini,huggingface`: which picture providers to try, in order;
  `--providers none` turns AI pictures off
- `--refresh-images`: make new pictures even if cached ones exist
- `--offline`: do not call Gemini for the story
- `--out FOLDER`: save the video somewhere other than `output/`

The first video with new characters takes longer (pictures are generated).
After that, about a minute per video.

## Settings: `config.yaml`

Change these without touching the code:

- `defaults`: language, style, output folder
- `video`: frames per second, minimum and maximum length, crossfade time
- `image_providers`: provider order, timeouts, retries, models
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

Each story is written in Hindi, Hinglish and English. The folk tales are public
domain and everything else is original. There are no copyrighted characters or songs.
To add your own story, copy an entry in `harmis/samples.py`.

## Good to know

- **edge-tts needs internet.** If it cannot connect, the tool switches to
  `espeak-ng` (offline, robotic voice) if it is installed
  (`sudo apt install espeak-ng`, `brew install espeak-ng`). If neither works,
  the video is still made, just without sound.
- **Hindi letters** need Pillow with "raqm" support. The normal `pip install Pillow`
  has it. If Hindi letters look broken, run `pip install --force-reinstall "Pillow<12"`.
- If a picture provider is slow or down, the next one is tried. If all are down,
  you still get a video in the shape style.
- If a story comes out longer than 60 seconds, the tool tries a built-in story
  instead. Short rhymes are sung twice.
- The font is **Noto Sans Devanagari** (SIL Open Font License, see `harmis/fonts/OFL.txt`).
- Uploading to YouTube or Instagram is not part of this phase.
