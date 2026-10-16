import os
import logging
from PIL import Image

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

logger = logging.getLogger("kavach.hf_ai")

MODEL_CHECKPOINTS = [
    "umm-maybe/AI-image-detector",
    "Organika/sdxl-detector"
]

_PIPELINE_CACHE = {}

def _get_pipeline(model_name):
    if model_name not in _PIPELINE_CACHE:
        from transformers import pipeline
        print(f"[HF_DETECTOR] Initializing Vision Transformer weights for {model_name}...", flush=True)
        _PIPELINE_CACHE[model_name] = pipeline("image-classification", model=model_name)
    return _PIPELINE_CACHE[model_name]

def run_hf_ai_detector(image_path):
    if not os.path.exists(image_path):
        return {
            "detector_name": "hf_vision_transformer",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"File {image_path} not found.",
            "status": "failed"
        }

    try:
        import torch
        torch.set_num_threads(2)

        image = Image.open(image_path).convert("RGB")
        max_dim = 1024
        if max(image.size) > max_dim:
            image.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)

        scores = []

        with torch.inference_mode():
            for model_name in MODEL_CHECKPOINTS:
                try:
                    pipe = _get_pipeline(model_name)
                    predictions = pipe(image)

                    fake_score = 0.0
                    for pred in predictions:
                        label = pred["label"].lower()
                        if "artificial" in label or "fake" in label or "ai" in label or "generator" in label:
                            fake_score = max(fake_score, float(pred["score"]))

                    scores.append(fake_score)
                except Exception:
                    continue

        if not scores:
            return {
                "detector_name": "hf_vision_transformer",
                "score": 0.5,
                "confidence": "low",
                "explanation": "Could not process image through Hugging Face pipelines.",
                "status": "failed"
            }

        avg_synthetic_score = float(sum(scores) / len(scores))

        return {
            "detector_name": "hf_vision_transformer",
            "score": round(avg_synthetic_score, 2),
            "confidence": "high",
            "explanation": f"Ensemble of {len(scores)} Hugging Face Vision Transformers evaluated synthetic probability at {int(avg_synthetic_score * 100)}%.",
            "status": "flagged" if avg_synthetic_score >= 0.4 else "passed"
        }

    except Exception as e:
        return {
            "detector_name": "hf_vision_transformer",
            "score": 0.5,
            "confidence": "low",
            "explanation": f"HF Vision Transformer error: {str(e)}",
            "status": "failed"
        }