"""
detectors/duplicate_id_detector.py
------------------------------------
Prevents identity fraud where the same face is registered under
different individual details (i.e. the same person trying to enroll
under multiple ID records).

How it works:
1. Keeps a local JSON store of previously-seen face embeddings, each
   tagged with the person/ID it was registered under
   (data/known_faces.json).
2. When a new 512-D face embedding comes in, it is compared against
   every stored embedding using cosine similarity.
3. If similarity to an embedding stored under a DIFFERENT person_id is
   above the threshold (default 0.85) -> flagged as HIGH RISK
   duplicate identity attempt.

Dependencies: numpy (required), json (stdlib), opencv-python + insightface
(only needed for run_duplicate_id_detector's own face extraction step;
not needed if you only ever call check_duplicate_identity directly with
an embedding you already have).

Pipeline integration:
    run_duplicate_id_detector(image_path) is the entry point
    kavach_engine.py's detector_pipeline calls, matching every other
    detector's (image_path) -> dict signature.
"""

import json
import os
from datetime import datetime, timezone

import numpy as np

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
KNOWN_FACES_PATH = os.path.join("data", "known_faces.json")
SIMILARITY_THRESHOLD = 0.85
EMBEDDING_DIM = 512


# ---------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------
def load_known_faces(store_path: str = KNOWN_FACES_PATH) -> list:
    """
    Loads the known_faces.json store.
    Expected format:
    [
      {"person_id": "ID12345", "embedding": [0.01, 0.02, ...], "registered_at": "..."},
      {"person_id": "ID67890", "embedding": [0.03, 0.05, ...], "registered_at": "..."}
    ]
    Returns an empty list if the file doesn't exist yet (first run).
    """
    if not os.path.exists(store_path):
        return []
    with open(store_path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Corrupt or empty file - treat as no records rather than crashing
            return []


def save_known_faces(records: list, store_path: str = KNOWN_FACES_PATH) -> None:
    """Overwrites the known_faces.json store with the given list of records."""
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    with open(store_path, "w") as f:
        json.dump(records, f, indent=2)


def save_new_face_vector(person_id: str, embedding_512d, store_path: str = KNOWN_FACES_PATH) -> None:
    """
    Appends a new face embedding to data/known_faces.json under the
    given person_id.

    Call this after check_duplicate_identity() has cleared a face as
    safe, so genuinely new/unique people get added to the historical
    record for future comparisons. Do NOT call this for a flagged or
    failed check - that would write a fraud attempt into the trusted
    store.

    Args:
        person_id: the ID/tag this face should be registered under.
        embedding_512d: a 512-D face embedding (list, tuple, or numpy array).
        store_path: which known_faces.json file to append to.

    Raises:
        ValueError: if embedding_512d isn't a valid 512-D vector.
    """
    vector = np.asarray(embedding_512d, dtype=float)
    if vector.ndim != 1 or vector.shape[0] != EMBEDDING_DIM:
        raise ValueError(f"embedding_512d must be a 512-D vector, got shape {vector.shape}")

    records = load_known_faces(store_path)
    records.append({
        "person_id": person_id,
        "embedding": vector.tolist(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    })
    save_known_faces(records, store_path)


# ---------------------------------------------------------------------
# Core similarity logic
# ---------------------------------------------------------------------
def cosine_similarity(vec_a, vec_b) -> float:
    """Standard cosine similarity between two vectors, returned as a float in [-1, 1]."""
    a = np.asarray(vec_a, dtype=float)
    b = np.asarray(vec_b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def check_duplicate_identity(
    embedding,
    person_id: str,
    store_path: str = KNOWN_FACES_PATH,
    threshold: float = SIMILARITY_THRESHOLD,
) -> dict:
    """
    Compares `embedding` against every record in the known_faces store.

    Only matches against records whose person_id is DIFFERENT from the
    incoming person_id count as a duplicate-identity risk - a returning
    person re-verifying under their OWN person_id is expected and safe.

    Returns a dict in the standard detector output format:
        detector_name, score, confidence, explanation, status
    """
    try:
        embedding = np.asarray(embedding, dtype=float)

        if embedding.ndim != 1 or embedding.shape[0] != EMBEDDING_DIM:
            return _build_result(
                score=0.0,
                confidence="low",
                explanation=f"Invalid embedding shape {embedding.shape}, expected ({EMBEDDING_DIM},).",
                status="failed",
            )

        known_faces = load_known_faces(store_path)

        best_match = None       # highest similarity seen against a DIFFERENT person_id
        best_similarity = -1.0

        for record in known_faces:
            record_person_id = record.get("person_id")
            record_embedding = record.get("embedding")
            if record_person_id is None or record_embedding is None:
                continue  # skip malformed records rather than crashing the kiosk

            similarity = cosine_similarity(embedding, record_embedding)

            if record_person_id != person_id and similarity > best_similarity:
                best_similarity = similarity
                best_match = record_person_id

        # No comparable records at all -> nothing to flag against
        if best_match is None:
            return _build_result(
                score=0.0,
                confidence="high",
                explanation="No prior records found under a different ID. No duplicate risk detected.",
                status="passed",
            )

        score = max(0.0, min(1.0, best_similarity))  # clamp into [0, 1] for the output schema

        if best_similarity > threshold:
            margin = best_similarity - threshold
            confidence = "high" if margin > 0.05 else "medium"
            return _build_result(
                score=round(score, 4),
                confidence=confidence,
                explanation=(
                    f"HIGH RISK: Face matches an existing record under a different ID "
                    f"('{best_match}') with similarity {best_similarity:.4f}, "
                    f"above the {threshold} duplicate-identity threshold."
                ),
                status="flagged",
            )

        # Below threshold - safe, but report how close it was for transparency
        margin = threshold - best_similarity
        confidence = "high" if margin > 0.05 else "medium"
        return _build_result(
            score=round(score, 4),
            confidence=confidence,
            explanation=(
                f"No duplicate identity detected. Closest match under a different ID "
                f"('{best_match}') had similarity {best_similarity:.4f}, "
                f"below the {threshold} threshold."
            ),
            status="passed",
        )

    except Exception as e:
        return _build_result(
            score=0.0,
            confidence="low",
            explanation=f"Duplicate identity check failed to run: {e}",
            status="failed",
        )


def _build_result(score: float, confidence: str, explanation: str, status: str) -> dict:
    """
    Builds the standard detector output dict:
        detector_name  -> short name of this check
        score          -> 0.0 (clean/low risk) to 1.0 (suspicious/high risk)
        confidence      -> "low" | "medium" | "high"
        explanation     -> short human sentence
        status          -> "passed" | "flagged" | "failed" | "unavailable"
    """
    return {
        "detector_name": "duplicate_identity_check",
        "score": score,
        "confidence": confidence,
        "explanation": explanation,
        "status": status,
    }


def _person_id_for(image_path: str) -> str:
    """
    Placeholder person_id source.

    kavach_engine.analyze_media(image_path) doesn't currently pass a
    real enrollment ID into the pipeline, so this uses the image's
    filename (without extension) as a stand-in person_id. Swap this
    out for a real ID as soon as one is available in analyze_media's
    call signature - filenames are NOT a real identity field.
    """
    return os.path.splitext(os.path.basename(image_path))[0]


# ---------------------------------------------------------------------
# Pipeline entry point - this is what kavach_engine.py calls
# ---------------------------------------------------------------------
def _resolve_image_path(image_path: str) -> str:
    """Resolve a user-supplied image path to a real file, including common workspace folders."""
    if image_path and os.path.exists(image_path):
        return image_path

    candidates = [
        os.path.join("images", image_path),
        os.path.join("uploads", image_path),
        os.path.join("test_images", image_path),
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return image_path


def _extract_embedding(image_path: str):
    """Reads an image, extracts the main face embedding, and returns it with a derived person_id."""
    resolved_image_path = _resolve_image_path(image_path)

    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv-python is not installed; duplicate identity check unavailable.")

    try:
        from insightface.app import FaceAnalysis  # noqa: F401 (import-check only)
    except ImportError:
        raise RuntimeError("insightface is not installed; duplicate identity check unavailable.")

    img = cv2.imread(resolved_image_path)
    if img is None:
        raise RuntimeError(f"Could not read image file: {resolved_image_path}")

    faces = _get_face_app().get(img)

    if not faces:
        raise RuntimeError("No face detected in image; duplicate identity check unavailable.")

    largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    embedding = largest_face.normed_embedding
    person_id = _person_id_for(resolved_image_path)
    return embedding, person_id


def compare_two_images(image_path_a: str, image_path_b: str) -> dict:
    """Compares two images directly and reports whether they look like the same person."""
    try:
        embedding_a, person_id_a = _extract_embedding(image_path_a)
        embedding_b, person_id_b = _extract_embedding(image_path_b)
    except Exception as e:
        return _build_result(
            score=0.0,
            confidence="low",
            explanation=f"Duplicate identity check failed to process the two images: {e}",
            status="failed",
        )

    similarity = cosine_similarity(embedding_a, embedding_b)
    score = max(0.0, min(1.0, similarity))

    if similarity > SIMILARITY_THRESHOLD:
        margin = similarity - SIMILARITY_THRESHOLD
        confidence = "high" if margin > 0.05 else "medium"
        return _build_result(
            score=round(score, 4),
            confidence=confidence,
            explanation=(
                f"HIGH RISK: The faces in '{person_id_a}' and '{person_id_b}' match with similarity "
                f"{similarity:.4f}, above the {SIMILARITY_THRESHOLD} duplicate-identity threshold."
            ),
            status="flagged",
        )

    margin = SIMILARITY_THRESHOLD - similarity
    confidence = "high" if margin > 0.05 else "medium"
    return _build_result(
        score=round(score, 4),
        confidence=confidence,
        explanation=(
            f"No duplicate identity detected. The faces in '{person_id_a}' and '{person_id_b}' had "
            f"similarity {similarity:.4f}, below the {SIMILARITY_THRESHOLD} threshold."
        ),
        status="passed",
    )


def run_duplicate_id_detector(image_path: str) -> dict:
    """
    Standard detector interface: takes an image path, returns the
    standard detector_signals dict (detector_name, score, confidence,
    explanation, status). Matches every other detector in detectors/
    so it can be dropped straight into kavach_engine.py's
    detector_pipeline list.
    """
    try:
        embedding, person_id = _extract_embedding(image_path)
        result = check_duplicate_identity(embedding, person_id=person_id)

        # Only add clean checks to the trusted known-faces store.
        # Flagged/failed/unavailable results are NOT auto-registered.
        if result["status"] == "passed":
            save_new_face_vector(person_id, embedding)

        return result

    except Exception as e:
        return _build_result(
            score=0.0,
            confidence="low",
            explanation=f"Duplicate identity check crashed during execution: {e}",
            status="failed",
        )


_FACE_APP = None


def _get_face_app():
    """Lazily loads and caches the InsightFace model (loaded once per process)."""
    global _FACE_APP
    if _FACE_APP is None:
        from insightface.app import FaceAnalysis
        _FACE_APP = FaceAnalysis(name="buffalo_l")
        _FACE_APP.prepare(ctx_id=-1, det_size=(640, 640))
    return _FACE_APP


# ---------------------------------------------------------------------
# CLI entry point:
#   python -m detectors.duplicate_id_detector <image_path>
#   python -m detectors.duplicate_id_detector <image_path_a> <image_path_b>
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2:
        image_path = sys.argv[1]
        result = run_duplicate_id_detector(image_path)
    elif len(sys.argv) == 3:
        result = compare_two_images(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python -m detectors.duplicate_id_detector <image_path> OR python -m detectors.duplicate_id_detector <image_path_a> <image_path_b>")
        sys.exit(1)

    print(json.dumps(result, indent=2))