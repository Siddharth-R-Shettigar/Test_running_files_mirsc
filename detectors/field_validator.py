def validate_document_fields(combined_fields, doc_type):
    missing = []
    required = []
    
    if doc_type == "passport":
        required = ["passport_number", "dob"]
    elif doc_type == "national_id":
        required = ["dob"]
        
    for req in required:
        if req not in combined_fields or not combined_fields[req]:
            missing.append(req)
            
    if missing:
        return {"status": "flagged", "score": 0.7, "explanation": f"Missing mandatory schema fields: {', '.join(missing)}"}
    return {"status": "passed", "score": 0.1, "explanation": "All required document fields are present."}