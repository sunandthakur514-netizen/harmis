"""Character and scene library, with cached images.

Characters live in harmis/assets/characters/<id>/:
    character.yaml   who they are and how they look (written once, never changes)
    custom.png       YOUR OWN picture (optional). Always wins over generated ones.
    blink.png        optional eyes-closed version of custom.png, used for blinking
    <style>.png      generated picture with a transparent background (cached)
    <style>.json     which prompt and provider made it

Backgrounds live in harmis/assets/backgrounds/:
    scenes.yaml           every scene and its description
    <scene>.png           YOUR OWN background (optional). Always wins.
    <scene>__<style>.png        generated vertical background (short videos), cached + .json
    <scene>__<style>__wide.png  generated 16:9 background (long videos), cached + .json

A picture is generated once and then reused in every video, so characters look
the same each time. If the description, style or safety words change, the prompt
changes and the picture is generated again.
"""

import json
import os
import re
import zlib

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import lipsync
from .config import CONFIG

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
CHARACTER_DIR = os.path.join(ASSETS, "characters")
BACKGROUND_DIR = os.path.join(ASSETS, "backgrounds")

# Sizes we ask the providers for (they are resized later).
CHARACTER_SIZE = (768, 1024)
BACKGROUND_SIZE = {"short": (768, 1344), "long": (1344, 768)}  # 9:16 and 16:9
COMPOSITION = {"short": "tall vertical composition", "long": "wide horizontal 16:9 composition"}
CACHE_SUFFIX = {"short": "", "long": "__wide"}


# ---------------------------------------------------------------------------
# Prompts and kid safety
# ---------------------------------------------------------------------------
def make_safe(text):
    """Remove blocked words (copyrighted characters, brands) from a prompt."""
    for word in CONFIG["safety"].get("blocked_words", []):
        text = re.sub(rf"\b{re.escape(word)}\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


def style_text(style):
    return CONFIG["styles"].get(style, CONFIG["styles"]["3d_cartoon"]).strip()


def character_prompt(character, style):
    return make_safe(
        f"{style_text(style)}. Full body character: {character['description'].strip()}. "
        "Single character, alone, full body, centered. Exactly one character, standing, facing the "
        "viewer, friendly expression, whole body visible from head to feet, plain pure white "
        "background, no other characters or objects. "
        f"{CONFIG['safety']['always_add']}"
    )


def background_prompt(description, style, mood, fmt="short"):
    return make_safe(
        f"{style_text(style)}. Background scenery only: {description.strip()}. {mood}. "
        f"Empty scene with no people, no animals, no characters, {COMPOSITION[fmt]}, "
        f"detailed environment. {CONFIG['safety']['always_add']}"
    )


# Short prompts for local models (Stable Diffusion reads only the first ~77
# tokens). The important words come first: style, kid safety, layout, then the
# description, so only the end of a long description can be cut off.
SAFE_CORE = "kid-friendly, wholesome, family-safe, non-violent"


def short_style(style):
    """The first two parts of a style, e.g. '3D animated movie style render, cute stylised proportions'."""
    return ", ".join(part.strip() for part in style_text(style).split(",")[:2])


def compact_character_prompt(character, style):
    return make_safe(f"{short_style(style)}, {SAFE_CORE}, single character, alone, full body, centered, "
                     f"plain white background, {character['description'].strip()}")


def face_prompt(character, style):
    """Prompt for repainting the mouth / eyes (lip movement variants)."""
    return make_safe(f"{short_style(style)}, {SAFE_CORE}, close-up of the face, "
                     f"{character['description'].strip()}")


def compact_background_prompt(description, style, mood):
    return make_safe(f"{short_style(style)}, {SAFE_CORE}, background scenery, no people, "
                     f"{description.strip()}, {mood}")


# ---------------------------------------------------------------------------
# Background removal (character pictures -> transparent PNG)
# ---------------------------------------------------------------------------
_rembg_session = None


def _rembg_cut(image):
    """Cut out the character with rembg. Returns None if rembg is unavailable."""
    global _rembg_session
    try:
        from rembg import new_session, remove
    except ImportError:
        return None
    try:
        if _rembg_session is None:
            _rembg_session = new_session(CONFIG["background_removal"].get("rembg_model", "u2net"))
        return remove(image, session=_rembg_session).convert("RGBA")
    except Exception as error:  # model download failed, etc.
        print(f"[library] rembg failed ({type(error).__name__}), using simple background removal.")
        return None


def _simple_cut(image, tolerance=40):
    """Fallback: flood-fill the plain background from the edges and make it transparent."""
    rgb = image.convert("RGB")
    marker = (255, 0, 255)
    w, h = rgb.size
    for point in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (0, h // 2), (w - 1, h // 2)]:
        if rgb.getpixel(point) != marker:
            ImageDraw.floodfill(rgb, point, marker, thresh=tolerance)
    is_background = np.all(np.array(rgb) == marker, axis=-1)
    mask = Image.fromarray(np.where(is_background, 0, 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def remove_background(image):
    """Return an RGBA image with the background removed and cropped to the character."""
    cut = _rembg_cut(image)
    if cut is not None:
        # Make sure rembg actually found something sensible (5%-95% of the picture).
        coverage = float((np.array(cut.getchannel("A")) > 128).mean())
        if not 0.05 < coverage < 0.95:
            cut = None
    if cut is None:
        cut = _simple_cut(image)
    box = cut.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
    return cut.crop(box) if box else cut


def has_transparency(image):
    return image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 250


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------
def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"


def _load_cached(png, json_path, prompt):
    """Return the cached image if it was made from the same prompt."""
    if not os.path.exists(png):
        return None
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as file:
            if json.load(file).get("prompt") != prompt:
                return None  # description or style changed: make a new one
    return Image.open(png)


def _save_meta(json_path, prompt, provider, style):
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump({"prompt": prompt, "provider": provider, "style": style}, file, indent=2, ensure_ascii=False)


class Library:
    def __init__(self, chain, style, genre, refresh=False, fmt="short"):
        self.chain = chain      # ImageChain (may have no providers at all)
        self.style = style
        self.genre = genre
        self.refresh = refresh  # True = ignore cached generated pictures
        self.fmt = fmt          # "short" (vertical) or "long" (16:9) backgrounds
        self.status = {}        # picture label -> "cached", "your own picture", provider name or "shapes"
        self.base_paths = {}    # character id -> file of its picture (for the lip-movement variants)
        self.characters = {}    # id -> data from character.yaml
        for folder in sorted(os.listdir(CHARACTER_DIR)):
            path = os.path.join(CHARACTER_DIR, folder, "character.yaml")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as file:
                    data = yaml.safe_load(file)
                data["id"] = folder
                self.characters[folder] = data
        with open(os.path.join(BACKGROUND_DIR, "scenes.yaml"), encoding="utf-8") as file:
            self.scenes = yaml.safe_load(file)

    # ----- characters -----
    def find(self, name):
        """Find a character by id or by the name used in scripts (any case)."""
        key, slug = name.strip().lower(), _slug(name)
        for data in self.characters.values():  # exact id first ("narrator_horror")
            if slug == data["id"]:
                return data
        for data in self.characters.values():  # then the name used in scripts ("Sharma")
            if key == str(data.get("name", "")).lower():
                return data
        return None

    def add_character(self, name, gender="m", age="adult", look="", hindi_label=None):
        """Create a new character.yaml (for characters invented by Gemini)."""
        char_id = _slug(name)
        while char_id in self.characters:
            char_id += "_2"
        folder = os.path.join(CHARACTER_DIR, char_id)
        os.makedirs(folder, exist_ok=True)
        person = {("m", "child"): "boy", ("f", "child"): "girl", ("m", "old"): "grandfather",
                  ("f", "old"): "grandmother", ("m", "adult"): "man", ("f", "adult"): "woman"}[(gender, age)]
        data = {
            "name": name,
            "label": {"hindi": hindi_label or name, "english": name},
            "gender": gender,
            "age": age,
            "seed": zlib.crc32(char_id.encode()) % 100000,
            "description": make_safe(look) or f"a friendly Indian {person} wearing colourful everyday clothes",
        }
        with open(os.path.join(folder, "character.yaml"), "w", encoding="utf-8") as file:
            file.write(f"# Added automatically for a Gemini story. Edit freely.\n")
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
        data["id"] = char_id
        self.characters[char_id] = data
        print(f"[library] Added new character '{name}' to {folder}")
        return data

    def character_image(self, data):
        """Transparent RGBA picture of a character, or None (then shapes are drawn)."""
        folder = os.path.join(CHARACTER_DIR, data["id"])
        custom = os.path.join(folder, "custom.png")
        if os.path.exists(custom):
            image = Image.open(custom)
            self.base_paths[data["id"]] = custom
            self.status[f"character {data['id']}"] = "your own picture"
            print(f"[library] {data['id']}: using your custom.png")
            return image.convert("RGBA") if has_transparency(image.convert("RGBA")) else remove_background(image)

        prompt = character_prompt(data, self.style)
        png = os.path.join(folder, f"{self.style}.png")
        meta = os.path.join(folder, f"{self.style}.json")
        if not self.refresh:
            cached = _load_cached(png, meta, prompt)
            if cached is not None:
                self.base_paths[data["id"]] = png
                self.status[f"character {data['id']}"] = "cached"
                print(f"[library] {data['id']}: using cached {self.style}.png")
                return cached.convert("RGBA")

        image, provider = self.chain.generate(prompt, *CHARACTER_SIZE, seed=data.get("seed", 1),
                                              label=f"character {data['id']}",
                                              negative=CONFIG["safety"]["negative"],
                                              compact=compact_character_prompt(data, self.style))
        self.status[f"character {data['id']}"] = provider
        if image is None:
            return None
        cut = remove_background(image)
        cut.save(png)
        _save_meta(meta, prompt, provider, self.style)
        self.base_paths[data["id"]] = png
        return cut

    def boxes(self, data, base):
        """Mouth and eyes boxes from character.yaml, or found now and written into it."""
        mouth, eyes = data.get("mouth_box"), data.get("eyes_box")
        if mouth and eyes:
            return [float(v) for v in mouth], [float(v) for v in eyes]
        mouth, eyes, method = lipsync.find_boxes(base, data.get("type", "human"))
        lipsync.save_boxes_to_yaml(os.path.join(CHARACTER_DIR, data["id"], "character.yaml"), mouth, eyes, method)
        data["mouth_box"], data["eyes_box"] = mouth, eyes
        print(f"[lipsync] {data['id']}: mouth/eyes found by {method}, saved in character.yaml")
        return mouth, eyes

    def character_frames(self, data, base):
        """Picture + lip-movement variants: {"closed", "half", "open", "blink", "mouth_box", "mouth_mode"}.

        Variants are made with local_sd when it is available (and cached); otherwise
        the animation draws a simple mouth over mouth_box.
        """
        if base is None:
            return None
        mouth, eyes = self.boxes(data, base)
        frames = {"closed": base, "mouth_box": mouth, "eyes_box": eyes, "mouth_mode": "drawn"}
        base_path = self.base_paths.get(data["id"])
        label = f"mouth {data['id']}"
        cached = None if (self.refresh or not base_path) else lipsync.load_variants(base_path, mouth, eyes)
        if cached is None and base_path:
            pipe = self.chain.local_pipe()
            if pipe is not None:
                lipsync.make_variants(pipe, base, base_path, mouth, eyes, face_prompt(data, self.style),
                                      data.get("seed", 1), data["id"])
                cached = lipsync.load_variants(base_path, mouth, eyes)
        if cached is not None:
            info, images = cached
            frames.update(images)
            frames["mouth_mode"] = info["mouth"]
            self.status[label] = f"variants: mouth {info['mouth']}, blink {info['blink']}"
        else:
            self.status[label] = "drawn mouth (local_sd not available to make variants)"
        user_blink = self.blink_image(data)  # your own blink.png always wins
        if user_blink is not None:
            frames["blink"] = user_blink.resize(base.size)
        return frames

    def blink_image(self, data):
        path = os.path.join(CHARACTER_DIR, data["id"], "blink.png")
        return Image.open(path).convert("RGBA") if os.path.exists(path) else None

    # ----- backgrounds -----
    def background_image(self, scene):
        """RGB background for a scene, or None (then the coloured shape background is drawn)."""
        if not scene:
            return None
        custom = os.path.join(BACKGROUND_DIR, f"{scene}.png")
        if os.path.exists(custom):
            self.status[f"scene {scene}"] = "your own picture"
            print(f"[library] scene {scene}: using your {scene}.png")
            return Image.open(custom).convert("RGB")
        if scene not in self.scenes:
            print(f"[library] Unknown scene '{scene}' (add it to scenes.yaml)")
            return None

        mood = CONFIG["genres"][self.genre].get("mood", "")
        prompt = background_prompt(self.scenes[scene], self.style, mood, self.fmt)
        name = f"{scene}__{self.style}{CACHE_SUFFIX[self.fmt]}"
        png = os.path.join(BACKGROUND_DIR, f"{name}.png")
        meta = os.path.join(BACKGROUND_DIR, f"{name}.json")
        if not self.refresh:
            cached = _load_cached(png, meta, prompt)
            if cached is not None:
                self.status[f"scene {scene}"] = "cached"
                print(f"[library] scene {scene}: using cached background")
                return cached.convert("RGB")

        size = BACKGROUND_SIZE[self.fmt]
        image, provider = self.chain.generate(prompt, *size, seed=zlib.crc32(scene.encode()) % 100000,
                                              label=f"scene {scene}", negative=CONFIG["safety"]["negative"],
                                              compact=compact_background_prompt(self.scenes[scene], self.style, mood))
        self.status[f"scene {scene}"] = provider
        if image is None:
            return None
        image = ImageOps.fit(image, size)
        image.save(png)
        _save_meta(meta, prompt, provider, self.style)
        return image

    # ----- everything one video needs -----
    def load_visuals(self, script):
        """Get (or make) every picture for a script. Missing pictures are None."""
        scenes = []
        for line in script["lines"]:
            if line.get("scene") and line["scene"] not in scenes:
                scenes.append(line["scene"])
        visuals = {"backgrounds": {scene: self.background_image(scene) for scene in scenes},
                   "characters": {}, "narrator": None}
        for character in script["characters"]:
            data = self.characters[character["id"]]
            base = self.character_image(data)
            visuals["characters"][character["name"]] = {"image": base, "frames": self.character_frames(data, base)}
        narrator_id = script["narrator"].get("id")
        if narrator_id:
            visuals["narrator"] = self.character_image(self.characters[narrator_id])
        return visuals

    # ----- used by `harmis.prepare --list-file / --only` (GitHub Actions) -----
    def needed_pictures(self, script):
        """Every picture a script needs, as ["scene:<name>", "character:<id>", ...]."""
        items = []
        for line in script["lines"]:
            if line.get("scene") and f"scene:{line['scene']}" not in items:
                items.append(f"scene:{line['scene']}")
        for character in script["characters"]:
            items.append(f"character:{character['id']}")
        if script["narrator"].get("id"):
            items.append(f"character:{script['narrator']['id']}")
        return items

    def is_ready(self, item):
        """True if a picture exists already (your own, or cached from the same prompt)."""
        kind, name = item.split(":", 1)
        if kind == "character":
            data = self.characters[name]
            folder = os.path.join(CHARACTER_DIR, name)
            custom = os.path.join(folder, "custom.png")
            png, meta = os.path.join(folder, f"{self.style}.png"), os.path.join(folder, f"{self.style}.json")
            if os.path.exists(custom):
                png = custom
            elif _load_cached(png, meta, character_prompt(data, self.style)) is None:
                return False
            # The picture exists; are its lip-movement variants made too?
            if not (data.get("mouth_box") and data.get("eyes_box")):
                return False
            return lipsync.load_variants(png, [float(v) for v in data["mouth_box"]],
                                         [float(v) for v in data["eyes_box"]]) is not None
        else:
            if os.path.exists(os.path.join(BACKGROUND_DIR, f"{name}.png")):
                return True
            if name not in self.scenes:
                return True  # unknown scene: nothing to make
            base = os.path.join(BACKGROUND_DIR, f"{name}__{self.style}{CACHE_SUFFIX[self.fmt]}")
            png, meta = base + ".png", base + ".json"
            prompt = background_prompt(self.scenes[name], self.style,
                                       CONFIG["genres"][self.genre].get("mood", ""), self.fmt)
        return _load_cached(png, meta, prompt) is not None

    def make_picture(self, item):
        """Get or make one picture ("scene:<name>" or "character:<id>")."""
        kind, name = item.split(":", 1)
        if kind == "character":
            data = self.characters[name]
            return self.character_frames(data, self.character_image(data))
        return self.background_image(name)
