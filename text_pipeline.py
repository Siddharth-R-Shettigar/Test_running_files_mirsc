import sys
import os

# Import from detectors folder
from detectors.ocr_extraction import extract_text
from detectors.document_classifier import classify_document
from detectors.ocr_field_extractor import extract_fields_from_ocr
from detectors.mrz_parser import parse_mrz
from detectors.ocr_mrz_consistency import check_ocr_mrz_consistency
from detectors.national_id_validator import validate_national_id
from detectors.field_validator import validate_document_fields

def run_text_pipeline(image_path: str):
    report = {"pipeline_status": "success", "signals": []}

    # STEP 1: Base Extraction
    ocr_raw = extract_text(image_path)
    if ocr_raw.get("status") == "failed":
        print("\n[DEBUG] OCR CRASH EXPLANATION:", ocr_raw.get("explanation", "No explanation provided"))
        return {"pipeline_status": "failed", "reason": "OCR Extraction failed."}
    
    ocr_text = " ".join([f.get("text", "") for f in ocr_raw.get("fields", [])])
    mrz_lines = ocr_raw.get("mrz_lines", [])

    # STEP 2: Classification (Restricted Scope)
    clf_result = classify_document(image_path, ocr_text)
    raw_doc_type = str(clf_result.get("doc_type", "unknown")).lower()
    
    allowed_types = ["passport", "visa", "national_id", "dl"]
    doc_type = next((t for t in allowed_types if t in raw_doc_type), "unknown")
    needs_mrz = doc_type in ["passport", "visa"]

    report["document_type"] = doc_type

    # STEP 3: Structured Visual Extraction
    visual_fields = extract_fields_from_ocr(ocr_raw, doc_type)
    mrz_fields = {}

    # STEP 4 & 5: MRZ Parsing & Consistency
    if needs_mrz and len(mrz_lines) >= 2:
        mrz_result = parse_mrz(mrz_lines)
        mrz_fields = mrz_result.get("fields", {})
        report["signals"].append({"module": "mrz_parser", "data": mrz_result})
        
        consistency_result = check_ocr_mrz_consistency(visual_fields, mrz_fields)
        report["signals"].append({"module": "ocr_mrz_consistency", "data": consistency_result})

    # STEP 6: National ID Validator
    if doc_type == "national_id":
        id_validation_result = validate_national_id(ocr_text) 
        report["signals"].append({"module": "national_id_validator", "data": id_validation_result})

    # STEP 7: Global Field Validator
    combined_fields = {**visual_fields, **mrz_fields}
    field_validation_result = validate_document_fields(combined_fields, doc_type)
    report["signals"].append({"module": "field_validator", "data": field_validation_result})

    return report

if __name__ == "__main__":
    import json
    
    if len(sys.argv) < 2:
        print("Please provide an image path.")
        sys.exit(1)
        
    test_image = sys.argv[1]
    print(f"Running text pipeline on: {test_image}\n")
    
    result = run_text_pipeline(test_image)
    print(json.dumps(result, indent=2, ensure_ascii=False))