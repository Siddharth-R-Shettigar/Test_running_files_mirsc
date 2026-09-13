"""
Document clarity checker (v2).

Changes vs. the original heuristic, and why:

1. Analysis resolution cap raised from 1000px -> 1800px (configurable).
   The old code always shrank the image to max-dimension 1000px before
   measuring sharpness. For a high-res scan/photo with small text, that
   throws away exactly the detail you need to tell "sharp" from "blurry".

2. Added an edge-density metric (adaptive Canny) alongside Laplacian
   variance and Tenengrad gradient magnitude.
   Edge density = (# edge pixels) / (total pixels), which is a
   percentage - it is naturally bounded 0-1 and far less sensitive to
   image scale/exposure than raw gradient magnitude. Documents have a
   fairly consistent "amount of edge" per unit area when in focus
   (character strokes, rules, borders), so this is a good scale-robust
   signal for this specific use case (unlike photos, which vary wildly
   in edge content by subject).

3. Laplacian variance is now normalized by the image's own contrast
   (variance / std_dev^2) instead of divided by a fixed constant (500).
   This removes sensitivity to lighting/exposure differences between
   captures (a dim photo of a sharp document was being scored as
   blurrier than a bright one under the old code).

4. Resolution scoring is now a smooth ramp instead of a hard floor.
   The old code only penalized images below 800x500 - a scan at
   801x501 and a scan at 8000x5000 got an identical res_factor of 1.0.
   Below the ramp's lower bound, res_factor -> 0; above the upper
   bound, res_factor -> 1. Tune MIN_OK_DIM / GOOD_DIM to your actual
   capture requirements (e.g. minimum legible dimension for your ID
   documents).

5. All the magic numbers are now named constants at the top of the
   file instead of buried inline, and there is a calibration script
   at the bottom (`calibrate`) that runs this scorer against two
   folders of your own labeled documents (clearly-fine vs
   clearly-reject) and reports the score distribution + best
   separating threshold - so `threshold=0.80` is a hard number you
   derive from your own data, not a doc-agnostic guess.

You should NOT trust the default constants below for production
without running `calibrate()` against a sample of your real captures
first - see bottom of file.
"""

import os
import glob
import cv2
import numpy as np

try:
    from detectors.ocr_extraction import extract_text
except Exception:
    extract_text = None

# ---- Tunable constants (calibrate these against your own document set) ----
ANALYSIS_MAX_DIM = 1800       # cap for the longer side during sharpness analysis
MIN_OK_DIM = 600              # shorter side at/below this -> res_factor 0
GOOD_DIM = 1200               # shorter side at/above this -> res_factor 1
LAP_NORM_DIVISOR = 2.5        # divisor for contrast-normalized Laplacian variance
EDGE_DENSITY_DIVISOR = 0.09   # expected edge-pixel fraction for a sharp document
TENENGRAD_DIVISOR = 220.0     # kept from original; re-check against your data
WEIGHT_LAP = 0.35
WEIGHT_EDGE = 0.35
WEIGHT_TENENGRAD = 0.30


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


def _smooth_res_factor(short_side):
    if short_side <= MIN_OK_DIM:
        return 0.0
    if short_side >= GOOD_DIM:
        return 1.0
    return (short_side - MIN_OK_DIM) / float(GOOD_DIM - MIN_OK_DIM)


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

    # -- Laplacian variance, normalized by the image's own contrast --
    lap = cv2.Laplacian(denoised, cv2.CV_64F)
    lap_var = float(np.var(lap))
    contrast = float(np.std(gray)) + 1e-6
    normalized_lap = lap_var / (contrast ** 2)
    sharpness_lap = _clamp(normalized_lap / LAP_NORM_DIVISOR)

    # -- Tenengrad (kept, same as original) --
    sobelx = cv2.Sobel(denoised, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(denoised, cv2.CV_64F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(sobelx, sobely)
    thresh = np.percentile(grad_mag, 90)
    high_gradients = grad_mag[grad_mag >= thresh]
    tenengrad_mean = float(np.mean(high_gradients)) if len(high_gradients) > 0 else 0.0
    sharpness_tenengrad = _clamp(tenengrad_mean / TENENGRAD_DIVISOR)

    # -- Edge density via adaptive (median-based) Canny --
    v = float(np.median(denoised))
    lower = int(max(0, 0.66 * v))
    upper = int(min(255, 1.33 * v))
    edges = cv2.Canny(denoised, lower, upper)
    edge_density = float(np.count_nonzero(edges)) / edges.size
    sharpness_edge = _clamp(edge_density / EDGE_DENSITY_DIVISOR)

    raw_sharpness = (WEIGHT_LAP * sharpness_lap
                      + WEIGHT_EDGE * sharpness_edge
                      + WEIGHT_TENENGRAD * sharpness_tenengrad)
    final_score = _clamp(raw_sharpness * res_factor)

    if debug:
        print(f"  dims={w}x{h} short_side={short_side} res_factor={res_factor:.3f}")
        print(f"  lap_var={lap_var:.2f} normalized_lap={normalized_lap:.3f} sharpness_lap={sharpness_lap:.3f}")
        print(f"  tenengrad_mean={tenengrad_mean:.2f} sharpness_tenengrad={sharpness_tenengrad:.3f}")
        print(f"  edge_density={edge_density:.4f} sharpness_edge={sharpness_edge:.3f}")
        print(f"  raw_sharpness={raw_sharpness:.3f} final_score={final_score:.3f}")

    return final_score


def _load_image(image_path):
    if not os.path.exists(image_path):
        return None, f"File does not exist: {image_path}"
    try:
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
        if img is not None:
            return img, None
    except Exception as e:
        return None, f"OpenCV read error: {e}"
    try:
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is not None:
            return img, None
    except Exception as e:
        return None, f"OpenCV fallback read error: {e}"
    try:
        with open(image_path, "rb") as f:
            raw = f.read()
        nparr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None:
            return img, None
    except Exception as e:
        return None, f"imdecode error: {e}"
    return None, f"Could not read image: {image_path}"


def check_image_clarity(image_path, threshold=0.80, debug=False):
    img, error = _load_image(image_path)
    if img is None:
        return {
            "status": "failed", "score": 0.0, "clarity_percent": 0.0,
            "band": "below 75%", "confidence": "low", "explanation": error,
        }

    try:
        if len(img.shape) == 4 or (len(img.shape) == 3 and img.shape[2] == 4):
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        heuristic_score = _heuristic_score(img, debug=debug)

        ocr_confidence = 0.0
        if extract_text is not None:
            try:
                ocr_result = extract_text(image_path) or {}
                ocr_confidence = _normalize_confidence(ocr_result.get("confidence", 0.0))
            except Exception:
                ocr_confidence = 0.0

        if ocr_confidence > 0:
            clarity_score = (0.6 * ocr_confidence) + (0.4 * heuristic_score)
        else:
            clarity_score = heuristic_score

        clarity_score = _clamp(clarity_score)
        clarity_percent = round(clarity_score * 100, 1)

        if clarity_percent >= 93:
            band, confidence = "93-100%", "high"
        elif clarity_percent >= 75:
            band, confidence = "75-93%", "medium"
        else:
            band, confidence = "below 75%", "low"

        status = "passed" if clarity_score >= threshold else "failed"

        if clarity_percent >= 93:
            explanation = f"Image clarity is {clarity_percent}% ({band}). Excellent quality. Proceeding."
        elif clarity_percent >= 75:
            explanation = (f"Image clarity is {clarity_percent}% ({band}). "
                            "Acceptable quality, but you may improve it for better OCR/classification accuracy.")
        else:
            explanation = f"Image clarity is {clarity_percent}% ({band}). Please rescan the image or upload it again."

        return {
            "status": status, "score": round(clarity_score, 3),
            "clarity_percent": clarity_percent, "band": band,
            "confidence": confidence, "explanation": explanation,
        }
    except Exception as e:
        return {
            "status": "failed", "score": 0.0, "clarity_percent": 0.0,
            "band": "below 75%", "confidence": "low",
            "explanation": f"Clarity check failed: {str(e)}",
        }


# ---------------------------------------------------------------------------
# Calibration harness.
#
# Point this at two folders of your OWN real documents:
#   good/  -> captures you know are fine to process (even if not perfect)
#   bad/   -> captures you know should be rejected (blurry/illegible)
#
# It prints the score distribution for each group and the threshold that
# best separates them, so you set `threshold=` from real data instead of
# guessing 0.80.
# ---------------------------------------------------------------------------
def calibrate(good_dir, bad_dir):
    def scores_for(folder):
        paths = sorted(sum([glob.glob(os.path.join(folder, ext))
                             for ext in ("*.jpg", "*.jpeg", "*.png")], []))
        out = []
        for p in paths:
            r = check_image_clarity(p, threshold=0.0)
            out.append((p, r["score"]))
        return out

    good_scores = scores_for(good_dir)
    bad_scores = scores_for(bad_dir)

    print("GOOD (should score high):")
    for p, s in good_scores:
        print(f"  {s:.3f}  {p}")
    print("BAD (should score low):")
    for p, s in bad_scores:
        print(f"  {s:.3f}  {p}")

    if not good_scores or not bad_scores:
        print("Need at least one file in each folder to calibrate.")
        return None

    g = [s for _, s in good_scores]
    b = [s for _, s in bad_scores]

    best_t, best_acc = 0.5, -1
    for t in np.arange(0.05, 0.96, 0.01):
        correct = sum(1 for x in g if x >= t) + sum(1 for x in b if x < t)
        acc = correct / (len(g) + len(b))
        if acc > best_acc:
            best_acc, best_t = acc, t

    print(f"\nGood scores: min={min(g):.3f} mean={np.mean(g):.3f} max={max(g):.3f}")
    print(f"Bad scores:  min={min(b):.3f} mean={np.mean(b):.3f} max={max(b):.3f}")
    print(f"Best separating threshold on this sample: {best_t:.2f} (accuracy={best_acc:.2%})")
    return best_t


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    check_p = sub.add_parser("check")
    check_p.add_argument("image_path")
    check_p.add_argument("--threshold", type=float, default=0.80)
    check_p.add_argument("--debug", action="store_true")

    cal_p = sub.add_parser("calibrate")
    cal_p.add_argument("good_dir")
    cal_p.add_argument("bad_dir")

    args = parser.parse_args()

    if args.cmd == "calibrate":
        calibrate(args.good_dir, args.bad_dir)
    else:
        # default to "check" for backward compatibility with the old CLI
        if args.cmd is None:
            parser.print_help()
        else:
            result = check_image_clarity(args.image_path, threshold=args.threshold, debug=args.debug)
            print(json.dumps(result, indent=2))