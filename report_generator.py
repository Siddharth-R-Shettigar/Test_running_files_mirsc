"""
report_generator.py — KAVACH PDF Report Generator
Generates a printable PDF forensic report from a case JSON file.
Requires: pip install reportlab
"""

import json
import os
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ── Colour palette (DigiLocker purple / navy) ────────────────────────────────
COL_NAVY   = colors.HexColor("#1a237e")
COL_PURPLE = colors.HexColor("#4527a0")
COL_LIGHT  = colors.HexColor("#ede7f6")
COL_GREEN  = colors.HexColor("#065f46")
COL_GREEN_BG = colors.HexColor("#d1fae5")
COL_RED    = colors.HexColor("#7f1d1d")
COL_RED_BG = colors.HexColor("#fee2e2")
COL_YELLOW = colors.HexColor("#78350f")
COL_YELLOW_BG = colors.HexColor("#fef3c7")
COL_MUTED  = colors.HexColor("#64748b")
COL_BORDER = colors.HexColor("#c7d2fe")
COL_WHITE  = colors.white
COL_BLACK  = colors.HexColor("#1e293b")


def _verdict_colors(risk_level: str):
    rl = str(risk_level).upper()
    if rl in ("PASS", "GENUINE"):
        return COL_GREEN, COL_GREEN_BG, "AUTHENTIC & VERIFIED"
    if rl in ("HIGH RISK", "HIGH_RISK"):
        return COL_RED, COL_RED_BG, "HIGH RISK — REVIEW REQUIRED"
    return COL_YELLOW, COL_YELLOW_BG, "NEEDS SECONDARY REVIEW"


def _signal_row_color(status: str):
    st = str(status).lower()
    if st == "passed":
        return COL_GREEN_BG
    if st in ("flagged", "failed"):
        return COL_RED_BG
    return colors.HexColor("#f8fafc")


def generate_case_report_pdf(report: dict, output_path: str) -> str:
    """
    Generate a PDF at output_path from the given report dict.
    Returns the output_path on success.
    Raises ImportError if reportlab is not installed.
    Raises RuntimeError on generation failure.
    """
    if not REPORTLAB_AVAILABLE:
        raise ImportError(
            "reportlab is not installed. Run: pip install reportlab"
        )

    # ── Styles ────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    style_h1 = ps("H1", fontSize=20, textColor=COL_NAVY, leading=26,
                  fontName="Helvetica-Bold", spaceAfter=4)
    style_h2 = ps("H2", fontSize=13, textColor=COL_PURPLE, leading=18,
                  fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4)
    style_label = ps("Label", fontSize=8, textColor=COL_MUTED,
                     fontName="Helvetica-Bold", leading=12)
    style_value = ps("Value", fontSize=10, textColor=COL_BLACK,
                     fontName="Helvetica", leading=14)
    style_verdict = ps("Verdict", fontSize=15, fontName="Helvetica-Bold",
                       leading=20, alignment=TA_CENTER)
    style_footer = ps("Footer", fontSize=7, textColor=COL_MUTED,
                      fontName="Helvetica", alignment=TA_CENTER, leading=10)
    style_mono = ps("Mono", fontSize=8, fontName="Courier",
                    textColor=COL_BLACK, leading=12)
    style_warn = ps("Warn", fontSize=9, fontName="Helvetica-Bold",
                    textColor=COL_RED, leading=13)

    # ── Document setup ────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    W = A4[0] - 3.6 * cm  # usable width
    story = []

    # ── Header band ───────────────────────────────────────────────────────────
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    case_id = report.get("case_id") or os.path.splitext(
        os.path.basename(report.get("file_analyzed", "unknown"))
    )[0]

    header_data = [[
        Paragraph("<b>KAVACH</b>", ps("LogoTxt", fontSize=22,
                  textColor=COL_WHITE, fontName="Helvetica-Bold", leading=26)),
        Paragraph(
            f"<b>Forensic Document Report</b><br/>"
            f"<font size=8 color='#c7d2fe'>Generated: {generated_at}</font>",
            ps("HdrRight", fontSize=12, textColor=COL_WHITE,
               fontName="Helvetica-Bold", leading=18, alignment=TA_RIGHT),
        ),
    ]]
    header_table = Table(header_data, colWidths=[W * 0.4, W * 0.6])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COL_NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",  (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [6, 6, 6, 6]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))

    # ── Verdict banner ────────────────────────────────────────────────────────
    risk_level = report.get("risk_level", "REVIEW")
    txt_col, bg_col, verdict_text = _verdict_colors(risk_level)
    risk_pct = report.get("forensic_risk_score", 0)
    try:
        risk_pct = float(risk_pct)
        risk_pct_str = f"{round(risk_pct * 100 if risk_pct <= 1.0 else risk_pct, 1)}%"
    except (TypeError, ValueError):
        risk_pct_str = "—"

    verdict_data = [[
        Paragraph(verdict_text, ps("VBig", fontSize=14, fontName="Helvetica-Bold",
                                   textColor=txt_col, leading=18)),
        Paragraph(f"<b>Risk Score: {risk_pct_str}</b>",
                  ps("VScore", fontSize=12, fontName="Helvetica-Bold",
                     textColor=txt_col, leading=16, alignment=TA_RIGHT)),
    ]]
    verdict_table = Table(verdict_data, colWidths=[W * 0.65, W * 0.35])
    verdict_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_col),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING",  (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 1.5, txt_col),
    ]))
    story.append(verdict_table)
    story.append(Spacer(1, 0.35 * cm))

    # ── Case metadata ─────────────────────────────────────────────────────────
    story.append(Paragraph("Case Details", style_h2))
    meta_rows = [
        ["Case ID",            case_id],
        ["File Analyzed",      report.get("file_analyzed", "—")],
        ["Live Image",         report.get("live_image") or "Not provided"],
        ["Engine",             report.get("engine", "KAVACH")],
        ["Detectors Evaluated", str(report.get("active_detectors_evaluated", "—"))],
        ["Risk Reason",        (report.get("risk_reason") or "—")[:160]],
    ]
    meta_table = Table(
        [[Paragraph(k, style_label), Paragraph(v, style_value)] for k, v in meta_rows],
        colWidths=[W * 0.28, W * 0.72],
    )
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), COL_LIGHT),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, COL_BORDER),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.4 * cm))

    # ── Detector signals table ────────────────────────────────────────────────
    signals = report.get("detector_signals") or []
    if signals:
        story.append(Paragraph("Detector Signal Summary", style_h2))
        sig_header = [
            Paragraph("<b>Detector</b>", style_label),
            Paragraph("<b>Status</b>", style_label),
            Paragraph("<b>Score</b>", style_label),
            Paragraph("<b>Confidence</b>", style_label),
            Paragraph("<b>Notes</b>", style_label),
        ]
        sig_rows = [sig_header]
        for s in signals:
            if not isinstance(s, dict):
                continue
            st = str(s.get("status", "unavailable")).lower()
            row_bg = _signal_row_color(st)
            score_val = s.get("score")
            try:
                score_str = f"{float(score_val):.3f}"
            except (TypeError, ValueError):
                score_str = "—"
            sig_rows.append([
                Paragraph(str(s.get("detector_name", "—"))[:32], style_mono),
                Paragraph(st.upper(), ps("StTxt", fontSize=8,
                          fontName="Helvetica-Bold", leading=12,
                          textColor=COL_GREEN if st == "passed" else (
                              COL_RED if st in ("flagged", "failed") else COL_MUTED
                          ))),
                Paragraph(score_str, style_mono),
                Paragraph(str(s.get("confidence", "—")), style_value),
                Paragraph((s.get("explanation") or "—")[:120], style_value),
            ])

        sig_table = Table(
            sig_rows,
            colWidths=[W * 0.22, W * 0.10, W * 0.09, W * 0.12, W * 0.47],
            repeatRows=1,
        )
        sig_style = [
            ("BACKGROUND", (0, 0), (-1, 0), COL_PURPLE),
            ("TEXTCOLOR",  (0, 0), (-1, 0), COL_WHITE),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.4, COL_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COL_WHITE, colors.HexColor("#f5f3ff")]),
        ]
        # Colour status cells by verdict
        for i, s in enumerate(signals, start=1):
            if not isinstance(s, dict):
                continue
            st = str(s.get("status", "")).lower()
            bg = _signal_row_color(st)
            sig_style.append(("BACKGROUND", (0, i), (-1, i), bg))

        sig_table.setStyle(TableStyle(sig_style))
        story.append(sig_table)
        story.append(Spacer(1, 0.4 * cm))

    # ── Human summary (if present) ────────────────────────────────────────────
    human_summary = report.get("human_summary")
    if human_summary and str(human_summary).strip():
        story.append(Paragraph("AI Officer Summary (Groq / Gemini)", style_h2))
        story.append(Paragraph(str(human_summary)[:1200], style_value))
        story.append(Spacer(1, 0.3 * cm))

    # ── Integrity ─────────────────────────────────────────────────────────────
    integrity = report.get("integrity_seal") or report.get("blockchain_anchor")
    if integrity:
        story.append(Paragraph("Integrity Seal", style_h2))
        story.append(Paragraph(str(integrity)[:200], style_mono))
        story.append(Spacer(1, 0.25 * cm))

    # ── Officer checklist ─────────────────────────────────────────────────────
    story.append(HRFlowable(width=W, thickness=1, color=COL_BORDER))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Officer Verification Protocol", style_h2))
    checklist = [
        "Compare document photograph to the person physically present.",
        "Re-check MRZ check digits and printed expiry / birth dates (0 vs O).",
        "Inspect photo-patch perimeter under raking or UV light for splice marks.",
        "Confirm hologram and secondary ghost portrait if document type requires them.",
        "Escalate to secondary biometric kiosk if any doubt remains.",
    ]
    for item in checklist:
        story.append(Paragraph(f"☐  {item}", style_value))
        story.append(Spacer(1, 0.1 * cm))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width=W, thickness=0.5, color=COL_BORDER))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "KAVACH Forensic Document Screening System — CONFIDENTIAL — "
        "For authorised border and customs personnel only. "
        f"Report generated {generated_at}.",
        style_footer,
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    try:
        doc.build(story)
    except Exception as e:
        raise RuntimeError(f"PDF build failed: {e}") from e

    return output_path


# ── CLI helper ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python report_generator.py <path_to_report.json> [output.pdf]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else src.replace(".json", ".pdf")
    with open(src, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    result = generate_case_report_pdf(data, out)
    print(f"PDF saved to: {result}")

