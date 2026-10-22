import json
import sys
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

try:
    from detectors.gemini_key_pool import (
        get_next_gemini_key,
        mark_key_cooling,
        gemini_model_name,
    )
except ModuleNotFoundError:
    from gemini_key_pool import (
        get_next_gemini_key,
        mark_key_cooling,
        gemini_model_name,
    )


def _mime_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".png",):
        return "image/png"
    if ext in (".webp",):
        return "image/webp"
    if ext in (".gif",):
        return "image/gif"
    return "image/jpeg"


def _call_gemini(api_key: str, model: str, encoded_image: str, mime: str, prompt: str) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": encoded_image}},
            ]
        }]
    }
    res = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    # 429 / quota → signal caller to rotate
    if res.status_code == 429:
        return {"_rate_limited": True, "body": res.text[:300]}
    try:
        data = res.json()
    except Exception:
        return {"_error": f"HTTP {res.status_code}: {res.text[:200]}"}
    data["_http_status"] = res.status_code
    return data


def run_vision_llm_inspector(image_path):
    prompt = """
You are a border-control document examiner. Inspect this identity document image for tampering or fraud risk.
Look for: replaced or pasted photograph, retyped or misaligned text, altered dates or numbers,
suspicious stamps, layout inconsistencies, or signs the page was digitally edited.
Do NOT focus on general AI-art artifacts (fingers, fantasy scenes) unless relevant to an ID photo.

Respond STRICTLY with a raw JSON object (no markdown, no backticks):
{"score": <float 0.0 = looks genuine to 1.0 = strong tampering risk>, "explanation": "<1-2 sentence plain text>"}
"""

    if not os.path.exists(image_path):
        return {
            "detector_name": "vision_llm_sanity_analysis",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"File not found: {image_path}",
            "status": "failed",
        }

    try:
        with open(image_path, "rb") as f:
            encoded_image = base64.b64encode(f.read()).decode("utf-8")
        mime = _mime_for(image_path)
        model = gemini_model_name()

        # Try several keys if one is rate-limited or fails hard
        max_attempts = 4
        last_error = "No GEMINI API keys configured."
        used = set()

        for _ in range(max_attempts):
            api_key, idx = get_next_gemini_key()
            if not api_key:
                break
            kid = api_key[-6:]
            if kid in used and len(used) >= max_attempts:
                break
            used.add(kid)

            res_data = _call_gemini(api_key, model, encoded_image, mime, prompt)

            if res_data.get("_rate_limited"):
                mark_key_cooling(api_key, 65.0)
                last_error = f"Rate limited on key ...{kid}"
                continue

            if res_data.get("_error"):
                last_error = res_data["_error"]
                continue

            # Quota / API errors in JSON body
            err = res_data.get("error") or {}
            msg = str(err.get("message", ""))
            if res_data.get("_http_status") == 429 or "quota" in msg.lower() or "rate" in msg.lower():
                mark_key_cooling(api_key, 65.0)
                last_error = msg or f"Quota on key ...{kid}"
                continue

            if "candidates" not in res_data:
                last_error = f"No candidates: {json.dumps(res_data)[:250]}"
                # Some errors are key-specific; try next key
                if "API key" in last_error or "PERMISSION" in last_error.upper():
                    mark_key_cooling(api_key, 120.0)
                    continue
                break

            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(raw_text)
            score = float(parsed.get("score", 0.5))

            return {
                "detector_name": "vision_llm_sanity_analysis",
                "score": score,
                "confidence": "high",
                "explanation": parsed.get("explanation", "Vision LLM scan complete."),
                "status": "passed" if score < 0.4 else "flagged",
            }

        return {
            "detector_name": "vision_llm_sanity_analysis",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Vision LLM unavailable after key rotation. Last error: {last_error}",
            "status": "unavailable",
        }

    except Exception as e:
        return {
            "detector_name": "vision_llm_sanity_analysis",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Vision LLM inspection failed: {str(e)}",
            "status": "failed",
        }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "DSC_0153.JPG"
    print(json.dumps(run_vision_llm_inspector(target), indent=2))