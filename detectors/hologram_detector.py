"""
Single-frame hologram / foil proxy. Cannot prove kinegram without tilt.
"""
import json
import sys
import cv2
import numpy as np


def run_hologram_detector(image_path: str) -> dict:
    try:
        img = cv2.imread(image_path)
        if img is None:
            return {
                "detector_name": "hologram_shift",
                "score": 0.5,
                "confidence": "low",
                "explanation": "Could not load image for hologram proxy check.",
                "status": "unavailable",
            }

        h, w = img.shape[:2]
        # Heuristic: upper-right / mid band often holds visa foil — weak assumption
        y0, y1 = int(h * 0.15), int(h * 0.55)
        x0, x1 = int(w * 0.45), int(w * 0.95)
        roi = img[y0:y1, x0:x1]
        if roi.size == 0:
            roi = img

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h_ch, s_ch, v_ch = cv2.split(hsv)

        sat_std = float(np.std(s_ch))
        val_std = float(np.std(v_ch))
        hue_std = float(np.std(h_ch))

        # Foil-ish regions often show higher local sat/val variation
        foil_proxy = max(0.0, min(1.0, (sat_std / 40.0) * 0.5 + (val_std / 45.0) * 0.5))
        risk = round(1.0 - foil_proxy, 3)

        return {
            "detector_name": "hologram_shift",
            "score": risk,
            "confidence": "low",
            "explanation": (
                f"Single-frame foil proxy (sat_std={sat_std:.1f}, val_std={val_std:.1f}, "
                f"hue_std={hue_std:.1f}). True kinegram needs multi-angle capture; "
                "this is not a lab hologram verification."
            ),
            "status": "passed" if risk < 0.55 else "flagged",
        }
    except Exception as e:
        return {
            "detector_name": "hologram_shift",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Hologram proxy failed: {e}",
            "status": "failed",
        }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "test.jpg"
    print(json.dumps(run_hologram_detector(path), indent=2))