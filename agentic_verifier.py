import json
import os
import sys
from typing import Any, Dict
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

# Import your existing detector modules as tools
from detectors.mrz_parser import parse_mrz
from detectors.ocr_extraction import extract_text
from detectors.ocr_field_extractor import extract_fields_from_ocr

# Load environment variables from .env file
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
  raise ValueError("GEMINI_API_KEY is missing. Please set it in your .env file.")

client = genai.Client(api_key=api_key)


# ---------------------------------------------------------
# Agent Tools (Wrapping Existing Detector Code)
# ---------------------------------------------------------
def extract_visual_ocr_fields(image_path: str) -> dict:
  """Tool: Runs the standard OCR extraction pipeline on the image to extract visual fields."""
  ocr_raw = extract_text(image_path)
  return extract_fields_from_ocr(ocr_raw) if isinstance(ocr_raw, dict) else {}


def parse_mrz_lines(line1: str, line2: str) -> dict:
  """Tool: Parses extracted MRZ strings into structured key-value pairs."""
  return parse_mrz([line1, line2])


def verify_mrz_checksum(mrz_line2: str) -> Dict[str, Any]:
  """Tool: Calculates ICAO 9303 checksums for MRZ fields (DOB, Expiry, Passport No)."""

  def calc_check_digit(data: str) -> int:
    weights = [7, 3, 1]
    total = 0
    for i, char in enumerate(data):
      if char.isdigit():
        val = int(char)
      elif char.isalpha():
        val = ord(char.upper()) - 55
      else:
        val = 0
      total += val * weights[i % 3]
    return total % 10

  if len(mrz_line2) < 44:
    return {"valid": False, "reason": "MRZ Line 2 length < 44 characters"}

  pass_num = mrz_line2[0:9]
  pass_check = mrz_line2[9]
  dob = mrz_line2[13:19]
  dob_check = mrz_line2[19]
  exp = mrz_line2[21:27]
  exp_check = mrz_line2[27]

  valid_pass = str(calc_check_digit(pass_num)) == pass_check
  valid_dob = str(calc_check_digit(dob)) == dob_check
  valid_exp = str(calc_check_digit(exp)) == exp_check

  return {
      "passport_checksum_valid": valid_pass,
      "dob_checksum_valid": valid_dob,
      "expiry_checksum_valid": valid_exp,
      "overall_mrz_valid": valid_pass and valid_dob and valid_exp,
  }


# ---------------------------------------------------------
# Main Agentic Workflow
# ---------------------------------------------------------
def audit_document_agentic(image_path: str) -> dict:
  """Executes the Agentic Verification Workflow."""
  img = Image.open(image_path)

  system_instruction = """
    You are an Agentic Document Authentication Auditor.
    Your task is to analyze passport/ID images and verify data consistency:
    
    1. Call `extract_visual_ocr_fields` using the provided image path to get the initial OCR extraction.
    2. Read the MRZ lines at the bottom of the image and call `parse_mrz_lines`.
    3. If MRZ Line 2 is present, call `verify_mrz_checksum` to validate the checksums.
    4. Self-Correction step: Compare visual fields with MRZ values. If any visual OCR field returns an empty string or unavailable status (e.g., Surname or Nationality missing), re-examine the image visually to read the field directly.
    5. Construct and return a unified JSON response matching this exact structure:
    {
      "status": "flagged" | "passed" | "incomplete",
      "score": float (0.0 to 1.0),
      "confidence": float,
      "mismatches": [list of field names],
      "unavailable": [list of field names],
      "comparisons": [
        {
          "field": "field_name",
          "status": "passed" | "flagged" | "unavailable",
          "ocr": "visual value",
          "mrz": "mrz value",
          "explanation": "Detailed comparison finding"
        }
      ],
      "explanation": "Summary of anomalies, checksum results, and self-corrections made."
    }
    IMPORTANT: Output ONLY valid raw JSON text. Do not include markdown code block wrappers (like ```json).
    """

  # Register tools for the agent
  tools = [
      types.Tool(
          function_declarations=[
              extract_visual_ocr_fields,
              parse_mrz_lines,
              verify_mrz_checksum,
          ]
      )
  ]

  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=[
          img,
          f"Perform a full document audit on image path: {image_path}",
      ],
      config=types.GenerateContentConfig(
          system_instruction=system_instruction,
          tools=tools,
          temperature=0.1,
      ),
  )

  try:
    cleaned_json = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned_json)
  except Exception as e:
    return {
        "status": "failed",
        "error": f"Failed to parse Agent output: {str(e)}",
        "raw_response": response.text,
    }


if __name__ == "__main__":
  if len(sys.argv) < 2:
    print("Usage: python kavach/agentic_verifier.py <path_to_image>")
    sys.exit(1)

  image_file = sys.argv[1]
  audit_result = audit_document_agentic(image_file)
  print(json.dumps(audit_result, indent=2, ensure_ascii=False))