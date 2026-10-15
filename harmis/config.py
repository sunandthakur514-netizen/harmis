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
    "video": {"crossfade_seconds": 0.6, "chunk_seconds": 60},
    "formats": {
        "short": {"width": 1080, "height": 1920, "fps": 30, "min_seconds": 30, "max_seconds": 60},
        "long": {"width": 1920, "height": 1080, "fps": 24, "min_seconds": 300, "max_seconds": 420,
                 "intro_seconds": 4, "outro_seconds": 7},
    },
    "image_providers": {
        "order": ["pollinations", "local_sd", "gemini", "huggingface"],
        "disable_after_failures": 3,
        "pollinations": {"url": "https://image.pollinations.ai/prompt/{prompt}", "model": "flux",
                         "timeout": 120, "tries": 4, "delay_seconds": 15, "backoff_seconds": 20},
        "local_sd": {"model": "stabilityai/sd-turbo", "variant": "fp16", "steps": 2, "size": 512,
                     "max_side": 768, "threads": 0, "cache_dir": None, "tries": 1, "delay_seconds": 0,
                     "variant_steps": 4},
        "gemini": {"model": "gemini-2.5-flash-image", "timeout": 120, "tries": 3,
                   "delay_seconds": 5, "backoff_seconds": 20},
        "huggingface": {"url": "https://router.huggingface.co/hf-inference/models/{model}",
                        "model": "black-forest-labs/FLUX.1-schnell", "timeout": 120, "tries": 3,
                        "delay_seconds": 5, "backoff_seconds": 20},
    },
    "background_removal": {"rembg_model": "u2net"},
    "publish": {
        "channel_name": "Kahani Khazana",
        "youtube": {"privacy": "private", "category_id": "27", "language": "hi", "thumbnail_for_long": True},
        "instagram": {"graph_api": "https://graph.facebook.com/v21.0", "share_to_feed": True,
                      "poll_seconds": 10, "max_wait_seconds": 900},
        "github": {"api": "https://api.github.com", "uploads": "https://uploads.github.com"},
        "hashtags": {"kids_story": ["#hindikahani", "#moralstories", "#kidsstories"], "always": ["#KahaniKhazana", "#hindi"],
                     "shorts": ["#shorts"], "reels": ["#reels"]},
    },
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
