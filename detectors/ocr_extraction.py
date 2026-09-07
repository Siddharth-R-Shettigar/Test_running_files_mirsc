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
    mrz_candidates = []
    for line in lines:
        cleaned = clean_mrz_text(line)
        if len(cleaned) >= 25:
            if cleaned.count('<') >= 2 or cleaned.startswith(('P<', 'I<', 'C<', 'V<', 'A<')):
                mrz_candidates.append(cleaned)
    return mrz_candidates


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
        mrz_candidates = extract_mrz_candidates(lines)
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
        print("\n--- Lines ---")
        for i, line in enumerate(result["lines"], 1):
            print(f"{i:02d}. {line}")
