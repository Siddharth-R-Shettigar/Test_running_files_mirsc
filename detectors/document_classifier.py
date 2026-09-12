# detectors/document_classifier.py
#
# Role: orchestrate the text-layer pipeline.
#
#   1. Classify the document type from OCR text.
#   2. Decide the routing:
#        - passport / visa  →  needs_mrz = True
#        - everything else  →  needs_mrz = False
#   3. Return classification result + routing metadata.
#
# kavach_engine.py reads `needs_mrz` and `doc_type` from the return value
# to decide whether to run MRZ / field_validator / ocr_mrz_consistency.

import re
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Supported document types
# passport / visa  → needs_mrz = True  (ICAO 9303 MRZ strip present)
# aadhaar / dl     → needs_mrz = False (no MRZ strip)
# ---------------------------------------------------------------------------
DOCUMENT_TYPES: Dict[str, Dict] = {
    "passport": {
        "keywords": [
            r"\bpassport\b",
            r"\bnationality\b",
            r"p<ind",
            r"p<",
            r"\brepublic\s+of\s+india\b",
            r"\bicao\b",
            r"\bmachine\s+readable\b",
        ],
    },
    "visa": {
        "keywords": [
            r"\bvisa\b",
            r"\bport\s+of\s+entry\b",
            r"\bvalid\s+for\s+stay\b",
            r"\bnumber\s+of\s+entries\b",
            r"\bplace\s+of\s+issue\b",
        ],
    },
    "aadhaar": {
        "keywords": [
            r"\baadhaar\b",
            r"\buidai\b",
            r"\bunique\s+identification\b",
            r"\baadhaar\s+number\b",
            r"\byour\s+aadhaar\b",
            r"\benrollment\s+no\b",
            r"\bvid\b",
        ],
    },
    "driving_licence": {
        "keywords": [
            r"\bdriving\s+licen[cs]e\b",
            r"\bdriving\s+licence\b",
            r"\bdl\s*no\b",
            r"\bmotor\s+vehicles?\s+act\b",
            r"\btransport\s+department\b",
            r"\bsarathi\b",
        ],
    },
}

# Document types that carry an MRZ strip (ICAO 9303)
MRZ_DOCUMENT_TYPES = {"passport", "visa"}

# Score contribution per matched keyword; capped at 1.0
KEYWORD_WEIGHT = 0.22

# Minimum score to commit to a classification; below this → "unknown"
MIN_SCORE = 0.30


def classify_document(image_path: str, ocr_text: str = "") -> Dict[str, Any]:
    """
    Classify a document from its OCR text and decide MRZ routing.

    Returns a standard KAVACH signal dict plus two extra keys that
    kavach_engine.py reads for pipeline routing:

        doc_type   (str)  – e.g. "passport", "aadhaar", "unknown"
        needs_mrz  (bool) – True only for passport / visa
    """
    ocr_lower = ocr_text.lower()
    scores: Dict[str, float] = {}
    keyword_hits: Dict[str, list] = {}

    for doc_type, rules in DOCUMENT_TYPES.items():
        matched = [p for p in rules["keywords"] if re.search(p, ocr_lower)]
        scores[doc_type] = round(min(len(matched) * KEYWORD_WEIGHT, 1.0), 3)
        keyword_hits[doc_type] = matched

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score < MIN_SCORE:
        best_type = "unknown"

    needs_mrz = best_type in MRZ_DOCUMENT_TYPES

    if best_score >= 0.65:
        conf = "high"
    elif best_score >= 0.40:
        conf = "medium"
    else:
        conf = "low"

    mrz_note = (
        "MRZ pipeline will be activated."
        if needs_mrz
        else "No MRZ required for this document type."
    )

    return {
        "detector_name": "document_classifier",
        "doc_type": best_type,
        "needs_mrz": needs_mrz,
        "score": float(best_score),
        "confidence": conf,
        "all_scores": scores,
        "keyword_hits": {k: v for k, v in keyword_hits.items() if v},
        "explanation": (
            f"Classified as '{best_type}' (score {best_score}). "
            f"Matched {len(keyword_hits.get(best_type, []))} keyword(s). "
            f"{mrz_note}"
        ),
        "status": "passed" if best_type != "unknown" else "unavailable",
    }


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    test_cases = [
        ("passport",        True,  "PASSPORT Republic of India Nationality IND MRZ P<IND ICAO machine readable"),
        ("visa",            True,  "VISA port of entry valid for stay number of entries place of issue"),
        ("aadhaar",         False, "Aadhaar UIDAI Unique Identification Authority of India VID enrollment no"),
        ("driving_licence", False, "Driving Licence DL No Motor Vehicles Act Transport Department Sarathi"),
        ("unknown",         False, "some random text that matches nothing at all"),
    ]

    print(f"{'Expected':<20} {'MRZ?':<6} {'Got':<20} {'Score':<8} {'needs_mrz':<12} {'OK?'}")
    print("-" * 80)
    all_ok = True
    for expected, exp_mrz, ocr in test_cases:
        result = classify_document("dummy.jpg", ocr_text=ocr)
        got = result["doc_type"]
        score = result["score"]
        needs = result["needs_mrz"]
        ok = (got == expected) and (needs == exp_mrz)
        all_ok = all_ok and ok
        mark = "✓" if ok else "✗"
        print(f"{mark} {expected:<18} {str(exp_mrz):<6} {got:<20} {score:<8} {str(needs):<12} {'OK' if ok else 'FAIL'}")
    print()
    print("All tests passed" if all_ok else "SOME TESTS FAILED")