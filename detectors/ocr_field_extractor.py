import re

def extract_fields_from_ocr(ocr_raw, doc_type):
    fields = ocr_raw.get("fields", [])
    full_text = " ".join([f.get("text", "") for f in fields]).lower()
    extracted = {}
    
    dob_match = re.search(r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b', full_text)
    if dob_match:
        extracted["dob"] = dob_match.group(1)
        
    if doc_type == "passport":
        passport_match = re.search(r'\b([a-z]\d{7})\b', full_text)
        if passport_match:
            extracted["passport_number"] = passport_match.group(1).upper()
            
    return extracted