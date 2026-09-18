import cv2
import easyocr
import ssl

ssl._create_default_https_context = ssl._create_unverified_context
reader = easyocr.Reader(['en', 'hi', 'mr'], gpu=False)

def extract_text(image_path: str) -> dict:
    result = {"status": "passed", "score": 0.0, "confidence": "high", "explanation": "Text extracted successfully.", "fields": [], "mrz_lines": []}
    
    try:
        # 1. Read and Preprocess Image
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Upscale image to make numbers larger for the detector
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        
        # Apply slight blur to remove background noise, then threshold to black & white
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 2. Pass preprocessed image to EasyOCR (instead of the file path)
        detections = reader.readtext(thresh)
        
        for bbox, text, conf in detections:
            clean_text = text.strip()
            if clean_text:
                result["fields"].append({
                    "text": clean_text,
                    "confidence": round(float(conf), 4),
                    "source": "easyocr_local"
                })
                if len(clean_text) >= 28 and ("<" in clean_text or clean_text.startswith("P")):
                    result["mrz_lines"].append(clean_text)
                    
    except Exception as e:
        result["status"] = "failed"
        result["confidence"] = "low"
        result["explanation"] = f"OCR processing crashed: {str(e)}"

    return result