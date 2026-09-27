from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
import uuid
import json
import subprocess
import sys
import glob

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kavach-dev-secret-change-me")

DEMO_USER = os.environ.get("KAVACH_DEMO_USER", "officer@agency.gov.in")
DEMO_PASS = os.environ.get("KAVACH_DEMO_PASS", "kavach123")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

try:
    from crypto_utils import encrypt_sensitive, decrypt_sensitive
    CRYPTO_AVAILABLE = True
except Exception as e:
    print(f"[WARNING] Crypto not available: {e}")
    CRYPTO_AVAILABLE = False

OFFICER_PASSWORD = os.environ.get("KAVACH_PASSWORD", "kavach2026")

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
    """Map engine / connector output → compact UI fields."""
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
    from connector import analyze_image  # lazy import so login still works if groq missing

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

    # 1. Instantaneous Clarity Check
    try:
        from detectors.clarity_detector import check_image_clarity
        clarity_res = check_image_clarity(path)
        if clarity_res.get("status") == "failed":
            if os.path.exists(path):
                os.remove(path)
            err_msg = f"Image clarity too low ({clarity_res.get('clarity_percent', 0)}%). Quality is insufficient for verification. Please capture or re-upload a sharper image."
            return redirect(url_for("scan", error=err_msg))
    except Exception as e:
        print(f"[WARNING] Clarity pre-check error: {e}", file=sys.stderr)
        if os.path.exists(path):
            os.remove(path)
        return redirect(url_for("scan", error="Image check unavailable. Please try again."))

    # 2. Instantaneous Face Presence Check (Face capture step)
    if step["key"] == "face":
        try:
            from detectors.face_verification_engine import check_face_presence
            has_face, face_msg = check_face_presence(path)
            if not has_face:
                if os.path.exists(path):
                    os.remove(path)
                return redirect(url_for("scan", error=face_msg))
        except Exception as e:
            print(f"[WARNING] Face presence pre-check error: {e}", file=sys.stderr)
            if os.path.exists(path):
                os.remove(path)
            return redirect(url_for("scan", error=f"Face check error: {e}"))


    captures = dict(session.get("captures") or {})
    captures[step["key"]] = path
    session["captures"] = captures
    # keep old keys for later engine wiring
    if step["key"] == "face":
        session["face_path"] = path
    if step["key"] == "passport":
        session["doc_path"] = path

    if _scan_index() >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))
    return redirect(url_for("scan"))


@app.route("/scan/skip", methods=["POST"])
def scan_skip():
    """Optional skip for docs the traveller may not carry (not for face)."""
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    idx = _scan_index()
    if idx <= 0 or idx >= len(SCAN_STEPS):
        return redirect(url_for("scan"))

    step = SCAN_STEPS[idx]
    captures = dict(session.get("captures") or {})
    captures[step["key"]] = None  # marked skipped
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


@app.route("/api/run_case")
def api_run_case():
    # One case id for this session (created in /scan; fallback if missing)
    case_id = session.get("case_id") or f"case_{uuid.uuid4().hex[:12]}"
    session["case_id"] = case_id
    os.makedirs("case_logs", exist_ok=True)

    # ── FAST UI demo: no heavy ML ────────────────────────────────────────────
        # ── FAST UI: lightweight demo path (no heavy ML) ─────────────────────────
    if os.environ.get("KAVACH_FAST_UI", "1").strip() != "0":
        demo_report = {
            "engine": "KAVACH-FAST-UI",
            "case_id": case_id,
            "risk_level": "REVIEW",
            "risk_reason": "Manual check recommended (demo mode).",
            "forensic_risk_score": 0.46,
            "detector_signals": [],
            "human_summary": "Demo screening complete.",
            "documents_analysed": ["demo"],
        }
        try:
            with open(
                os.path.join("case_logs", f"{case_id}_report.json"),
                "w",
                encoding="utf-8",
            ) as fh:
                json.dump(demo_report, fh, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARNING] could not save demo case log: {e}")

        ui = _map_result_ui(demo_report)
        ui["case_id"] = case_id
        try:
            session["last_case_id"] = case_id
            session["last_result_ui"] = ui
        except Exception:
            pass
        return jsonify(ui)

    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    captures = session.get("captures") or {}
    face_path = session.get("face_path") or captures.get("face")

    DOC_KEYS = ["passport", "visa", "national_id", "drivers_license", "border_permit"]
    available_docs = [
        (key, captures[key])
        for key in DOC_KEYS
        if captures.get(key) and os.path.exists(str(captures[key]))
    ]

    # Create case id at the START so PDF always has an id (even if analysis fails later)
    case_id = session.get("case_id") or f"case_{uuid.uuid4().hex[:12]}"
    session["case_id"] = case_id
    os.makedirs("case_logs", exist_ok=True)

    fallback = {
        "risk_level": "REVIEW",
        "risk_reason": "Full analysis did not finish on this machine. Captures were saved.",
        "forensic_risk_score": 0.5,
        "detector_signals": [],
        "case_id": case_id,
    }

    if not available_docs:
        fallback["risk_reason"] = "No document captures in this session (face only or all skipped). Capture a passport/ID to run document forensics."
        ui = _map_result_ui(fallback)
        ui["case_id"] = case_id
        session["last_case_id"] = case_id
        return jsonify(ui)

    # ── Run engine for each document and merge signals ────────────────────────
    merged_signals = []
    merged_risk_scores = []
    merged_risk_level = "REVIEW"
    merged_risk_reason = "Automated multi-document screening complete."

    for doc_key, doc_path in available_docs:
        try:
            cmd = [sys.executable, "kavach_engine.py", str(doc_path)]
            if face_path and os.path.exists(str(face_path)):
                cmd.append(str(face_path))
            else:
                cmd.append("")
            cmd.append(str(doc_key))


            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=240,
                cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
            )

            safe = os.path.splitext(os.path.basename(str(doc_path)))[0]
            log_path = os.path.join("case_logs", f"{safe}_report.json")

            doc_report = None
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as fh:
                    doc_report = json.load(fh)
            elif proc.returncode == 0:
                out = (proc.stdout or "").strip()
                start = out.find("{")
                end = out.rfind("}")
                if start != -1 and end != -1 and end > start:
                    doc_report = json.loads(out[start : end + 1])

            if isinstance(doc_report, dict):
                for sig in (doc_report.get("detector_signals") or []):
                    if isinstance(sig, dict):
                        sig = dict(sig)
                        sig["detector_name"] = f"[{doc_key}] {sig.get('detector_name', 'detector')}"
                        merged_signals.append(sig)

                score = doc_report.get("forensic_risk_score", 0.5)
                try:
                    merged_risk_scores.append(float(score))
                except (TypeError, ValueError):
                    merged_risk_scores.append(0.5)

                doc_rl = str(doc_report.get("risk_level", "REVIEW")).upper()
                if doc_rl in ("HIGH RISK", "HIGH_RISK"):
                    merged_risk_level = "HIGH RISK"
                    merged_risk_reason = f"[{doc_key}] {doc_report.get('risk_reason', '')}"
                elif doc_rl == "RESCAN" and merged_risk_level not in ("HIGH RISK", "HIGH_RISK"):
                    merged_risk_level = "RESCAN"
                    merged_risk_reason = f"[{doc_key}] {doc_report.get('risk_reason', '')}"
                elif doc_rl == "REVIEW" and merged_risk_level not in ("HIGH RISK", "HIGH_RISK", "RESCAN"):
                    merged_risk_level = "REVIEW"
                    if "complete" in merged_risk_reason:
                        merged_risk_reason = f"[{doc_key}] {doc_report.get('risk_reason', '')}"

                elif doc_rl in ("PASS", "GENUINE") and merged_risk_level not in (
                    "HIGH RISK",
                    "HIGH_RISK",
                    "REVIEW",
                ):
                    merged_risk_level = "PASS"

        except subprocess.TimeoutExpired:
            merged_signals.append({
                "detector_name": f"[{doc_key}] timeout",
                "status": "unavailable",
                "score": 0.5,
                "confidence": "low",
                "explanation": f"Engine timed out for {doc_key}.",
            })
        except Exception as exc:
            merged_signals.append({
                "detector_name": f"[{doc_key}] error",
                "status": "failed",
                "score": 0.5,
                "confidence": "low",
                "explanation": str(exc)[:200],
            })

    avg_risk = (sum(merged_risk_scores) / len(merged_risk_scores)) if merged_risk_scores else 0.5
    merged_report = {
        "engine": "KAVACH-MULTI",
        "case_id": case_id,
        "documents_analysed": [k for k, _ in available_docs],
        "live_image": os.path.basename(str(face_path)) if face_path else None,
        "risk_level": merged_risk_level,
        "risk_reason": merged_risk_reason,
        "forensic_risk_score": round(avg_risk, 3),
        "active_detectors_evaluated": len(merged_signals),
        "detector_signals": merged_signals,
    }

    try:
        merged_report["case_id"] = case_id   # use the one created at the start
        merged_log = os.path.join("case_logs", f"{case_id}_report.json")
        with open(merged_log, "w", encoding="utf-8") as fh:
            json.dump(merged_report, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARNING] could not save case log: {e}")

    ui = _map_result_ui(merged_report)
    ui["case_id"] = case_id
    try:
        session["last_result_ui"] = ui
        session["last_case_id"] = case_id
    except Exception:
        pass
    return jsonify(ui)

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

            report_hash = None
            anchor = rep.get("blockchain_anchor") or {}
            seal = rep.get("integrity_seal") or {}
            if isinstance(anchor, dict):
                report_hash = anchor.get("report_hash")
            if not report_hash and isinstance(seal, dict):
                report_hash = seal.get("report_hash")
            if not report_hash:
                report_hash = rep.get("report_hash")

            if report_hash:
                result = get_chain().verify_report_hash(str(report_hash))
                if isinstance(result, dict):
                    if result.get("valid") is True:
                        integrity = "intact"
                    elif result.get("reason") in ("not found", None) and result.get("valid") is False:
                        integrity = "unknown"
                    else:
                        integrity = "tampered"
                else:
                    integrity = "intact" if result else "unknown"
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
        os.path.join("case_logs", f"{safe_id}_report.json"),
        os.path.join("case_logs", f"{safe_id}.json"),
    ]
    if safe_id.endswith("_report"):
        candidates.insert(0, os.path.join("case_logs", f"{safe_id}.json"))

    log_path = next((path for path in candidates if os.path.exists(path)), None)

    if not log_path:
        return jsonify({"error": f"Case {safe_id} not found."}), 404

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:
        return jsonify({"error": f"Could not read report: {exc}"}), 500

    try:
        from report_generator import generate_case_report_pdf, REPORTLAB_AVAILABLE
        if not REPORTLAB_AVAILABLE:
            return jsonify({"error": "reportlab not installed on this server."}), 501
    except ImportError:
        return jsonify({"error": "report_generator module not found."}), 501

    import tempfile
    from flask import send_file
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
    if os.environ.get("KAVACH_FAST_UI", "1").strip() == "0":
        _warm_models()
    app.run(debug=True, use_reloader=False, threaded=True)