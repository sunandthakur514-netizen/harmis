# HARMIS

Automated 2D video maker for YouTube and Instagram, made for **Indian kids and families**.

Give it a genre and a language and it makes **one short vertical video**
(1080x1920, 30–60 seconds) with a story, Indian voices, cartoon characters and
big subtitles. It uses only free, open-source tools.

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

Each character gets a voice to match their gender and age: children sound
higher, and Dadi and uncles slower.

## How it works

| Step | File | What it does |
|------|------|--------------|
| 1 | `harmis/script.py` | Gets a short story (a narrator + up to 2 characters). Uses Google Gemini if you have a free API key, otherwise picks a built-in story from `harmis/samples.py`. |
| 2 | `harmis/voice.py` | Turns every line into speech with **edge-tts** Indian voices. |
| 3 | `harmis/animate.py` | Draws the cartoon with **Pillow** and builds the video with **MoviePy**: bright Indian colours (marigold toran, kites, festival flags), characters whose mouths move while talking, big subtitles, slow zoom. |
| 4 | `harmis/main.py` | The command you run. |

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
python -m harmis.main --genre kids_story                 # Hindi (default)
python -m harmis.main --genre kids_rhyme --lang hindi
python -m harmis.main --genre comedy --lang hinglish
python -m harmis.main --genre horror --lang english
```

The video is saved as `output/<date>_<genre>_<lang>.mp4`, for example
`output/2026-10-13_kids_story_hindi.mp4`. If that file already exists, a number
is added (`_2`, `_3`, …) so old videos are kept.

Options:

- `--genre kids_story|kids_rhyme|comedy|horror`: the type of story (required)
- `--lang hindi|hinglish|english`: the language (default: `hindi`)
- `--offline`: do not call Gemini, always use a built-in story
- `--out FOLDER`: save the video somewhere other than `output/`

Making one video takes about a minute on a normal laptop.

## Built-in stories

There are 10 built-in stories, each written in Hindi, Hinglish and English:

- **kids_story:** The Monkey and the Crocodile (Panchatantra), Birbal's Khichdi
  (Akbar-Birbal), Tenali and the Thieves (Tenali Raman), The Talkative Tortoise (Jataka)
- **kids_rhyme:** Chham Chham Baarish (monsoon), Diwali ka Mela. Both are original rhymes.
- **comedy:** Gali Cricket, Dadi ka Smartphone
- **horror:** Haveli ki Paayal, Aakhri Bus

The folk tales are public domain. Everything else is original. There are no
copyrighted characters or songs. To add your own story, copy one of the entries
in `harmis/samples.py`.

## Good to know

- **edge-tts needs internet.** If it cannot connect, the tool switches to
  `espeak-ng` (offline, robotic voice) if it is installed
  (`sudo apt install espeak-ng`, `brew install espeak-ng`). If neither works,
  the video is still made, just without sound.
- **Hindi letters** need Pillow with "raqm" support. The normal `pip install Pillow`
  has it. If Hindi letters look broken, run `pip install --force-reinstall Pillow`.
- If a story comes out longer than 60 seconds, the tool tries a built-in story
  instead. Short rhymes are sung twice.
- The font is **Noto Sans Devanagari** (SIL Open Font License, see `harmis/fonts/OFL.txt`).
- Uploading to YouTube or Instagram is not part of Phase 1.
