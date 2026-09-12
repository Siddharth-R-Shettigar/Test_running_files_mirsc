import os
import cv2
import numpy as np

try:
    from detectors.ocr_extraction import extract_text
except Exception:
    extract_text = None


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


def _heuristic_score(img):
    h, w = img.shape[:2]
    
    # 1. Penalize low-resolution inputs directly
    min_w, min_h = 800, 500
    res_factor = 1.0
    if w < min_w or h < min_h:
        res_factor = min(w / min_w, h / min_h)

    # Standardize image size for invariant calculations
    target_dim = 1000.0
    scale = target_dim / max(h, w)
    if scale < 1.0:
        img_resized = cv2.resize(
            img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
        )
    else:
        img_resized = img

    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

    # 2. Apply Gaussian Blur to eliminate JPEG compression artifacts and pixelation noise
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)

    # 3. Laplacian Variance on Denoised Image (Global Sharpness)
    lap = cv2.Laplacian(denoised, cv2.CV_64F)
    lap_var = float(np.var(lap))
    sharpness_lap = _clamp(lap_var / 500.0)

    # 4. Tenengrad Gradient Magnitude on Denoised Image
    sobelx = cv2.Sobel(denoised, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(denoised, cv2.CV_64F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(sobelx, sobely)

    thresh = np.percentile(grad_mag, 90)
    high_gradients = grad_mag[grad_mag >= thresh]
    tenengrad_mean = float(np.mean(high_gradients)) if len(high_gradients) > 0 else 0.0
    sharpness_tenengrad = _clamp(tenengrad_mean / 220.0)

    # 5. Combine Sharpness Metrics and scale by resolution quality factor
    raw_sharpness = (0.5 * sharpness_lap) + (0.5 * sharpness_tenengrad)
    final_score = raw_sharpness * res_factor

    return _clamp(final_score)

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


def check_image_clarity(image_path, threshold=0.80):
    img, error = _load_image(image_path)
    if img is None:
        return {
            "status": "failed",
            "score": 0.0,
            "clarity_percent": 0.0,
            "band": "below 75%",
            "confidence": "low",
            "explanation": error,
        }

    try:
        if len(img.shape) == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        heuristic_score = _heuristic_score(img)

        ocr_confidence = 0.0
        if extract_text is not None:
            try:
                ocr_result = extract_text(image_path) or {}
                ocr_confidence = _normalize_confidence(
                    ocr_result.get("confidence", 0.0)
                )
            except Exception:
                ocr_confidence = 0.0

        # Weighted blend when OCR confidence is available
        if ocr_confidence > 0:
            clarity_score = (0.6 * ocr_confidence) + (0.4 * heuristic_score)
        else:
            clarity_score = heuristic_score

        clarity_score = _clamp(clarity_score)
        clarity_percent = round(clarity_score * 100, 1)

        if clarity_percent >= 93:
            band = "93-100%"
            confidence = "high"
        elif clarity_percent >= 75:
            band = "75-93%"
            confidence = "medium"
        else:
            band = "below 75%"
            confidence = "low"

        status = "passed" if clarity_score >= threshold else "failed"

        if clarity_percent >= 93:
            explanation = (
                f"Image clarity is {clarity_percent}% ({band}). "
                "Excellent quality. Proceeding."
            )
        elif clarity_percent >= 75:
            explanation = (
                f"Image clarity is {clarity_percent}% ({band}). "
                "Acceptable quality, but you may improve it for better OCR/classification accuracy."
            )
        else:
            explanation = (
                f"Image clarity is {clarity_percent}% ({band}). "
                "Please rescan the image or upload it again."
            )

        return {
            "status": status,
            "score": round(clarity_score, 3),
            "clarity_percent": clarity_percent,
            "band": band,
            "confidence": confidence,
            "explanation": explanation,
        }

    except Exception as e:
        return {
            "status": "failed",
            "score": 0.0,
            "clarity_percent": 0.0,
            "band": "below 75%",
            "confidence": "low",
            "explanation": f"Clarity check failed: {str(e)}",
        }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("image_path", help="Path to the image file")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Clarity threshold (0.0 to 1.0)",
    )
    args = parser.parse_args()

    result = check_image_clarity(args.image_path, threshold=args.threshold)
    print(json.dumps(result, indent=2))