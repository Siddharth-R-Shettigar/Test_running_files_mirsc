"""document_engine.py - ID document screening.
The vision model READS. Python CHECKS. No names or ID numbers go in any signal text."""
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from kavach_engine import analyze_media
from vision_llm import vision_json

EXTRACT_PROMPT = """You read photos of identity documents for a screening system.
Image 1 is the full document photo. Image 2 is a magnified crop of the bottom part (the MRZ, if the document has one).
Copy text EXACTLY as printed. Do NOT correct, guess, or complete anything.
If a character cannot be read, write ? for that character. If a field is absent, use null.
For the MRZ, copy each line character by character, including every < symbol, with no spaces.
Reply with ONLY this JSON:
{
 "document_type": "passport | id_card | aadhaar | pan | driving_licence | other | unknown",
 "legibility": "good | fair | poor",
 "fields": {"surname": null, "given_names": null, "document_number": null, "date_of_birth": null, "expiry_date": null},
 "mrz_lines": [],
 "id_numbers": {"aadhaar": null, "pan": null},
 "visual_observations": {
   "photo_looks_pasted_or_edited": false,
   "font_or_size_inconsistent": false,
   "text_misaligned": false,
   "halo_or_blur_around_fields": false,
   "screen_capture_or_photocopy": false
 }
}
Set an observation to true only if you can clearly see it."""

SLOTS = ["extraction", "mrz", "id_number", "consistency", "visual_tamper", "photo_forensics"]


def _sig(slot, status, text, hard=False, verified=False):
    return {
        "detector_name": slot, "slot": slot, "status": status, "explanation": text,
        "hard": hard, "verified": verified,
        "score": {"flagged": 0.9, "clean": 0.1}.get(status, 0.5),
        "confidence": "low" if status == "skipped" else "medium",
    }


# ------------------------------ MRZ ------------------------------
def mrz_check_digit(s):
    """ICAO 9303 check digit: weights 7, 3, 1."""
    total = 0
    for i, ch in enumerate(s):
        if ch.isdigit():
            v = int(ch)
        elif ch == "<":
            v = 0
        elif "A" <= ch <= "Z":
            v = ord(ch) - 55
        else:
            return None
        total += v * (7, 3, 1)[i % 3]
    return str(total % 10)


def _cd_ok(field, cd, filler_ok=False):
    if filler_ok and cd in ("<", "0") and set(field) <= {"<"}:
        return True
    return mrz_check_digit(field) == cd


def parse_mrz(kind, lines):
    if kind == "TD3":  # passport: 2 lines x 44
        l1, l2 = lines
        checks = [
            ("document number", _cd_ok(l2[0:9], l2[9])),
            ("date of birth", _cd_ok(l2[13:19], l2[19])),
            ("expiry date", _cd_ok(l2[21:27], l2[27])),
            ("personal number", _cd_ok(l2[28:42], l2[42], True)),
            ("composite", _cd_ok(l2[0:10] + l2[13:20] + l2[21:43], l2[43])),
        ]
        fields = {"doc_number": l2[0:9].strip("<"), "surname": l1[5:].split("<<")[0].replace("<", " ").strip(),
                  "dob": l2[13:19], "expiry": l2[21:27]}
    else:  # TD1: ID card, 3 lines x 30
        l1, l2, l3 = lines
        checks = [
            ("document number", _cd_ok(l1[5:14], l1[14])),
            ("date of birth", _cd_ok(l2[0:6], l2[6])),
            ("expiry date", _cd_ok(l2[8:14], l2[14])),
            ("composite", _cd_ok(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29], l2[29])),
        ]
        fields = {"doc_number": l1[5:14].strip("<"), "surname": l3.split("<<")[0].replace("<", " ").strip(),
                  "dob": l2[0:6], "expiry": l2[8:14]}
    return checks, fields


def _mrz_candidates(raw):
    out = []
    for l in raw or []:
        if isinstance(l, str):
            t = re.sub(r"\s+", "", l.upper())
            if t.count("<") >= 2 or len(t) >= 28:
                out.append(t)
    return out


def _check_mrz(raw):
    """Return (signal, mrz_fields or None)."""
    lines = _mrz_candidates(raw)
    if not lines:
        return _sig("mrz", "skipped", "No MRZ was read. The document may have no MRZ."), None
    joined = "".join(lines)
    if "?" in joined or not re.fullmatch(r"[A-Z0-9<]+", joined):
        return _sig("mrz", "skipped", "The MRZ is not fully readable. Take a sharper photo."), None
    kind = None
    if len(lines) == 2 and all(len(l) == 44 for l in lines):
        kind = "TD3"
    elif len(lines) == 3 and all(len(l) == 30 for l in lines):
        kind = "TD1"
    if not kind:
        return _sig("mrz", "skipped", f"The MRZ shape is not standard ({len(lines)} lines). The photo may be cut off or misread."), None
    checks, fields = parse_mrz(kind, lines)
    bad = [label for label, ok in checks if not ok]
    if bad:
        return _sig("mrz", "flagged", f"MRZ check digit is wrong for: {', '.join(bad)}. A misread character is also possible.", hard=True), fields
    return _sig("mrz", "clean", f"MRZ {kind} found. All check digits are correct.", verified=True), fields


# --------------------- National ID (India) ---------------------
_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
      [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
      [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
      [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_valid(num):
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _check_id(ids):
    ids = ids if isinstance(ids, dict) else {}
    aad = re.sub(r"\D", "", str(ids.get("aadhaar") or ""))
    pan = re.sub(r"\s", "", str(ids.get("pan") or "").upper())
    if aad:
        if not re.fullmatch(r"[2-9]\d{11}", aad):
            return _sig("id_number", "flagged", "The Aadhaar number has a wrong length or start digit. A misread is possible.")
        ok = verhoeff_valid(aad)
        return _sig("id_number", "clean" if ok else "flagged",
                    "Aadhaar checksum is valid." if ok else "Aadhaar checksum is wrong. A misread digit is possible.",
                    hard=not ok, verified=ok)
    if pan:
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", pan):
            return _sig("id_number", "clean", "PAN format is valid. PAN has no public checksum, so this is not verified.")
        return _sig("id_number", "flagged", "The PAN format is wrong. A misread is possible.")
    return _sig("id_number", "skipped", "No Aadhaar or PAN number was read.")


# ------------------- Dates and cross-checks -------------------
_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y"]


def to_yymmdd(s):
    if not isinstance(s, str):
        return None
    s = re.sub(r"\s+", " ", s.strip().upper().replace(",", " "))
    for f in _FORMATS:
        try:
            return datetime.strptime(s, f).strftime("%y%m%d")
        except ValueError:
            pass
    return None


def _norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _to_date(yymmdd, kind):
    if not re.fullmatch(r"\d{6}", yymmdd or ""):
        return "bad"
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    year = 2000 + yy if (kind == "expiry" or yy <= date.today().year % 100) else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return "bad"


def _check_consistency(fields, mrz_fields):
    fields = fields if isinstance(fields, dict) else {}
    mism, compared = [], 0
    if mrz_fields:
        ps, ms = _norm(fields.get("surname")), _norm(mrz_fields.get("surname"))
        if ps and ms:
            compared += 1
            if ps not in ms and ms not in ps:
                mism.append("surname")
        pn, mn = _norm(fields.get("document_number")), _norm(mrz_fields.get("doc_number"))
        if pn and mn:
            compared += 1
            if pn != mn:
                mism.append("document number")
        for key, mkey, label in (("date_of_birth", "dob", "date of birth"), ("expiry_date", "expiry", "expiry date")):
            pd = to_yymmdd(fields.get(key))
            if pd and mrz_fields.get(mkey):
                compared += 1
                if pd != mrz_fields[mkey]:
                    mism.append(label)

    dob = (mrz_fields or {}).get("dob") or to_yymmdd(fields.get("date_of_birth"))
    exp = (mrz_fields or {}).get("expiry") or to_yymmdd(fields.get("expiry_date"))
    problems, dates_seen = [], 0
    today = date.today()
    if dob:
        dates_seen += 1
        d = _to_date(dob, "dob")
        if d == "bad":
            problems.append("the date of birth is impossible")
        elif d > today:
            problems.append("the date of birth is in the future")
    if exp:
        dates_seen += 1
        d = _to_date(exp, "expiry")
        if d == "bad":
            problems.append("the expiry date is impossible")
        elif d < today:
            problems.append("the document is expired")

    if mism or problems:
        text = []
        if mism:
            text.append(f"Printed text does not match the MRZ for: {', '.join(mism)}.")
        if problems:
            text.append("Date problem: " + "; ".join(problems) + ".")
        return _sig("consistency", "flagged", " ".join(text), hard=len(mism) >= 2)
    if compared >= 2:
        return _sig("consistency", "clean", "Printed fields match the MRZ. Dates are valid.", verified=True)
    if dates_seen:
        return _sig("consistency", "clean", "Dates are valid. Too few fields to compare with an MRZ.")
    return _sig("consistency", "skipped", "No fields could be compared.")


def _check_visual(obs):
    if not isinstance(obs, dict):
        return _sig("visual_tamper", "skipped", "No visual observations were returned.")
    labels = {
        "photo_looks_pasted_or_edited": "photo looks pasted or edited",
        "font_or_size_inconsistent": "inconsistent font or size",
        "text_misaligned": "misaligned text",
        "halo_or_blur_around_fields": "halo or blur around fields",
        "screen_capture_or_photocopy": "screen capture or photocopy",
    }
    seen = [lab for k, lab in labels.items() if obs.get(k) is True]
    if seen:
        return _sig("visual_tamper", "flagged", f"The vision model saw: {', '.join(seen)}. This check is weak. Verify by eye.")
    return _sig("visual_tamper", "clean", "The vision model saw no obvious edit marks. This check is weak.")


def _photo_signal(path):
    """Never raises."""
    try:
        media = analyze_media(path, mode="fast")
    except Exception as e:
        return _sig("photo_forensics", "skipped", f"Forensics crashed: {type(e).__name__}.")
    if "error" in media:
        return _sig("photo_forensics", "skipped", str(media["error"])[:150])
    p = str(media.get("probabilities", {}).get("synthetic_ai_generated", ""))
    if not (p.endswith("%") and p[:-1].isdigit()):
        return _sig("photo_forensics", "skipped", "Not enough detector data.")
    synth = int(p[:-1])
    if synth >= 75:
        return _sig("photo_forensics", "flagged", f"Image forensics score is high ({synth}% synthetic).", hard=True)
    if synth >= 50:
        return _sig("photo_forensics", "flagged", f"Image forensics score is medium ({synth}% synthetic).")
    return _sig("photo_forensics", "clean", f"Image forensics score is low ({synth}% synthetic). This does not prove the document is real.")


# ----------------------------- Main -----------------------------
def analyze_document(path):
    if not os.path.exists(path):
        return {"error": f"File {path} not found."}

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_vis = ex.submit(vision_json, path, EXTRACT_PROMPT)
        f_pho = ex.submit(_photo_signal, path)
        photo = f_pho.result()
        try:
            data, provider = f_vis.result()
            if not isinstance(data, dict):
                raise ValueError("the reply is not a JSON object")
            err = None
        except Exception as e:
            data, provider, err = None, None, f"{type(e).__name__}: {str(e)[:250]}"

    if data is None:
        sigs = [_sig("extraction", "skipped", f"The vision model failed. {err}")]
        sigs += [_sig(s, "skipped", "Needs the extraction step.") for s in ("mrz", "id_number", "consistency", "visual_tamper")]
    else:
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        legib = str(data.get("legibility", "")).lower()
        if legib in ("good", "fair"):
            sigs = [_sig("extraction", "clean", f"The document was read (legibility: {legib}).")]
        else:
            sigs = [_sig("extraction", "skipped", "The photo is hard to read. Take a clearer photo.")]
        mrz_sig, mrz_fields = _check_mrz(data.get("mrz_lines"))
        sigs += [mrz_sig, _check_id(data.get("id_numbers")),
                 _check_consistency(fields, mrz_fields), _check_visual(data.get("visual_observations"))]
    sigs.append(photo)

    return {
        "engine": "KAVACH document screening",
        "file_analyzed": os.path.basename(path),
        "document_type": (data or {}).get("document_type", "unknown"),
        "reader": provider,
        "detector_signals": sigs,
    }


# --------------------------- Self-test ---------------------------
def _selftest():
    l1 = "P<UTOERIKSSON<<ANNA<MARIA".ljust(44, "<")
    l2 = "L898902C<3UTO6908061F9406236ZE184226B<<<<<14"
    assert len(l1) == 44 and len(l2) == 44
    checks, _ = parse_mrz("TD3", [l1, l2])
    assert all(ok for _, ok in checks), checks
    bad, _ = parse_mrz("TD3", [l1, l2[:13] + "7" + l2[14:]])
    assert not all(ok for _, ok in bad), "A changed digit must fail."
    sig, fields = _check_mrz([l1, l2])
    assert sig["status"] == "clean" and fields["dob"] == "690806", sig
    assert _check_mrz([l1, l2.replace("L", "?", 1)])[0]["status"] == "skipped"
    assert verhoeff_valid("2363") and not verhoeff_valid("2364")
    assert to_yymmdd("06/08/1969") == "690806" and to_yymmdd("06 AUG 1969") == "690806"
    print("Self-test passed.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        import json
        print(json.dumps(analyze_document(sys.argv[1]), indent=2))