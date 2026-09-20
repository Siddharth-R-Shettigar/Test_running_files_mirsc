def classify_document(image_path, ocr_text):
    text = ocr_text.lower()
    
    if "passport" in text or "republic of" in text:
        return {"doc_type": "passport", "needs_mrz": True}
    elif "visa" in text:
        return {"doc_type": "visa", "needs_mrz": True}
    elif "driving" in text or "driver" in text or "dl" in text:
        return {"doc_type": "dl", "needs_mrz": False}
    elif "aadhaar" in text or "national" in text or "identity" in text:
        return {"doc_type": "national_id", "needs_mrz": False}
        
    return {"doc_type": "unknown", "needs_mrz": False}