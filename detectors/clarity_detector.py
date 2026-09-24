"""
Document clarity checker – final balanced version
"""

import os
import glob
import cv2
import numpy as np

try:
    from detectors.ocr_extraction import extract_text
except Exception:
    extract_text = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ANALYSIS_MAX_DIM = 1800

MIN_OK_DIM = 220
GOOD_DIM   = 1100

LAP_NORM_DIVISOR     = 0.022
EDGE_DENSITY_DIVISOR = 0.009
TENENGRAD_DIVISOR    = 85.0

WEIGHT_LAP       = 0.22
WEIGHT_EDGE      = 0.39
WEIGHT_TENENGRAD = 0.39

THRESHOLD_EXCELLENT  = 0.93
THRESHOLD_ACCEPTABLE = 0.60


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _normalize_confidence(value):
    if value is None:
        return 0.0
    try:
        value = float(value)
    except Exception:
        return 0.0
    if value > 1.0:
        value = value / 100.0
    return _clamp(value)



# Checkpoints the resolution curve is designed to pass through exactly.
# A single linear ramp cannot satisfy all four (slope must decrease at
# each stage — diminishing returns as resolution increases), so we
# interpolate piecewise between them instead.
_RES_FACTOR_CHECKPOINTS = [
    (MIN_OK_DIM, 0.42),   # 220 px -> tiny/unusable scan
    (400,        0.78),
    (620,        0.88),
    (GOOD_DIM,   1.00),   # 1100 px -> full quality, no penalty
]


def _smooth_res_factor(short_side: int) -> float:
    """
    Balanced resolution factor, matching documented checkpoints exactly:
    - ≤ 220 px   → 0.42 (tiny visa rejected)
    - 400 px     → 0.78
    - 620 px     → 0.88
    - ≥ 1100 px  → 1.00
    Linearly interpolated between checkpoints (not a single straight
    line across the whole range).
    """
    points = _RES_FACTOR_CHECKPOINTS

    if short_side <= points[0][0]:
        return points[0][1]
    if short_side >= points[-1][0]:
        return points[-1][1]

    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= short_side <= x1:
            frac = (short_side - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)

    # Unreachable given the checks above, but keep a safe fallback.
    return points[-1][1]


def _heuristic_score(img, debug=False):
    h, w = img.shape[:2]
    short_side = min(h, w)
    res_factor = _smooth_res_factor(short_side)

    scale = ANALYSIS_MAX_DIM / max(h, w)
    if scale < 1.0:
        img_analyzed = cv2.resize(img, (int(w * scale), int(h * scale)),
                                  interpolation=cv2.INTER_AREA)
    else:
        img_analyzed = img

    gray = cv2.cvtColor(img_analyzed, cv2.COLOR_BGR2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)

    # Laplacian with soft floor (protects soft high-res photos)
    lap = cv2.Laplacian(denoised, cv2.CV_64F)
    lap_var = float(np.var(lap))
    contrast = float(np.std(gray)) + 1e-6
    normalized_lap = lap_var / (contrast ** 2)
    sharpness_lap = _clamp(max(normalized_lap / LAP_NORM_DIVISOR, 0.42))

    # Tenengrad
    sobelx = cv2.Sobel(denoised, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(denoised, cv2.CV_64F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(sobelx, sobely)
    thresh = np.percentile(grad_mag, 90)
    high_gradients = grad_mag[grad_mag >= thresh]
    tenengrad_mean = float(np.mean(high_gradients)) if len(high_gradients) > 0 else 0.0
    sharpness_tenengrad = _clamp(tenengrad_mean / TENENGRAD_DIVISOR)

    # Edge density
    v = float(np.median(denoised))
    lower = int(max(0, 0.66 * v))
    upper = int(min(255, 1.33 * v))
    edges = cv2.Canny(denoised, lower, upper)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    sharpness_edge = _clamp(edge_density / EDGE_DENSITY_DIVISOR)

    raw_sharpness = (
        WEIGHT_LAP * sharpness_lap +
        WEIGHT_EDGE * sharpness_edge +
        WEIGHT_TENENGRAD * sharpness_tenengrad
    )
    final_score = _clamp(raw_sharpness * res_factor)

    if debug:
        print(f"  dims={w}x{h}  short_side={short_side}  res_factor={res_factor:.3f}")
        print(f"  lap_var={lap_var:.1f}  contrast={contrast:.1f}  "
              f"normalized_lap={normalized_lap:.3f} → lap={sharpness_lap:.3f}")
        print(f"  tenengrad_mean={tenengrad_mean:.1f} → ten={sharpness_tenengrad:.3f}")
        print(f"  edge_density={edge_density:.4f} → edge={sharpness_edge:.3f}")
        print(f"  raw_sharpness={raw_sharpness:.3f}  final={final_score:.3f}")

    return final_score


def _load_image(image_path):
    if not os.path.exists(image_path):
        return None, f"File does not exist: {image_path}"
    try:
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            return img, None
    except Exception:
        pass
    try:
        with open(image_path, "rb") as f:
            raw = f.read()
        nparr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None:
            return img, None
    except Exception as e:
        return None, f"Could not read image: {e}"
    return None, f"Could not read image: {image_path}"


def check_image_clarity(image_path, debug=False):
    img, error = _load_image(image_path)
    if img is None:
        return {
            "status": "failed", "score": 0.0, "clarity_percent": 0.0,
            "band": "below 60%", "action": "reject", "confidence": "low",
            "explanation": error,
        }

    try:
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        heuristic_score = _heuristic_score(img, debug=debug)

        ocr_confidence = 0.0
        if extract_text is not None:
            try:
                ocr_result = extract_text(image_path) or {}
                ocr_confidence = _normalize_confidence(ocr_result.get("confidence", 0.0))
            except Exception:
                ocr_confidence = 0.0

        if ocr_confidence > 0:
            clarity_score = 0.55 * heuristic_score + 0.45 * ocr_confidence
        else:
            clarity_score = heuristic_score

        clarity_score = _clamp(clarity_score)
        clarity_percent = round(clarity_score * 100, 1)

        if clarity_percent >= 93:
            band, action, status, confidence = "93-100%", "paddle_only", "passed", "high"
            explanation = (f"Image clarity is {clarity_percent}% ({band}). "
                           "Excellent quality – running PaddleOCR only.")
        elif clarity_percent >= 60:
            band, action, status, confidence = "60-93%", "paddle_plus_ai", "passed", "medium"
            explanation = (f"Image clarity is {clarity_percent}% ({band}). "
                           "Acceptable quality – running PaddleOCR + AI post-processing.")
        else:
            band, action, status, confidence = "below 60%", "reject", "failed", "low"
            explanation = (f"Image clarity is {clarity_percent}% ({band}). "
                           "Quality too low for reliable OCR. Please rescan or re-upload a sharper, higher-resolution image.")

        return {
            "status": status,
            "score": round(clarity_score, 3),
            "clarity_percent": clarity_percent,
            "band": band,
            "action": action,
            "confidence": confidence,
            "explanation": explanation,
        }

    except Exception as e:
        return {
            "status": "failed", "score": 0.0, "clarity_percent": 0.0,
            "band": "below 60%", "action": "reject", "confidence": "low",
            "explanation": f"Clarity check failed: {str(e)}",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] not in ("check", "calibrate", "-h", "--help"):
        sys.argv.insert(1, "check")

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check")
    check_p.add_argument("image_path")
    check_p.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    if args.cmd == "check":
        result = check_image_clarity(args.image_path, debug=args.debug)
        print(json.dumps(result, indent=2))