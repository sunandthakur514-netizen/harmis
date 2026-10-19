"""Image providers: free AI services that turn a text prompt into a picture.

Every provider has the same small interface:

    provider.name                 -> "pollinations"
    provider.available()          -> (True, "") or (False, "why not")
    provider.generate(prompt, width, height, seed) -> PIL.Image  (raises on failure)

ImageChain tries the providers in the order from config.yaml. Each provider:
  * sends strictly one request at a time, waiting `delay_seconds` between requests
    (free services like Pollinations limit how fast you may ask),
  * waits `timeout` seconds for a picture,
  * on a rate limit (HTTP 429), a timeout or a busy server (502/503/504) waits
    and tries again with growing pauses, up to `tries` times.
Rate limits never switch a provider off; only repeated real errors do. A
"payment required" answer (HTTP 402) or a used-up daily free quota switches it
off at once for this run. Gemini also gets the characters' own pictures as
references, so they look the same in every scene.

local_sd runs Stable Diffusion Turbo on your own computer's CPU: no limits, no
key, but it needs the optional packages in requirements-local-sd.txt.
If all providers fail the caller draws the simple shape style instead, so a
video is always produced.
"""

import base64
import importlib.util
import io
import os
import threading
import time
import urllib.parse

import requests
from PIL import Image, ImageOps

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
        self.tries = max(1, int(settings.get("tries", settings.get("retries", 1) + 1)))
        self.delay = float(settings.get("delay_seconds", 0))      # pause between requests
        self.backoff = float(settings.get("backoff_seconds", 10))  # first wait after a rate limit
        self._lock = threading.Lock()  # strictly one request at a time
        self._last_request = 0.0

    def wait_turn(self):
        """Sleep until `delay_seconds` have passed since the previous request."""
        wait = self._last_request + self.delay - time.time()
        if wait > 0:
            print(f"[images]   waiting {wait:.0f}s before the next {self.name} request ...")
            time.sleep(wait)
        self._last_request = time.time()

    def available(self):
        return True, ""

    def generate(self, prompt, width, height, seed, negative="", compact=None, references=None):
        """references: [(name, PIL image)] pictures of the characters, for models that can use them.
        compact: a short version of the prompt for models that read only ~77 tokens."""
        raise NotImplementedError


class PollinationsProvider(ImageProvider):
    """Pollinations.ai: free, no key needed. POLLINATIONS_TOKEN (optional) gives higher limits."""
    name = "pollinations"

    def generate(self, prompt, width, height, seed, negative="", compact=None, references=None):
        url = self.settings["url"].format(prompt=urllib.parse.quote(prompt, safe=""))
        params = {"width": width, "height": height, "seed": seed, "nologo": "true",
                  "safe": "true", "model": self.settings.get("model", "flux")}
        headers = {}
        if os.environ.get("POLLINATIONS_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['POLLINATIONS_TOKEN']}"
        response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
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

    def generate(self, prompt, width, height, seed, negative="", compact=None, references=None):
        # Gemini takes an aspect ratio instead of a size; pick the closest one.
        ratio = min(self.RATIOS, key=lambda r: abs(self.RATIOS[r] - width / height))
        parts = [{"text": prompt + (f". Avoid: {negative}" if negative else "")}]
        for name, picture in references or []:  # the characters' own pictures keep them looking the same
            buffer = io.BytesIO()
            flat = Image.new("RGB", picture.size, "white")
            flat.paste(picture, mask=picture.getchannel("A") if picture.mode == "RGBA" else None)
            flat.thumbnail((512, 512))
            flat.save(buffer, "JPEG", quality=88)
            parts += [{"text": f"Reference picture of {name} (draw {name} exactly like this):"},
                      {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buffer.getvalue()).decode()}}]
        response = requests.post(
            self.URL.format(model=self.settings["model"]),
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={
                "contents": [{"parts": parts}],
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

    def generate(self, prompt, width, height, seed, negative="", compact=None, references=None):
        response = requests.post(
            self.settings["url"].format(model=self.settings["model"]),
            headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}", "Accept": "image/png"},
            json={"inputs": prompt, "parameters": {"width": width, "height": height, "seed": seed,
                                                   "negative_prompt": negative}},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return _image_from_bytes(response.content)


class ModelUnavailable(Exception):
    """The local model could not be loaded (not downloaded yet and no internet, out of memory, ...)."""


class LocalSDProvider(ImageProvider):
    """Stable Diffusion Turbo on your own CPU: free and unlimited (optional packages needed).

    The model (about 2.5 GB) is downloaded once from Hugging Face and cached. It
    makes a small picture (512 px on the short side) in 1-4 steps, which is then
    enlarged with Pillow (LANCZOS) to the size HARMIS needs.
    """
    name = "local_sd"
    _pipe = None  # loaded once per run and shared

    def available(self):
        missing = [m for m in ("torch", "diffusers", "transformers") if importlib.util.find_spec(m) is None]
        if missing:
            return False, (f"{', '.join(missing)} not installed; to use it: "
                           "pip install -r requirements-local-sd.txt (see README)")
        return True, ""

    def _load(self):
        if LocalSDProvider._pipe is not None:
            return LocalSDProvider._pipe
        import torch
        from diffusers import AutoPipelineForText2Image

        torch.set_num_threads(int(self.settings.get("threads") or os.cpu_count() or 2))
        model = self.settings.get("model", "stabilityai/sd-turbo")
        cache_dir = self.settings.get("cache_dir") or None
        print(f"[images] local_sd: loading {model} on the CPU "
              "(the first time this downloads about 2.5 GB, then it is cached) ...")
        start = time.time()
        pipe, last_error = None, None
        for variant in dict.fromkeys([self.settings.get("variant") or None, None]):  # fp16 files: half the download
            try:
                pipe = AutoPipelineForText2Image.from_pretrained(
                    model, torch_dtype=torch.float32, variant=variant, cache_dir=cache_dir)
                break
            except Exception as error:
                last_error = error
        if pipe is None:
            raise ModelUnavailable(f"could not load {model}: {' '.join(str(last_error).split())[:150]}")
        pipe = pipe.to("cpu")
        pipe.set_progress_bar_config(disable=True)
        LocalSDProvider._pipe = pipe
        print(f"[images] local_sd: model ready in {time.time() - start:.0f}s")
        return pipe

    def small_size(self, width, height):
        """512 on the short side, the long side following the aspect ratio (multiple of 64)."""
        base = int(self.settings.get("size", 512))
        longest = int(self.settings.get("max_side", 768))
        if width == height:
            return base, base
        long_side = min(longest, max(base, round(base * max(width, height) / min(width, height) / 64) * 64))
        return (base, long_side) if width < height else (long_side, base)

    def generate(self, prompt, width, height, seed, negative="", compact=None, references=None):
        import torch
        pipe = self._load()
        w, h = self.small_size(width, height)
        image = pipe(
            prompt=compact or prompt,
            num_inference_steps=max(1, min(4, int(self.settings.get("steps", 2)))),
            guidance_scale=0.0,  # SD Turbo is made to run without guidance
            width=w, height=h,
            generator=torch.Generator("cpu").manual_seed(int(seed)),
        ).images[0]
        return ImageOps.fit(image.convert("RGB"), (width, height), Image.LANCZOS)


PROVIDERS = {cls.name: cls for cls in (PollinationsProvider, LocalSDProvider, GeminiProvider, HuggingFaceProvider)}


RATE_LIMIT, BUSY, FATAL, OTHER = "rate limited", "busy", "fatal", "error"
PAYMENT, UNAVAILABLE = "payment required", "unavailable"  # switch the provider off for this run
QUOTA = "out of free quota"  # daily quota used up (or none on the free tier): off for this run


def quota_exhausted(response):
    """A 429 that will not go away by waiting: the daily (or zero) free quota is used up."""
    text = response.text or ""
    return "PerDay" in text or "limit: 0" in text or "quota_limit_value\": \"0" in text


def classify(error):
    """What kind of failure is this? Decides whether to wait, retry or give up."""
    if isinstance(error, ModelUnavailable):
        return UNAVAILABLE
    if isinstance(error, requests.Timeout):
        return RATE_LIMIT  # free services time out when they are overloaded
    if isinstance(error, requests.HTTPError) and error.response is not None:
        code = error.response.status_code
        if code == 429:
            return QUOTA if quota_exhausted(error.response) else RATE_LIMIT
        if code in (502, 503, 504):
            return BUSY
        if code == 402:
            return PAYMENT
        if code in (400, 401, 403, 404):
            return FATAL  # wrong key, blocked or bad request: retrying will not help
    return OTHER


def describe(error):
    """One line with the HTTP status code and error text (never the API key)."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        response = error.response
        text = " ".join((response.text or "").split())[:120]
        return f"HTTP {response.status_code} {response.reason or ''} {text}".strip()
    return f"{type(error).__name__}: {' '.join(str(error).split())[:120]}"


def retry_after(error):
    """Seconds asked for by a Retry-After header, if any."""
    try:
        return float(error.response.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return None


class ImageChain:
    """Tries each provider in turn. Remembers which provider made each picture."""

    def __init__(self, order=None):
        settings = CONFIG["image_providers"]
        self.order = settings["order"] if order is None else order
        self.disable_after = settings.get("disable_after_failures", 3)
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
        self.failures = {p.name: 0 for p in self.providers}  # real errors in a row (not rate limits)
        self.used = {}  # label -> provider name (or "shapes")

    def _try(self, provider, prompt, width, height, seed, negative, label, compact, references=None):
        """One provider, up to `tries` attempts. Returns (image, seconds), or raises ProviderFailed."""
        for attempt in range(1, provider.tries + 1):
            with provider._lock:
                provider.wait_turn()
                start = time.time()
                try:
                    return (provider.generate(prompt, width, height, seed, negative, compact, references),
                            time.time() - start)
                except Exception as caught:
                    error, kind = caught, classify(caught)
            print(f"[images] {label}: {provider.name} try {attempt}/{provider.tries} failed after "
                  f"{time.time() - start:.1f}s ({kind}): {describe(error)}")
            if kind in (FATAL, PAYMENT, UNAVAILABLE, QUOTA) or attempt == provider.tries:
                raise ProviderFailed(error, kind)
            if kind in (RATE_LIMIT, BUSY):
                wait = retry_after(error) or provider.backoff * 2 ** (attempt - 1)
                wait = min(max(wait, provider.delay), 300)
            else:
                wait = max(2 * attempt, provider.delay)
            print(f"[images]   waiting {wait:.0f}s, then trying again ...")
            time.sleep(wait)

    def generate(self, prompt, width, height, seed, label, negative="", compact=None, references=None):
        """Return (image, provider name) or (None, "shapes") if every provider failed."""
        for provider in self.providers:
            if self.failures[provider.name] >= self.disable_after:
                continue  # switched off for this run
            try:
                image, seconds = self._try(provider, prompt, width, height, seed, negative, label, compact, references)
                self.failures[provider.name] = 0
                self.used[label] = provider.name
                print(f"[images] {label}: made by {provider.name} in {seconds:.1f}s")
                return image, provider.name
            except ProviderFailed as failed:
                if failed.kind in (RATE_LIMIT, BUSY):
                    # Only busy: keep using this provider for the next pictures.
                    print(f"[images] {label}: {provider.name} still {failed.kind} after "
                          f"{provider.tries} tries; it stays on for the next pictures")
                elif failed.kind in (PAYMENT, UNAVAILABLE, QUOTA):
                    self.failures[provider.name] = self.disable_after
                    why = {PAYMENT: "asks for payment (HTTP 402)", QUOTA: "has no free quota left today"}.get(
                        failed.kind, "cannot be used")
                    print(f"[images] {provider.name} {why}: skipping it for the rest of this run")
                else:
                    self.failures[provider.name] += 1
                    if self.failures[provider.name] >= self.disable_after:
                        print(f"[images] {provider.name}: {self.failures[provider.name]} errors in a row, "
                              "not asking it again in this run")
        self.used[label] = "shapes"
        reason = "no provider worked" if self.providers else "no image providers enabled"
        print(f"[images] {label}: {reason}, using the simple shape style")
        return None, "shapes"


class ProviderFailed(Exception):
    def __init__(self, error, kind):
        super().__init__(describe(error))
        self.error, self.kind = error, kind
