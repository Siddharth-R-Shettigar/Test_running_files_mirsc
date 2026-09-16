from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from connector import analyze_image
import os
import uuid
import json

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "kavach-dev-secret-change-me")

# Demo login only — replace later with real auth if needed
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


@app.route("/")
def home():
    if session.get("logged_in"):
        return redirect(url_for("scan"))  # scan page comes in next step
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
        # Next step will be scan; for now go to old index if scan missing
        return redirect(url_for("scan") if "scan" in app.view_functions else url_for("index"))

    return render_template("login.html", error="Invalid login id or password."), 401

@app.route("/analyze", methods=["POST"])
def analyze():
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
        os.remove(image_path)

        # Encrypt sensitive fields before sending to frontend
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
        return jsonify({
            "error": str(e),
            "details": error_details
        }), 500


@app.route("/decrypt", methods=["POST"])
def decrypt():
    """
    Officer enters password on frontend.
    Frontend sends encrypted report + password here.
    Returns full decrypted report if password correct.
    """
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
        return jsonify({
            "success": True,
            "report": result["report"]
        })
    else:
        return jsonify({
            "success": False,
            "error": "Invalid password."
        }), 401


@app.route("/verify", methods=["POST"])
def verify():
    """
    Verify integrity of a saved case log.
    Officer submits case log JSON, gets back valid/invalid.
    """
    try:
        from crypto_utils import verify_report
        data = request.get_json()
        if not data:
            return jsonify({"error": "No report provided."}), 400

        result = verify_report(data)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/manifest", methods=["GET"])
def manifest():
    """Return integrity manifest of all case logs."""
    try:
        from crypto_utils import build_integrity_manifest
        manifest = build_integrity_manifest()
        return jsonify(manifest)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/scan")
def scan():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    # placeholder until next step
    return "<h2>Scan screen coming next</h2><p>Login worked.</p>"

if __name__ == "__main__":
    app.run(debug=True)