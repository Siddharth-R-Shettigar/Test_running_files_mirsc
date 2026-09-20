import re

def validate_national_id(ocr_text):
    compact_text = re.sub(r'[\s-]', '', ocr_text)
    aadhaar_match = re.search(r'(?<!\d)([2-9]\d{11})(?!\d)', compact_text)
    
    if aadhaar_match:
        return {"status": "passed", "score": 0.1, "explanation": "Valid 12-digit National ID format detected."}
        
    return {"status": "unavailable", "score": 0.5, "explanation": "No recognized National ID pattern found."}