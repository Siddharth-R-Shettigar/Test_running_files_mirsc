"""
Production hybrid OCR engine.
Local engines (EasyOCR / PaddleOCR) for speed + Groq Qwen3.6-27B vision for accuracy & multilingual.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("kavach.ocr")

# ---------------------------------------------------------------------------
# Config (env overrides)
# ---------------------------------------------------------------------------
OCR_BACKENDS = os.getenv("KAVACH_OCR_BACKENDS", "easyocr,paddle,qwen").lower().split(",")
OCR_LANGS = os.getenv("KAVACH_OCR_LANGS", "en,hi,mr,bn,ta,te,kn,gu,pa").split(",")
QWEN_MODEL = os.getenv("KAVACH_QWEN_MODEL", "qwen/qwen3.6-27b")
GROQ_TIMEOUT = float(os.getenv("KAVACH_GROQ_TIMEOUT", "25"))
LOCAL_TIMEOUT = float(os.getenv("KAVACH_LOCAL_OCR_TIMEOUT", "20"))
MAX_IMAGE_SIDE = int(os.getenv("KAVACH_OCR_MAX_SIDE", "2048"))
USE_GPU = os.getenv("KAVACH_OCR_GPU", "0") == "1"

# ---------------------------------------------------------------------------
# Lazy loaders
# ---------------------------------------------------------------------------
_easy_reader = None
_paddle_ocr = None
_groq_client = None


def _get_easyocr():
    global _easy_reader
    if _easy_reader is None:
        import easyocr
        langs = [l.strip() for l in OCR_LANGS if l.strip()]
        _easy_reader = easyocr.Reader(langs, gpu=USE_GPU, verbose=False)
    return _easy_reader


def _get_paddle():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",          # multi-lang via model switch if needed
                use_gpu=USE_GPU,
                show_log=False,
            )
        except Exception as e:
            logger.warning("PaddleOCR unavailable: %s", e)
            _paddle_ocr = False
    return _paddle_ocr if _paddle_ocr is not False else None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY missing – Qwen OCR disabled")
            _groq_client = False
            return None
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
    return _groq_client if _groq_client is not False else None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------
def _load_and_preprocess(image_path: str) -> Tuple[np.ndarray, np.ndarray]:
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    h, w = img.shape[:2]
    scale = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # mild denoise + adaptive threshold for local engines
    denoised = cv2.fastNlMeansDenoising(gray, None, 8, 7, 21)
    thresh = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8
    )
    return img, thresh


def _image_to_b64(path: str, max_side: int = 1600) -> str:
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"Cannot read {path}")
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return base64.b64encode(buf).decode("ascii")


# ---------------------------------------------------------------------------
# Local engines
# ---------------------------------------------------------------------------
def _run_easyocr(thresh: np.ndarray) -> List[Dict[str, Any]]:
    reader = _get_easyocr()
    detections = reader.readtext(thresh, detail=1, paragraph=False)
    fields = []
    for bbox, text, conf in detections:
        t = (text or "").strip()
        if t:
            fields.append({
                "text": t,
                "confidence": round(float(conf), 4),
                "source": "easyocr",
                "bbox": [[float(x), float(y)] for x, y in bbox],
            })
    return fields


def _run_paddle(img: np.ndarray) -> List[Dict[str, Any]]:
    ocr = _get_paddle()
    if ocr is None:
        return []
    result = ocr.ocr(img, cls=True)
    fields = []
    if not result:
        return fields
    for page in result:
        if not page:
            continue
        for line in page:
            if not line or len(line) < 2:
                continue
            bbox, (text, conf) = line
            t = (text or "").strip()
            if t:
                fields.append({
                    "text": t,
                    "confidence": round(float(conf), 4),
                    "source": "paddleocr",
                    "bbox": [[float(x), float(y)] for x, y in bbox],
                })
    return fields


# ---------------------------------------------------------------------------
# Qwen vision (Groq)
# ---------------------------------------------------------------------------
_QWEN_SYSTEM = """You are an expert document OCR system for identity documents (passports, national IDs, visas, driving licences).
Extract ALL visible text exactly as printed. Preserve original language (Hindi, Tamil, etc.).
Return ONLY valid JSON with this schema:
{
  "full_text": "concatenated readable text",
  "lines": ["line1", "line2", ...],
  "mrz_candidates": ["possible MRZ lines if any"],
  "language_hint": "en|hi|..."
}
Do not invent text. If a region is unreadable mark it as [ILLEGIBLE].
"""


def _run_qwen(image_path: str) -> Dict[str, Any]:
    client = _get_groq()
    if client is None:
        return {"fields": [], "mrz_lines": [], "error": "no_groq"}

    b64 = _image_to_b64(image_path)
    try:
        resp = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": _QWEN_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Perform precise OCR on this identity document image."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=4096,
            response_format={"type": "json_object"},
            timeout=GROQ_TIMEOUT,
        )
        raw = resp.choices[0].message.content or "{}"
        import json
        data = json.loads(raw)
    except Exception as e:
        logger.warning("Qwen OCR failed: %s", e)
        return {"fields": [], "mrz_lines": [], "error": str(e)}

    fields = []
    for line in data.get("lines") or []:
        t = str(line).strip()
        if t:
            fields.append({"text": t, "confidence": 0.92, "source": "qwen"})
    mrz = [str(x).strip() for x in (data.get("mrz_candidates") or []) if x]
    return {
        "fields": fields,
        "mrz_lines": mrz,
        "full_text": data.get("full_text", ""),
        "language_hint": data.get("language_hint"),
    }


# ---------------------------------------------------------------------------
# Fusion & public API
# ---------------------------------------------------------------------------
def _merge_fields(*lists: List[Dict]) -> List[Dict]:
    seen = set()
    merged = []
    for lst in lists:
        for f in lst:
            key = re.sub(r"\s+", " ", f["text"].strip().lower())
            if key and key not in seen:
                seen.add(key)
                merged.append(f)
    return merged


def _detect_mrz_lines(fields: List[Dict], qwen_mrz: List[str]) -> List[str]:
    candidates = list(qwen_mrz)
    for f in fields:
        t = f["text"].strip().upper().replace(" ", "")
        if len(t) >= 28 and ("<" in t or t.startswith("P") or sum(c.isdigit() for c in t) >= 8):
            candidates.append(t)
    # unique preserve order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def extract_text(image_path: str) -> Dict[str, Any]:
    """
    Main entry point used by kavach_engine.
    Returns a stable schema that every downstream module expects.
    """
    start = time.time()
    result: Dict[str, Any] = {
        "status": "passed",
        "score": 0.15,
        "confidence": "high",
        "explanation": "Hybrid OCR completed",
        "fields": [],
        "mrz_lines": [],
        "engines_used": [],
        "elapsed_ms": 0,
    }

    if not image_path or not Path(image_path).is_file():
        result.update(status="failed", confidence="low",
                      explanation=f"Image not found: {image_path}")
        return result

    try:
        color, thresh = _load_and_preprocess(image_path)
    except Exception as e:
        result.update(status="failed", confidence="low", explanation=str(e))
        return result

    local_fields: List[Dict] = []
    qwen_data: Dict = {"fields": [], "mrz_lines": []}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        if "easyocr" in OCR_BACKENDS:
            futures["easy"] = pool.submit(_run_easyocr, thresh)
        if "paddle" in OCR_BACKENDS:
            futures["paddle"] = pool.submit(_run_paddle, color)
        if "qwen" in OCR_BACKENDS:
            futures["qwen"] = pool.submit(_run_qwen, image_path)

        for name, fut in futures.items():
            try:
                data = fut.result(timeout=LOCAL_TIMEOUT if name != "qwen" else GROQ_TIMEOUT)
                if name == "qwen":
                    qwen_data = data
                    result["engines_used"].append("qwen")
                else:
                    local_fields.extend(data)
                    result["engines_used"].append(name)
            except FuturesTimeout:
                logger.warning("%s timed out", name)
            except Exception as e:
                logger.warning("%s failed: %s", name, e)

    all_fields = _merge_fields(local_fields, qwen_data.get("fields", []))
    mrz_lines = _detect_mrz_lines(all_fields, qwen_data.get("mrz_lines", []))

    result["fields"] = all_fields
    result["mrz_lines"] = mrz_lines
    result["elapsed_ms"] = int((time.time() - start) * 1000)

    if not all_fields and not mrz_lines:
        result.update(
            status="failed",
            confidence="low",
            score=0.8,
            explanation="No text extracted by any engine",
        )
    elif "qwen" in result["engines_used"] and len(all_fields) > 5:
        result["confidence"] = "high"
        result["score"] = 0.1
    else:
        result["confidence"] = "medium"
        result["score"] = 0.25

    return result