"""vision_llm.py - ask Groq or Gemini to read an image and return JSON."""
import base64
import io
import json
import os

import requests
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GEMINI_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")


def _keys(*names):
    out = []
    for n in names:
        for part in (os.getenv(n) or "").split(","):
            p = part.strip()
            if p and p not in out:
                out.append(p)
    return out


def _jpeg_b64(img, max_side, quality=88):
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def prepare_images(path):
    """Return [full page, magnified bottom crop]. The MRZ is at the bottom."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    out = [_jpeg_b64(im, 1600)]
    w, h = im.size
    crop = im.crop((0, int(h * 0.6), w, h))
    if crop.width < 1600:
        crop = crop.resize((1600, int(crop.height * 1600 / crop.width)), Image.LANCZOS)
    out.append(_jpeg_b64(crop, 2000))
    return out


def _parse_json(text):
    text = (text or "").strip()
    s, e = text.find("{"), text.rfind("}") + 1
    if s == -1 or e == 0:
        raise ValueError("no JSON in the reply")
    return json.loads(text[s:e])


def _call_groq(prompt, images, key):
    content = [{"type": "text", "text": prompt}]
    for b in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}})
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": GROQ_VISION_MODEL,
            "temperature": 0,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}],
        },
        timeout=40,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    return _parse_json(r.json()["choices"][0]["message"]["content"])


def _call_gemini(prompt, images, key):
    parts = [{"text": prompt}] + [
        {"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in images
    ]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        },
        timeout=40,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    return _parse_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def vision_json(path, prompt):
    """Return (data_dict, provider_name). Try each provider in order."""
    images = prepare_images(path)
    order = [p.strip().lower() for p in os.getenv("VISION_PROVIDER_ORDER", "groq,gemini").split(",")]
    errors = []
    for provider in order:
        if provider == "groq":
            keys, fn = _keys("GROQ_API_KEYS", "GROQ_API_KEY"), _call_groq
        elif provider == "gemini":
            keys, fn = _keys("GEMINI_API_KEYS", "GEMINI_API_KEY"), _call_gemini
        else:
            continue
        if not keys:
            errors.append(f"{provider}: no key set")
            continue
        for key in keys[:2]:
            try:
                return fn(prompt, images, key), provider
            except Exception as e:
                errors.append(f"{provider}: {type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError(" | ".join(errors) or "no provider configured")


if __name__ == "__main__":
    import sys
    data, provider = vision_json(sys.argv[1], 'Reply with ONLY this JSON: {"ok": true, "text_seen": "<main text you can read>"}')
    print(provider, "->", json.dumps(data, indent=2))