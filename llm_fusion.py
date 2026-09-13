import json
import os
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
    try:
        from detectors.gemini_key_pool import (  # type: ignore
            get_next_gemini_key,
            mark_key_cooling,
            gemini_model_name,
        )
    except Exception:
        def get_next_gemini_key():
            return None, 0

        def mark_key_cooling(*args, **kwargs):
            return None

        gemini_model_name = "gemini-2.5-flash"


def _text_model_name() -> str:
    # Text-only officer summary. Override with Codespaces secret / .env if needed.
    return os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def _ansi(text, code):
    return f"\033[{code}m{text}\033[0m"


def _risk_to_verdict(risk_level):
    if risk_level == "PASS":
        return "Genuine"
    if risk_level == "REVIEW":
        return "Needs review"
    if risk_level == "HIGH RISK":
        return "Likely fake"
    return "Unknown"


def _color_for_verdict(verdict):
    if verdict == "Genuine":
        return _ansi(verdict, "32")   # green
    if verdict == "Needs review":
        return _ansi(verdict, "33")   # yellow/orange
    if verdict == "Likely fake":
        return _ansi(verdict, "31")   # red
    return _ansi(verdict, "36")     # cyan fallback


def _pick_reason(report):
    signals = report.get("detector_signals", []) or []

    # Strongest negative reason first
    for s in signals:
        if not isinstance(s, dict):
            continue

        status = str(s.get("status", "")).lower()
        explanation = (s.get("explanation") or "").strip()
        if status == "flagged" and explanation:
            # Prefer the meaningful detector reasons
            if s.get("detector_name") in {
                "ocr_mrz_consistency",
                "mrz_parser",
                "field_validator",
                "photo_patch_forensics",
                "vision_llm_sanity_analysis",
                "resampling_interpolation_analysis",
                "frequency_domain_fft",
                "cfa_demosaicing_analysis",
            }:
                return explanation

    # Fallback to top-level reason
    return report.get("risk_reason") or "No reason provided."


def _slim_report(report):
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

    return slim


def _fallback_summary(report: dict) -> str:
    file_name = report.get("file_analyzed", "unknown file")
    risk_level = report.get("risk_level", "UNKNOWN")
    verdict = _risk_to_verdict(risk_level)
    reason = _pick_reason(report)

    return (
        f"{file_name} | "
        f"{_color_for_verdict(verdict)} | "
        f"{reason}"
    )


def _llm_summary(slim: dict) -> str:
    prompt = f"""
You are a border-control assistant. An automated system (KAVACH) screened an identity document.

Below is a JSON summary of the run:
{json.dumps(slim, indent=2)}

Write exactly one crisp line for an officer, in this exact style:
<file_name> | <Genuine / Needs review / Likely fake> | <very short reason>

Rules:
- Keep it to one line only.
- Use the report's risk_level and strongest signals.
- Do NOT invent facts.
- Use short, plain English.
- If critical checks were skipped or unavailable, say that briefly.
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

            text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text.strip()

        except Exception as e:
            last_error = str(e)
            continue

    return _fallback_summary(slim)


def generate_human_summary(report: dict) -> str:
    """
    Officer-facing single-line summary from a full KAVACH engine report.
    Uses Gemini when available; otherwise falls back to a local rule-based summary.
    """
    slim = _slim_report(report)

    try:
        llm_text = _llm_summary(slim)
        if llm_text and llm_text.strip():
            return llm_text.strip()
    except Exception:
        pass

    return _fallback_summary(report)