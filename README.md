# KAVACH
### Verifiable Evidence & Digital Authenticity

**KAVACH** is a forensic document and image authenticity verification system designed for high-assurance identity screening (border control, law-enforcement, and official document checks).  

It combines classical image forensics, OCR + MRZ analysis, face verification, security-feature detection, AI-generated content detection, and LLM-based reasoning into a single risk-scoring pipeline.

---

## Features

- **Multi-document support**  
  Passport, Visa, National ID (Aadhaar), Driver’s Licence, Border Permit, and generic ID cards.

- **Rich forensic detector suite**  
  Error Level Analysis (ELA), CFA pattern analysis, copy-move forgery, resampling, JPEG ghosts, frequency & histogram analysis, quantization, inpainting, photo-patch tampering, AI-image detection, and more.

- **Security feature detectors**  
  Hologram, guilloche patterns, microtext, rainbow / optically variable ink gradients.

- **Document intelligence**  
  Multi-language OCR (EasyOCR + PaddleOCR), MRZ parsing & check-digit validation, field extraction, OCR–MRZ consistency checks, national-ID validators, and document-type classification.

- **Biometric checks**  
  Face matching between live capture and document photo + basic liveness / presentation-attack signals.

- **LLM fusion layer**  
  Combines detector scores into human-readable officer summaries (Groq + Gemini fallback).

- **Integrity & auditability**  
  Image hashing, report signing/encryption, integrity manifests, and optional blockchain/ledger validation.

- **RAG enrichment** (optional)  
  Knowledge-base retrieval to ground analysis against known document standards.

- **Web UI**  
  Officer login, guided multi-step capture flow, risk dashboard (PASS / REVIEW / HIGH RISK), case logging, and encrypted report handling.

- **Fast demo mode**  
  Instant UI responses without heavy ML (`KAVACH_FAST_UI=1`).

---

## Architecture (High Level)

```
app.py (Flask)
  └── connector.py
        ├── bridge.py → kavach_engine.py  (detector orchestration)
        └── analyst.py / llm_fusion.py   (LLM reasoning & summary)
```

`kavach_engine.analyze_media()` runs the full detector battery, normalises scores, applies risk rules, optionally enriches with RAG, signs the report, and returns a structured verdict.

---

## Project Structure

```
├── app.py                  # Flask web application
├── connector.py            # Thin bridge between UI and engine
├── bridge.py               # Collects detector scores
├── kavach_engine.py        # Core forensic engine
├── analyst.py              # Verdict / reasoning layer
├── llm_fusion.py           # LLM summary generation
├── crypto_utils.py         # Hashing, signing, encryption
├── blockchain.py           # Ledger-related utilities
├── report_generator.py     # PDF report generation
├── rag_*.py                # RAG indexing & retrieval
├── detectors/              # All forensic & OCR detectors
│   ├── ela_detector.py
│   ├── cfa_detector.py
│   ├── copy_move_detector.py
│   ├── mrz_parser.py
│   ├── face_verification_engine.py
│   ├── vision_llm_inspector.py
│   └── ... (30+ detectors)
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS / JS assets
├── knowledge_base/         # RAG source documents
├── case_logs/              # Saved case reports
├── data/                   # Supporting data
├── .env.example            # Environment variable template
└── requirements.txt
```

---

## Usage Flow

1. Log in as an officer.
2. Follow the guided capture steps:
   - Live face
   - Passport data page
   - Visa (optional)
   - National ID
   - Driver’s licence
   - Border permit
3. System runs the full detector pipeline (or demo path).
4. Results page shows:
   - Risk label (PASS / REVIEW / HIGH RISK)
   - Forensic risk score
   - Human-readable summary
   - Detector signal checklist
5. Reports can be encrypted and later decrypted with the officer password.
6. Case logs are stored under `case_logs/`.

---

## Detector Categories

| Category              | Examples |
|-----------------------|----------|
| Classical Forensics   | ELA, CFA, Copy-Move, Resampling, JPEG Ghost, Frequency, Histogram, Quantization, Inpainting |
| Security Features     | Hologram, Guilloche, Microtext, Rainbow Gradient |
| Image Quality         | Blur, Clarity |
| Metadata & Provenance | EXIF, C2PA, Perceptual Hash |
| AI Detection          | Hugging Face AI detector, Vision LLM inspector |
| Document Intelligence | OCR, MRZ Parser, Field Extractor / Validator, Document Classifier, National ID Validator |
| Biometrics            | Face Verification, Liveness |
| Identity Risk         | Duplicate ID detector |

All detectors are loaded safely via `_safe_import`; a missing or crashing detector does not bring down the whole pipeline.

---

## Risk Scoring Logic (Simplified)

The engine aggregates detector statuses and produces a forensic risk score (0–1). High-level rules include:

- Face mismatch → **HIGH RISK**
- MRZ / OCR inconsistency on MRZ documents → **HIGH RISK**
- Critical detectors unavailable → **REVIEW**
- Combined forensic risk ≥ 0.55 → **HIGH RISK**
- Moderate risk or any flagged signals → **REVIEW**
- Otherwise → **PASS**

---

**KAVACH** — Protecting the integrity of digital evidence.
