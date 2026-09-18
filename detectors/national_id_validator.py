import re

def validate_national_id(ocr_text: str) -> dict:
    """
    Validates Indian National ID (Aadhaar) formats:
    - Standard 12-digit format (XXXX XXXX XXXX)
    - Masked format (XXXX XXXX 1234 / **** **** 1234)
    - Includes common OCR character normalization (O->0, I/l->1, etc.)
    """
    text = ocr_text

    # 1. Direct search for standard spaced 4-4-4 grouping: XXXX XXXX XXXX
    grouped_pattern = re.search(r'\b([2-9]\d{3})[\s\-_]+(\d{4})[\s\-_]+(\d{4})\b', text)
    if grouped_pattern:
        return {
            "status": "passed",
            "score": 0.1,
            "explanation": "Valid 12-digit National ID format detected."
        }

    # 2. Check for Masked format: [X or *]{4} [X or *]{4} 1234
    masked_pattern = re.search(r'(?:[xX\*]{4}[\s\-_]+){2}(\d{4})\b', text)
    if masked_pattern:
        return {
            "status": "passed",
            "score": 0.15,
            "explanation": "Valid Masked National ID format detected."
        }

    # 3. OCR normalization check for character substitution in candidate blocks
    # Normalize common digit confusions (O/o -> 0, I/l/| -> 1, B -> 8, S -> 5)
    char_map = str.maketrans({
        'O': '0', 'o': '0', 'Q': '0', 'D': '0',
        'I': '1', 'l': '1', '|': '1', '!': '1',
        'S': '5', 's': '5',
        'B': '8'
    })
    normalized_text = text.translate(char_map)

    norm_match = re.search(r'\b([2-9]\d{3})[\s\-_]+(\d{4})[\s\-_]+(\d{4})\b', normalized_text)
    if norm_match:
        return {
            "status": "passed",
            "score": 0.2,
            "explanation": "Valid 12-digit National ID format detected after OCR noise normalization."
        }

    # 4. Fallback search for unspaced continuous 12 digits
    continuous_match = re.search(r'(?<!\d)([2-9]\d{11})(?!\d)', re.sub(r'[\s\-_]', '', text))
    if continuous_match:
        return {
            "status": "passed",
            "score": 0.1,
            "explanation": "Valid continuous 12-digit National ID format detected."
        }

    return {
        "status": "unavailable",
        "score": 0.5,
        "explanation": "No recognized National ID pattern found."
    }