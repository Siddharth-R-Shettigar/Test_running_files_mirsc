"""Aadhaar / PAN / National ID validation with Verhoeff check digit."""
from __future__ import annotations
import re
from typing import Dict

# Verhoeff tables
_d = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8],
    [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],
    [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]
_p = [
    [0,1,2,3,4,5,6,7,8,9],
    [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0],
    [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],
    [7,0,4,6,9,1,3,2,5,8],
]
_inv = [0,4,3,2,1,5,6,7,8,9]


def verhoeff_validate(num: str) -> bool:
    try:
        c = 0
        for i, digit in enumerate(reversed(num)):
            c = _d[c][_p[i % 8][int(digit)]]
        return c == 0
    except Exception:
        return False


def validate_national_id(ocr_text: str) -> Dict:
    text = ocr_text or ""
    char_map = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})
    norm = text.translate(char_map)

    # Grouped Aadhaar
    m = re.search(r"\b([2-9]\d{3})[\s\-_]+(\d{4})[\s\-_]+(\d{4})\b", norm)
    if m:
        aadhaar = m.group(1) + m.group(2) + m.group(3)
        ok = verhoeff_validate(aadhaar)
        return {
            "status": "passed" if ok else "flagged",
            "score": 0.1 if ok else 0.7,
            "confidence": "high",
            "explanation": f"Aadhaar format OK, Verhoeff {'PASS' if ok else 'FAIL'}",
            "aadhaar": aadhaar,
            "verhoeff": ok,
        }

    # Continuous
    m = re.search(r"(?<!\d)([2-9]\d{11})(?!\d)", re.sub(r"[\s\-_]", "", norm))
    if m:
        aadhaar = m.group(1)
        ok = verhoeff_validate(aadhaar)
        return {
            "status": "passed" if ok else "flagged",
            "score": 0.1 if ok else 0.7,
            "confidence": "high",
            "explanation": f"Continuous Aadhaar, Verhoeff {'PASS' if ok else 'FAIL'}",
            "aadhaar": aadhaar,
            "verhoeff": ok,
        }

    # Masked
    if re.search(r"(?:[xX\*]{4}[\s\-_]+){2}\d{4}\b", text):
        return {
            "status": "passed",
            "score": 0.2,
            "confidence": "medium",
            "explanation": "Masked Aadhaar format detected",
        }

    # PAN
    m = re.search(r"\b([A-Z]{5}\d{4}[A-Z])\b", text.upper())
    if m:
        return {
            "status": "passed",
            "score": 0.15,
            "confidence": "high",
            "explanation": "Valid PAN format",
            "pan": m.group(1),
        }

    return {
        "status": "unavailable",
        "score": 0.45,
        "confidence": "low",
        "explanation": "No recognised National ID pattern",
    }