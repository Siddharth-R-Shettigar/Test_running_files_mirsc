# detectors/ocr_extraction.py

import os
import re
import cv2
import argparse
import numpy as np
from paddleocr import PaddleOCR

_reader = None

def get_reader():
    global _reader
    if _reader is None:
        _reader = PaddleOCR(
            lang='en',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,   # turn this off for now
            enable_mkldnn=False,              # important
            device="cpu"
        )
    return _reader

def clean_mrz_text(raw_text: str) -> str:
    cleaned = raw_text.upper().replace(" ", "")
    cleaned = re.sub(r'[«\(\{\[\<_\-\–\—\~]', '<', cleaned)
    cleaned = re.sub(r'[^A-Z0-9<]', '', cleaned)
    return cleaned


def extract_mrz_candidates(lines: list) -> list:
    """
    First pass: look for lines that already look like a full MRZ line
    on their own (len >= 25 and enough '<' or a leading document-type char).
    """
    mrz_candidates = []
    for line in lines:
        cleaned = clean_mrz_text(line)
        if len(cleaned) >= 25:
            if cleaned.count('<') >= 2 or cleaned.startswith(('P<', 'I<', 'C<', 'V<', 'A<')):
                mrz_candidates.append(cleaned)
            # Fallback: MRZ line 2 (numbers/dates/checksums) can end up with
            # very few or zero '<' if OCR drops the filler character entirely.
            # Accept it if it's overwhelmingly alnum with a high digit ratio.
            elif sum(c.isdigit() for c in cleaned) >= 10:
                mrz_candidates.append(cleaned)
    return mrz_candidates


def _group_fields_into_rows(fields: list, y_tolerance_ratio: float = 0.6) -> list:
    """
    PaddleOCR's text detector returns one box per detected text region, not
    necessarily one box per printed line. Long, dense monospaced text (like
    the MRZ block at the bottom of a passport) frequently gets split across
    several boxes. This reconstructs full rows by grouping fields whose
    vertical spans overlap, then joining them left-to-right by x position.

    Returns a list of reconstructed row strings (raw, uncleaned).
    """
    if not fields:
        return []

    # Sort by vertical position first so nearby rows end up adjacent.
    boxes = []
    for f in fields:
        bb = f.get("bounding_box", {})
        y1, y2 = bb.get("y1", 0), bb.get("y2", 0)
        x1 = bb.get("x1", 0)
        text = f.get("text", "")
        if not text:
            continue
        height = max(y2 - y1, 1)
        y_center = (y1 + y2) / 2
        boxes.append({
            "text": text,
            "x1": x1,
            "y_center": y_center,
            "height": height,
        })

    boxes.sort(key=lambda b: b["y_center"])

    rows = []
    used = [False] * len(boxes)

    for i, b in enumerate(boxes):
        if used[i]:
            continue
        tolerance = b["height"] * y_tolerance_ratio
        row = [b]
        used[i] = True
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            if abs(boxes[j]["y_center"] - b["y_center"]) <= tolerance:
                row.append(boxes[j])
                used[j] = True
        row.sort(key=lambda b: b["x1"])
        row_text = "".join(item["text"] for item in row)
        rows.append(row_text)

    return rows


def extract_text(image_path: str) -> dict:
    if not os.path.exists(image_path):
        return {
            "status": "failed",
            "score": 0.0,
            "confidence": 0.0,
            "full_text": "",
            "lines": [],
            "fields": [],
            "mrz_lines": [],
            "explanation": f"File does not exist: {image_path}"
        }

    try:
        reader = get_reader()

        # === NEW API ===
        result = reader.predict(image_path)

        fields = []
        lines = []
        all_texts = []

        if result:
            # result is a list of page results
            page = result[0]

            # New structure in PaddleOCR 3.x
            rec_texts = page.get("rec_texts", [])
            rec_scores = page.get("rec_scores", [])
            rec_boxes  = page.get("rec_boxes", [])

            for text, score, box in zip(rec_texts, rec_scores, rec_boxes):
                text = str(text).strip()
                if not text:
                    continue

                all_texts.append(text)
                lines.append(text)

                # Convert box to simple x1,y1,x2,y2
                try:
                    xs = [pt[0] for pt in box]
                    ys = [pt[1] for pt in box]
                    x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
                except:
                    x1 = y1 = x2 = y2 = 0

                fields.append({
                    "text": text,
                    "confidence": round(float(score), 3),
                    "bounding_box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
                })

        full_text = " ".join(all_texts)

        # Pass 1: check raw detected lines individually.
        mrz_candidates = extract_mrz_candidates(lines)

        # Pass 2: reconstruct rows from bounding boxes in case the MRZ line
        # was split across multiple detection boxes, then check those too.
        reconstructed_rows = _group_fields_into_rows(fields)
        mrz_candidates += extract_mrz_candidates(reconstructed_rows)

        # De-duplicate while preserving order.
        seen = set()
        uniq_mrz = []
        for c in mrz_candidates:
            if c not in seen:
                seen.add(c)
                uniq_mrz.append(c)
        mrz_candidates = uniq_mrz

        avg_conf = round(float(np.mean([f["confidence"] for f in fields])), 3) if fields else 0.0

        return {
            "status": "passed" if fields else "failed",
            "score": 1.0 if fields else 0.0,
            "confidence": avg_conf,
            "full_text": full_text,
            "lines": lines,
            "fields": fields,
            "mrz_lines": mrz_candidates,
            "explanation": f"Extracted {len(fields)} tokens. Found {len(mrz_candidates)} MRZ candidates."
        }

    except Exception as e:
        return {
            "status": "failed",
            "score": 0.0,
            "confidence": 0.0,
            "full_text": "",
            "lines": [],
            "fields": [],
            "mrz_lines": [],
            "explanation": f"OCR error: {str(e)}"
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--image", required=True, help="Path to image")
    args = parser.parse_args()

    result = extract_text(args.image)

    print("\n=== OCR RESULT ===")
    print(f"Status      : {result['status']}")
    print(f"Confidence  : {result['confidence']}")
    print(f"Lines found : {len(result['lines'])}")
    print(f"MRZ lines   : {result['mrz_lines']}")
    print(f"Explanation : {result['explanation']}")
    print("\n--- Full Text ---")
    print(result["full_text"] if result["full_text"] else "(empty)")

    if result["lines"]:
        print("\n--- Lines (raw, as detected by PaddleOCR) ---")
        for i, line in enumerate(result["lines"], 1):
            print(f"{i:02d}. {line}")