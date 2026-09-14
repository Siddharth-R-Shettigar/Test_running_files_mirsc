import cv2
import numpy as np
import sys
import json

def analyze_gradient(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return {"error": "Could not load image"}

    # Convert to HSV for color analysis
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue_channel = hsv[:, :, 0]

    # Analyze hue gradient smoothness column by column
    col_means = [np.mean(hue_channel[:, c]) for c in range(hue_channel.shape[1])]
    col_means = np.array(col_means)

    # Calculate smoothness — genuine rainbow print has smooth transitions
    diffs = np.abs(np.diff(col_means))
    avg_diff = np.mean(diffs)
    max_diff = np.max(diffs)

    # Genuine rainbow print: low avg_diff, no sudden jumps
    # CMYK fake: high avg_diff, blocky transitions
    smoothness_score = max(0, 100 - (avg_diff * 10))
    has_gradient = bool(np.std(col_means) > 5)
    is_genuine = bool(avg_diff < 3.0 and max_diff < 15.0 and has_gradient)

    return {
        "image": image_path,
        "has_color_gradient": has_gradient,
        "smoothness_score": round(smoothness_score, 2),
        "avg_hue_transition": round(float(avg_diff), 4),
        "max_hue_jump": round(float(max_diff), 4),
        "verdict": "GENUINE GRADIENT" if is_genuine else "SUSPICIOUS — possible CMYK print",
        "confidence": round(smoothness_score, 2)
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rainbow_gradient_detector.py <image_path>")
        sys.exit(1)

    result = analyze_gradient(sys.argv[1])
    print(json.dumps(result, indent=2))