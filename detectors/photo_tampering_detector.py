import json
import sys
import os
import tempfile
import warnings

import cv2
import numpy as np

# Quiet noisy logs from InsightFace / ONNX
os.environ["ORT_LOGGING_LEVEL"] = "3"
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from detectors.ela_detector import run_ela_detector
from detectors.resampling_detector import run_resampling_detector

from detectors.face_app_singleton import get_face_app as _get_face_app

def _largest_face_box(image_bgr, pad_ratio=0.15):
    """
    Find faces; return (x1, y1, x2, y2) for the largest one,
    with a little padding so the crop includes the photo edge.
    Returns None if no face is found.
    """
    app = _get_face_app()
    faces = app.get(image_bgr)
    if not faces:
        return None

    largest = max(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )
    x1, y1, x2, y2 = [int(v) for v in largest.bbox]

    h, w = image_bgr.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    pad_x = int(bw * pad_ratio)
    pad_y = int(bh * pad_ratio)

    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)

    # Reject tiny crops (noise / bad detection)
    if (x2 - x1) < 20 or (y2 - y1) < 20:
        return None

    return x1, y1, x2, y2


def _combine_scores(ela_result, res_result):
    """
    Build one score from ELA + resampling results.
    Higher score = more suspicious photo patch.
    """
    ela_ok = ela_result.get("confidence") != "low"
    res_ok = res_result.get("confidence") != "low"

    ela_score = float(ela_result.get("score", 0.5))
    res_score = float(res_result.get("score", 0.5))

    if ela_ok and res_ok:
        # Average; both ran cleanly
        combined = (ela_score + res_score) / 2.0
        confidence = "high"
    elif ela_ok:
        combined = ela_score
        confidence = "medium"
    elif res_ok:
        combined = res_score
        confidence = "medium"
    else:
        combined = 0.5
        confidence = "low"

    combined = round(min(max(combined, 0.0), 1.0), 3)

    if confidence == "low":
        status = "failed"
    elif combined >= 0.4:
        status = "flagged"
    else:
        status = "passed"

    explanation = (
        f"Photo-patch forensics on document face crop. "
        f"ELA score={ela_score} ({ela_result.get('explanation', '')[:80]}). "
        f"Resampling score={res_score} ({res_result.get('explanation', '')[:80]})."
    )

    return combined, confidence, status, explanation


def run_photo_tampering_detector(image_path):
    """
    Standard KAVACH entry point.

    1) Detect face on the ID document
    2) Crop that region
    3) Run existing ELA + resampling on the crop only
    4) Return the standard 5-field dictionary
    """
    temp_path = None
    try:
        if not os.path.exists(image_path):
            return {
                "detector_name": "photo_patch_forensics",
                "score": 0.5,
                "confidence": "low",
                "explanation": f"File not found: {image_path}",
                "status": "failed",
            }

        img = cv2.imread(image_path)
        if img is None:
            return {
                "detector_name": "photo_patch_forensics",
                "score": 0.5,
                "confidence": "low",
                "explanation": "Could not read image file.",
                "status": "failed",
            }

        box = _largest_face_box(img)
        if box is None:
            return {
                "detector_name": "photo_patch_forensics",
                "score": 0.5,
                "confidence": "low",
                "explanation": "No face detected on document; photo-patch forensics skipped.",
                "status": "unavailable",
            }

        x1, y1, x2, y2 = box
        crop = img[y1:y2, x1:x2]

        # ELA / resampling expect a file path, so write a temporary JPEG
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        cv2.imwrite(temp_path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

        ela_result = run_ela_detector(temp_path)
        res_result = run_resampling_detector(temp_path)

        score, confidence, status, explanation = _combine_scores(ela_result, res_result)

        return {
            "detector_name": "photo_patch_forensics",
            "score": score,
            "confidence": confidence,
            "explanation": explanation,
            "status": status,
        }

    except Exception as e:
        return {
            "detector_name": "photo_patch_forensics",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Photo-patch forensics failed: {str(e)}",
            "status": "failed",
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join("test_images", "real", "Real.jpg")
    result = run_photo_tampering_detector(target)
    print(json.dumps(result, indent=2))