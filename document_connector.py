"""document_connector.py - engine -> rules -> brief -> API response."""
from document_analyst import get_document_brief
from document_engine import SLOTS, analyze_document

MIN_VERIFIED = 2  # Checks that must be verified for PASS. Lower it for a demo only.

_MAP = {
    "PASS": ("likely_real", "green"),
    "REVIEW": ("inconclusive", "amber"),
    "HIGH RISK": ("likely_fake", "red"),
}


def _decide(slots):
    flagged = [s for s in slots.values() if s["status"] == "flagged"]
    hard = [s for s in flagged if s.get("hard")]
    verified = [s for s in slots.values() if s["status"] == "clean" and s.get("verified")]
    if len(hard) >= 2:
        return "HIGH RISK"
    if flagged or len(verified) < MIN_VERIFIED:
        return "REVIEW"
    return "PASS"


def analyze_document_file(path):
    report = analyze_document(path)
    if "error" in report:
        return {"verdict": "inconclusive", "risk_level": "REVIEW", "summary_label": "REVIEW",
                "summary_color": "amber", "human_summary": report["error"], "degraded": True,
                "warnings": [report["error"]], "detector_status": {}}

    slots = {s["slot"]: s for s in report["detector_signals"]}
    risk = _decide(slots)
    verdict, color = _MAP[risk]
    brief = get_document_brief(risk, slots)

    summary = str(brief.get("reasoning", "")).strip()
    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."

    skipped = [s["explanation"] for s in slots.values() if s["status"] == "skipped"]
    flagged = [s["explanation"] for s in slots.values() if s["status"] == "flagged"]
    verified = [s["explanation"] for s in slots.values() if s["status"] == "clean" and s.get("verified")]
    return {
        "verdict": verdict,
        "risk_level": risk,
        "summary_label": risk,
        "summary_color": color,
        "human_summary": summary,
        "reasoning": brief.get("reasoning", ""),
        "officer_checklist": brief.get("officer_checklist", []),
        "key_signals": (flagged or verified)[:4],
        "warnings": list(brief.get("warnings", [])) + skipped,
        "confidence": None,
        "final_score": None,
        "degraded": len(skipped) >= 3,
        "document_type": report.get("document_type"),
        "reader": report.get("reader"),
        "detector_status": {n: {"status": slots[n]["status"], "text": slots[n]["explanation"]} for n in SLOTS if n in slots},
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(analyze_document_file(sys.argv[1]), indent=2))