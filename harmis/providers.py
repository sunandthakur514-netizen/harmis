"""Image providers: free AI services that turn a text prompt into a picture.

Every provider has the same small interface:

    provider.name                 -> "pollinations"
    provider.available()          -> (True, "") or (False, "why not")
    provider.generate(prompt, width, height, seed) -> PIL.Image  (raises on failure)

ImageChain tries the providers in the order from config.yaml, each with a
timeout and retries. If all of them fail it returns None and the caller draws
the simple shape style instead, so a video is always produced.
"""

import base64
import io
import os
import time
import urllib.parse

import requests
from PIL import Image

from .config import CONFIG


class ProviderError(Exception):
    """A provider could not make the picture."""


def _image_from_bytes(data):
    """Open image bytes, raising ProviderError if they are not a real picture."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image.convert("RGB")
    except Exception as error:
        raise ProviderError(f"response was not an image ({error})")


class ImageProvider:
    name = "base"

    def __init__(self, settings):
        self.settings = settings
        self.timeout = settings.get("timeout", 120)
        self.retries = settings.get("retries", 1)

    def available(self):
        return True, ""

    def generate(self, prompt, width, height, seed, negative=""):
        raise NotImplementedError


class PollinationsProvider(ImageProvider):
    """Pollinations.ai: free, no key needed."""
    name = "pollinations"

    def generate(self, prompt, width, height, seed, negative=""):
        url = self.settings["url"].format(prompt=urllib.parse.quote(prompt, safe=""))
        params = {"width": width, "height": height, "seed": seed, "nologo": "true",
                  "safe": "true", "model": self.settings.get("model", "flux")}
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("image/"):
            raise ProviderError(f"unexpected content type {response.headers.get('content-type')}")
        return _image_from_bytes(response.content)


class GeminiProvider(ImageProvider):
    """Google Gemini image generation (needs GEMINI_API_KEY)."""
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    RATIOS = {"1:1": 1.0, "3:4": 0.75, "9:16": 0.5625, "4:3": 1.333, "16:9": 1.778}

    def available(self):
        if not os.environ.get("GEMINI_API_KEY"):
            return False, "no GEMINI_API_KEY"
        return True, ""

    def generate(self, prompt, width, height, seed, negative=""):
        # Gemini takes an aspect ratio instead of a size; pick the closest one.
        ratio = min(self.RATIOS, key=lambda r: abs(self.RATIOS[r] - width / height))
        response = requests.post(
            self.URL.format(model=self.settings["model"]),
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={
                "contents": [{"parts": [{"text": prompt + (f". Avoid: {negative}" if negative else "")}]}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio}},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        for part in response.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return _image_from_bytes(base64.b64decode(part["inlineData"]["data"]))
        raise ProviderError("Gemini returned no image")


class HuggingFaceProvider(ImageProvider):
    """Hugging Face free inference API (needs HF_TOKEN)."""
    name = "huggingface"

    def available(self):
        if not os.environ.get("HF_TOKEN"):
            return False, "no HF_TOKEN"
        return True, ""

    def generate(self, prompt, width, height, seed, negative=""):
        response = requests.post(
            self.settings["url"].format(model=self.settings["model"]),
            headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}", "Accept": "image/png"},
            json={"inputs": prompt, "parameters": {"width": width, "height": height, "seed": seed,
                                                   "negative_prompt": negative}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return _image_from_bytes(response.content)


PROVIDERS = {cls.name: cls for cls in (PollinationsProvider, GeminiProvider, HuggingFaceProvider)}


def _short_error(error):
    """A one-line, key-free description of an error."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"HTTP {error.response.status_code}"
    return f"{type(error).__name__}: {str(error)[:80]}"


class ImageChain:
    """Tries each provider in turn. Remembers which provider made each picture."""

    def __init__(self, order=None):
        settings = CONFIG["image_providers"]
        self.order = settings["order"] if order is None else order
        self.disable_after = settings.get("disable_after_failures", 2)
        self.providers = []
        for name in self.order:
            if name not in PROVIDERS:
                print(f"[images] Unknown provider '{name}' in config, skipping it.")
                continue
            provider = PROVIDERS[name](settings.get(name, {}))
            ok, reason = provider.available()
            if ok:
                self.providers.append(provider)
            else:
                print(f"[images] {name}: skipped ({reason})")
        self.failures = {p.name: 0 for p in self.providers}
        self.used = {}  # label -> provider name (or "shapes")

    def _try(self, provider, prompt, width, height, seed, negative):
        """One provider with retries. Returns an image or raises the last error."""
        last_error = None
        for attempt in range(provider.retries + 1):
            try:
                return provider.generate(prompt, width, height, seed, negative)
            except Exception as error:
                last_error = error
                # A wrong key or a blocked request will not get better by retrying.
                if isinstance(error, requests.HTTPError) and error.response is not None \
                        and error.response.status_code in (400, 401, 403, 404):
                    break
                if attempt < provider.retries:
                    time.sleep(2 ** attempt)
        raise last_error

    def generate(self, prompt, width, height, seed, label, negative=""):
        """Return (image, provider name) or (None, "shapes") if every provider failed."""
        for provider in self.providers:
            if self.failures[provider.name] >= self.disable_after:
                continue  # this provider keeps failing in this run
            try:
                image = self._try(provider, prompt, width, height, seed, negative)
                self.failures[provider.name] = 0
                self.used[label] = provider.name
                print(f"[images] {label}: made by {provider.name}")
                return image, provider.name
            except Exception as error:
                self.failures[provider.name] += 1
                note = " (giving up on it for this run)" if self.failures[provider.name] >= self.disable_after else ""
                print(f"[images] {label}: {provider.name} failed ({_short_error(error)}){note}")
        self.used[label] = "shapes"
        reason = "no provider worked" if self.providers else "no image providers enabled"
        print(f"[images] {label}: {reason}, using the simple shape style")
        return None, "shapes"
