# verification/health_check.py
import os
import sys
import json
from pathlib import Path

# Add the parent directory to the path so we can find KAVACH files
sys.path.append(str(Path(__file__).parent.parent))

def check_step(name):
    print(f"\n--- [CHECKING: {name}] ---")

def run_diagnostic():
    passed = 0
    total = 5

    # 1. Check Environment Variables
    check_step("API Keys & .env")
    from dotenv import load_dotenv
    load_dotenv()
    
    keys = ["GROQ_API_KEY", "GEMINI_API_KEY"]
    for key in keys:
        val = os.getenv(key)
        if val:
            print(f"✅ {key} is set.")
        else:
            print(f"❌ {key} is MISSING in .env file.")
    
    # 2. Check Forensic Engine Imports
    check_step("Forensic Engine (KAVACH)")
    try:
        import kavach_engine
        print("✅ kavach_engine.py loaded successfully.")
        passed += 1
    except Exception as e:
        print(f"❌ Failed to load kavach_engine: {e}")

    # 3. Check AI Analyst (Groq)
    check_step("AI Analyst (Groq/Llama)")
    try:
        from analyst import get_verdict
        # Mock scores to test the AI's logic
        mock_scores = {
            'metadata': 10, 'metadata_details': 'Clean',
            'ela': 10, 'ela_details': 'Clean',
            'frequency': 10, 'frequency_details': 'Clean',
            'trufor': 10, 'trufor_details': 'Clean',
            'provenance': 10, 'provenance_details': 'Clean',
            'pixel_stats': 10, 'pixel_stats_details': 'Clean'
        }
        print("Testing AI reasoning with mock 'Clean' scores...")
        verdict = get_verdict(mock_scores)
        print(f"✅ AI Response received. Verdict: {verdict.get('verdict')}")
        passed += 1
    except Exception as e:
        print(f"❌ AI Analyst failed: {e}")

    # 4. Check Crypto/Security Layer
    check_step("Crypto & Integrity Seals")
    try:
        from crypto_utils import generate_keys, sign_report, verify_report
        generate_keys() # Ensure keys exist
        test_data = {"test": "data"}
        seal = sign_report(test_data)
        test_data["integrity_seal"] = seal
        verification = verify_report(test_data)
        if verification.get("valid"):
            print("✅ Crypto signing and verification working.")
            passed += 1
        else:
            print("❌ Crypto verification failed.")
    except Exception as e:
        print(f"❌ Crypto module error: {e}")

    # 5. Full Engine Test on Sample Image
    check_step("End-to-End Image Processing")
    sample_path = "images/VISA.jpg"
    if not os.path.exists(sample_path):
        print(f"❌ Skipping: Please put an image at {sample_path} to test.")
    else:
        try:
            from connector import analyze_image
            print(f"Processing {sample_path}... (This takes 10-30 seconds)")
            result = analyze_image(sample_path)
            print(f"✅ Full Analysis Complete!")
            print(f"Final Verdict: {result.get('verdict')}")
            print(f"Confidence: {result.get('confidence')}%")
            passed += 1
        except Exception as e:
            print(f"❌ Full Analysis Failed: {e}")

    print("\n" + "="*30)
    print(f"DIAGNOSTIC SUMMARY: {passed}/{total} Modules Functional")
    print("="*30)

if __name__ == "__main__":
    run_diagnostic()