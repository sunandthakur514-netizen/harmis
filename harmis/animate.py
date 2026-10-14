"""Step 3: animate the story and put it together with the voices.

Two formats (see config.yaml -> formats):
  short  1080x1920 vertical, 30-60 s (Shorts / Reels)
  long   1920x1080 horizontal, 5-7 min, with an intro title card and a
         "Like & Subscribe" style ending card

Layers, from back to front:
  1. the scene background (an AI picture from the library, or a bright
     Indian-style drawn background) with slow Ken Burns camera movement and
     crossfades when the scene changes
  2. the characters: transparent PNGs from the character library. The speaker
     bounces, grows a little and glows, and its mouth flaps with the voice
     (closed / half-open / open pictures, chosen from the loudness every 80 ms);
     everyone blinks every 3-5 s and breathes gently. Characters without a picture are drawn as
     simple shapes whose mouth moves with the voice. In long videos each scene
     shows only the characters who are in it.
  3. a small round narrator picture while the narrator speaks
  4. the title (short videos), big subtitles with the speaker's name, and a 13+
     badge for horror

Memory: every frame is drawn when it is needed and thrown away, all voices are
mixed into one audio file first, and the video is rendered in pieces of
`chunk_seconds` that ffmpeg joins at the end, so a 7-minute video needs no more
memory than a 30-second one.
"""

import bisect
import functools
import gc
import math
import os
import random
import subprocess
import wave
import zlib

import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip, VideoClip
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, features

from . import lipsync
from .config import CONFIG
from .script import NARRATOR

FADE = float(CONFIG["video"]["crossfade_seconds"])  # crossfade between scenes
GAP = 0.35            # pause between lines
AUDIO_RATE = 24000    # sample rate of the mixed voice track

# Colours and style for each genre (used by the drawn fallback background and shapes).
THEMES = {
    "kids_story": {
        "sky": ((255, 196, 60), (255, 110, 130)),   # marigold yellow to rose pink
        "ground": (70, 170, 70),
        "accent": (255, 225, 0),
        "title": (120, 20, 60),
        "characters": [(255, 120, 0), (0, 170, 150), (150, 90, 220), (230, 60, 90)],
        "decor": "toran",
    },
    "kids_rhyme": {
        "sky": ((0, 150, 210), (90, 220, 170)),      # peacock blue to parrot green
        "ground": (60, 180, 80),
        "accent": (255, 225, 0),
        "title": (255, 255, 255),
        "characters": [(255, 90, 150), (255, 160, 0), (90, 120, 255), (0, 170, 120)],
        "decor": "kites",
    },
    "comedy": {
        "sky": ((255, 225, 80), (255, 90, 150)),     # mango yellow to rani pink
        "ground": (205, 160, 110),                   # dusty gali
        "accent": (255, 255, 255),
        "title": (90, 20, 90),
        "characters": [(0, 160, 90), (130, 70, 200), (255, 120, 0), (40, 120, 255)],
        "decor": "bunting",
    },
    "horror": {
        "sky": ((40, 10, 60), (5, 5, 10)),
        "ground": (20, 20, 25),
        "accent": (255, 70, 70),
        "title": (230, 230, 230),
        "characters": [(150, 150, 175), (120, 135, 110), (140, 110, 110), (110, 120, 150)],
        "decor": "moon",
    },
}

END_TEXT = {"hindi": "समाप्त", "hinglish": "The End", "english": "The End"}
GROWN_UPS = {"hindi": "13+ बड़ों के लिए", "hinglish": "13+ only", "english": "13+ only"}
# Ending card of long videos: (question, actions, goodbye). Text only, no logos.
END_CARD = {
    "hindi": ("कहानी पसंद आई?", "लाइक करें  •  शेयर करें  •  सब्सक्राइब करें",
              "फिर मिलेंगे एक नई कहानी के साथ!"),
    "hinglish": ("Kahani pasand aayi?", "Like karein  •  Share karein  •  Subscribe karein",
                 "Phir milenge ek nayi kahani ke saath!"),
    "english": ("Enjoyed the story?", "Like  •  Share  •  Subscribe", "See you in the next story!"),
}


# ---------------------------------------------------------------------------
# Layout: where everything goes, for each format
# ---------------------------------------------------------------------------
class Layout:
    """Sizes and positions for one video format."""

    SETTINGS = {
        "short": dict(ground_y=1230, char_height=820, char_max_w=520, baseline=1450,
                      shape_size=360, shape_cy=980, tags_below=True,
                      sub_height=600, sub_sizes=(60, 54, 48, 42), sub_lines=4, sub_margin=70, sub_name=40,
                      title_size=80, cameo_size=240, intro=1.0, outro=2.0, pad_to_min=True,
                      cast_per_scene=False),
        "long": dict(ground_y=800, char_height=580, char_max_w=440, baseline=815,
                     shape_size=300, shape_cy=600, tags_below=False,
                     sub_height=330, sub_sizes=(46, 42, 38), sub_lines=3, sub_margin=160, sub_name=34,
                     title_size=110, cameo_size=190, intro=None, outro=None, pad_to_min=False,
                     cast_per_scene=True),
    }

    def __init__(self, fmt):
        settings = CONFIG["formats"][fmt]
        self.fmt = fmt
        self.w, self.h, self.fps = settings["width"], settings["height"], settings["fps"]
        self.min_seconds, self.max_seconds = float(settings["min_seconds"]), float(settings["max_seconds"])
        for key, value in self.SETTINGS[fmt].items():
            setattr(self, key, value)
        if self.intro is None:
            self.intro = float(settings.get("intro_seconds", 4))
            self.outro = float(settings.get("outro_seconds", 7))
        self.bg_w, self.bg_h = int(self.w * 1.1), int(self.h * 1.1)  # room for camera moves

    def positions(self, count):
        """x positions for 1, 2 or 3 characters standing side by side."""
        if count <= 1:
            return [self.w // 2]
        if count == 2:
            return ([self.w // 4 + 20, 3 * self.w // 4 - 20] if self.fmt == "short"
                    else [int(self.w * 0.3), int(self.w * 0.7)])
        return [int(self.w * f) for f in (0.2, 0.5, 0.8)][:count] if count == 3 else \
            [int(self.w * (i + 1) / (count + 1)) for i in range(count)]


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Bundled font: Noto Sans Devanagari Bold (SIL Open Font License, see fonts/OFL.txt).
# It has both Devanagari and English letters, so it works for every language.
FONT_FILE = os.path.join(os.path.dirname(__file__), "fonts", "NotoSansDevanagari-Bold.ttf")

if not features.check("raqm"):
    print("[animate] Warning: your Pillow has no 'raqm' support, so Hindi letters may join "
          "wrongly. Reinstall Pillow from pip: pip install --force-reinstall \"Pillow<12\"")


@functools.lru_cache(maxsize=32)
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


def draw_centered(draw, text, font, y, width, fill, stroke=4, stroke_fill="black", max_width=None):
    """Draw wrapped, centred text starting at y. Returns the y below the text."""
    for line in wrap_text(draw, text, font, max_width or width - 160):
        w = draw.textlength(line, font=font)
        draw.text(((width - w) / 2, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        y += int(font.size * 1.35)
    return y


# ---------------------------------------------------------------------------
# Drawn fallback background (used when a scene has no picture)
# ---------------------------------------------------------------------------
def draw_toran(draw, w):
    """A marigold garland (toran) with mango leaves across the top."""
    def sag(x):
        return 40 + 60 * (1 - ((x - w / 2) / (w / 2)) ** 2)

    for x in range(0, w + 1, 90):  # mango leaves hanging below
        y = sag(x) + 15
        draw.polygon([(x - 16, y), (x + 16, y), (x, y + 60)], fill=(30, 130, 40))
    for i, x in enumerate(range(0, w + 1, 40)):  # marigold flowers
        y = sag(x)
        colour = (255, 130, 0) if i % 2 else (255, 200, 0)
        draw.ellipse([x - 22, y - 22, x + 22, y + 22], fill=colour, outline=(200, 80, 0), width=3)


def draw_kites(draw, rng, w, ground):
    """Colourful patang kites with strings."""
    colours = [(255, 60, 60), (255, 200, 0), (60, 200, 90), (255, 90, 200), (140, 80, 255)]
    spots = [(0.157, 0.341), (0.398, 0.52), (0.815, 0.407), (0.648, 0.7), (0.231, 0.732)]
    for i, (fx, fy) in enumerate(spots):
        x, y, s = int(fx * w), int(fy * ground), rng.randint(55, 80)
        colour = colours[i % len(colours)]
        draw.line([(x, y + s), (x - 140 + i * 60, ground)], fill=(255, 255, 255), width=2)
        draw.polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], fill=colour)
        draw.line([(x, y - s), (x, y + s)], fill=(80, 40, 20), width=3)
        draw.line([(x - s, y), (x + s, y)], fill=(80, 40, 20), width=3)
        draw.polygon([(x, y + s), (x - 18, y + s + 30), (x + 18, y + s + 30)], fill=colour)


def draw_bunting(draw, w, ground):
    """Two strings of triangle festival flags."""
    colours = [(255, 140, 0), (0, 160, 90), (255, 60, 140), (40, 120, 255), (255, 215, 0)]
    for row, base in enumerate((30, int(0.27 * ground))):
        def sag(x):
            return base + 50 * (1 - ((x - w / 2) / (w / 2)) ** 2)
        draw.line([(x, sag(x)) for x in range(0, w + 1, 20)], fill=(90, 50, 30), width=4)
        for i, x in enumerate(range(20 + row * 30, w, 70)):
            y = sag(x)
            draw.polygon([(x - 25, y), (x + 25, y), (x, y + 60)], fill=colours[(i + row) % len(colours)])


def draw_background(theme, layout):
    """The drawn fallback background: gradient sky, decorations and ground."""
    w, h, ground = layout.w, layout.h, layout.ground_y
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)

    # Vertical gradient sky.
    (r1, g1, b1), (r2, g2, b2) = theme["sky"]
    for y in range(h):
        k = y / h
        draw.line([(0, y), (w, y)], fill=(int(r1 + (r2 - r1) * k), int(g1 + (g2 - g1) * k), int(b1 + (b2 - b1) * k)))

    rng = random.Random(42)  # fixed seed = same decoration every time
    decor = theme["decor"]
    if decor == "toran":
        cx, cy = int(0.82 * w), int(0.35 * ground)
        draw.ellipse([cx - 90, cy - 90, cx + 90, cy + 90], fill=(255, 240, 120))  # soft sun
        draw_toran(draw, w)
    elif decor == "kites":
        for fx, fy in [(0.10, 0.34), (0.78, 0.31)]:  # puffy clouds
            x, y = int(fx * w), int(fy * ground)
            for dx, dy, r in [(0, 0, 50), (50, -20, 60), (110, 0, 50)]:
                draw.ellipse([x + dx - r, y + dy - r, x + dx + r, y + dy + r], fill=(255, 255, 255))
        draw_kites(draw, rng, w, ground)
    elif decor == "bunting":
        draw_bunting(draw, w, ground)
    elif decor == "moon":
        for _ in range(int(90 * w / 1080)):  # stars
            x, y, r = rng.randint(0, w), rng.randint(0, int(0.9 * ground)), rng.randint(1, 4)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 220, 255))
        # Crescent moon: a full circle with a second, shifted circle cut out of it.
        cx, cy = int(0.78 * w), int(0.366 * ground)
        mask = Image.new("L", (w, h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([cx - 120, cy - 120, cx + 120, cy + 120], fill=255)
        mask_draw.ellipse([cx - 70, cy - 140, cx + 170, cy + 100], fill=0)
        image.paste((240, 240, 210), (0, 0), mask)

    # Ground under the characters.
    draw.rectangle([0, ground, w, h], fill=theme["ground"])
    return image


# ---------------------------------------------------------------------------
# Shape characters (used when a character has no picture)
# ---------------------------------------------------------------------------
def draw_character(draw, cx, cy, size, colour, shape, mouth_open, blink, info, font, layout):
    """Draw one cartoon character centred at (cx, cy).

    mouth_open goes from 0 (closed) to 1 (wide open).
    info is the character dict from the script (label, gender, age).
    """
    s = size / 360  # all the little details below were designed for size 360
    half = size // 2
    outline = (30, 30, 30)
    old = info["age"] == "old"
    ground = layout.ground_y

    # Shadow on the ground.
    draw.ellipse([cx - half, ground + 20 * s, cx + half, ground + 60 * s], fill=(0, 0, 0, 70))

    # Dadi / Nani get a grey hair bun on top.
    if old and info["gender"] == "f":
        draw.ellipse([cx - 70 * s, cy - half - 100 * s, cx + 70 * s, cy - half + 30 * s],
                     fill=(200, 200, 200), outline=outline, width=5)

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
            draw.line([ex - 30 * s, eye_y, ex + 30 * s, eye_y], fill=outline, width=max(3, int(8 * s)))
        else:
            draw.ellipse([ex - 32 * s, eye_y - 38 * s, ex + 32 * s, eye_y + 38 * s], fill="white", outline=outline, width=4)
            draw.ellipse([ex - 14 * s, eye_y - 10 * s, ex + 14 * s, eye_y + 18 * s], fill=outline)
        if old:  # round glasses
            draw.ellipse([ex - 48 * s, eye_y - 48 * s, ex + 48 * s, eye_y + 48 * s], outline=(40, 40, 40), width=6)
        if info["age"] == "child":  # rosy cheeks
            draw.ellipse([ex + side * 20 * s - 22 * s, eye_y + 60 * s, ex + side * 20 * s + 22 * s, eye_y + 90 * s],
                         fill=(255, 120, 140, 160))
    if old:
        draw.line([cx - 16 * s, eye_y, cx + 16 * s, eye_y], fill=(40, 40, 40), width=6)  # glasses bridge

    # Bindi for girls and women.
    if info["gender"] == "f":
        draw.ellipse([cx - 10 * s, eye_y - 75 * s, cx + 10 * s, eye_y - 55 * s], fill=(220, 0, 40))

    # Mouth
    mouth_y = cy + size // 6
    mouth_w = size // 6
    if old and info["gender"] == "m":  # white moustache for uncles and dadaji
        draw.ellipse([cx - 60 * s, mouth_y - 42 * s, cx, mouth_y - 18 * s], fill=(240, 240, 240), outline=outline, width=3)
        draw.ellipse([cx, mouth_y - 42 * s, cx + 60 * s, mouth_y - 18 * s], fill=(240, 240, 240), outline=outline, width=3)
    if mouth_open > 0.1:
        h = (10 + 55 * mouth_open) * s
        draw.ellipse([cx - mouth_w, mouth_y - h / 2, cx + mouth_w, mouth_y + h / 2],
                     fill=(120, 20, 30), outline=outline, width=4)
    else:
        draw.arc([cx - mouth_w, mouth_y - 30 * s, cx + mouth_w, mouth_y + 20 * s], 20, 160, fill=outline,
                 width=max(3, int(7 * s)))

    # Name tag under the character (short) or above its head (long, where subtitles cover the ground).
    w = draw.textlength(info["label"], font=font)
    tag_y = ground + 60 * s if layout.tags_below else cy - half - font.size * 1.6
    draw.text((cx - w / 2, tag_y), info["label"], font=font, fill="white", stroke_width=4, stroke_fill="black")


# ---------------------------------------------------------------------------
# Subtitles, badge, title and cards (rendered as transparent images)
# ---------------------------------------------------------------------------
def render_subtitle(speaker, text, accent, layout):
    image = Image.new("RGBA", (layout.w, layout.sub_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    name_font = load_font(layout.sub_name)
    margin = layout.sub_margin
    # Use the biggest text size that fits in the allowed number of lines.
    for size in layout.sub_sizes:
        text_font = load_font(size)
        lines = wrap_text(draw, text, text_font, layout.w - 2 * margin - 100)
        if len(lines) <= layout.sub_lines:
            break
    line_h = int(size * 1.4)  # Devanagari needs extra room above and below
    name_h = int(layout.sub_name * 1.5) if speaker else 0
    box_h = name_h + 24 + line_h * len(lines)
    top = max(0, layout.sub_height - box_h - 20)
    # A compact, see-through box that is only as wide as the text.
    text_w = max([draw.textlength(line, font=text_font) for line in lines] +
                 [draw.textlength(speaker or "", font=name_font)])
    box_w = min(layout.w - 2 * margin, text_w + 90)
    left = (layout.w - box_w) / 2
    draw.rounded_rectangle([left, top, left + box_w, layout.sub_height - 20], radius=30, fill=(0, 0, 0, 115))
    if speaker:
        draw.text((left + 30, top + 10), speaker, font=name_font, fill=accent, stroke_width=2, stroke_fill="black")
    y = top + name_h + 8
    for line in lines:
        w = draw.textlength(line, font=text_font)
        draw.text(((layout.w - w) / 2, y), line, font=text_font, fill="white", stroke_width=4, stroke_fill="black")
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


def render_title(title, theme, on_pictures, layout):
    """Title at the top of short videos. Over AI pictures it gets a soft dark band."""
    image = Image.new("RGBA", (layout.w, 420), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = load_font(layout.title_size)
    if on_pictures:
        for y in range(300):  # dark band fading out downwards
            draw.line([(0, y), (layout.w, y)], fill=(0, 0, 0, int(150 * (1 - y / 300))))
        y, fill, stroke = 70, (255, 255, 255), (0, 0, 0)
    else:  # drawn background: below the garland / flags, in the theme colours
        y, fill = 175, theme["title"]
        stroke = theme["sky"][0] if theme["decor"] != "kites" else (0, 90, 140)
    for line in wrap_text(draw, title, font, layout.w - 120):
        w = draw.textlength(line, font=font)
        draw.text(((layout.w - w) / 2, y), line, font=font, fill=fill, stroke_width=5, stroke_fill=stroke)
        y += int(layout.title_size * 1.3)
    return image, y


def card_background(base, layout):
    """A blurred, darkened copy of a scene, used behind the intro and ending cards."""
    image = ken_burns(base, 0.0, 0, layout).filter(ImageFilter.GaussianBlur(10))
    return ImageEnhance.Brightness(image).enhance(0.45)


def render_intro_card(base, title, tagline, theme, layout):
    """Long videos: big title card at the start."""
    image = card_background(base, layout)
    draw = ImageDraw.Draw(image)
    y = draw_centered(draw, title, load_font(layout.title_size), int(layout.h * 0.32), layout.w,
                      (255, 255, 255), stroke=6, max_width=layout.w - 300)
    draw.line([(layout.w * 0.38, y + 20), (layout.w * 0.62, y + 20)], fill=theme["accent"], width=6)
    if tagline:
        draw_centered(draw, tagline, load_font(56), y + 50, layout.w, theme["accent"])
    return image


def render_end_card(base, lang, theme, layout):
    """Long videos: friendly 'Like & Subscribe' style ending card (text only, no logos)."""
    question, actions, goodbye = END_CARD[lang]
    image = card_background(base, layout)
    draw = ImageDraw.Draw(image)
    y = draw_centered(draw, question, load_font(96), int(layout.h * 0.22), layout.w, (255, 255, 255), stroke=6)
    font = load_font(60)
    w = draw.textlength(actions, font=font)
    top = y + 40
    draw.rounded_rectangle([(layout.w - w) / 2 - 50, top, (layout.w + w) / 2 + 50, top + 120], radius=60,
                           fill=(220, 30, 40))
    draw.text(((layout.w - w) / 2, top + 22), actions, font=font, fill="white")
    draw_centered(draw, goodbye, load_font(56), top + 190, layout.w, theme["accent"])
    return image


# ---------------------------------------------------------------------------
# Character pictures
# ---------------------------------------------------------------------------
def _dim(image):
    dim = ImageEnhance.Brightness(image.convert("RGB")).enhance(0.8).convert("RGBA")
    dim.putalpha(image.getchannel("A"))
    return dim


def prepare_character(frames, layout):
    """Resize a character's pictures once (closed / half / open mouth, blink) and
    make dimmed copies and a soft glow."""
    image = frames["closed"]
    scale = min(layout.char_height / image.height, layout.char_max_w / image.width)
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    normal = image.resize(size, Image.LANCZOS)
    variants = {key: frames[key].resize(size, Image.LANCZOS) for key in ("half", "open", "blink") if frames.get(key)}
    alpha = normal.getchannel("A")
    pad = 40
    glow_alpha = Image.new("L", (normal.width + 2 * pad, normal.height + 2 * pad), 0)
    glow_alpha.paste(alpha, (pad, pad))
    glow_alpha = glow_alpha.filter(ImageFilter.GaussianBlur(18)).point(lambda a: min(255, int(a * 1.6)))
    glow = Image.new("RGBA", glow_alpha.size, (255, 235, 150, 0))
    glow.putalpha(glow_alpha)
    mouth_box = frames.get("mouth_box")
    drawn = frames.get("mouth_mode") != "inpainted" or "open" not in variants
    return {"normal": normal, "dim": _dim(normal), "glow": glow, "pad": pad, **variants,
            "dim_blink": _dim(variants["blink"]) if "blink" in variants else None,
            "mouth_box": mouth_box, "drawn_mouth": bool(drawn and mouth_box),
            "colours": lipsync.mouth_colours(normal, mouth_box) if mouth_box else None}


def render_cameo(image, size):
    """A round picture of the narrator's head and shoulders."""
    square = image.crop((0, 0, image.width, min(image.width, image.height)))
    square = ImageOps.fit(square.convert("RGBA"), (size, size))
    cameo = Image.new("RGBA", (size + 16, size + 16), (0, 0, 0, 0))
    ImageDraw.Draw(cameo).ellipse([0, 0, size + 15, size + 15], fill=(255, 255, 255, 235))
    inner = Image.new("RGBA", (size, size), (255, 248, 230, 255))
    inner.alpha_composite(square)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    cameo.paste(inner, (8, 8), mask)
    return cameo


# ---------------------------------------------------------------------------
# Timeline, camera and sound
# ---------------------------------------------------------------------------
def build_timeline(voiced_lines, fmt="short"):
    """Work out when each line starts and ends. Returns (segments, total_length)."""
    layout = Layout(fmt)
    segments, t = [], layout.intro
    for line in voiced_lines:
        segments.append({**line, "start": t, "end": t + line["duration"]})
        t += line["duration"] + GAP
    total = t + layout.outro
    if layout.pad_to_min:
        total = max(total, layout.min_seconds)
    return segments, total


def scene_spans(segments, total, characters, layout):
    """[{start, end, scene, cast}] - a new span starts whenever the scene (or its cast) changes."""
    spans = []
    for seg in segments:
        key = (seg.get("scene"), tuple(seg["cast"]) if seg.get("cast") is not None else None)
        if not spans or spans[-1]["key"] != key:
            if spans:
                spans[-1]["end"] = seg["start"]
            spans.append({"start": 0.0 if not spans else seg["start"], "end": total, "key": key,
                          "scene": seg.get("scene"), "cast": seg.get("cast"), "speakers": []})
        if seg["speaker"] != NARRATOR and seg["speaker"] not in spans[-1]["speakers"]:
            spans[-1]["speakers"].append(seg["speaker"])
    if not spans:
        spans = [{"start": 0.0, "end": total, "scene": None, "cast": None, "speakers": []}]
    names = [c["name"] for c in characters]
    for span in spans:
        if not layout.cast_per_scene:
            span["cast"] = names  # short videos: everyone is always on screen
        elif span["cast"] is None:
            span["cast"] = span["speakers"][:3]  # long videos: whoever talks in this scene
    return spans


def ken_burns(base, progress, index, layout):
    """Slow camera move over a background: zoom in or out and drift sideways.

    progress goes from 0 to 1 over the scene; index alternates the direction.
    """
    p = progress * progress * (3 - 2 * progress)  # smooth start and stop
    zoom = 1.0 + 0.10 * (p if index % 2 == 0 else 1 - p)
    cw, ch = layout.bg_w / zoom, layout.bg_h / zoom
    direction = 1 if index % 2 == 0 else -1
    cx = layout.bg_w / 2 + direction * (layout.bg_w - cw) / 2 * (2 * p - 1) * 0.8
    cy = layout.bg_h / 2 - (layout.bg_h - ch) / 2 * 0.3 * (2 * p - 1)
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return base.resize((layout.w, layout.h), Image.BILINEAR, box=box)


def rhyme_beat(samples, volume=0.12, bpm=100):
    """A soft dholak-like beat for rhymes: low 'dha' on the beat, high 'na' in between."""
    sound = np.zeros(samples, dtype=np.float32)
    hit_len = int(0.25 * AUDIO_RATE)
    t = np.arange(hit_len) / AUDIO_RATE
    dha = np.sin(2 * np.pi * 110 * t) * np.exp(-t * 18)
    na = 0.6 * np.sin(2 * np.pi * 330 * t) * np.exp(-t * 30)
    half_beat = int(30 / bpm * AUDIO_RATE)
    for k, start in enumerate(range(0, samples, half_beat)):
        hit = dha if k % 2 == 0 else na
        end = min(start + hit_len, samples)
        sound[start:end] += hit[:end - start]
    return sound * volume


def mix_audio(segments, total, path, fps, beat=False):
    """Mix every voice line into one mono WAV at its start time.

    Also measures how loud each line is in every video frame (for the shape
    characters' mouths) and stores it in seg["loudness"]. Clips are read one at
    a time, so memory stays small even for long videos.
    """
    track = np.zeros(int(total * AUDIO_RATE) + AUDIO_RATE, dtype=np.float32)
    cache = {}
    for seg in segments:
        if seg["audio"] not in cache:  # rhymes reuse the same clips
            with AudioFileClip(seg["audio"]) as clip:
                samples = clip.to_soundarray(fps=AUDIO_RATE).astype(np.float32)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            step = AUDIO_RATE // fps
            frames = max(1, len(samples) // step)
            rms = np.sqrt(np.mean(samples[:frames * step].reshape(frames, step) ** 2, axis=1)) \
                if len(samples) >= step else np.zeros(1)
            loudness = None if rms.max() < 1e-4 else np.clip(rms / (rms.max() * 0.6), 0, 1)
            cache[seg["audio"]] = (samples, loudness)  # a few MB even for long videos
        samples, seg["loudness"] = cache[seg["audio"]]
        start = int(seg["start"] * AUDIO_RATE)
        track[start:start + len(samples)] += samples[:len(track) - start]
    if beat:
        track += rhyme_beat(len(track))
    pcm = (np.clip(track, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(AUDIO_RATE)
        file.writeframes(pcm.tobytes())
    return path


def render_in_chunks(make_frame, total, layout, audio_path, out_path, work_dir):
    """Render the video in pieces, then let ffmpeg join them and add the audio."""
    chunk = float(CONFIG["video"].get("chunk_seconds", 60))
    count = max(1, math.ceil(total / chunk))
    parts = []
    for k in range(count):
        start = k * chunk
        duration = min(chunk, total - start)
        if count > 1:
            print(f"[render] part {k + 1}/{count} ({start:.0f}s to {start + duration:.0f}s)")
        clip = VideoClip(lambda t, offset=start: make_frame(offset + t), duration=duration)
        part = os.path.join(work_dir, f"part_{k:03d}.mp4")
        clip.write_videofile(part, fps=layout.fps, codec="libx264", audio=False, preset="medium",
                             threads=os.cpu_count(), logger="bar")
        clip.close()
        parts.append(part)
        gc.collect()

    listing = os.path.join(work_dir, "parts.txt")
    with open(listing, "w") as file:
        file.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", listing, "-i", audio_path,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-t", f"{total:.3f}", "-movflags", "+faststart", out_path], check=True)
    for part in parts:
        os.remove(part)


# ---------------------------------------------------------------------------
# Put it all together
# ---------------------------------------------------------------------------
def make_video(script, voiced_lines, out_path, visuals, work_dir):
    """Draw every frame, add the audio and save the mp4 to out_path.

    visuals comes from Library.load_visuals(): background pictures per scene and
    character pictures (any of them may be None, then shapes are drawn instead).
    """
    genre, lang, fmt = script["genre"], script["lang"], script.get("format", "short")
    layout = Layout(fmt)
    theme = THEMES[genre]
    segments, total = build_timeline(voiced_lines, fmt)
    end_start = segments[-1]["end"] + GAP if segments else layout.intro
    characters = script["characters"]
    spans = scene_spans(segments, total, characters, layout)
    span_starts = [span["start"] for span in spans]
    seg_starts = [seg["start"] for seg in segments]

    # ----- sound: one mixed track (also measures mouth movement) -----
    audio_path = mix_audio(segments, total, os.path.join(work_dir, "voices.wav"), layout.fps,
                           beat=genre == "kids_rhyme")

    # ----- backgrounds (one big image per scene, ready for the camera move) -----
    drawn = draw_background(theme, layout).resize((layout.bg_w, layout.bg_h), Image.BILINEAR)
    bases = {}
    for span in spans:
        if span["scene"] not in bases:
            picture = visuals["backgrounds"].get(span["scene"])
            bases[span["scene"]] = ImageOps.fit(picture, (layout.bg_w, layout.bg_h)) if picture is not None else drawn
    on_pictures = any(p is not None for p in visuals["backgrounds"].values())

    # ----- characters -----
    colour_of = {c["name"]: theme["characters"][i % len(theme["characters"])] for i, c in enumerate(characters)}
    shape_of = {c["name"]: ("round", "box")[i % 2] for i, c in enumerate(characters)}
    info_of = {c["name"]: c for c in characters}
    sprites = {}
    for info in characters:
        pictures = visuals["characters"].get(info["name"], {})
        if pictures.get("image") is not None:
            sprites[info["name"]] = prepare_character(pictures.get("frames") or {"closed": pictures["image"]}, layout)
    # Everyone blinks every 3-5 seconds (different times for each character).
    blinks = {c["name"]: lipsync.blink_times(total, zlib.crc32(c["name"].encode())) for c in characters}

    def blinking(name, t):
        times = blinks.get(name, [])
        index = bisect.bisect_right(times, t) - 1
        return index >= 0 and t - times[index] < 0.15

    # Mouth movement for every line: closed / half / open, decided every ~80 ms from the voice.
    for number, seg in enumerate(segments):
        count = int(math.ceil((seg["end"] - seg["start"]) * layout.fps)) + 2
        loud = seg["loudness"]
        if loud is not None and len(loud) < count:
            loud = np.pad(loud, (0, count - len(loud)))
        seg["mouth_state"], seg["mouth_level"] = lipsync.mouth_track(loud, count, layout.fps, seed=number)
    narrator = visuals.get("narrator")
    cameo = render_cameo(narrator, layout.cameo_size) if narrator is not None else None

    # ----- text and cards -----
    name_font = load_font(48 if fmt == "short" else 40)
    labels = {c["name"]: c["label"] for c in characters}
    labels[NARRATOR] = script["narrator"]["label"]

    @functools.lru_cache(maxsize=3)  # only the current subtitle is kept in memory
    def subtitle(index):
        seg = segments[index]
        return render_subtitle(labels.get(seg["speaker"], seg["speaker"]), seg["text"], theme["accent"], layout)

    badge = render_badge(GROWN_UPS[lang]) if genre == "horror" else None
    if fmt == "short":
        title, title_bottom = render_title(script["title"], theme, on_pictures, layout)
        end_card = render_subtitle("", END_TEXT[lang] + ("...?" if genre == "horror" else "!"), theme["accent"], layout)
        intro_card = outro_card = None
        cameo_pos = (40, title_bottom + 10)
        badge_pos = (layout.w - (badge.width if badge else 0) - 30, 330 if on_pictures else 40)
    else:
        title = end_card = None
        intro_card = render_intro_card(bases[spans[0]["scene"]], script["title"], script.get("tagline", ""), theme, layout)
        outro_card = render_end_card(bases[spans[-1]["scene"]], lang, theme, layout)
        cameo_pos = (40, 40)
        badge_pos = (layout.w - (badge.width if badge else 0) - 30, 30)

    def current_segment(t):
        index = bisect.bisect_right(seg_starts, t) - 1
        if index >= 0 and t < segments[index]["end"]:
            return index, segments[index]
        return None, None

    def background_at(t, index):
        span = spans[index]
        progress = min(1.0, max(0.0, (t - span["start"]) / max(0.1, span["end"] - span["start"])))
        frame = ken_burns(bases[span["scene"]], progress, index, layout)
        if index > 0 and t - span["start"] < FADE:  # crossfade from the previous scene
            previous = ken_burns(bases[spans[index - 1]["scene"]], 1.0, index - 1, layout)
            frame = Image.blend(previous, frame, (t - span["start"]) / FADE)
        return frame  # RGB, so semi-transparent drawing blends

    def draw_sprite(frame, sprite, cx, speaking, someone_speaks, local, t, i, name, seg):
        """Paste one character picture with its idle / speaking movement."""
        breathe = math.sin(t * 2.2 + i * 1.7)
        sx, sy, lift = 1 - 0.004 * breathe, 1 + 0.012 * breathe, 0
        dimmed = someone_speaks and not speaking
        image = sprite["dim"] if dimmed else sprite["normal"]
        if blinking(name, t) and sprite.get("blink") is not None:
            image = sprite["dim_blink"] if dimmed else sprite["blink"]
        elif speaking:
            index = min(int(local * layout.fps), len(seg["mouth_state"]) - 1)
            if sprite["drawn_mouth"]:  # no painted variants: draw a mouth that opens with the voice
                image = lipsync.draw_mouth(sprite["normal"], sprite["mouth_box"],
                                           float(seg["mouth_level"][index]), sprite["colours"])
            else:
                image = (sprite["normal"], sprite.get("half", sprite["normal"]), sprite["open"])[seg["mouth_state"][index]]
        if speaking:
            ease = min(1.0, local / 0.25)
            sx = sy = 1 + 0.05 * ease
            lift = int(16 * abs(math.sin(local * 6)) * ease)
        w, h = int(image.width * sx), int(image.height * sy)
        base = layout.baseline
        ImageDraw.Draw(frame, "RGBA").ellipse([cx - w * 0.35, base - 18, cx + w * 0.35, base + 18], fill=(0, 0, 0, 70))
        if speaking:  # warm glow behind the speaker
            glow = sprite["glow"].resize((int(sprite["glow"].width * sx), int(sprite["glow"].height * sy)))
            frame.paste(glow, (int(cx - glow.width / 2), int(base - h - lift - sprite["pad"] * sy)), glow)
        image = image.resize((w, h), Image.BILINEAR)
        frame.paste(image, (int(cx - w / 2), base - h - lift), image)

    def make_frame(t):
        t = min(t, total - 1e-3)
        # Long videos: intro title card, fading into the first scene.
        if intro_card is not None and t < layout.intro:
            if t < layout.intro - FADE:
                return np.array(intro_card)
            mix = (t - (layout.intro - FADE)) / FADE
            return np.array(Image.blend(intro_card, background_at(t, 0), mix))

        span_index = bisect.bisect_right(span_starts, t) - 1
        frame = background_at(t, span_index)
        draw = ImageDraw.Draw(frame, "RGBA")
        seg_index, seg = current_segment(t)
        someone_speaks = seg is not None and seg["speaker"] != NARRATOR

        cast = spans[span_index]["cast"]
        for i, (name, cx) in enumerate(zip(cast, layout.positions(len(cast)))):
            speaking = seg is not None and seg["speaker"] == name
            local = t - seg["start"] if speaking else 0.0
            if name in sprites:
                draw_sprite(frame, sprites[name], cx, speaking, someone_speaks, local, t, i, name, seg)
                continue
            # No picture: simple shape character whose mouth follows the (smoothed) voice.
            mouth, bounce = 0.0, 0
            if speaking:
                mouth = float(seg["mouth_level"][min(int(local * layout.fps), len(seg["mouth_level"]) - 1)])
                bounce = int(18 * abs(math.sin(local * 6)))
            idle = int(8 * math.sin(t * 2 + i * 1.7))
            blink = blinking(name, t)
            draw_character(draw, cx, layout.shape_cy + idle - bounce, layout.shape_size, colour_of[name],
                           shape_of[name], mouth, blink, info_of[name], name_font, layout)

        if title is not None:
            frame.paste(title, (0, 0), title)
        # Narrator picture fades in while the narrator talks.
        if cameo is not None and seg is not None and seg["speaker"] == NARRATOR:
            fade = min(1.0, (t - seg["start"]) / 0.3, (seg["end"] - t) / 0.3)
            faded = cameo.copy()
            faded.putalpha(cameo.getchannel("A").point(lambda a: int(a * fade)))
            frame.paste(faded, cameo_pos, faded)
        # Subtitles and badge go on top.
        if seg is not None:
            sub = subtitle(seg_index)
            frame.paste(sub, (0, layout.h - layout.sub_height - 20), sub)
        elif t >= end_start and end_card is not None:
            frame.paste(end_card, (0, layout.h - layout.sub_height - 20), end_card)
        if badge is not None:
            frame.paste(badge, badge_pos, badge)
        # Long videos: "Like & Subscribe" card fades in at the end.
        if outro_card is not None and t >= end_start:
            frame = Image.blend(frame, outro_card, min(1.0, (t - end_start) / FADE))
        return np.array(frame)

    render_in_chunks(make_frame, total, layout, audio_path, out_path, work_dir)
    return out_path, total
