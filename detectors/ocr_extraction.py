import os
import base64
import requests
import easyocr
from dotenv import load_dotenv

# Load environment variables (API keys)
load_dotenv()

BHASHINI_API_KEY = os.getenv("BHASHINI_API_KEY")
BHASHINI_ENDPOINT = os.getenv(
    "BHASHINI_ENDPOINT", 
    "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
)

# Initialize standard English reader (loads once in memory)
try:
    eng_reader = easyocr.Reader(['en', 'hi'], gpu=False)
except Exception as e:
    print(f"[WARNING] EasyOCR init failed: {e}")
    eng_reader = None

def _call_bhashini_api(image_path: str, source_lang: str = "hi") -> str:
    """Sends the image to the Bhashini Dhruva API for Indic language OCR."""
    if not BHASHINI_API_KEY:
        return ""

    try:
        with open(image_path, "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
            
        payload = {
            "pipelineTasks": [{"taskType": "ocr", "config": {"language": {"sourceLanguage": source_lang}}}],
            "inputData": {"image": [{"imageContent": img_base64}]}
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BHASHINI_API_KEY}"
        }
        
        response = requests.post(BHASHINI_ENDPOINT, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        extracted_text = []
        if "pipelineResponse" in data:
            for task in data["pipelineResponse"]:
                if task.get("taskType") == "ocr":
                    for output in task.get("output", []):
                        source_text = output.get("source", "")
                        if source_text:
                            extracted_text.append(source_text)
                            
        return " ".join(extracted_text).strip()
        
    except Exception as e:
        print(f"[BHASHINI API ERROR] {e}")
        return ""

def extract_text(image_path: str) -> dict:
    """Main entry point for kavach_engine.py."""
    result = {
        "status": "passed",
        "score": 0.0,
        "confidence": "high",
        "explanation": "Text extracted successfully.",
        "fields": [],
        "mrz_lines": []
    }
    
    try:
        if eng_reader:
            eng_results = eng_reader.readtext(image_path)
            for bbox, text, conf in eng_results:
                result["fields"].append({
                    "text": text,
                    "confidence": float(conf),
                    "source": "easyocr"
                })
                if len(text) >= 28 and ("<" in text or text.startswith("P")):
                    result["mrz_lines"].append(text)
        
        for lang in ["hi", "ta"]: 
            indic_text = _call_bhashini_api(image_path, source_lang=lang)
            if indic_text:
                result["fields"].append({
                    "text": indic_text,
                    "confidence": 0.95,
                    "source": f"bhashini_{lang}"
                })
                
    except Exception as e:
        result["status"] = "failed"
        result["confidence"] = "low"
        result["explanation"] = f"OCR pipeline crashed: {str(e)}"
        
    return result