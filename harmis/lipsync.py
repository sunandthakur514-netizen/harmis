"""Mouth-flap lip movement and blinking for picture characters.

For every character picture HARMIS keeps a few variants next to it:
    <base>.png              mouth closed (the normal picture)
    <base>_mouth_half.png   mouth half open
    <base>_mouth_open.png   mouth open
    <base>_blink.png        eyes closed
    <base>_variants.json    how they were made (so they are only made once)

They are made with local_sd (Stable Diffusion Turbo) by repainting ONLY a small
area around the mouth or the eyes, with the same seed and description, so the
rest of the character stays exactly the same. If that is not possible, the
animation draws a simple cartoon mouth (a dark oval that opens with the voice)
over the mouth instead.

Where are the mouth and eyes? character.yaml can say it:
    mouth_box: [x, y, width, height]   # fractions of the picture (0..1)
    eyes_box:  [x, y, width, height]
If it does not, HARMIS looks for them (face detection, or the shape of the head
in the cut-out picture, or a default for humans / animals), writes what it found
into character.yaml, and you can edit the numbers there.
"""

import hashlib
import json
import os
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import CONFIG

# Defaults when nothing can be found (fractions of a full-body picture).
DEFAULT_BOXES = {
    "human": {"mouth": [0.44, 0.19, 0.12, 0.035], "eyes": [0.35, 0.125, 0.30, 0.05]},
    "animal": {"mouth": [0.42, 0.22, 0.16, 0.045], "eyes": [0.32, 0.13, 0.36, 0.06]},
}

# How each variant is made: (box, words added to the prompt, repaint strength).
VARIANTS = {
    "half": ("mouth", "mouth slightly open, talking", 0.55),
    "open": ("mouth", "mouth wide open, talking, singing", 0.75),
    "blink": ("eyes", "eyes closed, blinking, peaceful face", 0.65),
}


# ---------------------------------------------------------------------------
# Finding the mouth and eyes
# ---------------------------------------------------------------------------
def _round(box):
    return [round(float(v), 3) for v in box]


def detect_with_opencv(image):
    """Face detection with OpenCV's bundled face models (works on some cartoons)."""
    try:
        import cv2
    except ImportError:
        return None
    folder = getattr(getattr(cv2, "data", None), "haarcascades", "")
    models = [os.path.join(folder, name) for name in
              ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")]
    models = [m for m in models if os.path.exists(m)]
    if not models:
        return None  # this OpenCV build has no face models
    white = Image.new("RGB", image.size, "white")
    white.paste(image, (0, 0), image)
    gray = np.array(white.convert("L"))
    w, h = image.size
    top = gray[: h // 2]  # faces are in the upper half of a full-body picture
    faces = []
    for model in models:
        found = cv2.CascadeClassifier(model).detectMultiScale(top, 1.1, 4, minSize=(int(w * 0.12), int(w * 0.12)))
        faces += [tuple(f) for f in found if 0.12 * w <= f[2] <= 0.9 * w]
    if not faces:
        return None
    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    mouth = [(x + 0.30 * fw) / w, (y + 0.68 * fh) / h, 0.40 * fw / w, 0.16 * fh / h]
    eyes = [(x + 0.17 * fw) / w, (y + 0.32 * fh) / h, 0.66 * fw / w, 0.20 * fh / h]
    return _round(mouth), _round(eyes)


def detect_from_shape(image):
    """Find the head from the cut-out outline: the wide part above the narrow neck."""
    alpha = np.array(image.getchannel("A")) > 40
    h, w = alpha.shape
    rows = alpha.sum(axis=1).astype(float)
    filled = np.nonzero(rows)[0]
    if len(filled) == 0:
        return None
    top = filled[0]
    k = max(3, h // 100)
    rows = np.convolve(rows, np.ones(k) / k, mode="same")
    head_end = min(h, top + int(0.25 * h))
    region_end = min(h, top + int(0.48 * h))
    head_row = top + int(np.argmax(rows[top:head_end]))
    head_w = rows[head_row]
    if head_w < 4:
        return None
    neck = head_row + int(np.argmin(rows[head_row:region_end]))
    neck_w = rows[neck]
    after = rows[neck:min(h, neck + int(0.15 * h))].max() if neck < h else 0
    head_h = neck - top
    if not (neck_w < 0.8 * head_w and after > 1.15 * neck_w and 0.07 * h < head_h < 0.45 * h):
        return None  # no clear neck (animals on four legs, big costumes ...)
    cols = np.nonzero(alpha[top:neck].any(axis=0))[0]
    weights = alpha[top:neck].sum(axis=0)[cols]
    cx = float(np.average(cols, weights=weights))
    face_w = head_w
    # Cartoon faces: eyes a little below the middle of the head, mouth low on the face.
    mouth = [(cx - 0.14 * face_w) / w, (top + 0.72 * head_h) / h, 0.28 * face_w / w, 0.12 * head_h / h]
    eyes = [(cx - 0.30 * face_w) / w, (top + 0.44 * head_h) / h, 0.60 * face_w / w, 0.16 * head_h / h]
    return _round(mouth), _round(eyes)


def find_boxes(image, kind="human"):
    """Return (mouth_box, eyes_box, how they were found)."""
    for method, finder in (("face detection", detect_with_opencv), ("head shape", detect_from_shape)):
        try:
            found = finder(image)
        except Exception:
            found = None
        if found:
            return found[0], found[1], method
    boxes = DEFAULT_BOXES.get(kind, DEFAULT_BOXES["human"])
    return boxes["mouth"], boxes["eyes"], f"default for {'an' if kind == 'animal' else 'a'} {kind}"


def save_boxes_to_yaml(yaml_path, mouth, eyes, method):
    """Add mouth_box / eyes_box to character.yaml (keeping its comments)."""
    with open(yaml_path, encoding="utf-8") as file:
        text = file.read()
    if "mouth_box:" in text:
        return
    text = text.rstrip("\n") + (
        "\n# Mouth and eyes position as fractions of the picture: [x, y, width, height].\n"
        f"# Found automatically ({method}). Edit the numbers if the mouth moves in the wrong place\n"
        "# (then delete the *_mouth_*.png / *_blink.png / *_variants.json files to remake them).\n"
        f"mouth_box: {mouth}\n"
        f"eyes_box: {eyes}\n")
    with open(yaml_path, "w", encoding="utf-8") as file:
        file.write(text)


# ---------------------------------------------------------------------------
# Making the variants with local_sd (inpainting a small area)
# ---------------------------------------------------------------------------
def _pixels(box, size):
    w, h = size
    return box[0] * w, box[1] * h, box[2] * w, box[3] * h


def inpaint_area(inpaint, base, box, prompt, seed, strength, steps=4, grow=1.3):
    """Repaint the area `box` of an RGBA picture. Only that area changes."""
    import torch

    w, h = base.size
    bx, by, bw, bh = _pixels(box, base.size)
    cx, cy = bx + bw / 2, by + bh / 2
    side = int(min(max(bw, bh) * 3.2 + 32, w, h))
    side = max(side, min(96, w, h))
    left = int(min(max(0, cx - side / 2), w - side))
    top = int(min(max(0, cy - side / 2), h - side))
    crop_box = (left, top, left + side, top + side)

    white = Image.new("RGB", base.size, "white")
    white.paste(base, (0, 0), base)
    crop = white.crop(crop_box).resize((512, 512), Image.LANCZOS)
    scale = 512 / side
    mask = Image.new("L", (512, 512), 0)
    ex, ey = bw * grow / 2 * scale, bh * grow / 2 * scale
    mx, my = (cx - left) * scale, (cy - top) * scale
    ImageDraw.Draw(mask).ellipse([mx - ex, my - ey, mx + ex, my + ey], fill=255)

    result = inpaint(prompt=prompt, image=crop, mask_image=mask, strength=strength,
                     num_inference_steps=steps, guidance_scale=0.0, width=512, height=512,
                     generator=torch.Generator("cpu").manual_seed(int(seed))).images[0]
    result = result.convert("RGB").resize((side, side), Image.LANCZOS)

    # Paste back only the masked area, with soft edges; everything else (and the
    # outline / transparency) stays exactly as in the original picture.
    soft = mask.resize((side, side)).filter(ImageFilter.GaussianBlur(max(2, side // 40)))
    patch = result.convert("RGBA")
    patch.putalpha(base.crop(crop_box).getchannel("A"))
    out = base.copy()
    out.paste(patch, crop_box[:2], soft)
    return out


def area_changed(a, b, box, threshold=4.0):
    """Did the repaint actually change the area? (average colour difference)"""
    x, y, w, h = [int(v) for v in _pixels(box, a.size)]
    if w < 2 or h < 2:
        return False
    pa = np.asarray(a.convert("RGB").crop((x, y, x + w, y + h)), dtype=float)
    pb = np.asarray(b.convert("RGB").crop((x, y, x + w, y + h)), dtype=float)
    return float(np.abs(pa - pb).mean()) > threshold


def file_sha(path):
    with open(path, "rb") as file:
        return hashlib.sha1(file.read()).hexdigest()


def make_variants(pipe, base, base_path, mouth_box, eyes_box, prompt_core, seed, label):
    """Make and save the half / open / blink variants. Returns the info that was saved."""
    from diffusers import AutoPipelineForInpainting

    inpaint = AutoPipelineForInpainting.from_pipe(pipe)
    inpaint.set_progress_bar_config(disable=True)
    stem = os.path.splitext(base_path)[0]
    info = {"base_sha": file_sha(base_path), "mouth_box": mouth_box, "eyes_box": eyes_box,
            "mouth": "inpainted", "blink": "inpainted"}
    steps = int(CONFIG["image_providers"].get("local_sd", {}).get("variant_steps", 4))
    for name, (which, words, strength) in VARIANTS.items():
        box = mouth_box if which == "mouth" else eyes_box
        start = time.time()
        try:
            variant = inpaint_area(inpaint, base, box, f"{prompt_core}, {words}", seed, strength, steps)
            if not area_changed(base, variant, box):
                raise ValueError("the area did not change")
            variant.save(f"{stem}_{'mouth_' if which == 'mouth' else ''}{name}.png")
            print(f"[lipsync] {label}: {name} made by local_sd in {time.time() - start:.1f}s")
        except Exception as error:
            print(f"[lipsync] {label}: {name} failed ({type(error).__name__}: {str(error)[:80]})")
            info["mouth" if which == "mouth" else "blink"] = "drawn" if which == "mouth" else "none"
    if info["mouth"] == "drawn":  # do not mix a painted half-open mouth with a drawn one
        for name in ("half", "open"):
            if os.path.exists(f"{stem}_mouth_{name}.png"):
                os.remove(f"{stem}_mouth_{name}.png")
    with open(f"{stem}_variants.json", "w", encoding="utf-8") as file:
        json.dump(info, file, indent=2)
    return info


def load_variants(base_path, mouth_box, eyes_box):
    """Cached variants for this exact picture and boxes, or None."""
    stem = os.path.splitext(base_path)[0]
    try:
        with open(f"{stem}_variants.json", encoding="utf-8") as file:
            info = json.load(file)
    except (OSError, ValueError):
        return None
    if info.get("base_sha") != file_sha(base_path) or info.get("mouth_box") != mouth_box \
            or info.get("eyes_box") != eyes_box:
        return None
    frames = {}
    for key, path in (("half", f"{stem}_mouth_half.png"), ("open", f"{stem}_mouth_open.png"),
                      ("blink", f"{stem}_blink.png")):
        if os.path.exists(path):
            frames[key] = Image.open(path).convert("RGBA")
    return info, frames


# ---------------------------------------------------------------------------
# Drawn mouth (fallback) and mouth movement from the voice
# ---------------------------------------------------------------------------
def mouth_colours(image, mouth_box):
    """Lip colour (a darker shade of the skin around the mouth) and mouth inside colour."""
    x, y, w, h = [int(v) for v in _pixels(mouth_box, image.size)]
    area = np.asarray(image.crop((x, y, x + max(w, 2), y + max(h, 2))).convert("RGBA"))
    pixels = area[area[..., 3] > 128][:, :3]
    skin = np.median(pixels, axis=0) if len(pixels) else np.array([200, 150, 120])
    lip = tuple(int(c * 0.55) for c in skin)
    return lip, (95, 25, 35)


def draw_mouth(image, mouth_box, level, colours):
    """Draw an open cartoon mouth on a copy of the picture; level 0 (closed) to 1 (open)."""
    if level < 0.08:
        return image
    x, y, w, h = _pixels(mouth_box, image.size)
    cx, cy = x + w / 2, y + h / 2
    rw = w * (0.30 + 0.15 * level)
    rh = max(2.0, h * (0.25 + 1.1 * level))
    out = image.copy()
    lip, inside = colours
    ImageDraw.Draw(out).ellipse([cx - rw, cy - rh / 2, cx + rw, cy + rh / 2], fill=inside,
                                outline=lip, width=max(2, int(w * 0.06)))
    return out


def mouth_track(loudness, frames, fps, seed=0):
    """Per video frame: (state 0/1/2 = closed/half/open, smooth level 0..1).

    The voice loudness is looked at every ~80 ms and smoothed, with a little
    hysteresis, so the mouth does not flicker.
    """
    if loudness is None:  # silent clip: gentle pretend talking
        rng = np.random.default_rng(seed)
        loudness = np.clip(0.5 + 0.4 * np.sin(np.arange(frames) / fps * 11) + rng.normal(0, 0.1, frames), 0, 1)
    window = max(1, round(0.08 * fps))
    states, levels = np.zeros(frames, dtype=np.int8), np.zeros(frames, dtype=np.float32)
    smooth, state = 0.0, 0
    for start in range(0, frames, window):
        chunk = loudness[start:start + window]
        value = float(np.mean(chunk)) if len(chunk) else 0.0
        smooth = 0.6 * value + 0.4 * smooth
        if state == 2:
            state = 2 if smooth > 0.45 else (1 if smooth > 0.18 else 0)
        elif state == 1:
            state = 2 if smooth > 0.58 else (1 if smooth > 0.15 else 0)
        else:
            state = 2 if smooth > 0.58 else (1 if smooth > 0.24 else 0)
        states[start:start + window] = state
        levels[start:start + window] = smooth
    return states, levels


def blink_times(total, seed):
    """Start times of blinks, every 3 to 5 seconds."""
    rng = np.random.default_rng(seed)
    times, t = [], float(rng.uniform(1.0, 3.0))
    while t < total:
        times.append(t)
        t += float(rng.uniform(3.0, 5.0))
    return times
