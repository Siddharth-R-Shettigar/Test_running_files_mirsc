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



@app.route("/result")
def result_placeholder():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    captures = session.get("captures") or {}
    lines = ["<h2>All capture steps finished</h2><ul>"]
    for s in SCAN_STEPS:
        val = captures.get(s["key"])
        label = "skipped" if val is None and s["key"] in captures else (val or "missing")
        lines.append(f"<li><b>{s['title']}</b>: {label}</li>")
    lines.append("</ul><p><a href='/scan/reset'>Start over</a> · <a href='/result'>Result UI next</a></p>")
    return "\n".join(lines)


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

SCAN_STEPS = [
    {"key": "face", "title": "Face Capture", "blurb": "Biometric alignment & facial inspection"},
    {"key": "passport", "title": "Passport", "blurb": "Data page & MRZ"},
    {"key": "visa", "title": "Visa", "blurb": "Visa sticker / foil page"},
    {"key": "national_id", "title": "National ID", "blurb": "Aadhaar / national identity card"},
    {"key": "drivers_license", "title": "Driver’s License", "blurb": "License front"},
    {"key": "border_permit", "title": "Border Permit", "blurb": "Permit / supporting travel doc"},
]

def _scan_index():
    """How many captures done → next step index (0-based)."""
    captures = session.get("captures") or {}
    for i, step in enumerate(SCAN_STEPS):
        if step["key"] not in captures:
            return i
    return len(SCAN_STEPS)

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

if __name__ == "__main__":
    app.run(debug=True)