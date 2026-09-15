import hashlib
import json
import os
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

# ---------------------------------------------------------------------------
# Key Management
# ---------------------------------------------------------------------------

KEY_DIR = os.path.join(os.path.dirname(__file__), "data", "keys")
PRIVATE_KEY_PATH = os.path.join(KEY_DIR, "kavach_private.pem")
PUBLIC_KEY_PATH = os.path.join(KEY_DIR, "kavach_public.pem")


def generate_keys():
    """Generate RSA key pair for KAVACH. Run once."""
    os.makedirs(KEY_DIR, exist_ok=True)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    public_key = private_key.public_key()
    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))

    print(f"Keys generated at {KEY_DIR}")
    return private_key, public_key


def load_private_key():
    if not os.path.exists(PRIVATE_KEY_PATH):
        generate_keys()
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )


def load_public_key():
    if not os.path.exists(PUBLIC_KEY_PATH):
        generate_keys()
    with open(PUBLIC_KEY_PATH, "rb") as f:
        return serialization.load_pem_public_key(
            f.read(), backend=default_backend()
        )


# ---------------------------------------------------------------------------
# Image Fingerprinting
# ---------------------------------------------------------------------------

def hash_image(image_path):
    """
    Generate SHA-256 hash of image file.
    Call at intake in kavach_engine.py before any processing.
    This fingerprint proves the image wasn't modified after submission.
    """
    sha256 = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_image_integrity(image_path, original_hash):
    """
    Verify image hasn't been modified since intake.
    Compare current hash against stored intake hash.
    """
    current_hash = hash_image(image_path)
    return {
        "intact": current_hash == original_hash,
        "original_hash": original_hash,
        "current_hash": current_hash
    }


# ---------------------------------------------------------------------------
# Report Signing
# ---------------------------------------------------------------------------

def sign_report(report_dict):
    """
    Sign the final KAVACH report with RSA private key.
    Adds integrity_seal to the report.
    """
    try:
        private_key = load_private_key()

        # Create deterministic string from report
        report_copy = {k: v for k, v in report_dict.items() if k != "integrity_seal"}
        report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
        report_bytes = report_str.encode("utf-8")

        # SHA-256 hash of report
        report_hash = hashlib.sha256(report_bytes).hexdigest()

        # RSA signature
        signature = private_key.sign(
            report_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        return {
            "report_hash": report_hash,
            "signature": signature.hex(),
            "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "algorithm": "RSA-PKCS1v15-SHA256",
            "verified": True
        }

    except Exception as e:
        return {
            "report_hash": None,
            "signature": None,
            "signed_at": None,
            "error": str(e),
            "verified": False
        }


def verify_report(report_dict):
    """
    Verify a signed KAVACH report hasn't been tampered with.
    Returns True if signature is valid.
    """
    try:
        seal = report_dict.get("integrity_seal", {})
        if not seal or not seal.get("signature"):
            return {"valid": False, "reason": "No integrity seal found"}

        public_key = load_public_key()

        report_copy = {k: v for k, v in report_dict.items() if k != "integrity_seal"}
        report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
        report_bytes = report_str.encode("utf-8")

        signature_bytes = bytes.fromhex(seal["signature"])

        public_key.verify(
            signature_bytes,
            report_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        return {"valid": True, "signed_at": seal.get("signed_at")}

    except Exception as e:
        return {"valid": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Case Log Integrity
# ---------------------------------------------------------------------------

def hash_case_log(log_path):
    """Hash a case log JSON file for integrity checking."""
    with open(log_path, "rb") as f:
        content = f.read()
    return hashlib.sha256(content).hexdigest()


def build_integrity_manifest(case_logs_dir="case_logs"):
    """
    Build a manifest of all case log hashes.
    Run this to create a tamper-evident audit trail.
    """
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "logs": {}
    }

    if not os.path.exists(case_logs_dir):
        return manifest

    for filename in sorted(os.listdir(case_logs_dir)):
        if filename.endswith(".json"):
            path = os.path.join(case_logs_dir, filename)
            manifest["logs"][filename] = hash_case_log(path)

    manifest_path = os.path.join(case_logs_dir, "integrity_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Manifest saved to {manifest_path}")
    return manifest


if __name__ == "__main__":
    print("KAVACH CRYPTO UTILS TEST")
    print("========================")

    # Generate keys
    generate_keys()
    print("Keys generated.")

    # Test image hashing
    test_images = [
        "images/passport2.jpg",
        "images/PAN.jpeg"
    ]

    for img in test_images:
        if os.path.exists(img):
            h = hash_image(img)
            print(f"Hash of {img}: {h[:32]}...")

    # Test report signing
    test_report = {
        "engine": "KAVACH",
        "file_analyzed": "passport2.jpg",
        "risk_level": "PASS",
        "forensic_risk_score": 0.23
    }

    seal = sign_report(test_report)
    print(f"\nReport signed: {seal['verified']}")
    print(f"Hash: {seal['report_hash'][:32]}...")

    test_report["integrity_seal"] = seal
    verification = verify_report(test_report)
    print(f"Verification: {verification['valid']}")

    # Build manifest
    manifest = build_integrity_manifest()
    print(f"\nManifest covers {len(manifest['logs'])} case logs")