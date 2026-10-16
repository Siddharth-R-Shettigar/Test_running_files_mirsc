"""
Production hybrid OCR engine.
Local engines (EasyOCR / PaddleOCR) for speed + Groq Qwen3.6-27B vision for accuracy & multilingual.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("kavach.ocr")

# ---------------------------------------------------------------------------
# Config (env overrides)
# ---------------------------------------------------------------------------
OCR_BACKENDS = os.getenv("KAVACH_OCR_BACKENDS", "easyocr,paddle,qwen").lower().split(",")
OCR_LANGS = [
    language.strip().lower()
    for language in os.getenv("KAVACH_OCR_LANGS", "en,hi,mr").split(",")
    if language.strip() and language.strip().lower() not in {"gu", "pa"}
]
QWEN_MODEL = os.getenv("KAVACH_QWEN_MODEL", "qwen/qwen3.8-27b")
GROQ_TIMEOUT = float(os.getenv("KAVACH_GROQ_TIMEOUT", "25"))
MAX_IMAGE_SIDE = int(os.getenv("KAVACH_OCR_MAX_SIDE", "2048"))
USE_GPU = os.getenv("KAVACH_OCR_GPU", "0") == "1"

# ---------------------------------------------------------------------------
# Lazy loaders
# ---------------------------------------------------------------------------
_easy_reader = None
_paddle_ocr = None
_groq_clients: Dict[str, Any] = {}
_groq_key_index = 0
_groq_key_lock = threading.Lock()
_groq_key_count = 0


def _groq_api_keys() -> List[str]:
    numbered_keys = []
    for name, value in os.environ.items():
        match = re.fullmatch(r"GROQ_API_KEY_(\d+)", name)
        if match and value.strip():
            numbered_keys.append((int(match.group(1)), value.strip()))

    keys = [value for _, value in sorted(numbered_keys)]
    keys.extend(
        value.strip()
        for value in (os.getenv("GROQ_API_KEYS") or "").split(",")
        if value.strip()
    )
    single_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if single_key:
        keys.append(single_key)
    return list(dict.fromkeys(keys))


def _get_easyocr():
    global _easy_reader
    if _easy_reader is None:
        try:
            import easyocr
            langs = [l.strip() for l in OCR_LANGS if l.strip()]
            _easy_reader = easyocr.Reader(langs or ["en"], gpu=USE_GPU, verbose=False)
        except Exception as e:
            logger.warning("EasyOCR init with %s failed (%s); falling back to ['en']", OCR_LANGS, e)
            try:
                import easyocr
                _easy_reader = easyocr.Reader(["en"], gpu=USE_GPU, verbose=False)
            except Exception as e2:
                logger.warning("EasyOCR unavailable: %s", e2)
                _easy_reader = False
    return _easy_reader if _easy_reader is not False else None


def _get_paddle():
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            import paddle  # noqa: F401
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(use_angle_cls=True, lang="en")
        except Exception as e:
            logger.info("PaddleOCR engine unavailable (paddlepaddle not installed or failed: %s)", e)
            _paddle_ocr = False
    return _paddle_ocr if _paddle_ocr is not False else None


def _get_groq_client(api_key: str):
    client = _groq_clients.get(api_key)
    if client is None:
        from groq import Groq
        client = Groq(api_key=api_key, timeout=GROQ_TIMEOUT, max_retries=0)
        _groq_clients[api_key] = client
    return client


def _starting_groq_key_index(key_count: int) -> int:
    global _groq_key_index, _groq_key_count
    with _groq_key_lock:
        if _groq_key_count != key_count:
            _groq_key_count = key_count
            _groq_key_index = 0
        start = _groq_key_index % key_count
        _groq_key_index = (start + 1) % key_count
        return start


def _should_rotate_key(error: Exception) -> bool:
    """Determine whether an error is key- or quota-related and warrants rotating to another Groq key."""
    status_code = getattr(error, "status_code", None)
    if status_code in (429, 401, 403, 500, 502, 503, 504):
        return True
    err_type = type(error).__name__
    if err_type in ("APIConnectionError", "APITimeoutError", "RateLimitError", "AuthenticationError", "InternalServerError"):
        return True
    msg = str(error).lower()
    return any(p in msg for p in ["rate limit", "quota", "too many requests", "invalid api key", "unauthorized", "timed out", "timeout"])


def _parse_qwen_response(raw: str) -> Dict[str, Any]:
    """Resiliently parse Qwen OCR output into dict with lines and mrz_candidates."""
    if not raw or not raw.strip():
        return {"lines": [], "mrz_candidates": []}

    import json

    # 1. Direct JSON parse
    try:
        data = json.loads(raw.strip())
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Extract markdown code block
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. Extract outer braces
    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            data = json.loads(raw[brace_start:brace_end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 4. Fallback line-by-line regex extraction
    lines = []
    m_lines = re.search(r'"lines"\s*:\s*\[([\s\S]*?)\]', raw)
    if m_lines:
        items = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', m_lines.group(1))
        lines = [item.strip() for item in items if item.strip()]

    if not lines:
        for l in raw.splitlines():
            clean = l.strip().strip(",\"'[]")
            if clean and not clean.startswith(("{", "}", "```", '"lines"', '"mrz_candidates"', '"language_hint"')):
                lines.append(clean)

    mrz_lines = []
    m_mrz = re.search(r'"mrz_candidates"\s*:\s*\[([\s\S]*?)\]', raw)
    if m_mrz:
        items = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', m_mrz.group(1))
        mrz_lines = [item.strip() for item in items if item.strip()]

    return {"lines": lines, "mrz_candidates": mrz_lines}


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
  "lines": ["line1", "line2", ...],
  "mrz_candidates": ["possible MRZ lines if any"],
  "language_hint": "en|hi|..."
}
Do not include a duplicate full_text field. Keep each visible text line separate.
Do not invent text. Skip unreadable fragments rather than expanding them.
"""


def _run_qwen(image_path: str) -> Dict[str, Any]:
    api_keys = _groq_api_keys()
    if not api_keys:
        logger.warning("No Groq API key configured – Qwen OCR disabled")
        return {"fields": [], "mrz_lines": [], "error": "no_groq"}

    b64 = _image_to_b64(image_path)
    start_index = _starting_groq_key_index(len(api_keys))
    last_error = None
    data = None

    for offset in range(len(api_keys)):
        key_index = (start_index + offset) % len(api_keys)
        masked_key = f"...{api_keys[key_index][-6:]}" if len(api_keys[key_index]) >= 6 else "key"
        logger.info("Qwen OCR attempting Groq key %d/%d (%s)...", key_index + 1, len(api_keys), masked_key)

        try:
            client = _get_groq_client(api_keys[key_index])
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
                temperature=0.1,
                max_completion_tokens=2500,
                response_format={"type": "json_object"},
                timeout=GROQ_TIMEOUT,
            )
            raw = resp.choices[0].message.content or "{}"
            data = _parse_qwen_response(raw)
            logger.info(
                "Qwen OCR succeeded using Groq key %d/%d (%s): extracted %d lines, %d MRZ candidates",
                key_index + 1,
                len(api_keys),
                masked_key,
                len(data.get("lines") or []),
                len(data.get("mrz_candidates") or []),
            )
            break
        except Exception as e:
            last_error = e
            err_str = str(e)

            # If Groq failed because strict JSON mode hit token limit, retry immediately without JSON restriction
            if "json_validate_failed" in err_str or "completion hit max completion tokens" in err_str:
                logger.warning(
                    "Groq key %d/%d (%s) encountered json_validate_failed. Retrying with free-form text format...",
                    key_index + 1,
                    len(api_keys),
                    masked_key,
                )
                try:
                    resp = client.chat.completions.create(
                        model=QWEN_MODEL,
                        messages=[
                            {"role": "system", "content": _QWEN_SYSTEM},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Perform precise OCR on this identity document image. Return valid JSON lines."},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                                    },
                                ],
                            },
                        ],
                        temperature=0.1,
                        max_completion_tokens=2500,
                        timeout=GROQ_TIMEOUT,
                    )
                    raw = resp.choices[0].message.content or ""
                    data = _parse_qwen_response(raw)
                    if data.get("lines") or data.get("mrz_candidates"):
                        logger.info(
                            "Free-form Qwen retry succeeded on key %d/%d (%s) with %d lines, %d MRZ candidates.",
                            key_index + 1,
                            len(api_keys),
                            masked_key,
                            len(data.get("lines") or []),
                            len(data.get("mrz_candidates") or []),
                        )
                        break
                except Exception as retry_err:
                    logger.warning("Free-form Qwen retry failed on key %d/%d (%s): %s", key_index + 1, len(api_keys), masked_key, retry_err)

            if _should_rotate_key(e):
                logger.warning(
                    "Qwen OCR request with Groq key %d/%d (%s) failed (%s: %s). Rotating to next key...",
                    key_index + 1,
                    len(api_keys),
                    masked_key,
                    type(e).__name__,
                    e,
                )
                if getattr(e, "status_code", None) == 429:
                    time.sleep(1.2)
                continue
            else:
                logger.warning(
                    "Qwen OCR request with Groq key %d/%d (%s) failed with non-rotatable error: %s",
                    key_index + 1,
                    len(api_keys),
                    masked_key,
                    e,
                )
                break

    if data is None:
        return {
            "fields": [],
            "mrz_lines": [],
            "error": str(last_error or "Qwen OCR request failed"),
        }

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
    if "qwen" in OCR_BACKENDS:
        try:
            qwen_data = _run_qwen(image_path)
            if qwen_data.get("fields") or qwen_data.get("mrz_lines"):
                result["engines_used"].append("qwen")
                logger.info(
                    "Qwen OCR active for %s: %d text fields, %d MRZ lines found.",
                    os.path.basename(image_path),
                    len(qwen_data.get("fields", [])),
                    len(qwen_data.get("mrz_lines", [])),
                )
            else:
                reason = qwen_data.get("error") or "0 fields returned"
                logger.warning(
                    "Qwen OCR yielded no usable text for %s (reason: %s); trying configured local OCR backups: %s",
                    os.path.basename(image_path),
                    reason,
                    [b for b in OCR_BACKENDS if b != "qwen"],
                )
        except Exception as e:
            logger.warning(
                "Qwen OCR failed for %s (%s); trying configured local OCR backups",
                os.path.basename(image_path),
                e,
            )

    if not qwen_data.get("fields") and not qwen_data.get("mrz_lines"):
        local_backends = []
        if "easyocr" in OCR_BACKENDS:
            local_backends.append(("easy", lambda: _run_easyocr(thresh)))
        if "paddle" in OCR_BACKENDS:
            local_backends.append(("paddle", lambda: _run_paddle(color)))

        for name, run_backend in local_backends:
            try:
                logger.info("Executing local OCR engine '%s' for %s...", name, os.path.basename(image_path))
                fields = run_backend()
                if fields:
                    local_fields.extend(fields)
                    result["engines_used"].append(name)
                    logger.info("Local OCR engine '%s' extracted %d fields.", name, len(fields))
                else:
                    logger.info("Local OCR engine '%s' extracted 0 fields.", name)
            except Exception as e:
                logger.warning("Local OCR engine '%s' failed: %s", name, e)

    all_fields = _merge_fields(qwen_data.get("fields", []), local_fields)
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