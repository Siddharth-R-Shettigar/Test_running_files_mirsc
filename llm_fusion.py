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

def _groq_keys():
    keys = []
    blob = (os.getenv("GROQ_API_KEYS") or "").strip()
    for part in blob.split(","):
        k = part.strip()
        if k:
            keys.append(k)
    single = (os.getenv("GROQ_API_KEY") or "").strip()
    if single:
        keys.append(single)
    out, seen = [], set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _summary_prompt(slim: dict) -> str:
    return f"""
You are writing a short brief for a border officer using KAVACH (automated document screening).

Report JSON:
{json.dumps(slim, indent=2)}

Output EXACTLY in this format (plain text, no markdown fences):

LINE1: <GREEN or YELLOW or RED> | <PASS or REVIEW or HIGH RISK> | <file_name>
LINE2: Why: <one or two short sentences; use risk_level and strongest flagged signals; do not invent facts>
LINE3: empty
Then heading: Officer checklist:
Then 3 to 5 lines starting with [ ] describing concrete things the officer should verify manually.
Then one line: Signals: <up to 5 detector_name=status pairs for the most important signals>

Rules:
- GREEN only if risk_level is PASS.
- YELLOW if risk_level is REVIEW.
- RED if risk_level is HIGH RISK.
- Prefer fail-closed language (when unsure, push checklist, not "definitely fake").
- Mention if face live-check was skipped.
- Do not claim hologram/microtext proof from phone capture alone.
""".strip()


def _groq_summary(slim: dict) -> str:
    """Text-only summary via Groq. Returns empty string if unavailable."""
    keys = _groq_keys()
    if not keys:
        return ""

    model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    prompt = _summary_prompt(slim)

    for key in keys:
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Follow the user's format exactly. Plain text only. No markdown code fences.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=45,
            )
            if res.status_code == 429:
                continue
            data = res.json()
            if res.status_code >= 400:
                continue
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if text:
                return text.splitlines()[0].strip()
        except Exception:
            continue
    return ""


def _llm_summary(slim: dict) -> str:
    """Gemini fallback for summary."""
    prompt = _summary_prompt(slim)
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
    Officer-facing one-line summary.
    Order: Groq → Gemini pool → local rule fallback.
    """
    slim = _slim_report(report)

    try:
        text = _groq_summary(slim)
        if text:
            return text
    except Exception:
        pass

    try:
        text = _llm_summary(slim)
        if text and text.strip():
            return text.strip()
    except Exception:
        pass

    return _fallback_summary(report)