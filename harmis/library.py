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
    <scene>__<style>.png  generated background (cached) + .json

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

from .config import CONFIG

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
CHARACTER_DIR = os.path.join(ASSETS, "characters")
BACKGROUND_DIR = os.path.join(ASSETS, "backgrounds")

# Sizes we ask the providers for (they are resized later).
CHARACTER_SIZE = (768, 1024)
BACKGROUND_SIZE = (768, 1344)  # 9:16


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
        "Standing, facing the viewer, friendly expression, whole body visible from head to feet, "
        "centered, single character only, plain pure white background, no other objects. "
        f"{CONFIG['safety']['always_add']}"
    )


def background_prompt(description, style, mood):
    return make_safe(
        f"{style_text(style)}. Background scenery only: {description.strip()}. {mood}. "
        "Empty scene with no people, no animals, no characters, tall vertical composition, "
        f"detailed environment. {CONFIG['safety']['always_add']}"
    )


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
    def __init__(self, chain, style, genre, refresh=False):
        self.chain = chain      # ImageChain (may have no providers at all)
        self.style = style
        self.genre = genre
        self.refresh = refresh  # True = ignore cached generated pictures
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
            print(f"[library] {data['id']}: using your custom.png")
            return image.convert("RGBA") if has_transparency(image.convert("RGBA")) else remove_background(image)

        prompt = character_prompt(data, self.style)
        png = os.path.join(folder, f"{self.style}.png")
        meta = os.path.join(folder, f"{self.style}.json")
        if not self.refresh:
            cached = _load_cached(png, meta, prompt)
            if cached is not None:
                print(f"[library] {data['id']}: using cached {self.style}.png")
                return cached.convert("RGBA")

        image, provider = self.chain.generate(prompt, *CHARACTER_SIZE, seed=data.get("seed", 1),
                                              label=f"character {data['id']}",
                                              negative=CONFIG["safety"]["negative"])
        if image is None:
            return None
        cut = remove_background(image)
        cut.save(png)
        _save_meta(meta, prompt, provider, self.style)
        return cut

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
            print(f"[library] scene {scene}: using your {scene}.png")
            return Image.open(custom).convert("RGB")
        if scene not in self.scenes:
            print(f"[library] Unknown scene '{scene}' (add it to scenes.yaml)")
            return None

        mood = CONFIG["genres"][self.genre].get("mood", "")
        prompt = background_prompt(self.scenes[scene], self.style, mood)
        png = os.path.join(BACKGROUND_DIR, f"{scene}__{self.style}.png")
        meta = os.path.join(BACKGROUND_DIR, f"{scene}__{self.style}.json")
        if not self.refresh:
            cached = _load_cached(png, meta, prompt)
            if cached is not None:
                print(f"[library] scene {scene}: using cached background")
                return cached.convert("RGB")

        image, provider = self.chain.generate(prompt, *BACKGROUND_SIZE, seed=zlib.crc32(scene.encode()) % 100000,
                                              label=f"scene {scene}", negative=CONFIG["safety"]["negative"])
        if image is None:
            return None
        image = ImageOps.fit(image, BACKGROUND_SIZE)
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
            visuals["characters"][character["name"]] = {"image": self.character_image(data),
                                                        "blink": self.blink_image(data)}
        narrator_id = script["narrator"].get("id")
        if narrator_id:
            visuals["narrator"] = self.character_image(self.characters[narrator_id])
        return visuals
