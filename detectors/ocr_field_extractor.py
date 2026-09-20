"""Structured field extraction from OCR output."""
from __future__ import annotations
import re
from typing import Any, Dict, List

DATE_RE = re.compile(
    r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})\b"
)
PASSPORT_RE = re.compile(r"\b([A-Z]\d{7,8})\b", re.I)
AADHAAR_RE = re.compile(r"\b([2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4})\b")
PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b", re.I)
NAME_HINT = re.compile(r"(?:name|नाम|surname|given)\s*[:\-]?\s*([A-Za-z\u0900-\u097F\s]{3,40})", re.I)


def extract_fields_from_ocr(ocr_raw: Dict[str, Any], doc_type: str) -> Dict[str, str]:
    fields_list: List[Dict] = ocr_raw.get("fields") or []
    full = " ".join(f.get("text", "") for f in fields_list if isinstance(f, dict))
    full_upper = full.upper()

    extracted: Dict[str, str] = {}

    # Dates
    dates = DATE_RE.findall(full)
    if dates:
        # heuristic: earliest-looking → DOB, latest → expiry
        extracted["dob"] = dates[0]
        if len(dates) > 1:
            extracted["expiry"] = dates[-1]

    # Document numbers
    if doc_type in ("passport", "visa"):
        m = PASSPORT_RE.search(full_upper)
        if m:
            extracted["passport_number"] = m.group(1).upper()

    if doc_type in ("national_id", "unknown"):
        m = AADHAAR_RE.search(full)
        if m:
            extracted["aadhaar"] = re.sub(r"[\s\-]", "", m.group(1))
        m = PAN_RE.search(full_upper)
        if m:
            extracted["pan"] = m.group(1).upper()

    # Names (best-effort)
    m = NAME_HINT.search(full)
    if m:
        extracted["name"] = m.group(1).strip()

    # Sex
    if re.search(r"\b(M|MALE|पुरुष)\b", full_upper):
        extracted["sex"] = "M"
    elif re.search(r"\b(F|FEMALE|महिला)\b", full_upper):
        extracted["sex"] = "F"

    return extracted