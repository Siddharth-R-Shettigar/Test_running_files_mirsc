# detectors/ocr_field_extractor.py
# Pulls structured fields out of raw OCR token list for non-MRZ documents

import re
from datetime import datetime

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
}


def normalize_date(raw: str) -> str:
    """
    Convert human-readable date to YYMMDD.
    Handles: 'JAN 1981', '30 NOV 2009', '29 NOV 2019',
    and numeric forms like '14.07.1981', '14/07/1981', '14-07-1981'.
    Returns '' if unparseable.
    """
    raw = raw.upper().strip()

    # Format: MON YYYY (DOB) → just YYMM01 approximate
    m = re.match(r'^([A-Z]{3})\s+(\d{4})$', raw)
    if m:
        mon = MONTH_MAP.get(m.group(1), "01")
        yy = m.group(2)[2:]
        return f"{yy}{mon}01"

    # Format: DD MON YYYY
    m = re.match(r'^(\d{1,2})\s+([A-Z]{3})\s+(\d{4})$', raw)
    if m:
        dd = m.group(1).zfill(2)
        mon = MONTH_MAP.get(m.group(2), "01")
        yy = m.group(3)[2:]
        return f"{yy}{mon}{dd}"

    # Format: DD.MM.YYYY / DD/MM/YYYY / DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$', raw)
    if m:
        dd = m.group(1).zfill(2)
        mon = m.group(2).zfill(2)
        yy = m.group(3)[2:]
        return f"{yy}{mon}{dd}"

    return ""


# Matches any of the human-readable date shapes normalize_date understands.
DATE_LIKE_RE = re.compile(
    r'^([A-Z]{3}\s+\d{4}|\d{1,2}\s+[A-Z]{3}\s+\d{4}|\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})$'
)


def _find_value_near_label(texts: list, label_keywords: list, window: int = 4, value_check=None):
    """
    Bilingual passport layouts frequently put two field labels side by side
    on one row, with both values on the row below (e.g. 'Date de naissance/
    Date of birth' next to 'Lieu de naissance/Place of birth'). That means
    the value for a label is often NOT the very next OCR token — it can be
    a few tokens further along, after the other label(s) on that row.

    This scans a small forward window after the matched label for the first
    token that passes value_check (or, if value_check is None, the first
    non-empty token that doesn't itself look like another field label).
    """
    for i, t in enumerate(texts):
        tu = t.upper()
        if not any(kw in tu for kw in label_keywords):
            continue
        for j in range(i + 1, min(i + 1 + window, len(texts))):
            candidate = texts[j].strip()
            if not candidate:
                continue
            if value_check is not None:
                if value_check(candidate):
                    return candidate
                continue
            # Default: skip tokens that look like another label (contain '/'
            # the way these bilingual headers do) and accept the first that doesn't.
            if "/" not in candidate:
                return candidate
        # Found the label but no usable value nearby — keep scanning in case
        # the same label text appears again elsewhere.
    return None


def extract_fields_from_ocr(ocr_result: dict) -> dict:
    """
    Extracts structured document fields from the OCR token list.
    Works for documents without MRZ (passport cards, ID cards, licences).

    Returns a dict compatible with what mrz_parser would return in 'fields'.
    """
    fields_list = ocr_result.get("fields", [])
    extracted = {}

    texts = [f["text"].strip() for f in fields_list]
    full = " ".join(texts).upper()

    # ── Surname ──────────────────────────────────────────────────────────────
    surname = _find_value_near_label(
        texts, ["SURNAME"],
        value_check=lambda c: c.upper() == c and c.isalpha() and len(c) > 1
    )
    if surname:
        extracted["surname"] = surname.upper()

    # ── Given names ──────────────────────────────────────────────────────────
    given = _find_value_near_label(
        texts, ["GIVEN"],
        value_check=lambda c: c.upper() == c and c.isalpha() and len(c) > 1
    )
    if given:
        extracted["given_names"] = given.upper()

    # ── Sex ──────────────────────────────────────────────────────────────────
    sex = _find_value_near_label(
        texts, ["SEX"],
        value_check=lambda c: c.upper() in ("M", "F", "X")
    )
    if sex:
        extracted["sex"] = sex.upper()

    # ── DOB ──────────────────────────────────────────────────────────────────
    dob_raw = _find_value_near_label(
        texts, ["DATE DE NAISSANCE", "DATE OF BIRTH"],
        value_check=lambda c: bool(DATE_LIKE_RE.match(c.upper()))
    )
    if dob_raw:
        extracted["dob"] = normalize_date(dob_raw)
    else:
        # Fallback: scan the whole text for any date-like token.
        for t in texts:
            if DATE_LIKE_RE.match(t.upper()):
                d = normalize_date(t)
                if d:
                    extracted["dob"] = d
                    break

    # ── Expiry ───────────────────────────────────────────────────────────────
    expiry_raw = _find_value_near_label(
        texts, ["EXPIRATION", "EXPIRY", "DATE OF EXPIRY"],
        value_check=lambda c: bool(DATE_LIKE_RE.match(c.upper()))
    )
    if expiry_raw:
        extracted["expiry"] = normalize_date(expiry_raw)

    # ── Nationality / Country code ────────────────────────────────────────────
    # NOTE: printed passports often show the spelled-out nationality
    # ("EOLIAN") rather than the ISO-3166 alpha-3 code the MRZ uses ("EOL").
    # This captures whichever is printed; if it's a full word, comparing it
    # directly against the MRZ code will still show a mismatch downstream
    # unless a nationality-word -> country-code lookup is added to the
    # comparison step itself.
    nat = _find_value_near_label(
        texts, ["NATIONALITY"],
        value_check=lambda c: c.isalpha() and 2 <= len(c) <= 20
    )
    if nat:
        nat = nat.upper()
        extracted["nationality"] = nat
        if re.match(r'^[A-Z]{2,3}$', nat):
            extracted["country_code"] = nat

    # ── Passport / Card number ────────────────────────────────────────────────
    passport_no = _find_value_near_label(
        texts, ["PASSPORT CARD NO", "CARD NO", "PASSPORT NO", "PASSPORT NR", "PASSPORT N"],
        value_check=lambda c: bool(re.match(r'^[A-Z]{0,3}\d{6,9}$', c.replace(" ", "").upper()))
    )
    if passport_no:
        extracted["passport_number"] = passport_no.replace(" ", "").upper()

    # Fallback: look for a bare token that looks like a passport number
    # anywhere in the document (1-3 letters followed by 6-9 digits).
    if "passport_number" not in extracted:
        for t in texts:
            candidate = t.replace(" ", "").upper()
            if re.match(r'^[A-Z]{1,3}\d{6,9}$', candidate):
                extracted["passport_number"] = candidate
                break

    return extracted