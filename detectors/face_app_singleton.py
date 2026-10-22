"""
One shared InsightFace FaceAnalysis for the whole process.
Import get_face_app() from face_verification, photo_tampering, duplicate_id.
"""
from __future__ import annotations

import os
import threading
import warnings

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

_FACE_APP = None
_FACE_APP_LOCK = threading.Lock()


def get_face_app():
    """Load buffalo_l once with only required modules; reuse for every detector and every image."""
    global _FACE_APP
    if _FACE_APP is None:
        with _FACE_APP_LOCK:
            if _FACE_APP is None:
                from insightface.app import FaceAnalysis

                print("[KAVACH] Loading InsightFace buffalo_l (detection + recognition)...", flush=True)
                app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
                app.prepare(ctx_id=-1, det_size=(640, 640))  # CPU
                _FACE_APP = app
                print("[KAVACH] InsightFace ready.", flush=True)
    return _FACE_APP
