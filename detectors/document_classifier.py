"""Robust multi-language document classifier."""
from __future__ import annotations
import re
from typing import Dict

def classify_document(image_path: str, ocr_text: str) -> Dict:
    if not ocr_text or not ocr_text.strip():
        return {"doc_type": "unknown", "needs_mrz": False, "confidence": 0.0,
                "status": "unavailable", "score": 0.5,
                "explanation": "Empty OCR text"}

    text = ocr_text.lower()
    # Normalise common OCR noise
    text = re.sub(r"[^\w\s\u0900-\u097F\u0B80-\u0BFF\u0C00-\u0C7F]", " ", text)

    scores = {
        "national_id": 0.0,
        "passport": 0.0,
        "visa": 0.0,
        "dl": 0.0,
        "pan": 0.0,
    }

    # Aadhaar / National ID
    aadhaar_kw = [
        "aadhaar", "aadhar", "uidai", "unique identification",
        "आधार", "भारत सरकार", "mera aadhaar", "government of india",
        "enrollment", "vid"
    ]
    scores["national_id"] += sum(2.0 for k in aadhaar_kw if k in text)
    if re.search(r"\b[2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4}\b", text):
        scores["national_id"] += 3.0

    # Passport
    passport_kw = ["passport", "पासपोर्ट", "republic of", "nationality", "p<", "type p"]
    scores["passport"] += sum(2.0 for k in passport_kw if k in text)
    if re.search(r"\bp[<\s]?[a-z]{3}", text) or "mrz" in text:
        scores["passport"] += 2.5

    # Visa
    visa_kw = ["visa", "वीज़ा", "entry", "valid from", "number of entries"]
    scores["visa"] += sum(2.0 for k in visa_kw if k in text)

    # Driving licence
    dl_kw = ["driving", "driver", "licence", "license", "dl no", "rto", "transport"]
    scores["dl"] += sum(1.5 for k in dl_kw if k in text)

    # PAN
    if re.search(r"\b[a-z]{5}\d{4}[a-z]\b", text) or "permanent account" in text or "income tax" in text:
        scores["pan"] += 4.0

    best = max(scores, key=scores.get)
    conf = scores[best]

    if conf < 1.5:
        return {
            "doc_type": "unknown",
            "needs_mrz": False,
            "confidence": 0.2,
            "status": "passed",
            "score": 0.4,
            "explanation": "Could not confidently classify document",
        }

    needs_mrz = best in ("passport", "visa")
    return {
        "doc_type": best if best != "pan" else "national_id",  # pan treated as national_id family
        "needs_mrz": needs_mrz,
        "confidence": min(1.0, conf / 8.0),
        "status": "passed",
        "score": 0.1,
        "explanation": f"Classified as {best} (score={conf:.1f})",
    }