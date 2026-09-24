import json
import sys
import os
import cv2
import numpy as np
import warnings

# Suppress ONNX and InsightFace stdout logging/warnings
os.environ["ORT_LOGGING_LEVEL"] = "3"
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

_FACE_APP = None

def _get_face_app():
    """Loads the InsightFace ArcFace model once and reuses it across calls."""
    global _FACE_APP
    if _FACE_APP is None:
        from insightface.app import FaceAnalysis
        _FACE_APP = FaceAnalysis(name='buffalo_l')
        _FACE_APP.prepare(ctx_id=-1, det_size=(640, 640))  # ctx_id=-1 -> CPU (no GPU assumed)
    return _FACE_APP


def _get_largest_face_embedding(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return None, "Could not read image file."

    app = _get_face_app()
    faces = app.get(img)

    if not faces:
        return None, "No face detected in image."

    # If multiple faces are found, use the largest bounding box (most likely the primary subject)
    largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest_face.normed_embedding, None  # already L2-normalized 512-D vector


_CASCADES = []

def _init_cascades():
    global _CASCADES
    if not _CASCADES:
        paths = [
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml',
            cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml',
            cv2.data.haarcascades + 'haarcascade_profileface.xml',
        ]
        for p in paths:
            if os.path.exists(p):
                c = cv2.CascadeClassifier(p)
                if not c.empty():
                    _CASCADES.append(c)

def check_face_presence(image_path):
    """
    Fast face detection for instantaneous kiosk feedback.
    Uses multi-cascade OpenCV check (frontal + alt + profile, ~20ms).
    Falls back to InsightFace if OpenCV cascades miss (e.g. angle / lighting).
    Returns (has_face: bool, message: str)
    """
    if not os.path.exists(image_path):
        return False, "File not found."

    img = cv2.imread(image_path)
    if img is None:
        return False, "Could not load image file."

    _init_cascades()

    gray = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 1. Ultra-fast OpenCV cascades
    for cascade in _CASCADES:
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(35, 35))
        if len(faces) > 0:
            return True, f"Face detected ({len(faces)} face(s) found)."

    # Try horizontally flipped gray image for profile cascade
    flipped_gray = cv2.flip(gray, 1)
    for cascade in _CASCADES:
        faces = cascade.detectMultiScale(flipped_gray, scaleFactor=1.1, minNeighbors=3, minSize=(35, 35))
        if len(faces) > 0:
            return True, f"Face detected ({len(faces)} face(s) found)."

    # 2. Secondary fallback with InsightFace if OpenCV missed
    try:
        app = _get_face_app()
        faces = app.get(img)
        if faces and len(faces) > 0:
            return True, f"Face detected via InsightFace ({len(faces)} face(s) found)."
    except Exception as e:
        print(f"[WARNING] InsightFace face check fallback skipped: {e}", file=sys.stderr)

    return False, "No face detected in the captured image. Please ensure your face is clearly visible and centered, then try again."




def run_face_verification(document_image_path, live_image_path):
    doc_embedding, doc_err = _get_largest_face_embedding(document_image_path)
    if doc_embedding is None:
        return {
            "detector_name": "face_verification",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Document image: {doc_err}",
            "status": "unavailable"
        }

    live_embedding, live_err = _get_largest_face_embedding(live_image_path)
    if live_embedding is None:
        return {
            "detector_name": "face_verification",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Live image: {live_err}",
            "status": "unavailable"
        }

    # Embeddings are already L2-normalized, so dot product = cosine similarity directly
    cosine_similarity = float(np.dot(doc_embedding, live_embedding))
    cosine_distance = 1.0 - cosine_similarity

    is_match = cosine_distance <= 0.4

    # Score convention matches the rest of the pipeline: HIGH score = risk/suspicious.
    # A face MISMATCH is the risk condition here, so a match gets a LOW score.
    score = 0.1 if is_match else 0.9

    return {
        "detector_name": "face_verification",
        "score": round(score, 2),
        "confidence": "high",
        "explanation": f"Cosine distance: {round(cosine_distance, 4)} (match threshold: 0.4). " +
                       ("Faces match \u2014 likely the same person." if is_match else "Faces do not match \u2014 possible impersonation."),
        "status": "passed" if is_match else "flagged"
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 face_verification_engine.py <document_image> <live_image>")
        sys.exit(1)
    result = run_face_verification(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
