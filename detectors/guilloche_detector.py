"""
Guilloché / fine background pattern check (phone-capture aware, low confidence).
"""
import json
import sys
import cv2
import numpy as np


def run_guilloche_detector(image_path: str) -> dict:
    try:
        img = cv2.imread(image_path)
        if img is None:
            return {
                "detector_name": "guilloche_pattern",
                "score": 0.5,
                "confidence": "low",
                "explanation": "Could not load image for guilloché check.",
                "status": "unavailable",
            }

        h, w = img.shape[:2]
        if min(h, w) < 400:
            return {
                "detector_name": "guilloche_pattern",
                "score": 0.5,
                "confidence": "low",
                "explanation": "Image too small for reliable background pattern analysis.",
                "status": "unavailable",
            }

        # Prefer outer band (background) — avoid center face/text when possible
        margin_y, margin_x = int(h * 0.12), int(w * 0.08)
        band = img[margin_y : h - margin_y, margin_x : w - margin_x]
        if band.size == 0:
            band = img

        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        f = np.fft.fft2(gray.astype(np.float32))
        fshift = np.fft.fftshift(f)
        mag = np.log1p(np.abs(fshift))

        cy, cx = 256, 256
        y, x = np.ogrid[:512, :512]
        r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        # Mid-high ring: fine line patterns live away from DC
        mask = (r > 25) & (r < 180)
        energy = float(mag[mask].mean()) if mask.any() else 0.0
        # Normalize roughly from empirical phone scans
        integrity = max(0.0, min(1.0, (energy - 3.5) / 4.0))

        # Risk = lack of fine pattern structure
        risk = round(1.0 - integrity, 3)
        if risk < 0.4:
            status = "passed"
        elif risk < 0.65:
            status = "flagged"
        else:
            status = "flagged"

        return {
            "detector_name": "guilloche_pattern",
            "score": risk,
            "confidence": "low",  # phone JPEG + security print is fragile
            "explanation": (
                f"Background frequency energy={energy:.2f}, pattern integrity≈{integrity:.2f}. "
                "Single-frame phone capture; sensitive to focus and compression."
            ),
            "status": status,
        }
    except Exception as e:
        return {
            "detector_name": "guilloche_pattern",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Guilloché check failed: {e}",
            "status": "failed",
        }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "test.jpg"
    print(json.dumps(run_guilloche_detector(path), indent=2))