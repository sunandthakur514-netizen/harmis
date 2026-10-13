"""Step 3: draw a simple 2D animation and put it together with the voices.

Everything is drawn with Pillow, one frame at a time, and MoviePy turns the
frames + audio into an mp4.

What you see:
  * a background whose colours depend on the genre
  * up to 2 simple cartoon characters (shapes with eyes and a mouth)
  * the speaking character bounces and its mouth moves with the voice volume
  * big subtitles at the bottom
  * a gentle slow zoom over the whole video
"""

import math
import os
import random

import numpy as np
from moviepy import AudioFileClip, CompositeAudioClip, VideoClip
from PIL import Image, ImageDraw, ImageFont

from .script import NARRATOR

# Video settings: vertical 1080x1920 at 30 frames per second.
WIDTH, HEIGHT = 1080, 1920
FPS = 30

# Timing (seconds)
INTRO = 1.0        # quiet time at the start (title only)
GAP = 0.35         # pause between lines
OUTRO = 2.0        # "The End" card
MIN_LENGTH = 30.0  # videos shorter than this get a longer outro

# Colours and style for each genre.
THEMES = {
    "comedy": {
        "sky": ((255, 214, 92), (255, 140, 66)),   # top colour, bottom colour
        "ground": (120, 72, 40),
        "accent": (255, 255, 255),
        "title": (60, 20, 0),
        "characters": [((66, 135, 245), "round"), ((236, 72, 153), "box")],
        "decor": "confetti",
        "end_text": "Ha ha! The End",
    },
    "horror": {
        "sky": ((40, 10, 60), (5, 5, 10)),
        "ground": (20, 20, 25),
        "accent": (255, 70, 70),
        "title": (230, 230, 230),
        "characters": [((220, 220, 230), "ghost"), ((110, 170, 110), "round")],
        "decor": "moon",
        "end_text": "The End...?",
    },
    "kids": {
        "sky": ((120, 200, 255), (200, 240, 255)),
        "ground": (90, 190, 90),
        "accent": (255, 220, 0),
        "title": (20, 60, 120),
        "characters": [((255, 150, 50), "round"), ((160, 110, 230), "box")],
        "decor": "sun",
        "end_text": "The End!",
    },
}

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",            # Linux
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",                        # Arch
    "/Library/Fonts/Arial Bold.ttf",                                   # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",               # macOS
    "C:/Windows/Fonts/arialbd.ttf",                                    # Windows
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
]


def load_font(size):
    """Find a bold font on this computer; fall back to Pillow's built-in font."""
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
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
    if theme["decor"] == "confetti":
        colours = [(255, 255, 255), (66, 135, 245), (236, 72, 153), (50, 200, 120)]
        for _ in range(70):
            x, y, r = rng.randint(0, WIDTH), rng.randint(0, 1250), rng.randint(6, 14)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=rng.choice(colours))
    elif theme["decor"] == "moon":
        for _ in range(90):  # stars
            x, y, r = rng.randint(0, WIDTH), rng.randint(0, 1100), rng.randint(1, 4)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 220, 255))
        # Crescent moon: a full circle with a second, shifted circle cut out of it.
        mask = Image.new("L", (WIDTH, HEIGHT), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([720, 330, 960, 570], fill=255)
        mask_draw.ellipse([770, 310, 1010, 550], fill=0)
        image.paste((240, 240, 210), (0, 0), mask)
    elif theme["decor"] == "sun":
        draw.ellipse([780, 300, 980, 500], fill=(255, 230, 60))
        for i in range(12):  # sun rays
            a = i * math.pi / 6
            draw.line([(880 + 130 * math.cos(a), 400 + 130 * math.sin(a)),
                       (880 + 180 * math.cos(a), 400 + 180 * math.sin(a))],
                      fill=(255, 230, 60), width=10)

    # Ground under the characters.
    draw.rectangle([0, 1230, WIDTH, HEIGHT], fill=theme["ground"])

    # Story title at the top.
    font = load_font(76)
    y = 140
    for line in wrap_text(draw, title, font, WIDTH - 120):
        w = draw.textlength(line, font=font)
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill=theme["title"],
                  stroke_width=4, stroke_fill=theme["sky"][0])
        y += 92
    return image


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------
def draw_character(draw, cx, cy, size, colour, shape, mouth_open, blink, name, font):
    """Draw one cartoon character centred at (cx, cy).

    mouth_open goes from 0 (closed) to 1 (wide open).
    """
    half = size // 2
    outline = (30, 30, 30)

    # Shadow on the ground.
    draw.ellipse([cx - half, 1250, cx + half, 1290], fill=(0, 0, 0, 70))

    # Body
    box = [cx - half, cy - half, cx + half, cy + half]
    if shape == "round":
        draw.ellipse(box, fill=colour, outline=outline, width=6)
    elif shape == "box":
        draw.rounded_rectangle(box, radius=size // 5, fill=colour, outline=outline, width=6)
    else:  # ghost: round head, wavy bottom
        draw.ellipse([cx - half, cy - half, cx + half, cy + half // 2], fill=colour)
        draw.rectangle([cx - half, cy - half // 4, cx + half, cy + half - 30], fill=colour)
        for i in range(4):
            x0 = cx - half + i * size // 4
            draw.ellipse([x0, cy + half - 60, x0 + size // 4, cy + half], fill=colour)

    # Eyes (white with black pupils, or a line when blinking)
    eye_y = cy - size // 8
    for side in (-1, 1):
        ex = cx + side * size // 5
        if blink:
            draw.line([ex - 30, eye_y, ex + 30, eye_y], fill=outline, width=8)
        else:
            draw.ellipse([ex - 32, eye_y - 38, ex + 32, eye_y + 38], fill="white", outline=outline, width=4)
            draw.ellipse([ex - 14, eye_y - 10, ex + 14, eye_y + 18], fill=outline)

    # Mouth
    mouth_y = cy + size // 6
    mouth_w = size // 6
    if mouth_open > 0.1:
        h = 10 + int(55 * mouth_open)
        draw.ellipse([cx - mouth_w, mouth_y - h // 2, cx + mouth_w, mouth_y + h // 2],
                     fill=(120, 20, 30), outline=outline, width=4)
    else:
        draw.arc([cx - mouth_w, mouth_y - 30, cx + mouth_w, mouth_y + 20], 20, 160, fill=outline, width=7)

    # Name tag under the character
    w = draw.textlength(name, font=font)
    draw.text((cx - w / 2, 1300), name, font=font, fill="white", stroke_width=4, stroke_fill="black")


# ---------------------------------------------------------------------------
# Subtitles (rendered once per line as a transparent image)
# ---------------------------------------------------------------------------
def render_subtitle(speaker, text, accent):
    image = Image.new("RGBA", (WIDTH, 560), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    text_font, name_font = load_font(70), load_font(50)
    lines = wrap_text(draw, text, text_font, WIDTH - 200)
    line_h = 86
    box_h = 100 + line_h * len(lines)
    top = 560 - box_h - 20
    draw.rounded_rectangle([50, top, WIDTH - 50, 540], radius=40, fill=(0, 0, 0, 170))
    if speaker:
        draw.text((100, top + 22), speaker.upper(), font=name_font, fill=accent)
    y = top + 85
    for line in lines:
        w = draw.textlength(line, font=text_font)
        draw.text(((WIDTH - w) / 2, y), line, font=text_font, fill="white",
                  stroke_width=4, stroke_fill="black")
        y += line_h
    return image


# ---------------------------------------------------------------------------
# Mouth movement from the voice volume
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
    theme = THEMES[script["genre"]]
    segments, total = build_timeline(voiced_lines)
    end_start = segments[-1]["end"] + GAP if segments else INTRO

    background = draw_background(theme, script["title"])
    name_font = load_font(48)

    # Pre-render things that do not change from frame to frame.
    for seg in segments:
        label = None if seg["speaker"] == NARRATOR else seg["speaker"]
        seg["subtitle"] = render_subtitle(label or "Narrator", seg["text"], theme["accent"])
        seg["loudness"] = loudness_per_frame(seg["audio"])
    end_card = render_subtitle("", theme["end_text"], theme["accent"])

    # Where each character stands.
    characters = script["characters"]
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

        for i, name in enumerate(characters):
            colour, shape = theme["characters"][i]
            speaking = seg is not None and seg["speaker"] == name
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
            draw_character(draw, positions[i], 980 + idle - bounce, 360, colour, shape,
                           mouth, blink, name, name_font)

        # Gentle zoom: crop a slightly smaller area from the centre and scale it up.
        zoom = 1.0 + 0.08 * (t / total)
        cw, ch = int(WIDTH / zoom), int(HEIGHT / zoom)
        left, top = (WIDTH - cw) // 2, (HEIGHT - ch) // 2
        frame = frame.crop((left, top, left + cw, top + ch)).resize((WIDTH, HEIGHT), Image.BILINEAR)

        # Subtitles go on top after the zoom so they stay sharp and in place.
        if seg is not None:
            frame.paste(seg["subtitle"], (0, HEIGHT - 600), seg["subtitle"])
        elif t >= end_start:
            frame.paste(end_card, (0, HEIGHT - 600), end_card)
        return np.array(frame)

    # Audio: each line placed at its start time.
    audio_clips = [AudioFileClip(seg["audio"]).with_start(seg["start"]) for seg in segments]
    audio = CompositeAudioClip(audio_clips).with_duration(total)

    video = VideoClip(make_frame, duration=total).with_audio(audio)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    video.write_videofile(out_path, fps=FPS, codec="libx264", audio_codec="aac",
                          preset="medium", threads=os.cpu_count(), logger="bar",
                          temp_audiofile_path=work_dir or "")

    for clip in audio_clips:
        clip.close()
    return out_path, total
