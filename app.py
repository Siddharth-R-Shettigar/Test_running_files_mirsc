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
    # UI demo: never block on heavy models
    if os.environ.get("KAVACH_FAST_UI", "1").strip() != "0":
        return jsonify(_map_result_ui({
            "risk_level": "REVIEW",
            "risk_reason": "Manual check recommended",
            "forensic_risk_score": 0.46,
            "detector_signals": [],
        }))

    if not session.get("logged_in"):
        return jsonify({"error": "not logged in"}), 401

    import subprocess
    import sys

    captures = session.get("captures") or {}
    doc_path = session.get("doc_path") or captures.get("passport")
    face_path = session.get("face_path") or captures.get("face")

    fallback = {
        "risk_level": "REVIEW",
        "risk_reason": "Full analysis did not finish on this machine. Captures were saved.",
        "forensic_risk_score": 0.5,
        "detector_signals": [],
    }

    if not doc_path or not os.path.exists(str(doc_path)):
        fallback["risk_reason"] = "No passport capture found in session."
        return jsonify(_map_result_ui(fallback))

    # Fast demo mode: set KAVACH_FAST_UI=1 in env to skip heavy models
    if os.environ.get("KAVACH_FAST_UI", "").strip() == "1":
        ui = _map_result_ui({
            "risk_level": "REVIEW",
            "risk_reason": "Fast UI mode: document captured. Run full engine offline for forensic scores.",
            "forensic_risk_score": 0.35,
            "detector_signals": [
                {"detector_name": "capture_pipeline", "status": "passed", "score": 0.1, "confidence": "high", "explanation": "All scan steps completed."},
            ],
            "human_summary": "Captures OK. Full forensics skipped (FAST_UI).",
        })
        return jsonify(ui)

    report = None
    try:
        cmd = [sys.executable, "kavach_engine.py", str(doc_path)]
        if face_path and os.path.exists(str(face_path)):
            cmd.append(str(face_path))

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        )

        safe = os.path.splitext(os.path.basename(str(doc_path)))[0]
        log_path = os.path.join("case_logs", f"{safe}_report.json")

        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        elif proc.returncode == 0:
            out = (proc.stdout or "").strip()
            # engine prints JSON then may print "Saved case log..."
            start = out.find("{")
            end = out.rfind("}")
            if start != -1 and end != -1 and end > start:
                report = json.loads(out[start : end + 1])

        if not isinstance(report, dict):
            err = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-400:]
            fallback["risk_reason"] = f"Engine did not return a report (code {proc.returncode}). {err}"
            report = fallback

    except subprocess.TimeoutExpired:
        fallback["risk_reason"] = "Analysis timed out (4 min). Use FAST_UI or a stronger machine."
        report = fallback
    except Exception as e:
        fallback["risk_reason"] = f"Could not run analysis: {e}"
        report = fallback

    ui = _map_result_ui(report)
    try:
        session["last_result_ui"] = ui
    except Exception:
        pass
    return jsonify(ui)

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