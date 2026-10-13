# HARMIS

Automated 2D video maker for YouTube and Instagram.

**Phase 1:** give it a genre and it makes **one short vertical video**
(1080x1920, 30–60 seconds) with a story, voices, cartoon characters and subtitles.
It uses only free, open-source tools.

## How it works

| Step | File | What it does |
|------|------|--------------|
| 1 | `harmis/script.py` | Gets a short story (a narrator + up to 2 characters). Uses Google Gemini if you have a free API key, otherwise picks a built-in story. |
| 2 | `harmis/voice.py` | Turns every line into speech with **edge-tts** (a different voice for each character). |
| 3 | `harmis/animate.py` | Draws the cartoon with **Pillow** and builds the video with **MoviePy**: coloured background, characters whose mouths move while talking, big subtitles, slow zoom. |
| 4 | `harmis/main.py` | The command you run. |

Genres: `comedy`, `horror`, `kids`.

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

4. *(Optional)* For brand new AI stories, get a free Gemini API key from
   <https://aistudio.google.com/apikey> and set it:

   ```bash
   export GEMINI_API_KEY="your-key"      # Windows: set GEMINI_API_KEY=your-key
   ```

   Without a key the tool still works. It uses its built-in stories.

## Run it

```bash
python -m harmis.main --genre horror
```

The video is saved as `output/<date>_<genre>.mp4`, for example
`output/2026-10-13_horror.mp4`. If that file already exists, a number is added
(`_2`, `_3`, …) so old videos are kept.

Options:

- `--genre comedy|horror|kids`: the type of story (required)
- `--offline`: do not call Gemini, always use a built-in story
- `--out FOLDER`: save the video somewhere other than `output/`

Making one video takes about a minute on a normal laptop.

## Good to know

- **edge-tts needs internet.** If it cannot connect, the tool switches to
  `espeak-ng` (offline, robotic voice) if it is installed
  (`sudo apt install espeak-ng`, `brew install espeak-ng`). If neither works,
  the video is still made, just without sound.
- If a Gemini story comes out longer than 60 seconds, the tool uses a built-in
  story instead.
- Uploading to YouTube or Instagram is not part of Phase 1.
