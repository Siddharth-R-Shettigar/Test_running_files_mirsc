import re

def classify_document(image_path: str, ocr_text: str) -> dict:
    if not ocr_text:
        return {"doc_type": "unknown", "needs_mrz": False}
        
    text = ocr_text.lower()

    # 1. Aadhaar / National ID keywords (English, Devanagari, and common OCR fragments)
    aadhaar_markers = [
        "aadhaar", "aadhar", "uidai", "government of india",
        "unique identification", "आधार", "भारत सरकार", "mera aadhaar"
    ]
    if any(marker in text for marker in aadhaar_markers):
        return {"doc_type": "national_id", "needs_mrz": False}
        
    # 2. Passport markers (English and Hindi)
    if "passport" in text or "republic of" in text or "पासपोर्ट" in text:
        return {"doc_type": "passport", "needs_mrz": True}
        
    # 3. Visa markers
    if "visa" in text or "वीज़ा" in text:
        return {"doc_type": "visa", "needs_mrz": True}
        
    # 4. Driving License markers (Standalone words only)
    if re.search(r'\b(driving|driver|license|licence|dl)\b', text):
        return {"doc_type": "dl", "needs_mrz": False}
        
    # 5. Mandatory Fallback (Prevents the NoneType crash)
    return {"doc_type": "unknown", "needs_mrz": False}