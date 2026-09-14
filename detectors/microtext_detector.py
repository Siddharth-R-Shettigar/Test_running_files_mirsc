import cv2
import numpy as np
import sys
import json

def detect_microtext(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return {"error": "Could not load image"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Apply FFT to find high frequency content
    f = np.fft.fft2(gray)
    fshift = np.fft.fftshift(f)
    magnitude = np.abs(fshift)

    rows, cols = gray.shape
    crow, ccol = rows // 2, cols // 2
    radius = min(rows, cols) // 8

    y, x = np.ogrid[:rows, :cols]
    low_mask = (x - ccol)**2 + (y - crow)**2 <= radius**2
    high_mask = ~low_mask

    low_energy = np.sum(magnitude[low_mask])
    high_energy = np.sum(magnitude[high_mask])
    total_energy = low_energy + high_energy

    high_freq_ratio = high_energy / total_energy if total_energy > 0 else 0

    # Edge detection — microtext has dense fine edges
    edges = cv2.Canny(gray, 100, 200)
    edge_density = np.sum(edges > 0) / (rows * cols)

    # Zoom into center region for microtext analysis
    h, w = gray.shape
    center_crop = gray[h//4:3*h//4, w//4:3*w//4]
    center_edges = cv2.Canny(center_crop, 150, 250)
    center_edge_density = np.sum(center_edges > 0) / center_crop.size

    # Local variance — microtext creates high local variance
    kernel = np.ones((5, 5), np.float32) / 25
    local_mean = cv2.filter2D(gray.astype(np.float32), -1, kernel)
    local_variance = np.mean((gray.astype(np.float32) - local_mean) ** 2)

    has_microtext = bool(
        high_freq_ratio > 0.25 and
        edge_density > 0.04 and
        local_variance > 100
    )

    confidence = round(min(100, (
        high_freq_ratio * 60 +
        edge_density * 500 +
        min(local_variance / 10, 20)
    )), 2)

    return {
        "image": image_path,
        "high_frequency_ratio": round(float(high_freq_ratio), 4),
        "edge_density": round(float(edge_density), 4),
        "center_edge_density": round(float(center_edge_density), 4),
        "local_variance": round(float(local_variance), 2),
        "microtext_detected": has_microtext,
        "verdict": "MICROTEXT PRESENT — document likely genuine" if has_microtext else "NO MICROTEXT — possible fake or low resolution scan",
        "confidence": confidence
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 microtext_detector.py <image_path>")
        sys.exit(1)

    result = detect_microtext(sys.argv[1])
    print(json.dumps(result, indent=2))

def run_microtext_detector(image_path: str) -> dict:
    try:
        raw = detect_microtext(image_path)
        if not isinstance(raw, dict) or raw.get("error"):
            return {
                "detector_name": "microtext_analysis",
                "score": 0.5,
                "confidence": "low",
                "explanation": str(raw.get("error", raw)),
                "status": "unavailable",
            }
        present = bool(raw.get("microtext_detected"))
        # Risk high if microtext NOT present
        score = 0.25 if present else 0.7
        conf_num = float(raw.get("confidence", 50))
        conf = "high" if conf_num >= 70 else ("medium" if conf_num >= 40 else "low")
        return {
            "detector_name": "microtext_analysis",
            "score": score,
            "confidence": "low",  # force low for phone
            "explanation": raw.get("verdict", "Microtext check complete."),
            "status": "passed" if present else "flagged",
        }
    except Exception as e:
        return {
            "detector_name": "microtext_analysis",
            "score": 0.5,
            "confidence": "low",
            "explanation": str(e),
            "status": "failed",
        }