import json
import os
from rag_query import build_rag_context

def enrich_with_rag(doc_type, country, detector_results):
    """
    Takes detector results and enriches them with RAG context.
    Drop-in addition to kavach_engine.py pipeline.
    
    Usage in kavach_engine.py:
        from rag_integration import enrich_with_rag
        rag_context = enrich_with_rag(doc_type, country, detector_results)
        # pass rag_context to llm_fusion
    """
    try:
        context = build_rag_context(doc_type, country, detector_results)
        return {
            "success": True,
            "rag_context": context,
            "context_length": len(context)
        }
    except Exception as e:
        return {
            "success": False,
            "rag_context": "",
            "error": str(e)
        }


def build_enriched_prompt(base_prompt, rag_context):
    """
    Injects RAG context into any existing LLM prompt.
    Use this in llm_fusion.py before sending to model.
    """
    if not rag_context:
        return base_prompt

    enriched = f"""
RETRIEVED KNOWLEDGE BASE CONTEXT:
==================================
{rag_context}
==================================

CURRENT DOCUMENT ANALYSIS:
{base_prompt}

INSTRUCTIONS:
- Use the retrieved standards to validate document fields
- Compare detector findings against similar past fraud cases
- Check if expected security features are present
- Flag any deviation from official document standards
- Provide confidence score based on standards compliance
"""
    return enriched


def validate_against_standards(doc_type, country, extracted_fields):
    """
    Validates extracted OCR fields against retrieved standards.
    Use this in field_validator.py for dynamic validation.
    """
    from rag_query import query_document_standards

    standards = query_document_standards(doc_type, country)

    if not standards['retrieved']:
        return {
            "validated": False,
            "reason": "Could not retrieve standards",
            "fields": extracted_fields
        }

    validation_results = {}
    issues = []

    # Basic field presence checks based on doc type
    if "passport" in doc_type.lower():
        required_fields = [
            "surname", "given_names", "nationality",
            "date_of_birth", "sex", "expiry_date", "passport_number"
        ]
        for field in required_fields:
            present = field in extracted_fields and extracted_fields[field]
            validation_results[field] = "PRESENT" if present else "MISSING"
            if not present:
                issues.append(f"Missing required field: {field}")

    elif "pan" in doc_type.lower():
        required_fields = ["pan_number", "name", "father_name", "date_of_birth"]
        for field in required_fields:
            present = field in extracted_fields and extracted_fields[field]
            validation_results[field] = "PRESENT" if present else "MISSING"
            if not present:
                issues.append(f"Missing required field: {field}")

        # PAN format check
        if "pan_number" in extracted_fields:
            pan = extracted_fields["pan_number"]
            import re
            if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', str(pan)):
                issues.append(f"Invalid PAN format: {pan}")
                validation_results["pan_format"] = "INVALID"
            else:
                validation_results["pan_format"] = "VALID"

    elif "aadhaar" in doc_type.lower():
        required_fields = ["aadhaar_number", "name", "date_of_birth", "gender"]
        for field in required_fields:
            present = field in extracted_fields and extracted_fields[field]
            validation_results[field] = "PRESENT" if present else "MISSING"
            if not present:
                issues.append(f"Missing required field: {field}")

        # Aadhaar format check
        if "aadhaar_number" in extracted_fields:
            aadhaar = str(extracted_fields["aadhaar_number"]).replace(" ", "")
            if not (len(aadhaar) == 12 and aadhaar.isdigit()):
                issues.append(f"Invalid Aadhaar format: {aadhaar}")
                validation_results["aadhaar_format"] = "INVALID"
            else:
                validation_results["aadhaar_format"] = "VALID"

    is_valid = len(issues) == 0
    confidence = round(
        (sum(1 for v in validation_results.values() if v in ["PRESENT", "VALID"]) /
         max(len(validation_results), 1)) * 100, 2
    )

    return {
        "validated": is_valid,
        "confidence": confidence,
        "field_results": validation_results,
        "issues": issues,
        "standards_used": standards['standards'][0]['type'] if standards['standards'] else "unknown",
        "retrieved_standards": standards['standards'][0]['content'][:300] if standards['standards'] else ""
    }


if __name__ == "__main__":
    print("Testing RAG Integration")
    print("=======================")

    # Test enrichment
    detector_results = {
        "ela_score": 0.73,
        "copy_move_detected": True,
        "mrz_consistent": False,
        "blur_score": 0.2
    }

    result = enrich_with_rag("Indian Passport", "India", detector_results)
    print(f"RAG enrichment success: {result['success']}")
    print(f"Context length: {result['context_length']} chars")
    print()

    # Test field validation
    fields = {
        "pan_number": "ABCDE1234F",
        "name": "TEST USER",
        "father_name": "TEST FATHER",
        "date_of_birth": "01/01/1990"
    }

    validation = validate_against_standards("PAN Card", "India", fields)
    print(f"Validation result: {json.dumps(validation, indent=2)}")