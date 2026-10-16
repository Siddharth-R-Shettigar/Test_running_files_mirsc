from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
import uuid
import json
import sys
import glob
import threading
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kavach-dev-secret-change-me")

DEMO_USER = os.environ.get("KAVACH_DEMO_USER", "officer@agency.gov.in")
DEMO_PASS = os.environ.get("KAVACH_DEMO_PASS", "kavach123")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("case_logs", exist_ok=True)

try:
    from crypto_utils import encrypt_sensitive, decrypt_sensitive
    CRYPTO_AVAILABLE = True
except Exception as e:
    print(f"[WARNING] Crypto not available: {e}")
    CRYPTO_AVAILABLE = False

OFFICER_PASSWORD = os.environ.get("KAVACH_PASSWORD", "kavach2026")
CASE_PROGRESS = {}
CASE_PROGRESS_LOCK = threading.Lock()
CASE_EVENTS = {}
CASE_THREADS = {}

SCAN_STEPS = [
    {"key": "face", "title": "Face capture", "blurb": "Centre the face. Even light, no heavy glare."},
    {"key": "passport", "title": "Passport capture", "blurb": "Place the passport data page within the frame."},
    {"key": "visa", "title": "Visa capture", "blurb": "Place the visa page or sticker within the frame."},
    {"key": "national_id", "title": "National ID verification", "blurb": "Place the national ID card within the frame."},
    {"key": "drivers_license", "title": "Driver's license", "blurb": "Place the driver's license within the frame."},
    {"key": "border_permit", "title": "Border permit", "blurb": "Place the border permit document within the frame."},
]


def _scan_index():
    captures = session.get("captures") or {}
    for i, step in enumerate(SCAN_STEPS):
        if step["key"] not in captures:
            return i
    return len(SCAN_STEPS)


@app.route("/")
def home():
    if session.get("logged_in"):
        return redirect(url_for("scan"))
    return render_template("landing.html")


@app.route("/landing")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if email == DEMO_USER.lower() and password == DEMO_PASS:
        session["logged_in"] = True
        session["officer_email"] = email
        session.pop("captures", None)
        session.pop("face_path", None)
        session.pop("doc_path", None)
        session.pop("case_id", None)
        return redirect(url_for("scan"))

    return render_template("login.html", error="Invalid login id or password."), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/scan")
def scan():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    if "captures" not in session:
        session["captures"] = {}
    if "case_id" not in session:
        session["case_id"] = f"case_{uuid.uuid4().hex[:12]}"

    idx = _scan_index()
    if idx >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))

    error_msg = request.args.get("error")

    return render_template(
        "scan.html",
        steps=SCAN_STEPS,
        current_index=idx,
        current=SCAN_STEPS[idx],
        captures=session.get("captures") or {},
        case_id=session.get("case_id"),
        scan_error=error_msg,
    )


def _map_result_ui(report):
    if not isinstance(report, dict):
        report = {}

    risk_level = str(report.get("risk_level") or report.get("summary_label") or "REVIEW").upper()
    if risk_level in ("PASS", "GENUINE") or report.get("verdict") == "likely_real":
        color, title, label = "green", "AUTHENTIC & VERIFIED", "PASS"
    elif risk_level in ("HIGH RISK", "HIGH_RISK") or report.get("verdict") == "likely_fake":
        color, title, label = "red", "HIGH RISK — REVIEW REQUIRED", "HIGH RISK"
    elif risk_level == "RESCAN" or report.get("needs_rescan"):
        color, title, label = "orange", "IMAGE CLARITY TOO LOW — RE-CAPTURE RECOMMENDED", "RESCAN"
    else:
        color, title, label = "yellow", "NEEDS REVIEW", "REVIEW"

    score = report.get("forensic_risk_score")
    if score is None:
        score = report.get("risk_score")
    try:
        score = float(score)
        risk_pct = round(score * 100, 1) if score <= 1.0 else round(score, 1)
    except (TypeError, ValueError):
        risk_pct = 0.0

    why = (
        report.get("risk_reason")
        or report.get("human_summary")
        or report.get("reasoning")
        or "Automated screening complete."
    )
    if isinstance(why, str) and len(why) > 280:
        why = why[:277].rstrip() + "…"

    checklist = report.get("officer_checklist") or [
        "Compare document photo to the person present",
        "Re-check MRZ / printed fields (0 vs O, dates)",
        "Inspect photo area if face forensics flagged",
        "Confirm hologram / secondary portrait if present",
        "Secondary inspection if still unclear",
    ]

    signals = []
    for s in (report.get("detector_signals") or [])[:8]:
        if not isinstance(s, dict):
            continue
        st = str(s.get("status", "unavailable")).lower()
        if st not in ("passed", "flagged", "failed", "unavailable"):
            st = "unavailable"
        signals.append({
            "name": (s.get("detector_name") or "detector")[:28],
            "status": st,
        })

    return {
        "color": color,
        "title": title,
        "label": label,
        "risk_pct": risk_pct,
        "why": why,
        "checklist": checklist,
        "signals": signals,
    }


@app.route("/result")
def result_placeholder():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("result_loading.html")


@app.route("/cases", methods=["GET", "POST"])
def cases():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if request.method == "POST":
        code = (request.form.get("passcode") or "").strip()
        if code == os.environ.get("KAVACH_CASES_PASS", DEMO_PASS):
            session["cases_unlocked"] = True
        else:
            return render_template("cases.html", cases_unlocked=False, cases_error="Invalid password.")
    return render_template("cases.html", cases_unlocked=bool(session.get("cases_unlocked")), cases_error=None)


@app.route("/settings")
def settings():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("settings.html", officer_email=session.get("officer_email", DEMO_USER))


@app.route("/analyze", methods=["POST"])
def analyze():
    from connector import analyze_image

    if "image" not in request.files:
        return jsonify({"error": "No image uploaded."}), 400

    file = request.files["image"]
    allowed_extensions = {"jpg", "jpeg", "png", "webp"}
    file_extension = file.filename.rsplit(".", 1)[-1].lower()
    if file_extension not in allowed_extensions:
        return jsonify({"error": "Invalid file type."}), 400

    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    image_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(image_path)

    try:
        result = analyze_image(image_path)
        if os.path.exists(image_path):
            os.remove(image_path)

        if CRYPTO_AVAILABLE:
            encrypted_result = encrypt_sensitive(result, OFFICER_PASSWORD)
            return jsonify(encrypted_result)

        return jsonify(result)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print("CRASH DETAILS:")
        print(error_details)
        if os.path.exists(image_path):
            os.remove(image_path)
        return jsonify({"error": str(e), "details": error_details}), 500


@app.route("/decrypt", methods=["POST"])
def decrypt():
    if not CRYPTO_AVAILABLE:
        return jsonify({"error": "Crypto module not available."}), 500

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided."}), 400

    password = data.get("password")
    encrypted_report = data.get("report")

    if not password:
        return jsonify({"error": "Password required."}), 400
    if not encrypted_report:
        return jsonify({"error": "Encrypted report required."}), 400

    result = decrypt_sensitive(encrypted_report, password)

    if result["success"]:
        return jsonify({"success": True, "report": result["report"]})
    return jsonify({"success": False, "error": "Invalid password."}), 401


@app.route("/verify", methods=["POST"])
def verify():
    try:
        from crypto_utils import verify_report
        data = request.get_json()
        if not data:
            return jsonify({"error": "No report provided."}), 400
        return jsonify(verify_report(data))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/manifest", methods=["GET"])
def manifest():
    try:
        from crypto_utils import build_integrity_manifest
        return jsonify(build_integrity_manifest())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/scan/capture", methods=["POST"])
def scan_capture():
    if not session.get("case_id"):
        session["case_id"] = f"case_{uuid.uuid4().hex[:12]}"

    if not session.get("logged_in"):
        return redirect(url_for("login"))

    idx = _scan_index()
    if idx >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))

    step = SCAN_STEPS[idx]
    f = request.files.get("capture_image")
    if not f or not f.filename:
        return redirect(url_for("scan"))

    ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
    name = f"{step['key']}_{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_FOLDER, name)
    f.save(path)

    # Clarity check (non-fatal — only block if check definitively fails)
    try:
        from detectors.clarity_detector import check_image_clarity
        clarity_res = check_image_clarity(path)
        if clarity_res.get("status") == "failed":
            if os.path.exists(path):
                os.remove(path)
            err_msg = f"Image clarity too low ({clarity_res.get('clarity_percent', 0):.0f}%). Please capture a sharper image."
            return redirect(url_for("scan", error=err_msg))
    except Exception as e:
        print(f"[WARNING] Clarity pre-check error (image kept): {e}", file=sys.stderr)
        # Do NOT delete file or abort — continue with the capture


    # Face presence check (only hard-block on definitive no-face, not on detector crash)
    if step["key"] == "face":
        try:
            from detectors.face_verification_engine import check_face_presence
            has_face, face_msg = check_face_presence(path)
            if not has_face:
                if os.path.exists(path):
                    os.remove(path)
                return redirect(url_for("scan", error=face_msg))
        except Exception as e:
            print(f"[WARNING] Face presence pre-check error (image kept): {e}", file=sys.stderr)
            # Do NOT delete file or abort — continue with the capture

    captures = dict(session.get("captures") or {})
    captures[step["key"]] = path
    session["captures"] = captures

    if step["key"] == "face":
        session["face_path"] = path
    if step["key"] == "passport":
        session["doc_path"] = path

    if _scan_index() >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))
    return redirect(url_for("scan"))


@app.route("/scan/skip", methods=["POST"])
def scan_skip():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    idx = _scan_index()
    if idx <= 0 or idx >= len(SCAN_STEPS):
        return redirect(url_for("scan"))

    step = SCAN_STEPS[idx]
    captures = dict(session.get("captures") or {})
    captures[step["key"]] = None
    session["captures"] = captures

    if _scan_index() >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))
    return redirect(url_for("scan"))


@app.route("/scan/reset")
def scan_reset():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    session.pop("captures", None)
    session.pop("face_path", None)
    session.pop("doc_path", None)
    session.pop("case_id", None)
    return redirect(url_for("scan"))


def _execute_case_analysis(case_id, available_docs, face_path, done_event):
    with CASE_PROGRESS_LOCK:
        CASE_PROGRESS[case_id] = {
            "status": "running",
            "documents_completed": 0,
            "documents_total": len(available_docs),
            "active_document": None,
            "active_detector": None,
            "detector_signals": [],
            "result": None,
            "error": None,
        }

    merged_signals = []
    merged_risk_scores = []
    merged_risk_level = "REVIEW"
    merged_risk_reason = "Automated multi-document screening complete."

    try:
        from kavach_engine import analyze_media
    except Exception as e:
        print(f"[ERROR] Could not import kavach_engine: {e}", flush=True)
        with CASE_PROGRESS_LOCK:
            CASE_PROGRESS[case_id].update(status="failed", error="Analysis engine could not be loaded.")
        done_event.set()
        return

    try:
        for document_number, (doc_key, doc_path) in enumerate(available_docs, start=1):
            with CASE_PROGRESS_LOCK:
                CASE_PROGRESS[case_id]["active_document"] = doc_key

            def _make_progress_cb(current_doc_key):
                def _cb(event_type, data):
                    with CASE_PROGRESS_LOCK:
                        prog = CASE_PROGRESS.get(case_id)
                        if not prog:
                            return
                        if event_type == "detector_start":
                            prog["active_detector"] = data.get("detector_name")
                        elif event_type == "detector_complete":
                            prog["active_detector"] = None
                            sig = data.get("signal")
                            if sig:
                                sig_c = dict(sig)
                                sig_c["detector_name"] = f"[{current_doc_key}] {sig.get('detector_name', 'detector')}"
                                sig_c["raw_detector_name"] = sig.get("detector_name")
                                prog["detector_signals"].append(sig_c)
                return _cb

            try:
                print(f"[KAVACH] Analyzing {doc_key}: {doc_path}", flush=True)
                doc_report = analyze_media(
                    image_path=str(doc_path),
                    live_image_path=str(face_path) if face_path and os.path.exists(str(face_path)) else None,
                    expected_doc_type=doc_key,
                    progress_callback=_make_progress_cb(doc_key),
                )

                safe = os.path.splitext(os.path.basename(str(doc_path)))[0]
                os.makedirs("case_logs", exist_ok=True)
                log_path = os.path.join("case_logs", f"{safe}_report.json")
                with open(log_path, "w", encoding="utf-8") as fh:
                    json.dump(doc_report, fh, indent=2, ensure_ascii=False)

                if isinstance(doc_report, dict):
                    for sig in (doc_report.get("detector_signals") or []):
                        if isinstance(sig, dict):
                            sig_c = dict(sig)
                            sig_c["detector_name"] = f"[{doc_key}] {sig.get('detector_name', 'detector')}"
                            sig_c["raw_detector_name"] = sig.get("detector_name")
                            merged_signals.append(sig_c)

                    score = doc_report.get("forensic_risk_score", 0.5)
                    try:
                        merged_risk_scores.append(float(score))
                    except (TypeError, ValueError):
                        merged_risk_scores.append(0.5)

                    doc_rl = str(doc_report.get("risk_level", "REVIEW")).upper()
                    if doc_rl in ("HIGH RISK", "HIGH_RISK"):
                        merged_risk_level = "HIGH RISK"
                        merged_risk_reason = f"[{doc_key}] {doc_report.get('risk_reason', '')}"
                    elif doc_rl == "PASS" and merged_risk_level != "HIGH RISK":
                        merged_risk_level = "PASS"
                        merged_risk_reason = doc_report.get("risk_reason", "All checks passed.")

            except Exception as e:
                print(f"[ERROR] Failed analyzing {doc_key}: {e}", flush=True)
                import traceback
                traceback.print_exc()
                continue
            finally:
                with CASE_PROGRESS_LOCK:
                    CASE_PROGRESS[case_id].update(
                        documents_completed=document_number,
                        active_document=None,
                        active_detector=None,
                    )
                import gc
                gc.collect()

        if merged_risk_scores:
            final_score = sum(merged_risk_scores) / len(merged_risk_scores)
        else:
            final_score = 0.5

        final_report = {
            "engine": "KAVACH",
            "case_id": case_id,
            "risk_level": merged_risk_level,
            "risk_reason": merged_risk_reason,
            "forensic_risk_score": round(final_score, 3),
            "detector_signals": merged_signals,
            "human_summary": merged_risk_reason,
            "documents_analysed": [k for k, _ in available_docs],
        }

        os.makedirs("case_logs", exist_ok=True)
        try:
            with open(os.path.join("case_logs", f"{case_id}_report.json"), "w", encoding="utf-8") as fh:
                json.dump(final_report, fh, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARNING] could not save case log: {e}", flush=True)

        ui = _map_result_ui(final_report)
        ui["case_id"] = case_id

        with CASE_PROGRESS_LOCK:
            CASE_PROGRESS[case_id].update(
                status="complete",
                result=ui,
                active_document=None,
                active_detector=None,
            )

    except Exception as exc:
        print(f"[ERROR] Background analysis failed: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        with CASE_PROGRESS_LOCK:
            CASE_PROGRESS[case_id].update(status="failed", error=str(exc))
    finally:
        done_event.set()


@app.route("/api/run_case")
def api_run_case():
    # ── FAST UI demo: return immediately without ML ──────────────────────────
    if os.environ.get("KAVACH_FAST_UI", "0").strip() == "1":
        case_id = f"case_{uuid.uuid4().hex[:12]}"
        demo_report = {
            "engine": "KAVACH-FAST-UI",
            "case_id": case_id,
            "risk_level": "REVIEW",
            "risk_reason": "Manual check recommended (demo mode).",
            "forensic_risk_score": 0.46,
            "detector_signals": [
                {
                    "detector_name": "capture_pipeline",
                    "status": "passed",
                    "score": 0.1,
                    "confidence": "high",
                    "explanation": "Demo path: full ML skipped (KAVACH_FAST_UI=1).",
                }
            ],
            "human_summary": "Demo screening complete. Run with KAVACH_FAST_UI=0 for full forensics.",
            "documents_analysed": ["demo"],
        }
        os.makedirs("case_logs", exist_ok=True)
        with open(os.path.join("case_logs", f"{case_id}_report.json"), "w", encoding="utf-8") as fh:
            json.dump(demo_report, fh, indent=2, ensure_ascii=False)

        ui = _map_result_ui(demo_report)
        ui["case_id"] = case_id
        session["last_case_id"] = case_id
        session["last_result_ui"] = ui
        return jsonify(ui)

    # ---------- REAL ANALYSIS (Fast UI is OFF) ----------
    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    case_id = session.get("case_id") or f"case_{uuid.uuid4().hex[:12]}"
    session["case_id"] = case_id

    captures = session.get("captures") or {}
    face_path = session.get("face_path") or captures.get("face")

    DOC_KEYS = ["passport", "visa", "national_id", "drivers_license", "border_permit"]
    available_docs = [
        (key, captures[key])
        for key in DOC_KEYS
        if captures.get(key) and os.path.exists(str(captures[key]))
    ]

    fallback = {
        "risk_level": "REVIEW",
        "risk_reason": "Full analysis did not finish. Captures were saved.",
        "forensic_risk_score": 0.5,
        "detector_signals": [],
        "case_id": case_id,
    }

    if not available_docs:
        fallback["risk_reason"] = "No document captures in this session. Capture a passport/ID to run analysis."
        ui = _map_result_ui(fallback)
        ui["case_id"] = case_id
        session["last_case_id"] = case_id
        return jsonify(ui)

    with CASE_PROGRESS_LOCK:
        prog = CASE_PROGRESS.get(case_id)
        if prog and prog.get("status") == "complete" and prog.get("result"):
            session["last_case_id"] = case_id
            session["last_result_ui"] = prog["result"]
            return jsonify(prog["result"])
        if prog and prog.get("status") == "failed":
            return jsonify({"error": prog.get("error", "Analysis failed")}), 500

    done_event = CASE_EVENTS.get(case_id)
    if not done_event or case_id not in CASE_PROGRESS:
        done_event = threading.Event()
        CASE_EVENTS[case_id] = done_event
        t = threading.Thread(
            target=_execute_case_analysis,
            args=(case_id, available_docs, face_path, done_event),
            daemon=True,
        )
        CASE_THREADS[case_id] = t
        t.start()

    # Wait up to 12s so fast runs return synchronously, but NEVER block long enough to cause a proxy 502!
    done = done_event.wait(timeout=12.0)
    with CASE_PROGRESS_LOCK:
        prog = CASE_PROGRESS.get(case_id, {})
        if done and prog.get("status") == "complete" and prog.get("result"):
            session["last_case_id"] = case_id
            session["last_result_ui"] = prog["result"]
            return jsonify(prog["result"])
        if done and prog.get("status") == "failed":
            return jsonify({"error": prog.get("error", "Analysis failed")}), 500

    # Still running in background: return 200 with status="running"
    return jsonify({
        "status": "running",
        "case_id": case_id,
        "message": "Analysis is actively executing in background."
    }), 200


@app.route("/api/run_case/progress")
def api_run_case_progress():
    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    case_id = session.get("case_id") or session.get("last_case_id")
    with CASE_PROGRESS_LOCK:
        progress = CASE_PROGRESS.get(case_id)
        if progress is None:
            return jsonify({"status": "not_started"}), 200
        return jsonify(dict(progress))


# ── GET /api/cases ─────────────────────────────────────────────────────────────
@app.route("/api/cases")
def api_cases():
    """List all case_logs/*_report.json with optional blockchain integrity check."""
    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    os.makedirs("case_logs", exist_ok=True)
    pattern = os.path.join("case_logs", "*_report.json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    from datetime import datetime as _dt
    cases_out = []
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                rep = json.load(fh)
        except Exception:
            continue

        integrity = "unknown"
        try:
            from blockchain import get_chain
            if rep.get("blockchain_anchor") or rep.get("integrity_seal"):
                result = get_chain().verify_report_hash(rep)
                integrity = "intact" if result else "tampered"
        except Exception:
            integrity = "unknown"

        risk_level = str(rep.get("risk_level") or "REVIEW").upper()
        if risk_level in ("PASS", "GENUINE"):
            color, verdict = "green", "CLEARANCE GRANTED"
        elif risk_level in ("HIGH RISK", "HIGH_RISK"):
            color, verdict = "red", "CLEARANCE DENIED"
        else:
            color, verdict = "yellow", "SECONDARY REVIEW"

        score = rep.get("forensic_risk_score", 0.0)
        try:
            score = float(score)
            risk_pct = round(score * 100 if score <= 1.0 else score, 1)
        except (TypeError, ValueError):
            risk_pct = 0.0

        case_id = rep.get("case_id") or os.path.splitext(os.path.basename(fpath))[0]
        mtime = _dt.utcfromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M")

        cases_out.append({
            "id": case_id,
            "name": ", ".join(rep.get("documents_analysed") or [rep.get("file_analyzed") or "Unknown"]),
            "color": color,
            "risk": risk_pct,
            "date": mtime,
            "officer": session.get("officer_email", "officer@agency.gov.in"),
            "verdict": verdict,
            "summary": (rep.get("risk_reason") or "")[:200],
            "integrity": integrity,
            "filename": os.path.basename(fpath),
        })

    return jsonify({"cases": cases_out})


# ── GET /api/report/<case_id>.pdf ──────────────────────────────────────────────
@app.route("/api/report/<case_id>.pdf")
def api_report_pdf(case_id):
    """Stream a PDF forensic report for the given case_id."""
    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    safe_id = "".join(c for c in case_id if c.isalnum() or c in ("_", "-"))
    candidates = [
        os.path.join("case_logs", f"{safe_id}.json"),
        os.path.join("case_logs", f"{safe_id}_report.json"),
    ]
    log_path = next((p for p in candidates if os.path.exists(p)), None)
    if not log_path:
        return jsonify({"error": f"Case {safe_id} not found."}), 404    

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:
        return jsonify({"error": f"Could not read report: {exc}"}), 500

    from flask import send_file
    import tempfile

    try:
        from report_generator import generate_case_report_pdf, REPORTLAB_AVAILABLE
    except ImportError:
        return jsonify({"error": "report_generator module not found."}), 501

    if not REPORTLAB_AVAILABLE:
        return jsonify({"error": "ReportLab not installed; PDF generation unavailable."}), 501

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        generate_case_report_pdf(report, tmp_path)
        return send_file(
            tmp_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"kavach_{safe_id}_report.pdf",
        )
    except Exception as exc:
        return jsonify({"error": f"PDF generation failed: {exc}"}), 500

def _warm_models():
    try:
        print("[KAVACH] Warming engine imports...", flush=True)
        import kavach_engine  # noqa: F401
        print("[KAVACH] Engine import done.", flush=True)
    except Exception as e:
        print(f"[KAVACH] Warmup skipped: {e}", flush=True)

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0").strip().lower() in ("1", "true")
    use_reloader = os.environ.get("FLASK_USE_RELOADER", "0").strip().lower() in ("1", "true")

    # In reloader mode, only start the warmup in the child worker process
    if not use_reloader or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=_warm_models, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=debug_mode, use_reloader=use_reloader, threaded=True)