"""Step 3: draw a simple 2D animation and put it together with the voices.

Everything is drawn with Pillow, one frame at a time, and MoviePy turns the
frames + audio into an mp4.

What you see:
  * a bright Indian-style background for the genre (marigold toran, kites,
    bunting flags) or a dark night for horror
  * up to 2 simple cartoon characters (shapes with eyes and a mouth); children
    get rosy cheeks, girls and women a bindi, Dadi a grey bun and glasses
  * the speaking character bounces and its mouth moves with the voice volume
  * big subtitles (Hindi in Devanagari, using the bundled Noto Sans Devanagari font)
  * a gentle slow zoom over the whole video
"""

import math
import os
import random

import numpy as np
from moviepy import AudioFileClip, CompositeAudioClip, VideoClip
from moviepy.audio.AudioClip import AudioArrayClip
from PIL import Image, ImageDraw, ImageFont, features

from .script import NARRATOR

# Video settings: vertical 1080x1920 at 30 frames per second.
WIDTH, HEIGHT = 1080, 1920
FPS = 30

# Timing (seconds)
INTRO = 1.0        # quiet time at the start (title only)
GAP = 0.35         # pause between lines
OUTRO = 2.0        # "The End" card
MIN_LENGTH = 30.0  # videos shorter than this get a longer outro

GROUND_Y = 1230    # where the ground starts

# Colours and style for each genre.
THEMES = {
    "kids_story": {
        "sky": ((255, 196, 60), (255, 110, 130)),   # marigold yellow to rose pink
        "ground": (70, 170, 70),
        "accent": (255, 225, 0),
        "title": (120, 20, 60),
        "characters": [(255, 120, 0), (0, 170, 150)],  # saffron, peacock teal
        "decor": "toran",
    },
    "kids_rhyme": {
        "sky": ((0, 150, 210), (90, 220, 170)),      # peacock blue to parrot green
        "ground": (60, 180, 80),
        "accent": (255, 225, 0),
        "title": (255, 255, 255),
        "characters": [(255, 90, 150), (255, 160, 0)],  # rani pink, mango
        "decor": "kites",
    },
    "comedy": {
        "sky": ((255, 225, 80), (255, 90, 150)),     # mango yellow to rani pink
        "ground": (205, 160, 110),                   # dusty gali
        "accent": (255, 255, 255),
        "title": (90, 20, 90),
        "characters": [(0, 160, 90), (130, 70, 200)],  # green, purple
        "decor": "bunting",
    },
    "horror": {
        "sky": ((40, 10, 60), (5, 5, 10)),
        "ground": (20, 20, 25),
        "accent": (255, 70, 70),
        "title": (230, 230, 230),
        "characters": [(150, 150, 175), (120, 135, 110)],  # pale, muted
        "decor": "moon",
    },
}

END_TEXT = {"hindi": "समाप्त", "hinglish": "The End", "english": "The End"}
GROWN_UPS = {"hindi": "13+ बड़ों के लिए", "hinglish": "13+ only", "english": "13+ only"}

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Bundled font: Noto Sans Devanagari Bold (SIL Open Font License, see fonts/OFL.txt).
# It has both Devanagari and English letters, so it works for every language.
FONT_FILE = os.path.join(os.path.dirname(__file__), "fonts", "NotoSansDevanagari-Bold.ttf")

if not features.check("raqm"):
    print("[animate] Warning: your Pillow has no 'raqm' support, so Hindi letters may join "
          "wrongly. Reinstall Pillow from pip: pip install --force-reinstall Pillow")


def load_font(size):
    """Load the bundled font (falls back to Pillow's built-in font if it is missing)."""
    try:
        return ImageFont.truetype(FONT_FILE, size)
    except OSError:
        return ImageFont.load_default(size)


def wrap_text(draw, text, font, max_width):
    """Split text into lines that fit inside max_width pixels."""
    lines, current = [], ""
    for word in text.split():
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Background (drawn once, then reused for every frame)
# ---------------------------------------------------------------------------
def draw_toran(draw):
    """A marigold garland (toran) with mango leaves across the top."""
    def sag(x):
        return 40 + 60 * (1 - ((x - WIDTH / 2) / (WIDTH / 2)) ** 2)

    for i, x in enumerate(range(0, WIDTH + 1, 90)):  # mango leaves hanging below
        y = sag(x) + 15
        draw.polygon([(x - 16, y), (x + 16, y), (x, y + 60)], fill=(30, 130, 40))
    for i, x in enumerate(range(0, WIDTH + 1, 40)):  # marigold flowers
        y = sag(x)
        colour = (255, 130, 0) if i % 2 else (255, 200, 0)
        draw.ellipse([x - 22, y - 22, x + 22, y + 22], fill=colour, outline=(200, 80, 0), width=3)


def draw_kites(draw, rng):
    """Colourful patang kites with strings."""
    colours = [(255, 60, 60), (255, 200, 0), (60, 200, 90), (255, 90, 200), (140, 80, 255)]
    for i, (x, y) in enumerate([(170, 420), (430, 640), (880, 500), (700, 860), (250, 900)]):
        s = rng.randint(55, 80)
        colour = colours[i % len(colours)]
        draw.line([(x, y + s), (x - 140 + i * 60, GROUND_Y)], fill=(255, 255, 255), width=2)
        draw.polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], fill=colour)
        draw.line([(x, y - s), (x, y + s)], fill=(80, 40, 20), width=3)
        draw.line([(x - s, y), (x + s, y)], fill=(80, 40, 20), width=3)
        draw.polygon([(x, y + s), (x - 18, y + s + 30), (x + 18, y + s + 30)], fill=colour)


def draw_bunting(draw):
    """Two strings of triangle festival flags."""
    colours = [(255, 140, 0), (0, 160, 90), (255, 60, 140), (40, 120, 255), (255, 215, 0)]
    for row, base in enumerate((30, 330)):
        def sag(x):
            return base + 50 * (1 - ((x - WIDTH / 2) / (WIDTH / 2)) ** 2)
        draw.line([(x, sag(x)) for x in range(0, WIDTH + 1, 20)], fill=(90, 50, 30), width=4)
        for i, x in enumerate(range(20 + row * 30, WIDTH, 70)):
            y = sag(x)
            draw.polygon([(x - 25, y), (x + 25, y), (x, y + 60)], fill=colours[(i + row) % len(colours)])


def draw_background(theme, title):
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)

    # Vertical gradient sky.
    (r1, g1, b1), (r2, g2, b2) = theme["sky"]
    for y in range(HEIGHT):
        k = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)],
                  fill=(int(r1 + (r2 - r1) * k), int(g1 + (g2 - g1) * k), int(b1 + (b2 - b1) * k)))

    rng = random.Random(42)  # fixed seed = same decoration every time
    decor = theme["decor"]
    if decor == "toran":
        draw.ellipse([800, 340, 980, 520], fill=(255, 240, 120))  # soft sun
        draw_toran(draw)
    elif decor == "kites":
        for x, y in [(110, 420), (840, 380)]:  # puffy clouds
            for dx, dy, r in [(0, 0, 50), (50, -20, 60), (110, 0, 50)]:
                draw.ellipse([x + dx - r, y + dy - r, x + dx + r, y + dy + r], fill=(255, 255, 255))
        draw_kites(draw, rng)
    elif decor == "bunting":
        draw_bunting(draw)
    elif decor == "moon":
        for _ in range(90):  # stars
            x, y, r = rng.randint(0, WIDTH), rng.randint(0, 1100), rng.randint(1, 4)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 220, 255))
        # Crescent moon: a full circle with a second, shifted circle cut out of it.
        mask = Image.new("L", (WIDTH, HEIGHT), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([720, 330, 960, 570], fill=255)
        mask_draw.ellipse([770, 310, 1010, 550], fill=0)
        image.paste((240, 240, 210), (0, 0), mask)

    # Ground under the characters.
    draw.rectangle([0, GROUND_Y, WIDTH, HEIGHT], fill=theme["ground"])

    # Story title near the top (below the garland / flags).
    font = load_font(80)
    y = 175
    for line in wrap_text(draw, title, font, WIDTH - 120):
        w = draw.textlength(line, font=font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=theme["title"],
                  stroke_width=5, stroke_fill=theme["sky"][0] if decor != "kites" else (0, 90, 140))
        y += 105
    return image


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------
def draw_character(draw, cx, cy, size, colour, shape, mouth_open, blink, info, font):
    """Draw one cartoon character centred at (cx, cy).

    mouth_open goes from 0 (closed) to 1 (wide open).
    info is the character dict from the script (label, gender, age).
    """
    half = size // 2
    outline = (30, 30, 30)
    old = info["age"] == "old"

    # Shadow on the ground.
    draw.ellipse([cx - half, GROUND_Y + 20, cx + half, GROUND_Y + 60], fill=(0, 0, 0, 70))

    # Dadi / Nani get a grey hair bun on top.
    if old and info["gender"] == "f":
        draw.ellipse([cx - 70, cy - half - 100, cx + 70, cy - half + 30], fill=(200, 200, 200), outline=outline, width=5)

    # Body
    box = [cx - half, cy - half, cx + half, cy + half]
    if shape == "round":
        draw.ellipse(box, fill=colour, outline=outline, width=6)
    else:
        draw.rounded_rectangle(box, radius=size // 5, fill=colour, outline=outline, width=6)

    # Eyes (white with black pupils, or a line when blinking)
    eye_y = cy - size // 8
    for side in (-1, 1):
        ex = cx + side * size // 5
        if blink:
            draw.line([ex - 30, eye_y, ex + 30, eye_y], fill=outline, width=8)
        else:
            draw.ellipse([ex - 32, eye_y - 38, ex + 32, eye_y + 38], fill="white", outline=outline, width=4)
            draw.ellipse([ex - 14, eye_y - 10, ex + 14, eye_y + 18], fill=outline)
        if old:  # round glasses
            draw.ellipse([ex - 48, eye_y - 48, ex + 48, eye_y + 48], outline=(40, 40, 40), width=6)
        if info["age"] == "child":  # rosy cheeks
            draw.ellipse([ex + side * 20 - 22, eye_y + 60, ex + side * 20 + 22, eye_y + 90], fill=(255, 120, 140, 160))
    if old:
        draw.line([cx - 16, eye_y, cx + 16, eye_y], fill=(40, 40, 40), width=6)  # glasses bridge

    # Bindi for girls and women.
    if info["gender"] == "f":
        draw.ellipse([cx - 10, eye_y - 75, cx + 10, eye_y - 55], fill=(220, 0, 40))

    # Mouth
    mouth_y = cy + size // 6
    mouth_w = size // 6
    if old and info["gender"] == "m":  # white moustache for uncles and dadaji
        draw.ellipse([cx - 60, mouth_y - 42, cx, mouth_y - 18], fill=(240, 240, 240), outline=outline, width=3)
        draw.ellipse([cx, mouth_y - 42, cx + 60, mouth_y - 18], fill=(240, 240, 240), outline=outline, width=3)
    if mouth_open > 0.1:
        h = 10 + int(55 * mouth_open)
        draw.ellipse([cx - mouth_w, mouth_y - h // 2, cx + mouth_w, mouth_y + h // 2],
                     fill=(120, 20, 30), outline=outline, width=4)
    else:
        draw.arc([cx - mouth_w, mouth_y - 30, cx + mouth_w, mouth_y + 20], 20, 160, fill=outline, width=7)

    # Name tag under the character
    w = draw.textlength(info["label"], font=font)
    draw.text((cx - w / 2, GROUND_Y + 60), info["label"], font=font, fill="white",
              stroke_width=4, stroke_fill="black")


# ---------------------------------------------------------------------------
# Subtitles and badges (rendered once as transparent images)
# ---------------------------------------------------------------------------
def render_subtitle(speaker, text, accent):
    image = Image.new("RGBA", (WIDTH, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    name_font = load_font(48)
    # Use the biggest text size that fits in 4 lines.
    for size in (70, 62, 54, 48):
        text_font = load_font(size)
        lines = wrap_text(draw, text, text_font, WIDTH - 200)
        if len(lines) <= 4:
            break
    line_h = int(size * 1.45)  # Devanagari needs extra room above and below
    box_h = 110 + line_h * len(lines)
    top = 600 - box_h - 20
    draw.rounded_rectangle([50, top, WIDTH - 50, 580], radius=40, fill=(0, 0, 0, 170))
    if speaker:
        draw.text((100, top + 18), speaker, font=name_font, fill=accent)
    y = top + 90
    for line in lines:
        w = draw.textlength(line, font=text_font)
        draw.text(((WIDTH - w) / 2, y), line, font=text_font, fill="white",
                  stroke_width=4, stroke_fill="black")
        y += line_h
    return image


def render_badge(text):
    """A small red '13+' style badge for the top corner."""
    font = load_font(40)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(probe.textlength(text, font=font)) + 50
    image = Image.new("RGBA", (w, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, w - 1, 79], radius=20, fill=(200, 0, 0, 220))
    draw.text((25, 8), text, font=font, fill="white")
    return image


# ---------------------------------------------------------------------------
# Sound
# ---------------------------------------------------------------------------
def loudness_per_frame(audio_path):
    """Return one number per video frame (0..1) saying how loud the voice is."""
    with AudioFileClip(audio_path) as clip:
        samples = clip.to_soundarray(fps=16000)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    step = 16000 // FPS
    frames = max(1, len(samples) // step)
    rms = np.array([np.sqrt(np.mean(samples[i * step:(i + 1) * step] ** 2)) for i in range(frames)])
    if rms.max() < 1e-4:
        return None  # silent clip: caller will fake the mouth movement
    return np.clip(rms / (rms.max() * 0.6), 0, 1)


def rhyme_beat(duration, bpm=100, rate=44100, volume=0.12):
    """A soft dholak-like beat for rhymes: low 'dha' on the beat, high 'na' in between."""
    sound = np.zeros(int(duration * rate))
    hit_len = int(0.25 * rate)
    t = np.arange(hit_len) / rate
    dha = np.sin(2 * np.pi * 110 * t) * np.exp(-t * 18)
    na = 0.6 * np.sin(2 * np.pi * 330 * t) * np.exp(-t * 30)
    half_beat = 30 / bpm  # seconds
    for k in range(int(duration / half_beat)):
        start = int(k * half_beat * rate)
        hit = dha if k % 2 == 0 else na
        end = min(start + hit_len, len(sound))
        sound[start:end] += hit[:end - start]
    sound *= volume
    return AudioArrayClip(np.column_stack([sound, sound]), fps=rate)


# ---------------------------------------------------------------------------
# Put it all together
# ---------------------------------------------------------------------------
def build_timeline(voiced_lines):
    """Work out when each line starts and ends. Returns (segments, total_length)."""
    segments, t = [], INTRO
    for line in voiced_lines:
        segments.append({**line, "start": t, "end": t + line["duration"]})
        t += line["duration"] + GAP
    total = max(t + OUTRO, MIN_LENGTH)
    return segments, total


def make_video(script, voiced_lines, out_path, work_dir=None):
    """Draw every frame, add the audio and save the mp4 to out_path.

    work_dir is where MoviePy may put its temporary audio file.
    """
    genre, lang = script["genre"], script["lang"]
    theme = THEMES[genre]
    segments, total = build_timeline(voiced_lines)
    end_start = segments[-1]["end"] + GAP if segments else INTRO

    background = draw_background(theme, script["title"])
    name_font = load_font(48)
    characters = script["characters"]
    labels = {c["name"]: c["label"] for c in characters}
    labels[NARRATOR] = script["narrator_label"]

    # Pre-render things that do not change from frame to frame.
    for seg in segments:
        seg["subtitle"] = render_subtitle(labels[seg["speaker"]], seg["text"], theme["accent"])
        seg["loudness"] = loudness_per_frame(seg["audio"])
    end_card = render_subtitle("", END_TEXT[lang] + ("...?" if genre == "horror" else "!"), theme["accent"])
    badge = render_badge(GROWN_UPS[lang]) if genre == "horror" else None

    # Where each character stands.
    if len(characters) == 1:
        positions = [WIDTH // 2]
    else:
        positions = [WIDTH // 4 + 10, 3 * WIDTH // 4 - 10]

    def current_segment(t):
        for seg in segments:
            if seg["start"] <= t < seg["end"]:
                return seg
        return None

    def make_frame(t):
        frame = background.copy()
        draw = ImageDraw.Draw(frame, "RGBA")
        seg = current_segment(t)

        for i, info in enumerate(characters):
            speaking = seg is not None and seg["speaker"] == info["name"]
            mouth = 0.0
            bounce = 0
            if speaking:
                local = t - seg["start"]
                if seg["loudness"] is not None:
                    index = min(int(local * FPS), len(seg["loudness"]) - 1)
                    mouth = float(seg["loudness"][index])
                else:  # no audio volume available: simple open/close
                    mouth = 0.5 + 0.5 * math.sin(local * 18)
                bounce = int(18 * abs(math.sin(local * 6)))
            # Idle characters gently float; each blinks now and then.
            idle = int(8 * math.sin(t * 2 + i * 1.7))
            blink = (t + i * 1.3) % 3.2 < 0.12
            shape = "round" if i == 0 else "box"
            draw_character(draw, positions[i], 980 + idle - bounce, 360, theme["characters"][i],
                           shape, mouth, blink, info, name_font)

        # Gentle zoom: crop a slightly smaller area from the centre and scale it up.
        zoom = 1.0 + 0.08 * (t / total)
        cw, ch = int(WIDTH / zoom), int(HEIGHT / zoom)
        left, top = (WIDTH - cw) // 2, (HEIGHT - ch) // 2
        frame = frame.crop((left, top, left + cw, top + ch)).resize((WIDTH, HEIGHT), Image.BILINEAR)

        # Subtitles and badge go on top after the zoom so they stay sharp and in place.
        if seg is not None:
            frame.paste(seg["subtitle"], (0, HEIGHT - 620), seg["subtitle"])
        elif t >= end_start:
            frame.paste(end_card, (0, HEIGHT - 620), end_card)
        if badge is not None:
            frame.paste(badge, (WIDTH - badge.width - 30, 40), badge)
        return np.array(frame)

    # Audio: each line placed at its start time (+ a soft beat under rhymes).
    audio_clips = [AudioFileClip(seg["audio"]).with_start(seg["start"]) for seg in segments]
    music = [rhyme_beat(total)] if genre == "kids_rhyme" else []
    audio = CompositeAudioClip(music + audio_clips).with_duration(total)

    video = VideoClip(make_frame, duration=total).with_audio(audio)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    video.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac",
                          preset="medium", threads=os.cpu_count(), logger="bar",
                          temp_audiofile_path=work_dir or "")

    for clip in audio_clips:
        clip.close()
    return out_path, total
