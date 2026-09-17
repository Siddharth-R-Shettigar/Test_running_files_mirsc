# detectors/field_validator.py

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


def parse_mrz_date(yymmdd: str, is_expiry: bool = False) -> date | None:
    try:
        yy = int(yymmdd[0:2])
        mm = int(yymmdd[2:4])
        dd = int(yymmdd[4:6])
        current_yy = date.today().year % 100

        if is_expiry:
            year = 2000 + yy if yy <= (current_yy + 50) else 1900 + yy
        else:
            year = 2000 + yy if yy <= current_yy else 1900 + yy

        return date(year, mm, dd)
    except Exception:
        return None


def validate_passport_number(number: str) -> dict:
    clean = number.upper().replace(" ", "")
    ok = bool(re.match(r"^[A-Z][0-9]{7}$", clean))
    return {
        "field": "passport_number",
        "status": "passed" if ok else "flagged",
        "value": number,
        "explanation": f"Passport number '{number}' is {'valid' if ok else 'INVALID'} (expected 1 letter + 7 digits).",
    }


def validate_dob(dob_yymmdd: str) -> dict:
    parsed = parse_mrz_date(dob_yymmdd, is_expiry=False)
    if parsed is None:
        return {
            "field": "dob",
            "status": "flagged",
            "value": dob_yymmdd,
            "explanation": f"DOB '{dob_yymmdd}' could not be parsed.",
        }

    today = date.today()
    if parsed >= today:
        return {
            "field": "dob",
            "status": "flagged",
            "value": dob_yymmdd,
            "explanation": f"DOB {parsed} is in the future.",
        }

    age = (today - parsed).days // 365
    if age > 120:
        return {
            "field": "dob",
            "status": "flagged",
            "value": dob_yymmdd,
            "explanation": f"Age {age} is implausible.",
        }

    return {
        "field": "dob",
        "status": "passed",
        "value": str(parsed),
        "explanation": f"DOB {parsed} is valid (age ~{age}).",
    }


def validate_expiry(expiry_yymmdd: str) -> dict:
    parsed = parse_mrz_date(expiry_yymmdd, is_expiry=True)
    if parsed is None:
        return {
            "field": "expiry",
            "status": "flagged",
            "value": expiry_yymmdd,
            "explanation": f"Expiry '{expiry_yymmdd}' could not be parsed.",
        }

    today = date.today()
    if parsed < today:
        return {
            "field": "expiry",
            "status": "flagged",
            "value": str(parsed),
            "explanation": f"Document EXPIRED on {parsed}.",
        }

    return {
        "field": "expiry",
        "status": "passed",
        "value": str(parsed),
        "explanation": f"Document valid until {parsed}.",
    }


def validate_sex(sex: str) -> dict:
    valid = sex.upper() in ("M", "F", "X", "<")
    return {
        "field": "sex",
        "status": "passed" if valid else "flagged",
        "value": sex,
        "explanation": f"Sex '{sex}' is {'valid' if valid else 'INVALID'}.",
    }


def validate_country_code(code: str) -> dict:
    ok = bool(re.match(r"^[A-Z]{3}$", code.replace("<", "").strip()))
    return {
        "field": "country_code",
        "status": "passed" if ok else "flagged",
        "value": code,
        "explanation": f"Country code '{code}' is {'valid' if ok else 'INVALID'}.",
    }


def validate_document_fields(
    mrz_fields: dict, doc_type: str = "passport"
) -> dict:
    results = []

    if doc_type == "passport":
        results.append(
            validate_passport_number(mrz_fields.get("passport_number", ""))
        )
        results.append(validate_dob(mrz_fields.get("dob", "")))
        results.append(validate_expiry(mrz_fields.get("expiry", "")))
        results.append(validate_sex(mrz_fields.get("sex", "")))
        results.append(
            validate_country_code(mrz_fields.get("country_code", ""))
        )

    failures = [r for r in results if r["status"] == "flagged"]
    score = round(1.0 - (len(failures) / max(len(results), 1)), 2)

    return {
        "status": "passed" if not failures else "flagged",
        "score": score,
        "confidence": 0.95,
        "field_results": results,
        "failures": [r["field"] for r in failures],
        "explanation": (
            "All document fields are valid."
            if not failures
            else f"Validation failures: {', '.join(r['field'] for r in failures)}"
        ),
    }


def process_and_validate_image(image_path: str) -> dict:
    """Takes a user-provided image path, extracts MRZ data via OCR, and runs validation."""
    workspace_root = Path(__file__).resolve().parents[1]
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    from detectors.mrz_parser import parse_mrz
    from detectors.ocr_extraction import extract_text
    from detectors.ocr_mrz_consistency import _collect_mrz_lines

    path = Path(image_path)
    if not path.is_file():
        return {
            "status": "error",
            "score": 0.0,
            "explanation": f"File not found: '{image_path}'",
        }

    # Extract OCR data from user image
    ocr_raw = extract_text(str(path))
    mrz_lines = _collect_mrz_lines(
        ocr_raw if isinstance(ocr_raw, dict) else {}
    )

    if len(mrz_lines) < 2:
        return {
            "status": "flagged",
            "score": 0.0,
            "confidence": 0.0,
            "explanation": "No valid MRZ lines detected in the uploaded image.",
        }

    mrz_data = parse_mrz(mrz_lines)
    extracted_fields = (
        mrz_data.get("fields", {}) if isinstance(mrz_data, dict) else {}
    )

    return validate_document_fields(extracted_fields, doc_type="passport")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract and validate fields from a user-uploaded passport image."
    )
    parser.add_argument(
        "--image",
        required=False,
        help="Path to the document image file.",
    )
    args = parser.parse_args()

    # Prompt user for image path if not provided via CLI argument
    user_image_path = args.image
    if not user_image_path:
        user_image_path = input("Please enter the path to your document image: ").strip()

    validation_result = process_and_validate_image(user_image_path)
    print("\n--- Validation Results ---")
    print(json.dumps(validation_result, indent=2))
