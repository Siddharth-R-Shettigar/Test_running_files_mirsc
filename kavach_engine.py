import json
import sys
import os
from dotenv import load_dotenv

load_dotenv()


def _safe_import(module_path, func_name):
    """Import a detector function without crashing the whole engine if it fails."""
    try:
        module = __import__(module_path, fromlist=[func_name])
        return getattr(module, func_name)
    except Exception as e:
        print(f"[WARNING] Could not load {module_path}.{func_name}: {e}", file=sys.stderr)
        return None


# --- Forensic / image detectors ---
run_exif_detector = _safe_import("detectors.exif_detector", "run_exif_detector")
run_c2pa_detector = _safe_import("detectors.c2pa_detector", "run_c2pa_detector")
run_ela_detector = _safe_import("detectors.ela_detector", "run_ela_detector")
run_jpeg_ghost_detector = _safe_import("detectors.jpeg_ghost", "run_jpeg_ghost_detector")
run_phash_detector = _safe_import("detectors.phash_detector", "run_phash_detector")
run_histogram_detector = _safe_import("detectors.histogram_detector", "run_histogram_detector")
run_frequency_detector = _safe_import("detectors.frequency_detector", "run_frequency_detector")
run_hf_ai_detector = _safe_import("detectors.hf_ai_detector", "run_hf_ai_detector")
run_copy_move_detector = _safe_import("detectors.copy_move_detector", "run_copy_move_detector")
run_blur_detector = _safe_import("detectors.blur_detector", "run_blur_detector")
run_cfa_detector = _safe_import("detectors.cfa_detector", "run_cfa_detector")
run_resampling_detector = _safe_import("detectors.resampling_detector", "run_resampling_detector")
run_quantization_detector = _safe_import("detectors.quantization_detector", "run_quantization_detector")
run_inpainting_detector = _safe_import("detectors.inpainting_detector", "run_inpainting_detector")
run_vision_llm_inspector = _safe_import("detectors.vision_llm_inspector", "run_vision_llm_inspector")
run_photo_tampering_detector = _safe_import("detectors.photo_tampering_detector", "run_photo_tampering_detector")

# --- Face ---
run_face_verification = _safe_import("detectors.face_verification_engine", "run_face_verification")
run_liveness_detection = _safe_import("detectors.liveness_detector", "run_liveness_detection")
run_duplicate_id_detector = _safe_import("detectors.duplicate_id_detector", "run_duplicate_id_detector")

# --- Text / document (subgroup 1) ---
extract_text = _safe_import("detectors.ocr_extraction", "extract_text")
parse_mrz = _safe_import("detectors.mrz_parser", "parse_mrz")
classify_document = _safe_import("detectors.document_classifier", "classify_document")
extract_fields_from_ocr = _safe_import("detectors.ocr_field_extractor", "extract_fields_from_ocr")
validate_document_fields = _safe_import("detectors.field_validator", "validate_document_fields")
check_ocr_mrz_consistency = _safe_import("detectors.ocr_mrz_consistency", "check_ocr_mrz_consistency")
validate_national_id = _safe_import("detectors.national_id_validator", "validate_national_id")


def _confidence_str(value):
    if value is None:
        return "low"
    if isinstance(value, str):
        v = value.lower()
        if v in ("low", "medium", "high"):
            return v
        return "medium"
    try:
        x = float(value)
        if x >= 0.75:
            return "high"
        if x >= 0.4:
            return "medium"
        return "low"
    except (TypeError, ValueError):
        return "low"


def _normalize(detector_name, raw, score_means_risk=True):
    """
    Force every module into:
    detector_name, score (0=clean risk … 1=high risk), confidence str, explanation, status
    """
    if raw is None:
        return {
            "detector_name": detector_name,
            "score": 0.5,
            "confidence": "low",
            "explanation": "Detector unavailable (import or call failed).",
            "status": "unavailable",
        }

    status = str(raw.get("status", "unavailable")).lower()
    # Map odd status words from some modules
    if status in ("pass", "ok", "success"):
        status = "passed"
    if status in ("fail", "error"):
        status = "failed"

    explanation = raw.get("explanation") or raw.get("details") or ""
    conf = _confidence_str(raw.get("confidence"))

    try:
        base = float(raw.get("score", 0.5))
    except (TypeError, ValueError):
        base = 0.5

    if score_means_risk:
        risk = base
    else:
        # Validators: high score = healthy document → low risk
        if status == "flagged":
            risk = max(0.7, 1.0 - base)
        elif status == "passed":
            risk = min(0.25, 1.0 - base)
        elif status in ("failed", "unavailable"):
            risk = 0.5
        else:
            risk = 1.0 - base

    risk = round(min(max(risk, 0.0), 1.0), 3)

    out = {
        "detector_name": raw.get("detector_name") or detector_name,
        "score": risk,
        "confidence": conf,
        "explanation": explanation,
        "status": status if status in ("passed", "flagged", "failed", "unavailable") else "unavailable",
    }
    # Keep useful extras for debugging / UI
    for key in ("doc_type", "fields", "mrz_lines", "issues", "mismatches", "field_results"):
        if key in raw:
            out[key] = raw[key]
    return out


def _run_safe(fn, *args, detector_name="unknown", score_means_risk=True, **kwargs):
    if fn is None:
        return _normalize(detector_name, None, score_means_risk=score_means_risk)
    try:
        raw = fn(*args, **kwargs)
        return _normalize(detector_name, raw, score_means_risk=score_means_risk)
    except Exception as e:
        return {
            "detector_name": detector_name,
            "score": 0.5,
            "confidence": "low",
            "explanation": f"Detector crashed: {e}",
            "status": "failed",
        }


def _risk_level(signals, forensic_risk):
    """
    Fail-closed risk decision from detector statuses + weighted forensic score.

    MRZ-specific hard rules only apply when the document_classifier routed
    the document through the MRZ pipeline (passport / visa).
    Aadhaar and driving_licence never reach those checks.
    """
    statuses = {s["detector_name"]: s for s in signals}

    def st(name):
        return statuses.get(name, {}).get("status")

    # Read MRZ routing flag set by the classifier
    clf = statuses.get("document_classifier", {})
    is_mrz_doc = bool(clf.get("needs_mrz", False))

    # ── Hard failures → HIGH RISK ────────────────────────────────────────────
    if st("face_verification") == "flagged":
        return "HIGH RISK", "Face on document does not match live capture."
    if is_mrz_doc and st("ocr_mrz_consistency") == "flagged":
        return "HIGH RISK", "OCR and MRZ data disagree."
    if is_mrz_doc and st("mrz_parser") == "flagged":
        return "HIGH RISK", "MRZ check digits or structure failed."

    # ── Missing critical evidence → REVIEW ──────────────────────────────────
    critical_missing = []
    if st("ocr_extraction") in ("failed", "unavailable", None):
        critical_missing.append("ocr_extraction")
    # For MRZ docs, failed MRZ parse or failed cross-check is also critical
    if is_mrz_doc:
        for name in ("mrz_parser", "ocr_mrz_consistency"):
            if st(name) == "failed":
                critical_missing.append(name)
    if critical_missing:
        return "REVIEW", f"Critical checks not available: {', '.join(critical_missing)}."

    # ── Soft failures → REVIEW ───────────────────────────────────────────────
    if st("liveness_analysis") == "flagged":
        return "REVIEW", "Liveness check suggests possible presentation attack."
    if st("duplicate_identity_check") == "flagged":
        return "REVIEW", "Possible duplicate identity match in local store."
    if st("photo_patch_forensics") == "flagged":
        return "REVIEW", "Document face photo region shows forensic anomalies."

    # ── Forensic score thresholds ────────────────────────────────────────────
    if forensic_risk >= 0.55:
        return "HIGH RISK", "Combined forensic risk is high."
    if forensic_risk >= 0.35:
        return "REVIEW", "Combined forensic risk is moderate."

    # ── Any remaining flagged signal → REVIEW ────────────────────────────────
    flagged = [s["detector_name"] for s in signals if s.get("status") == "flagged"]
    if flagged:
        return "REVIEW", f"Flagged signals: {', '.join(flagged[:6])}."

    return "PASS", "No strong risk signals from available checks."


def _clean_mrz_candidate(text: str) -> str:
    """Normalize a possible MRZ string from OCR."""
    if not text:
        return ""
    t = text.upper().replace(" ", "")
    # Common OCR confusions near '<'
    for ch in ("«", "‹", "(", "{", "[", "_", "–", "—", "~"):
        t = t.replace(ch, "<")
    # Keep only MRZ alphabet
    t = "".join(c for c in t if c.isalnum() or c == "<")
    return t

def _find_national_ids(ocr_text: str) -> list:
    """
    Best-effort: pull Aadhaar (12 digits) or PAN (ABCDE1234F) from OCR text.
    Returns list of (id_type, id_value).
    """
    import re

    found = []
    if not ocr_text:
        return found

    text = ocr_text.upper()

    # PAN: 5 letters + 4 digits + 1 letter
    for m in re.finditer(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text):
        found.append(("pan", m.group(1)))

    # Aadhaar: 12 digits (allow spaces/hyphens in source)
    compact = re.sub(r"[\s-]", "", ocr_text)
    for m in re.finditer(r"(?<!\d)([2-9]\d{11})(?!\d)", compact):
        found.append(("aadhaar", m.group(1)))

    # Deduplicate
    seen = set()
    out = []
    for t, v in found:
        key = (t, v)
        if key not in seen:
            seen.add(key)
            out.append((t, v))
    return out

def _collect_mrz_lines(ocr_raw: dict) -> list:
    """
    Build up to 2 TD3-style MRZ lines from OCR output.
    Uses official mrz_lines first, then long field tokens.
    """
    if not isinstance(ocr_raw, dict):
        return []

    candidates = []

    for line in ocr_raw.get("mrz_lines") or []:
        cleaned = _clean_mrz_candidate(str(line))
        if cleaned:
            candidates.append(cleaned)

    for f in ocr_raw.get("fields") or []:
        if isinstance(f, dict):
            text = f.get("text") or ""
        else:
            text = str(f)
        cleaned = _clean_mrz_candidate(text)
        if not cleaned:
            continue
        # MRZ-like: long, has '<' or starts with P< or is mostly ID+digits
        if len(cleaned) >= 28 and (cleaned.startswith("P<") or cleaned.count("<") >= 2 or sum(c.isdigit() for c in cleaned) >= 10):
            candidates.append(cleaned)

    # Deduplicate, keep order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)

    line1 = None
    line2 = None

    for c in uniq:
        if c.startswith("P<") and line1 is None:
            line1 = c
            break
    if line1 is None and uniq:
        # fallback: longest line with '<'
        with_chevron = [c for c in uniq if "<" in c]
        line1 = max(with_chevron, key=len) if with_chevron else uniq[0]

    for c in uniq:
        if c is line1:
            continue
        # Second MRZ line is usually digits + letters, may start with passport number
        if not c.startswith("P<") and len(c) >= 28:
            line2 = c
            break
    if line2 is None:
        for c in uniq:
            if c is not line1 and len(c) >= 28:
                line2 = c
                break

    lines = []
    if line1:
        # TD3 is 44 chars; pad/truncate lightly for parser stability
        lines.append(line1[:44].ljust(44, "<"))
    if line2:
        lines.append(line2[:44].ljust(44, "<"))

    return lines


def analyze_media(image_path, live_image_path=None):
    """
    Full KAVACH screening on a document image.
    Optional live_image_path enables face match + liveness + duplicate checks.
    """
    if not os.path.exists(image_path):
        return {"error": f"File {image_path} not found."}

    ext = os.path.splitext(image_path)[1].lower()
    is_jpeg = ext in [".jpg", ".jpeg"]

    signals = []

    # ----- 1) OCR -----
    ocr_raw = None
    if extract_text is not None:
        try:
            ocr_raw = extract_text(image_path)
        except Exception as e:
            ocr_raw = {
                "status": "failed",
                "score": 0.0,
                "confidence": "low",
                "explanation": str(e),
                "fields": [],
                "mrz_lines": [],
            }
    signals.append(_normalize("ocr_extraction", ocr_raw, score_means_risk=False))

    # Build flat OCR text blob for classifier
    ocr_text = ""
    if isinstance(ocr_raw, dict):
        parts = []
        for f in ocr_raw.get("fields") or []:
            if isinstance(f, dict) and f.get("text"):
                parts.append(str(f["text"]))
            elif isinstance(f, str):
                parts.append(f)
        ocr_text = " ".join(parts)

    # ----- 2) Document classification (runs before MRZ to gate the pipeline) -----
    # Supported types: passport, visa, aadhaar, driving_licence
    # passport / visa  → needs_mrz = True  → MRZ pipeline runs
    # aadhaar / dl     → needs_mrz = False → MRZ pipeline skipped entirely
    doc_type = "unknown"
    needs_mrz = False

    if classify_document is not None:
        clf_raw = _run_safe(
            classify_document,
            image_path,
            ocr_text,
            detector_name="document_classifier",
            score_means_risk=False,
        )
        signals.append(clf_raw)
        doc_type = clf_raw.get("doc_type", "unknown")
        needs_mrz = bool(clf_raw.get("needs_mrz", False))
    else:
        signals.append(
            _normalize(
                "document_classifier",
                {
                    "status": "unavailable",
                    "score": 0.0,
                    "confidence": "low",
                    "explanation": "document_classifier not loaded.",
                },
                score_means_risk=False,
            )
        )

    # ----- 3) MRZ pipeline — passport / visa only -----
    mrz_fields = {}
    ocr_fields_for_consistency = {}

    if needs_mrz:
        # 3a) Parse MRZ from OCR output
        mrz_raw = None
        mrz_lines = _collect_mrz_lines(ocr_raw if isinstance(ocr_raw, dict) else {})

        if parse_mrz is not None and len(mrz_lines) >= 2:
            try:
                mrz_raw = parse_mrz(mrz_lines)
                mrz_fields = (mrz_raw or {}).get("fields") or {}
            except Exception as e:
                mrz_raw = {
                    "status": "failed",
                    "score": 0.0,
                    "confidence": "low",
                    "explanation": str(e),
                    "fields": {},
                }
        elif parse_mrz is not None:
            mrz_raw = {
                "status": "unavailable",
                "score": 0.0,
                "confidence": "low",
                "explanation": (
                    f"'{doc_type}' requires MRZ but could not build two lines from OCR "
                    f"(got {len(mrz_lines)}: {mrz_lines})."
                ),
                "fields": {},
                "issues": ["Two MRZ lines are required."],
            }
        signals.append(_normalize("mrz_parser", mrz_raw, score_means_risk=False))

        # Build consistency dict from parsed MRZ fields
        if mrz_fields:
            ocr_fields_for_consistency = {
                "passport_number": mrz_fields.get("passport_number") or mrz_fields.get("document_number") or "",
                "dob":             mrz_fields.get("dob") or mrz_fields.get("date_of_birth") or "",
                "expiry":          mrz_fields.get("expiry") or mrz_fields.get("date_of_expiry") or "",
                "surname":         mrz_fields.get("surname") or mrz_fields.get("primary_identifier") or "",
                "nationality":     mrz_fields.get("nationality") or mrz_fields.get("country_code") or "",
            }

        # 3b) Field validation
        if validate_document_fields is not None and mrz_fields:
            signals.append(
                _run_safe(
                    validate_document_fields,
                    mrz_fields,
                    doc_type,
                    detector_name="field_validator",
                    score_means_risk=False,
                )
            )
        else:
            signals.append(
                _normalize(
                    "field_validator",
                    {
                        "status": "unavailable",
                        "score": 0.0,
                        "confidence": "low",
                        "explanation": (
                            f"Skipped; '{doc_type}' needs MRZ but parsing yielded no fields."
                        ),
                    },
                    score_means_risk=False,
                )
            )

        # 3c) OCR ↔ MRZ cross-check
        if check_ocr_mrz_consistency is not None and mrz_fields:
            signals.append(
                _run_safe(
                    check_ocr_mrz_consistency,
                    ocr_fields_for_consistency,
                    mrz_fields,
                    detector_name="ocr_mrz_consistency",
                    score_means_risk=False,
                )
            )
        else:
            signals.append(
                _normalize(
                    "ocr_mrz_consistency",
                    {
                        "status": "unavailable",
                        "score": 0.0,
                        "confidence": "low",
                        "explanation": "Skipped; no MRZ fields to cross-check against.",
                    },
                    score_means_risk=False,
                )
            )

    else:
        # Aadhaar / driving_licence / unknown — MRZ not applicable, record transparent skips
        skip_reason = (
            f"Not applicable: '{doc_type}' does not carry an MRZ strip."
            if doc_type != "unknown"
            else "Document type unknown; MRZ pipeline skipped."
        )
        for name in ("mrz_parser", "field_validator", "ocr_mrz_consistency"):
            signals.append(
                _normalize(
                    name,
                    {
                        "status": "unavailable",
                        "score": 0.0,
                        "confidence": "low",
                        "explanation": skip_reason,
                    },
                    score_means_risk=False,
                )
            )

    national_hits = _find_national_ids(ocr_text)
    if validate_national_id is not None and national_hits:
        # Validate the first hit (or loop all if you prefer)
        id_type, id_value = national_hits[0]
        try:
            raw = validate_national_id(id_type, id_value)
            # Ensure standard keys for _normalize
            if "score" not in raw:
                raw = dict(raw)
                raw["score"] = 1.0 if raw.get("status") == "passed" else 0.0
            if "confidence" not in raw:
                raw["confidence"] = "high"
            if "detector_name" not in raw:
                raw["detector_name"] = "national_id_validator"
            signals.append(_normalize("national_id_validator", raw, score_means_risk=False))
        except Exception as e:
            signals.append(
                _normalize(
                    "national_id_validator",
                    {
                        "status": "failed",
                        "score": 0.5,
                        "confidence": "low",
                        "explanation": str(e),
                    },
                    score_means_risk=False,
                )
            )
    else:
        signals.append(
            _normalize(
                "national_id_validator",
                {
                    "status": "unavailable",
                    "score": 0.0,
                    "confidence": "low",
                    "explanation": (
                        "No Aadhaar/PAN pattern found in OCR text."
                        if not national_hits
                        else "national_id_validator not loaded."
                    ),
                },
                score_means_risk=False,
            )
        )

    # ----- 7) Forensics (sequential) -----
    forensic_pipeline = [
        (run_exif_detector, "exiftool", 0.4, False),
        (run_c2pa_detector, "c2pa", 0.0, False),
        (run_cfa_detector, "cfa_demosaicing_analysis", 1.8, False),      # was 1.0 → restore for grafted photo regions
        (run_hf_ai_detector, "hf_vision_transformer", 1.2, False),
        (run_resampling_detector, "resampling_interpolation_analysis", 1.8, False),
        (run_ela_detector, "ela_compression", 1.3, False),
        (run_histogram_detector, "histogram_color_forensics", 0.5, False),
        (run_frequency_detector, "frequency_domain_fft", 0.5, False),
        (run_copy_move_detector, "copy_move_forgery", 2.0, False),
        (run_blur_detector, "blur_sharpness_analysis", 0.5, False),
        (run_phash_detector, "phash", 0.0, False),
        (run_jpeg_ghost_detector, "jpeg_ghost_analysis", 0.4, True),     # was 1.0 → lower (weak global signal)
        (run_quantization_detector, "jpeg_quantization_analysis", 1.0, True),
        (run_inpainting_detector, "inpainting", 1.5, False),             # was 1.0 → text/photo erasure+reprint
        (run_vision_llm_inspector, "vision_llm_sanity_analysis", 1.5, False),  # was 1.2 → layout/font/photo placement
        (run_photo_tampering_detector, "photo_patch_forensics", 2.0, False),
    ]

    weighted_sum = 0.0
    total_weight = 0.0

    for fn, name, weight, req_jpeg in forensic_pipeline:
        if req_jpeg and not is_jpeg:
            continue
        sig = _run_safe(fn, image_path, detector_name=name, score_means_risk=True)
        signals.append(sig)
        if weight > 0 and sig.get("confidence") != "low" and sig.get("status") not in ("failed", "unavailable"):
            weighted_sum += sig["score"] * weight
            total_weight += weight

    forensic_risk = weighted_sum / max(total_weight, 1.0)

    # ----- 8) Face stack (needs live image) -----
    if live_image_path and os.path.exists(live_image_path):
        signals.append(
            _run_safe(
                run_face_verification,
                image_path,
                live_image_path,
                detector_name="face_verification",
                score_means_risk=True,
            )
        )
        signals.append(
            _run_safe(
                run_liveness_detection,
                live_image_path,
                detector_name="liveness_analysis",
                score_means_risk=True,
            )
        )
        signals.append(
            _run_safe(
                run_duplicate_id_detector,
                live_image_path,
                detector_name="duplicate_identity_check",
                score_means_risk=True,
            )
        )
    else:
        for name, expl in [
            ("face_verification", "No live image provided; face match skipped."),
            ("liveness_analysis", "No live image provided; liveness skipped."),
            ("duplicate_identity_check", "No live image provided; duplicate-ID skipped."),
        ]:
            signals.append(
                _normalize(
                    name,
                    {
                        "status": "unavailable",
                        "score": 0.5,
                        "confidence": "low",
                        "explanation": expl,
                    },
                    score_means_risk=True,
                )
            )

    level, reason = _risk_level(signals, forensic_risk)

    return {
        "engine": "KAVACH",
        "file_analyzed": os.path.basename(image_path),
        "live_image": os.path.basename(live_image_path) if live_image_path else None,
        "risk_level": level,
        "risk_reason": reason,
        "forensic_risk_score": round(forensic_risk, 3),
        "active_detectors_evaluated": len(signals),
        "detector_signals": signals,
    }


def analyze_file(path, live_image_path=None):
    ext = os.path.splitext(path)[1].lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    if ext in image_exts:
        return analyze_media(path, live_image_path=live_image_path)
    return {"error": f"Unsupported file type: {ext}"}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "DSC_0153.JPG"
    live = sys.argv[2] if len(sys.argv) > 2 else None
    report = analyze_file(target, live_image_path=live)

    try:
        from llm_fusion import generate_human_summary
        report["human_summary"] = generate_human_summary(report)
    except Exception as e:
        report["human_summary"] = f"(AI summary unavailable: {e})"

    print(json.dumps(report, indent=2))

    os.makedirs("case_logs", exist_ok=True)
    safe_name = os.path.splitext(os.path.basename(target))[0]
    log_path = os.path.join("case_logs", f"{safe_name}_report.json")
    with open(log_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved case log to {log_path}", file=sys.stderr)