def check_ocr_mrz_consistency(visual_fields, mrz_fields):
    mismatches = []
    keys_to_check = ["dob", "passport_number", "surname", "expiry"]
    
    for key in keys_to_check:
        vis_val = visual_fields.get(key, "").strip().upper()
        mrz_val = mrz_fields.get(key, "").strip().upper()
        if vis_val and mrz_val and vis_val != mrz_val:
            mismatches.append(key)
            
    if mismatches:
        return {"status": "flagged", "score": 0.8, "explanation": f"Data mismatch found in fields: {', '.join(mismatches)}"}
    return {"status": "passed", "score": 0.1, "explanation": "Visual data and MRZ data align perfectly."}