# kavach/ocr_mrz_consistency.py

def _clean_mrz_candidate(text: str) -> str:
    """Normalize a possible MRZ string from OCR."""
    if not text:
        return ""
    t = text.upper().replace(" ", "")
    for ch in ("«", "‹", "(", "{", "[", "_", "–", "—", "~"):
        t = t.replace(ch, "<")
    t = "".join(c for c in t if c.isalnum() or c == "<")
    return t


def _collect_mrz_lines(ocr_raw: dict) -> list:
    """
    Build up to 2 TD3-style MRZ lines from OCR output.
    Uses official mrz_lines first, then long field tokens.
    """
    if not isinstance(ocr_raw, dict):
        return []

    candidates = []

    for line in ocr_raw.get("mrz_lines") or []:
        cleaned = _clean_mrz_candidate(str(line))
        if cleaned:
            candidates.append(cleaned)

    for f in ocr_raw.get("fields") or []:
        if isinstance(f, dict):
            text = f.get("text") or ""
        else:
            text = str(f)
        cleaned = _clean_mrz_candidate(text)
        if not cleaned:
            continue
        if len(cleaned) >= 28 and (cleaned.startswith("P<") or cleaned.count("<") >= 2 or sum(c.isdigit() for c in cleaned) >= 10):
            candidates.append(cleaned)

    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)

    line1 = None
    for c in uniq:
        if c.startswith("P<") and line1 is None:
            line1 = c
            break

    if line1 is None and uniq:
        with_chevron = [c for c in uniq if "<" in c]
        line1 = max(with_chevron, key=len) if with_chevron else uniq[0]

    line2 = None
    for c in uniq:
        if c is line1:
            continue
        if not c.startswith("P<") and len(c) >= 28:
            line2 = c
            break
    if line2 is None:
        for c in uniq:
            if c is not line1 and len(c) >= 28:
                line2 = c
                break

    lines = []
    if line1:
        lines.append(line1[:44].ljust(44, "<"))
    if line2:
        lines.append(line2[:44].ljust(44, "<"))

    return lines


def normalize(text: str) -> str:
    """Strip, uppercase, remove spaces and filler characters."""
    return text.upper().replace("<", "").replace(" ", "").strip()


def compare_fields(ocr_value: str, mrz_value: str, field_name: str) -> dict:
    ocr_n = normalize(ocr_value)
    mrz_n = normalize(mrz_value)

    if not ocr_n or not mrz_n:
        return {
            "field": field_name,
            "status": "unavailable",
            "ocr": ocr_value,
            "mrz": mrz_value,
            "explanation": f"One or both values missing for {field_name}"
        }

    match = ocr_n == mrz_n
    return {
        "field": field_name,
        "status": "passed" if match else "flagged",
        "ocr": ocr_value,
        "mrz": mrz_value,
        "explanation": f"{field_name}: OCR='{ocr_value}' MRZ='{mrz_value}' → {'MATCH' if match else 'MISMATCH'}"
    }


def check_ocr_mrz_consistency(ocr_fields: dict, mrz_fields: dict) -> dict:
    """
    Compares extracted OCR fields against MRZ-decoded fields.

    ocr_fields: dict with keys like 'passport_number', 'dob', 'expiry', 'surname', 'nationality'
    mrz_fields: dict from mrz_parser.parse_mrz()

    Three possible per-field statuses:
      - "passed"      -> OCR and MRZ values are present and match
      - "flagged"     -> OCR and MRZ values are present and DON'T match
      - "unavailable" -> one or both values are missing, so nothing was actually checked

    Overall status follows the same idea and must never report "passed"
    unless every field was actually compared and matched:
      - "flagged"    -> at least one real mismatch was found (highest priority)
      - "incomplete" -> no mismatches, but at least one field couldn't be checked
      - "passed"     -> every field was checked and all matched
    """
    comparisons = []
    mismatches = []
    unavailable = []

    fields_to_check = [
        ("passport_number", "passport_number"),
        ("dob",             "dob"),
        ("expiry",          "expiry"),
        ("surname",         "surname"),
        ("nationality",     "nationality"),
    ]

    for ocr_key, mrz_key in fields_to_check:
        ocr_val = ocr_fields.get(ocr_key, "")
        mrz_val = mrz_fields.get(mrz_key, "")

        result = compare_fields(str(ocr_val), str(mrz_val), ocr_key)
        comparisons.append(result)

        if result["status"] == "flagged":
            mismatches.append(ocr_key)
        elif result["status"] == "unavailable":
            unavailable.append(ocr_key)

    total = len(comparisons)
    bad = len(mismatches) + len(unavailable)
    score = 1.0 - (bad / max(total, 1))

    if mismatches:
        status = "flagged"
        explanation = f"Mismatches found in: {', '.join(mismatches)}"
    elif unavailable:
        status = "incomplete"
        explanation = f"Could not verify (missing data) for: {', '.join(unavailable)}"
    else:
        status = "passed"
        explanation = "All OCR and MRZ fields match."

    return {
        "status": status,
        "score": round(score, 2),
        "confidence": 0.9,
        "mismatches": mismatches,
        "unavailable": unavailable,
        "comparisons": comparisons,
        "explanation": explanation,
    }


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    workspace_root = Path(__file__).resolve().parents[1]
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    from detectors.ocr_extraction import extract_text
    from detectors.ocr_field_extractor import extract_fields_from_ocr
    from detectors.mrz_parser import parse_mrz

    parser = argparse.ArgumentParser(description="Compare OCR-extracted fields against MRZ fields from an image.")
    parser.add_argument("--image", required=True, help="Path to the document image to analyze.")
    args = parser.parse_args()

    ocr_raw = extract_text(args.image)
    ocr_fields = extract_fields_from_ocr(ocr_raw) if isinstance(ocr_raw, dict) else {}

    mrz_lines = _collect_mrz_lines(ocr_raw if isinstance(ocr_raw, dict) else {})
    if len(mrz_lines) < 2:
        print(json.dumps({
            "status": "failed",
            "score": 0.0,
            "confidence": "low",
            "explanation": "No valid MRZ lines were found in the image OCR output.",
            "mismatches": [],
            "unavailable": [],
            "comparisons": [],
        }, indent=2))
    else:
        mrz_raw = parse_mrz(mrz_lines)
        print(json.dumps(check_ocr_mrz_consistency(ocr_fields, mrz_raw.get("fields", {})), indent=2))