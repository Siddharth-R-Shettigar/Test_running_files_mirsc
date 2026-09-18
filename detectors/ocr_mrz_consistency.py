"""Cross-check visual OCR fields against parsed MRZ."""
from __future__ import annotations
import re
from typing import Dict, List

def _norm_date(d: str) -> str:
    if not d:
        return ""
    d = re.sub(r"[^\d]", "", d)
    if len(d) == 6:          # YYMMDD
        return d
    if len(d) == 8:          # DDMMYYYY or YYYYMMDD
        if int(d[:2]) > 31:  # YYYYMMDD
            return d[2:]
        return d[4:6] + d[2:4] + d[0:2]  # rough → YYMMDD
    return d


def _norm_name(n: str) -> str:
    return re.sub(r"[^A-Z]", "", (n or "").upper())


def check_ocr_mrz_consistency(visual_fields: Dict, mrz_fields: Dict) -> Dict:
    mismatches: List[str] = []
    details = {}

    mapping = {
        "dob": ("dob", "date_of_birth"),
        "passport_number": ("passport_number", "document_number"),
        "surname": ("surname", "primary_identifier"),
        "expiry": ("expiry", "date_of_expiry"),
        "sex": ("sex", "gender"),
        "nationality": ("nationality", "country_code"),
    }

    for key, mrz_keys in mapping.items():
        vis = str(visual_fields.get(key, "")).strip()
        mrz = ""
        for k in mrz_keys:
            mrz = str(mrz_fields.get(k, "")).strip()
            if mrz:
                break
        if not vis or not mrz:
            continue

        if key in ("dob", "expiry"):
            if _norm_date(vis) != _norm_date(mrz):
                mismatches.append(key)
                details[key] = {"visual": vis, "mrz": mrz}
        elif key in ("surname",):
            if _norm_name(vis) != _norm_name(mrz) and _norm_name(vis) not in _norm_name(mrz):
                mismatches.append(key)
                details[key] = {"visual": vis, "mrz": mrz}
        else:
            if vis.upper() != mrz.upper():
                mismatches.append(key)
                details[key] = {"visual": vis, "mrz": mrz}

    if mismatches:
        return {
            "status": "flagged",
            "score": 0.75,
            "confidence": "high",
            "explanation": f"OCR↔MRZ mismatch on: {', '.join(mismatches)}",
            "mismatches": mismatches,
            "details": details,
        }
    return {
        "status": "passed",
        "score": 0.1,
        "confidence": "high",
        "explanation": "Visual OCR and MRZ fields are consistent",
        "mismatches": [],
    }