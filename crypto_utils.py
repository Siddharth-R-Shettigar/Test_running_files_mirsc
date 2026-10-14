import hashlib
import json
import os
import time
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# ---------------------------------------------------------------------------
# Key Management
# ---------------------------------------------------------------------------

KEY_DIR = os.path.join(os.path.dirname(__file__), "data", "keys")
PRIVATE_KEY_PATH = os.path.join(KEY_DIR, "kavach_private.pem")
PUBLIC_KEY_PATH = os.path.join(KEY_DIR, "kavach_public.pem")
SALT_PATH = os.path.join(KEY_DIR, "kavach.salt")


def generate_keys():
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

    # Generate and save a fixed salt for password derivation
    salt = os.urandom(16)
    with open(SALT_PATH, "wb") as f:
        f.write(salt)

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


def load_salt():
    if not os.path.exists(SALT_PATH):
        generate_keys()
    with open(SALT_PATH, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Password-Based AES-256 Encryption
# ---------------------------------------------------------------------------

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive AES-256 key from password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
        backend=default_backend()
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_sensitive(data: dict, password: str) -> dict:
    """
    Encrypt sensitive fields from report using password-derived AES-256-GCM key.
    Returns dict with encrypted blob + public summary only.
    """
    salt = load_salt()
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)

    # Fields that stay visible without password
    public_fields = {
        "engine": data.get("engine"),
        "file_analyzed": data.get("file_analyzed"),
        "risk_level": data.get("risk_level"),
        "risk_reason": data.get("risk_reason"),
        "forensic_risk_score": data.get("forensic_risk_score"),
        "active_detectors_evaluated": data.get("active_detectors_evaluated"),
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "encrypted": True,
        "message": "Full report requires officer authentication."
    }

    # Everything else gets encrypted
    sensitive_fields = {
        k: v for k, v in data.items()
        if k not in public_fields and k != "encrypted" and k != "message"
    }

    plaintext = json.dumps(sensitive_fields, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    public_fields["encrypted_payload"] = {
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-SHA256-480000"
    }

    return public_fields


def decrypt_sensitive(encrypted_report: dict, password: str) -> dict:
    """
    Decrypt report using officer password.
    Returns full report if password correct, error dict if wrong.
    """
    try:
        payload = encrypted_report.get("encrypted_payload")
        if not payload:
            return {"error": "No encrypted payload found.", "success": False}

        salt = load_salt()
        key = _derive_key(password, salt)
        aesgcm = AESGCM(key)

        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])

        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        sensitive_fields = json.loads(plaintext.decode("utf-8"))

        # Merge public + decrypted fields
        full_report = {
            k: v for k, v in encrypted_report.items()
            if k not in ("encrypted_payload", "encrypted", "message")
        }
        full_report.update(sensitive_fields)
        full_report["decrypted"] = True
        full_report["decrypted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        return {"success": True, "report": full_report}

    except Exception:
        return {
            "success": False,
            "error": "Invalid password or corrupted report."
        }


# ---------------------------------------------------------------------------
# Image Fingerprinting
# ---------------------------------------------------------------------------

def hash_image(image_path):
    sha256 = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_image_integrity(image_path, original_hash):
    current_hash = hash_image(image_path)
    return {
        "intact": current_hash == original_hash,
        "original_hash": original_hash,
        "current_hash": current_hash
    }


# ---------------------------------------------------------------------------
# Report Signing (RSA)
# ---------------------------------------------------------------------------

def sign_report(report_dict):
    try:
        private_key = load_private_key()
        report_copy = {k: v for k, v in report_dict.items() if k != "integrity_seal"}
        report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
        report_bytes = report_str.encode("utf-8")
        report_hash = hashlib.sha256(report_bytes).hexdigest()

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
        return {"report_hash": None, "signature": None, "error": str(e), "verified": False}


def verify_report(report_dict):
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
# Case Log Integrity Manifest
# ---------------------------------------------------------------------------

def hash_case_log(log_path):
    with open(log_path, "rb") as f:
        content = f.read()
    return hashlib.sha256(content).hexdigest()


def build_integrity_manifest(case_logs_dir="case_logs"):
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "logs": {}
    }

    if not os.path.exists(case_logs_dir):
        return manifest

    for filename in sorted(os.listdir(case_logs_dir)):
        if filename.endswith(".json") and filename != "integrity_manifest.json":
            path = os.path.join(case_logs_dir, filename)
            manifest["logs"][filename] = hash_case_log(path)

    manifest_path = os.path.join(case_logs_dir, "integrity_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("KAVACH CRYPTO TEST")
    print("==================")

    generate_keys()

    test_report = {
        "engine": "KAVACH",
        "file_analyzed": "passport2.jpg",
        "risk_level": "REVIEW",
        "risk_reason": "Forensic anomaly detected.",
        "forensic_risk_score": 0.43,
        "active_detectors_evaluated": 25,
        "detector_signals": [{"detector_name": "ela", "score": 0.7}],
        "image_fingerprint": "abc123",
        "rag_context": {"standards": "Indian Passport"}
    }

    PASSWORD = "kavach2026"

    print("\n1. Encrypting report...")
    encrypted = encrypt_sensitive(test_report, PASSWORD)
    print(f"   Public fields visible: {list(k for k in encrypted if k != 'encrypted_payload')}")
    print(f"   Encrypted payload: present ✅")

    print("\n2. Decrypting with CORRECT password...")
    result = decrypt_sensitive(encrypted, PASSWORD)
    print(f"   Success: {result['success']}")
    if result['success']:
        print(f"   Fields restored: {list(result['report'].keys())}")

    print("\n3. Decrypting with WRONG password...")
    result_wrong = decrypt_sensitive(encrypted, "wrongpassword")
    print(f"   Success: {result_wrong['success']}")
    print(f"   Error: {result_wrong['error']}")

    print("\n4. Signing report...")
    seal = sign_report(test_report)
    print(f"   Signed: {seal['verified']}")
    # ---------------------------------------------------------------------------
# Blockchain Anchoring
# ---------------------------------------------------------------------------

def anchor_report_on_chain(report_dict: dict, case_id: str = None) -> dict:
    """
    Create a clean hash of the report and anchor it on the local blockchain.
    Returns the blockchain receipt.
    """
    from blockchain import get_chain

    # Hash the report without previous seals/anchors
    report_copy = {
        k: v for k, v in report_dict.items()
        if k not in ("integrity_seal", "blockchain_anchor")
    }
    report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
    report_hash = hashlib.sha256(report_str.encode("utf-8")).hexdigest()

    chain = get_chain()
    receipt = chain.add_report_anchor(
        report_hash=report_hash,
        case_id=case_id or report_dict.get("case_id"),
        risk_level=report_dict.get("risk_level"),
        extra={
            "file_analyzed": report_dict.get("file_analyzed"),
            "engine": report_dict.get("engine", "KAVACH"),
        },
    )
    return receipt


def verify_report_on_chain(report_dict: dict) -> dict:
    """Verify both the RSA signature and the blockchain anchor."""
    from blockchain import get_chain

    # 1. Existing RSA check
    rsa_result = verify_report(report_dict)

    # 2. Blockchain check
    report_copy = {
        k: v for k, v in report_dict.items()
        if k not in ("integrity_seal", "blockchain_anchor")
    }
    report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
    report_hash = hashlib.sha256(report_str.encode("utf-8")).hexdigest()

    chain_result = get_chain().verify_report_hash(report_hash)

    return {
        "rsa_valid": rsa_result.get("valid", False),
        "blockchain_valid": chain_result.get("valid", False),
        "rsa_details": rsa_result,
        "blockchain_details": chain_result,
        "overall_valid": rsa_result.get("valid", False) and chain_result.get("valid", False),
    }
# ---------------------------------------------------------------------------
# Blockchain Anchoring
# ---------------------------------------------------------------------------

def anchor_report_on_chain(report_dict, case_id=None):
    """
    Create a clean hash of the report and anchor it on the local blockchain.
    Returns the blockchain receipt.
    """
    from blockchain import get_chain

    # Hash the report without previous seals/anchors
    report_copy = {
        k: v for k, v in report_dict.items()
        if k not in ("integrity_seal", "blockchain_anchor")
    }
    report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
    report_hash = hashlib.sha256(report_str.encode("utf-8")).hexdigest()

    chain = get_chain()
    receipt = chain.add_report_anchor(
        report_hash=report_hash,
        case_id=case_id or report_dict.get("case_id"),
        risk_level=report_dict.get("risk_level"),
        extra={
            "file_analyzed": report_dict.get("file_analyzed"),
            "engine": report_dict.get("engine", "KAVACH"),
        },
    )
    return receipt


def verify_report_on_chain(report_dict):
    """Verify both the RSA signature and the blockchain anchor."""
    from blockchain import get_chain

    # 1. Existing RSA check
    rsa_result = verify_report(report_dict)

    # 2. Blockchain check
    report_copy = {
        k: v for k, v in report_dict.items()
        if k not in ("integrity_seal", "blockchain_anchor")
    }
    report_str = json.dumps(report_copy, sort_keys=True, ensure_ascii=False)
    report_hash = hashlib.sha256(report_str.encode("utf-8")).hexdigest()

    chain_result = get_chain().verify_report_hash(report_hash)

    return {
        "rsa_valid": rsa_result.get("valid", False),
        "blockchain_valid": chain_result.get("valid", False),
        "rsa_details": rsa_result,
        "blockchain_details": chain_result,
        "overall_valid": rsa_result.get("valid", False) and chain_result.get("valid", False),
    }