import os
import json
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
    from detectors.gemini_key_pool import (  # type: ignore
        get_next_gemini_key,
        mark_key_cooling,
        gemini_model_name,
    )


def _text_model_name() -> str:
    # Text-only officer summary. Override with Codespaces secret / .env if needed.
    # Does NOT need a different product line from vision; payload has NO image.
    return os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def generate_human_summary(report: dict) -> str:
    """
    Officer-facing plain-English summary from a full KAVACH engine report.
    Uses the same Gemini key pool as vision_llm_inspector (Codespaces secrets / .env).
    """
    # Slim the report so we don't burn tokens on huge OCR field lists
    slim = {
        "engine": report.get("engine"),
        "file_analyzed": report.get("file_analyzed"),
        "live_image": report.get("live_image"),
        "risk_level": report.get("risk_level"),
        "risk_reason": report.get("risk_reason"),
        "forensic_risk_score": report.get("forensic_risk_score"),
        "active_detectors_evaluated": report.get("active_detectors_evaluated"),
        "detector_signals": [],
    }
    for s in report.get("detector_signals") or []:
        if not isinstance(s, dict):
            continue
        slim["detector_signals"].append(
            {
                "detector_name": s.get("detector_name"),
                "score": s.get("score"),
                "confidence": s.get("confidence"),
                "status": s.get("status"),
                "explanation": (s.get("explanation") or "")[:240],
            }
        )

    prompt = f"""
You are a border-control assistant. An automated system (KAVACH) screened an identity document.
Below is a JSON summary: overall risk_level plus per-check signals.
Scores are risk-oriented (higher = more suspicious) unless status is unavailable/failed.

Rules:
- Trust risk_level and critical failures (OCR/MRZ/face mismatch) more than a single weak forensic flag.
- If critical checks are unavailable, say the officer should review manually (fail-closed).
- Do NOT invent passport numbers, names, or facts not in the JSON.
- Write for a non-technical officer.

Report JSON:
{json.dumps(slim, indent=2)}

Write 4-6 plain English sentences:
1) Overall recommendation (PASS / REVIEW / HIGH RISK — use the report's risk_level if present).
2) The 2-3 strongest reasons.
3) Any important limitations (skipped face, missing OCR, low confidence).
"""

    model = _text_model_name()
    last_error = "No GEMINI API keys configured (set GEMINI_API_KEYS or GEMINI_API_KEY)."

    for _ in range(19):
        api_key, _idx = get_next_gemini_key()
        if not api_key:
            break

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        try:
            res = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=45,
            )
            if res.status_code == 429:
                mark_key_cooling(api_key, 65.0)
                last_error = "Rate limited; tried next key."
                continue

            res_data = res.json()
            err = res_data.get("error") or {}
            msg = str(err.get("message", ""))
            if "quota" in msg.lower() or "rate" in msg.lower():
                mark_key_cooling(api_key, 65.0)
                last_error = msg or "Quota error"
                continue

            if "candidates" not in res_data:
                last_error = f"Gemini response: {json.dumps(res_data)[:250]}"
                if "API key" in last_error or "PERMISSION" in last_error.upper():
                    mark_key_cooling(api_key, 120.0)
                    continue
                continue

            return res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

        except Exception as e:
            last_error = str(e)
            continue

    return f"LLM summary unavailable after key rotation. Last error: {last_error}"