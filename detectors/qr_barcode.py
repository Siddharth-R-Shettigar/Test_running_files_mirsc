import json
import os
import cv2
from pyzbar.pyzbar import decode


def preprocess_for_barcodes(img):
    """Generates variants to improve decode success rate on degraded images."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    yield img
    yield gray
    # Contrast stretching / OTSU thresholding for low-contrast scans
    yield cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]


def read_qr_barcodes(image_path: str) -> list:
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at path: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"cv2 could not load image: {image_path}")

    decoded_objects = []
    seen_payloads = set()

    # Try preprocessing passes until at least one barcode is detected
    for processed in preprocess_for_barcodes(img):
        found = decode(processed)
        for obj in found:
            if obj.data not in seen_payloads:
                seen_payloads.add(obj.data)
                decoded_objects.append(obj)
        if decoded_objects:
            break

    results = []
    for obj in decoded_objects:
        try:
            data = obj.data.decode("utf-8")
        except UnicodeDecodeError:
            data = obj.data.decode("latin-1", errors="replace")

        results.append({
            "type": obj.type,
            "raw_bytes": obj.data,
            "data": data,
            "rect": {
                "x": obj.rect.left,
                "y": obj.rect.top,
                "w": obj.rect.width,
                "h": obj.rect.height,
            },
        })
    return results


def parse_payload(raw_data: str) -> dict:
    """Attempts JSON decoding, then falls back to delimited token parsing."""
    try:
        return json.loads(raw_data)
    except Exception:
        pass

    # Fallback for plain-text delimited formats (e.g. PDF417 lines or MRZ lines)
    tokens = {}
    lines = raw_data.splitlines()
    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
            tokens[k.strip().lower()] = v.strip()
    return tokens


def check_qr_consistency(image_path: str, ocr_fields: dict) -> dict:
    try:
        qr_data = read_qr_barcodes(image_path)
    except Exception as e:
        return {
            "status": "error",
            "score": 0.0,
            "confidence": 0.0,
            "qr_found": False,
            "error": str(e),
        }

    if not qr_data:
        return {
            "status": "unavailable",
            "score": 0.5,
            "confidence": 0.3,
            "qr_found": False,
            "explanation": "No QR code or barcode detected."
        }

    mismatches = []
    comparisons = []
    parsed_any = False

    for qr_item in qr_data:
        raw = qr_item["data"]
        qr_parsed = parse_payload(raw)

        if not qr_parsed:
            # Fallback: check if OCR fields appear as substrings in the raw payload
            ocr_surname = ocr_fields.get("surname", "").strip().upper()
            if ocr_surname:
                match = ocr_surname in raw.upper()
                comparisons.append({"field": "surname", "qr": "[raw_text]", "ocr": ocr_surname, "match": match})
                if not match:
                    mismatches.append("surname")
            continue

        parsed_any = True

        # Check Name / Surname
        if "name" in qr_parsed or "surname" in qr_parsed:
            qr_name = str(qr_parsed.get("name") or qr_parsed.get("surname", "")).upper()
            ocr_name = (ocr_fields.get("surname", "") + " " + ocr_fields.get("given_names", "")).strip().upper()
            match = qr_name in ocr_name or ocr_name in qr_name
            comparisons.append({"field": "name", "qr": qr_name, "ocr": ocr_name, "match": match})
            if not match:
                mismatches.append("name")

        # Check DOB
        if "dob" in qr_parsed:
            qr_dob = str(qr_parsed["dob"]).replace("-", "").replace("/", "")
            ocr_dob = str(ocr_fields.get("dob", "")).replace("-", "").replace("/", "")
            match = qr_dob == ocr_dob
            comparisons.append({"field": "dob", "qr": qr_dob, "ocr": ocr_dob, "match": match})
            if not match:
                mismatches.append("dob")

    if not comparisons:
        return {
            "status": "unverified",
            "score": 0.5,
            "confidence": 0.4,
            "qr_found": True,
            "qr_count": len(qr_data),
            "explanation": "Barcode detected, but payload schema did not contain recognizable matching fields."
        }

    score = 1.0 - (len(mismatches) / len(comparisons))

    return {
        "status": "passed" if not mismatches else "flagged",
        "score": round(score, 2),
        "confidence": 0.85,
        "qr_found": True,
        "qr_count": len(qr_data),
        "comparisons": comparisons,
        "mismatches": mismatches,
        "explanation": (
            "Barcode/QR data matches visible fields." if not mismatches
            else f"Mismatches detected in: {', '.join(mismatches)}"
        )
    }
if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python3 test.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]

    result = check_qr_consistency(image_path, {})

    print(json.dumps(result, indent=2, default=str))
