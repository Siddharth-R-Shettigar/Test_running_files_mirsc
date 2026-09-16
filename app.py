from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
import uuid
import json

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
    {"key": "face", "title": "Face Capture", "blurb": "Biometric alignment & facial inspection"},
    {"key": "passport", "title": "Passport", "blurb": "Data page & MRZ"},
    {"key": "visa", "title": "Visa", "blurb": "Visa sticker / foil page"},
    {"key": "national_id", "title": "National ID", "blurb": "Aadhaar / national identity card"},
    {"key": "drivers_license", "title": "Driver’s License", "blurb": "License front"},
    {"key": "border_permit", "title": "Border Permit", "blurb": "Permit / supporting travel doc"},
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
    return redirect(url_for("login"))


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

    idx = _scan_index()
    if idx >= len(SCAN_STEPS):
        return redirect(url_for("result_placeholder"))

    return render_template(
        "scan.html",
        steps=SCAN_STEPS,
        current_index=idx,
        current=SCAN_STEPS[idx],
        captures=session.get("captures") or {},
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

    checklist = [
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

    captures = session.get("captures") or {}
    doc_path = session.get("doc_path") or captures.get("passport")
    face_path = session.get("face_path") or captures.get("face")

    report = {
        "risk_level": "REVIEW",
        "risk_reason": "No document image available for analysis.",
        "forensic_risk_score": 0.5,
        "detector_signals": [],
        "human_summary": "Capture a passport page to run full screening.",
    }

    if doc_path and os.path.exists(str(doc_path)):
        try:
            from kavach_engine import analyze_media
            live = face_path if face_path and os.path.exists(str(face_path)) else None
            report = analyze_media(str(doc_path), live_image_path=live)
            try:
                from llm_fusion import generate_human_summary
                report["human_summary"] = generate_human_summary(report)
            except Exception:
                pass
        except Exception as e:
            try:
                from connector import analyze_image
                report = analyze_image(str(doc_path))
                report["risk_reason"] = report.get("human_summary") or str(e)
            except Exception as e2:
                report["risk_reason"] = f"Analysis failed: {e2}"

    ui = _map_result_ui(report)
    return render_template("result.html", **ui) 


@app.route("/cases")
def cases():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return "<h2>Case logs screen next</h2>"


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
    return redirect(url_for("scan"))    


@app.route("/api/run_case")
def api_run_case():
    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    captures = session.get("captures") or {}
    doc_path = session.get("doc_path") or captures.get("passport")
    face_path = session.get("face_path") or captures.get("face")

    if not doc_path or not os.path.exists(str(doc_path)):
        ui = _map_result_ui({
            "risk_level": "REVIEW",
            "risk_reason": "No passport capture found.",
            "forensic_risk_score": 0.5,
            "detector_signals": [],
        })
        return jsonify(ui)

    try:
        from kavach_engine import analyze_media
        live = face_path if face_path and os.path.exists(str(face_path)) else None
        report = analyze_media(str(doc_path), live_image_path=live)
        try:
            from llm_fusion import generate_human_summary
            report["human_summary"] = generate_human_summary(report)
        except Exception:
            pass
        ui = _map_result_ui(report)
        session["last_result_ui"] = ui
        return jsonify(ui)
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui = _map_result_ui({
            "risk_level": "REVIEW",
            "risk_reason": f"Analysis failed or was interrupted: {e}",
            "forensic_risk_score": 0.5,
            "detector_signals": [],
        })
        return jsonify(ui)

def _warm_models():
    try:
        print("[KAVACH] Warming engine imports...", flush=True)
        import kavach_engine  # noqa: F401
        print("[KAVACH] Engine import done.", flush=True)
    except Exception as e:
        print(f"[KAVACH] Warmup skipped: {e}", flush=True)

if __name__ == "__main__":
    _warm_models()
    app.run(debug=True, use_reloader=False, threaded=True)