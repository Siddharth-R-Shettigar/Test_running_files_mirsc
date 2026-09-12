# connector.py
from bridge import get_all_scores
from analyst import get_verdict


def _build_human_summary(verdict):
    """Convert the raw verdict into a short, consistent summary for the UI."""
    if not isinstance(verdict, dict):
        return "No assessment available.", "amber", "REVIEW"

    verdict_name = str(verdict.get("verdict", "")).lower()

    if verdict_name == "likely_real":
        color = "green"
        label = "PASS"
    elif verdict_name == "likely_fake":
        color = "red"
        label = "HIGH RISK"
    else:
        color = "amber"
        label = "REVIEW"

    summary = verdict.get("human_summary") or verdict.get("summary") or verdict.get("reasoning") or "No assessment available."
    summary = str(summary).strip()

    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."

    return summary, color, label


def analyze_image(image_path, preprocess=None):
    print(f"Starting analysis: {image_path}")

    # Get real scores from Siddharth's detection engine
    scores = get_all_scores(image_path)

    print("Scores collected. Sending to AI reasoning layer...")

    # Pass to your AI reasoning layer
    verdict = get_verdict(scores, preprocess)
    summary, summary_color, summary_label = _build_human_summary(verdict)
    verdict["human_summary"] = summary
    verdict["summary_color"] = summary_color
    verdict["summary_label"] = summary_label
    return verdict


if __name__ == "__main__":
    import json
    import os
    import sys
    default_path = os.path.join("test_images", "real", "20260804_073446.jpg")
    path = sys.argv[1] if len(sys.argv) > 1 else default_path
    result = analyze_image(path)
    print(json.dumps(result, indent=2))