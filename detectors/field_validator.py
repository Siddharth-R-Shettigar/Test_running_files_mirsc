"""Schema validation of extracted fields."""
from __future__ import annotations
from typing import Dict, List

REQUIRED = {
    "passport": ["passport_number", "dob", "expiry", "surname"],
    "visa": ["passport_number", "dob"],
    "national_id": ["dob"],
    "dl": ["dob"],
    "unknown": [],
}

def validate_document_fields(combined_fields: Dict, doc_type: str) -> Dict:
    doc_type = (doc_type or "unknown").lower()
    required = REQUIRED.get(doc_type, [])
    missing: List[str] = []

    for r in required:
        val = combined_fields.get(r) or combined_fields.get(r.replace("_", ""))
        if not val:
            missing.append(r)

    if missing:
        return {
            "status": "flagged",
            "score": 0.65,
            "confidence": "medium",
            "explanation": f"Missing mandatory fields for {doc_type}: {', '.join(missing)}",
            "missing": missing,
        }
    return {
        "status": "passed",
        "score": 0.1,
        "confidence": "high",
        "explanation": "All required fields present",
        "missing": [],
    }