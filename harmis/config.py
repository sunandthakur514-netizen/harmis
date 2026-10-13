"""Load config.yaml (in the project folder).

If the file is missing or a setting is left out, the built-in defaults below
are used, so the tool still works.
"""

import copy
import os

import yaml

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("HARMIS_CONFIG", os.path.join(PROJECT_DIR, "config.yaml"))

# Minimal defaults; config.yaml has the full, commented version.
DEFAULTS = {
    "defaults": {"lang": "hindi", "style": "3d_cartoon", "output_dir": "output"},
    "video": {"fps": 30, "min_seconds": 30, "max_seconds": 60, "crossfade_seconds": 0.6},
    "image_providers": {
        "order": ["pollinations", "gemini", "huggingface"],
        "disable_after_failures": 2,
        "pollinations": {"url": "https://image.pollinations.ai/prompt/{prompt}", "model": "flux",
                         "timeout": 120, "retries": 2},
        "gemini": {"model": "gemini-2.5-flash-image", "timeout": 120, "retries": 1},
        "huggingface": {"url": "https://router.huggingface.co/hf-inference/models/{model}",
                        "model": "black-forest-labs/FLUX.1-schnell", "timeout": 120, "retries": 2},
    },
    "background_removal": {"rembg_model": "u2net"},
    "styles": {
        "storybook": "children's storybook illustration, soft watercolour painting, warm colours",
        "3d_cartoon": "3D animated movie style render, cute stylised proportions, soft lighting, vibrant colours",
        "anime": "anime style illustration, clean line art, cel shading, bright colours",
    },
    "safety": {
        "always_add": "kid-friendly, wholesome, family-safe, non-violent, no gore, no weapons, "
                      "original character design, no text, no logo, no watermark",
        "negative": "nsfw, gore, blood, violence, weapon, text, watermark, logo",
        "blocked_words": [],
    },
    "genres": {
        "kids_story": {"style": "3d_cartoon", "narrator": "narrator", "narrator_voice": {"rate": -5, "pitch": 0},
                       "default_scene": "village_day", "mood": "bright cheerful daylight"},
        "kids_rhyme": {"style": "3d_cartoon", "narrator": "narrator", "narrator_voice": {"rate": -5, "pitch": 8},
                       "default_scene": "village_day", "mood": "bright cheerful colours"},
        "comedy": {"style": "3d_cartoon", "narrator": "narrator_comedy", "narrator_voice": {"rate": 5, "pitch": 0},
                   "default_scene": "gali", "mood": "bright sunny colours"},
        "horror": {"style": "storybook", "narrator": "narrator_horror", "narrator_voice": {"rate": -15, "pitch": -10},
                   "default_scene": "haveli_night", "mood": "dark moonlit night, mildly spooky, no gore"},
    },
}


def _merge(base, extra):
    """Copy of base with values from extra laid on top (nested dicts are merged)."""
    result = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path=CONFIG_FILE):
    """Return the settings as a dict."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            return _merge(DEFAULTS, yaml.safe_load(file))
    print(f"[config] {path} not found, using built-in defaults.")
    return copy.deepcopy(DEFAULTS)


# Loaded once when HARMIS starts.
CONFIG = load_config()
