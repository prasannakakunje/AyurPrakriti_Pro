#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AyurPrakriti_Pro_Mega_fixed.py
Corrected full file focused on report generation and PDF builder.
Includes robust logo handling, legend fallback, chart generation, and
cleaned career rationale logic.
"""

import os
import sys
import json
import yaml
import logging
import traceback
import shutil
import math
import re
from io import BytesIO
from datetime import datetime
from pathlib import Path

# reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    PageBreak,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# plotting
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# logging
logger = logging.getLogger("ayur")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

# ======== APP DIRs & files =========
# set APP_DIR: prefer to keep app data in user home folder for runtime state
APP_DIR = Path(__file__).parent.resolve()  # keep simple: use project dir
TMP_DIR = APP_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = APP_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "ayurprakriti.db"
CFG_PATH = APP_DIR / "config_rules.yaml"
LOG_PATH = APP_DIR / "app_debug.log"

# Try to copy logo from common container location or repo if present (safe, non-failing)
try:
    src_logo = Path("/mnt/data/logo.png")
    dest_logo = APP_DIR / "logo.png"
    # prefer container mount first
    if src_logo.exists():
        if not dest_logo.exists():
            shutil.copy(str(src_logo), str(dest_logo))
    else:
        # fallback to repo logo next to script
        repo_logo = Path(__file__).parent / "logo.png"
        if repo_logo.exists():
            if not dest_logo.exists():
                shutil.copy(str(repo_logo), str(dest_logo))
except Exception:
    logger.exception("Logo copy failed (non-critical)")

# local logo path
logo_path = APP_DIR / "logo.png"

# Branding default (editable)
BRAND = {
    "clinic_name": "Kakunje Wellness",
    "tagline": "Authentic Ayurveda | Modern Precision",
    "doctor": "Prof. Dr. Prasanna Kakunje, MD (Ayu), (PhD)",
    "address": "Janani Complex, Nagarakatte Road, Moodbidri, Karnataka",
    "phone": "+91-9483697676",
    "email": "prasanna@kakunje.com",
    "website": "https://kakunje.com",
    "accent_color": "#0F7A61",
}

# PDF watermark/footer defaults
WCONF = {
    "watermark_text": BRAND.get("clinic_name", ""),
    "watermark_opacity": 0.06,
    "show_footer_logo": True,
    "use_footer_signature": False,
    "page_number_format": "Page {page}",
    "footer_signature_file": str(APP_DIR / "signature.png"),
}

# Psychometric display mapping
_psy_label_map = {
    "extraversion": "Extroversion",
    "extravert": "Extroversion",
    "extroversion": "Extroversion",
    "openness": "Openness",
    "agreeableness": "Agreeableness",
    "conscientiousness": "Conscientiousness",
    "emotionality": "Emotionality",
    "neuroticism": "Emotionality",
    "anxiety": "Anxiety",
    "burnout": "Burnout",
    "stress": "Stress",
}

# ---------- Helpers ----------
def _neutralize_personal_tone(text: str) -> str:
    """
    Convert common second-person phrasing to neutral third-person clinical phrasing.
    """
    if not text:
        return text
    t = str(text)
    t = re.sub(r'\b[Yy]ou\s+have\b', 'the client presents with', t)
    t = re.sub(r'\b[Yy]ou\s+may\b', 'there may be', t)
    t = re.sub(r'\b[Yy]ou\s+are\b', 'the client is', t)
    t = re.sub(r'\b[Yy]ou\s+can\b', 'it may be useful to', t)
    t = re.sub(r'\b[Yy]ou\b', 'the client', t)
    t = re.sub(r'\bthe client is the client\b', 'the client', t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()

# Career domain templates used for scoring
CAREER_DOMAINS = [
    ("Creative / Writing / Design", ["Vata", "Openness"]),
    ("Research / Analysis / Teaching", ["Pitta", "Conscientiousness"]),
    ("Leadership / Management", ["Pitta", "Extroversion"]),
    ("Caregiving / Wellness / Counsel", ["Kapha", "Agreeableness"]),
    ("Hospitality & Wellness Operations", ["Kapha", "Conscientiousness"]),
    ("Entrepreneurship / Product", ["Vata", "Extroversion", "Openness"]),
]

def _career_rationale_for_report(cr, prakriti_pct, vikriti_pct, psych_pct):
    """
    Slightly longer, personalised rationale for one career suggestion (cr is a dict).
    We will derive a personalised rationale using predominant prakriti/vikriti and psych.
    """
    role = cr.get("role", "Role")
    score = cr.get("score", "")
    # Avoid using cr['reason'] directly because it may be generic/repeated across entries.
    # Build rationale from constitution and psych
    parts = []
    try:
        dom_pr = max(prakriti_pct, key=prakriti_pct.get)
        parts.append(f"predominant {dom_pr} constitution")
    except Exception:
        dom_pr = None
    try:
        cur_vk = max(vikriti_pct, key=vikriti_pct.get)
        parts.append(f"current tendency toward {cur_vk}")
    except Exception:
        cur_vk = None
    try:
        top_psy_key = max(psych_pct, key=psych_pct.get) if psych_pct else None
        top_psy_label = _psy_label_map.get(top_psy_key.strip().lower(), top_psy_key.title()) if top_psy_key else None
        if top_psy_label:
            parts.append(f"psychometric profile: {top_psy_label}")
    except Exception:
        pass

    combined = "; ".join([p for p in parts if p])
    tailored = ""
    if dom_pr == "Vata":
        tailored = "Supports creative, flexible roles allowing autonomy and variety."
    elif dom_pr == "Pitta":
        tailored = "Fits analytical, decision-oriented roles with structure and responsibility."
    elif dom_pr == "Kapha":
        tailored = "Suitable for steady, people-centered, supportive roles with routine."

    # incorporate cr.get('reason') only if it's non-generic
    extra = cr.get("reason", "")
    if extra and len(extra) > 40:
        extra_clean = _neutralize_personal_tone(extra)
        extra_text = f" {extra_clean}"
    else:
        extra_text = ""

    if combined:
        final = f"{role} — {combined}. {tailored}{extra_text} (score: {score})."
    else:
        final = f"{role} — {tailored}{extra_text} (score: {score})."
    return final

# ========== Chart helpers (simple, robust using matplotlib) ==========
def _make_bar_chart(data_dict, title, out_path):
    """
    Make a horizontal bar chart for the dict and save as PNG.
    data_dict: mapping label->value (numbers)
    """
    if not data_dict:
        return
    labels = list(data_dict.keys())
    values = [float(v) for v in data_dict.values()]
    y_pos = np.arange(len(labels))
    plt.figure(figsize=(6, 1.8 + 0.3 * len(labels)))
    bars = plt.barh(y_pos, values, align='center')
    plt.yticks(y_pos, labels)
    plt.xlabel('%')
    plt.title(title)
    plt.xlim(0, max(100, max(values) + 5))
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150)
    plt.close()

def make_radar_chart(prakriti_pct, vikriti_pct, out_path):
    """
    Create a simple radar-like triangle overlay for three doshas if data present.
    This is a lightweight representation that produces a PNG.
    """
    # choose the 3 doshas in consistent order
    labels = ['Vata', 'Pitta', 'Kapha']
    def to_vals(source):
        return [float(source.get(l, 0)) for l in labels]
    vals1 = to_vals(prakriti_pct or {})
    vals2 = to_vals(vikriti_pct or {})
    # normalize to 0-100
    vals1 = [min(100, max(0, v)) for v in vals1]
    vals2 = [min(100, max(0, v)) for v in vals2]

    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    vals1 = vals1 + vals1[:1]
    vals2 = vals2 + vals2[:1]
    angles = angles + angles[:1]

    fig = plt.figure(figsize=(4, 4))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(angles, vals1, linewidth=1, linestyle='-', label='Prakriti')
    ax.fill(angles, vals1, alpha=0.15)
    ax.plot(angles, vals2, linewidth=1, linestyle='--', label='Vikriti')
    ax.fill(angles, vals2, alpha=0.10)
    ax.set_thetagrids(np.degrees(angles[:-1]), labels)
    ax.set_ylim(0, 100)
    ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.1))
    plt.tight_layout()
    fig.savefig(str(out_path), dpi=150)
    plt.close()

# ---------- Legend helper for PDF ----------
def _color_box(hexcolor):
    b = Table([['']], colWidths=[8 * mm], rowHeights=[6 * mm])
    b.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), colors.HexColor(hexcolor)), ('BOX', (0, 0), (0, 0), 0.25, colors.lightgrey)]))
    return b

def _legend_table(styles):
    rows = []
    rows.append([_color_box(BRAND.get('accent_color', '#0F7A61')), Paragraph('Prakriti', styles['AP_Body'])])
    rows.append([_color_box('#3CB371'), Paragraph('Vikriti', styles['AP_Body'])])
    rows.append([_color_box('#7B61FF'), Paragraph('Psychometric', styles['AP_Body'])])
    t = Table(rows, colWidths=[10 * mm, 70 * mm])
    t.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LEFTPADDING', (0,0), (-1,-1), 2)]))
    return t

# ========== Main PDF Builder: branded_pdf_report ==========
def branded_pdf_report(
    patient,
    prakriti_pct,
    vikriti_pct,
    psych_pct,
    career_recs,
    rel_tips,
    health_recs,
    include_appendix=False,
    report_id=None,
    wconf=None,
    wow=None,
    guideline_text=None,
    doctor_note=None,
):
    """
    Build a polished PDF report (ReportLab Platypus).
    Returns BytesIO buffer containing the PDF.
    """
    if wconf is None:
        wconf = WCONF

    # prepare chart image paths (unique names)
    tstamp = int(datetime.now().timestamp() * 1000)
    p1 = TMP_DIR / f"prakriti_{tstamp}.png"
    p2 = TMP_DIR / f"vikriti_{tstamp}.png"
    p3 = TMP_DIR / f"psych_{tstamp}.png"
    radar = TMP_DIR / f"radar_{tstamp}.png"

    # Generate charts (safe)
    try:
        _make_bar_chart(prakriti_pct or {}, "Prakriti (constitutional %)", p1)
        _make_bar_chart(vikriti_pct or {}, "Vikriti (today %)", p2)
        # normalize psych labels
        psych_for_chart = {}
        for k, v in (psych_pct or {}).items():
            lab = _psy_label_map.get(k.strip().lower(), k.title())
            psych_for_chart[lab] = v
        _make_bar_chart(psych_for_chart, "Psychometric (approx %)", p3)
        make_radar_chart(prakriti_pct or {}, vikriti_pct or {}, radar)
        logger.info("Charts created: p1 %s p2 %s p3 %s radar %s", p1.exists(), p2.exists(), p3.exists(), radar.exists())
    except Exception:
        logger.exception("Chart generation failed; continuing without charts")

    try:
        buf = BytesIO()
        # Increase bottomMargin to avoid footer overlap
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=35 * mm,  # increased
        )

        styles = getSampleStyleSheet()
        base_font = "DejaVuSans" if False else "Helvetica"
        accent = colors.HexColor(BRAND.get("accent_color", "#0F7A61"))

        styles.add(ParagraphStyle(name="AP_Title", fontName=base_font, fontSize=18, leading=22, spaceAfter=6))
        styles.add(ParagraphStyle(name="AP_Small", fontName=base_font, fontSize=9, leading=11))
        styles.add(ParagraphStyle(name="AP_Heading", fontName=base_font, fontSize=12, leading=14, spaceBefore=8, spaceAfter=4, textColor=accent))
        styles.add(ParagraphStyle(name="AP_Body", fontName=base_font, fontSize=10, leading=13))
        styles.add(ParagraphStyle(name="AP_Bullet", fontName=base_font, fontSize=10, leading=12, leftIndent=10, bulletIndent=4))

        flow = []

        # Header (logo + clinic info)
        flow.append(Spacer(1, 6))
        try:
            if logo_path.exists():
                img = RLImage(str(logo_path), width=40 * mm, height=40 * mm)
                clinic_info = Paragraph(f"<b>{BRAND.get('clinic_name','')}</b><br/>{BRAND.get('tagline','')}", styles["AP_Body"])
                header_t = Table([[img, clinic_info]], colWidths=[45 * mm, 120 * mm])
                header_t.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 0)]))
                flow.append(header_t)
            else:
                flow.append(Paragraph(f"<b>{BRAND.get('clinic_name','')}</b><br/>{BRAND.get('tagline','')}", styles["AP_Title"]))
        except Exception:
            logger.exception("Header logo insertion failed")
            flow.append(Paragraph(f"<b>{BRAND.get('clinic_name','')}</b>", styles["AP_Title"]))

        flow.append(Spacer(1, 6))
        flow.append(Paragraph(f"<b>{patient.get('name','Patient Name')}</b>", styles["AP_Title"]))
        if wow and wow.get("hero"):
            flow.append(Paragraph(_neutralize_personal_tone(wow.get("hero")), styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # Badges row
        try:
            dom = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else "-"
            cur = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else "-"
        except Exception:
            dom, cur = "-", "-"
        badges = [
            Paragraph(f"<b>Dominant</b><br/>{dom}", styles["AP_Body"]),
            Paragraph(f"<b>Current</b><br/>{cur}", styles["AP_Body"]),
            Paragraph(f"<b>Top career</b><br/>{career_recs[0]['role'] if career_recs else '-'}", styles["AP_Body"]),
        ]
        t_badges = Table([[badges[0], badges[1], badges[2]]], colWidths=[60 * mm, 60 * mm, 60 * mm])
        t_badges.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ALIGN", (0,0), (-1,-1), "CENTER")]))
        flow.append(t_badges)
        flow.append(Spacer(1, 8))

        # Executive summary
        flow.append(Paragraph("Executive summary", styles["AP_Heading"]))
        exec_lines = []
        if prakriti_pct:
            try:
                exec_lines.append(f"Constitutional predominance: {max(prakriti_pct, key=prakriti_pct.get)}.")
            except Exception:
                pass
        if vikriti_pct:
            try:
                exec_lines.append(f"Primary current imbalance: {max(vikriti_pct, key=vikriti_pct.get)}.")
            except Exception:
                pass
        if psych_pct:
            try:
                top_psy = max(psych_pct, key=psych_pct.get)
                exec_lines.append(f"Psychometric snapshot indicates: {_psy_label_map.get(top_psy.strip().lower(), top_psy.title())}.")
            except Exception:
                pass
        if wow and wow.get("hero"):
            exec_lines.append(_neutralize_personal_tone(wow.get("hero")))
        for line in exec_lines:
            flow.append(Paragraph(line, styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # Charts area: use table layout and conservative heights
        try:
            chart_cells = []
            if p1.exists():
                img1 = RLImage(str(p1), width=85 * mm, height=38 * mm)
                chart_cells.append(img1)
            else:
                chart_cells.append(Paragraph('Prakriti chart unavailable', styles['AP_Body']))
            if p2.exists():
                img2 = RLImage(str(p2), width=85 * mm, height=38 * mm)
                chart_cells.append(img2)
            else:
                chart_cells.append(Paragraph('Vikriti chart unavailable', styles['AP_Body']))

            # table with two columns
            flow.append(Table([chart_cells], colWidths=[85 * mm, 85 * mm], hAlign='CENTER'))
            flow.append(Spacer(1, 6))

            if p3.exists():
                img3 = RLImage(str(p3), width=160 * mm, height=40 * mm)
                flow.append(img3)
                flow.append(Spacer(1, 6))
        except Exception:
            logger.exception("Adding chart images failed")

        # Radar / triangle diagram OR legend fallback
        if radar.exists():
            try:
                flow.append(RLImage(str(radar), width=120 * mm, height=120 * mm))
                flow.append(Paragraph("<i>Prakriti–Vikriti radar (triangle) chart</i>", styles["AP_Small"]))
                flow.append(Spacer(1, 8))
            except Exception:
                logger.exception("Adding radar failed; adding legend fallback")
                flow.append(_legend_table(styles))
                flow.append(Spacer(1, 8))
        else:
            flow.append(_legend_table(styles))
            flow.append(Spacer(1, 8))

        # Prakriti / Vikriti tables
        flow.append(Paragraph("Prakriti — percentage distribution", styles["AP_Heading"]))
        pp = [[k, f"{v} %"] for k, v in (prakriti_pct or {}).items()]
        if pp:
            tpp = Table(pp, colWidths=[80 * mm, 80 * mm])
            tpp.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey), ("LEFTPADDING", (0,0), (-1,-1), 6)]))
            flow.append(tpp)
            flow.append(Spacer(1, 6))

        flow.append(Paragraph("Vikriti — percentage distribution (today)", styles["AP_Heading"]))
        vp = [[k, f"{v} %"] for k, v in (vikriti_pct or {}).items()]
        if vp:
            tvp = Table(vp, colWidths=[80 * mm, 80 * mm])
            tvp.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey), ("LEFTPADDING", (0,0), (-1,-1), 6)]))
            flow.append(tvp)
            flow.append(Spacer(1, 8))

        # Personalised guideline insertion (sanitised)
        if guideline_text:
            flow.append(Paragraph("Personalised Ayurvedic Guideline", styles["AP_Heading"]))
            flow.append(Spacer(1, 4))
            for para in guideline_text.split("\n\n"):
                if not para.strip():
                    continue
                flow.append(Paragraph(_neutralize_personal_tone(para.strip()).replace("\n", "<br/>"), styles["AP_Body"]))
                flow.append(Spacer(1, 4))

        # Dosha-specific priority actions (simpler)
        try:
            dominant_vikriti = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else None
        except Exception:
            dominant_vikriti = None

        if dominant_vikriti == "Vata":
            priority = [
                ("Start today (Vata grounding)", "Warm water on waking; 5–10 min gentle oil rub + slow stretch; warm cooked meals."),
                ("This week", "3 days of gentle 20–25 min walk; fix sleep/wake time; reduce screen exposure after 9 PM."),
                ("This month", "Stabilise meal timings; 2–3 days/week light yoga; keep home warm and organised."),
            ]
        elif dominant_vikriti == "Pitta":
            priority = [
                ("Start today (Pitta cooling)", "Room-temperature water; 5–10 min cooling breath (Sheetali); prefer cooling foods; avoid spicy/heavy meals."),
                ("This week", "3 days moderate walk (avoid peak heat); reduce stimulants after 4 PM; start calming routines."),
                ("This month", "Cultivate relaxed work rhythm; consistent hydration; add cooling spices like coriander, fennel."),
            ]
        elif dominant_vikriti == "Kapha":
            priority = [
                ("Start today (Kapha lightening)", "Warm water with dry ginger; 5–10 min brisk stretch; choose lighter meals; avoid day naps."),
                ("This week", "4 days brisk 20–30 min walk; wake 15–20 min earlier; reduce refined sugar."),
                ("This month", "Build morning activity habit; move every 60–90 minutes; add warming spices."),
            ]
        else:
            priority = [
                ("Start today", "Warm water on waking; 5–10 min light stretch; eat freshly cooked food."),
                ("This week", "3 days 20–25 min walk; fix waking time; light digestion ritual."),
                ("This month", "Regular meals & sleep; weekly light home-cleaning; pick one small habit."),
            ]

        cols_cells = []
        for title, text in priority:
            txt = text.replace("\n", "<br/>")
            cols_cells.append(Paragraph(f"<b>{title}</b><br/>{txt}", styles["AP_Body"]))

        strip_tbl = Table([cols_cells], colWidths=[60 * mm, 60 * mm, 60 * mm])
        strip_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.Color(0.96,0.98,0.96)), ("BOX", (0,0), (-1,-1), 0.5, colors.lightgrey), ("VALIGN",(0,0),(-1,-1),"TOP"), ("ALIGN",(0,0),(-1,-1),"LEFT"), ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6)]))
        flow.append(strip_tbl)
        flow.append(Spacer(1, 8))

        # Recommendations — career (personalised, unique)
        flow.append(Paragraph("Recommendations — prioritized", styles["AP_Heading"]))
        flow.append(Paragraph("<b>Career</b>:", styles["AP_Body"]))
        if career_recs:
            # compute overall dominant keys for context
            try:
                prakriti_top = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else None
            except Exception:
                prakriti_top = None
            try:
                psych_top = max(psych_pct, key=psych_pct.get) if psych_pct else None
            except Exception:
                psych_top = None

            # Instead of returning identical cr['reason'] for each, create custom rationales
            for cr in career_recs[:8]:
                rationale = _career_rationale_for_report(cr, prakriti_pct or {}, vikriti_pct or {}, psych_pct or {})
                flow.append(Paragraph(f"• {rationale}", styles["AP_Bullet"]))
        else:
            flow.append(Paragraph("No career recommendations available.", styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # Relationship tips
        flow.append(Paragraph("<b>Relationship tips</b>:", styles["AP_Body"]))
        if rel_tips:
            for t in rel_tips:
                title = _neutralize_personal_tone(t[0]) if isinstance(t, (list, tuple)) and t else (t if isinstance(t, str) else "")
                body = _neutralize_personal_tone(t[1]) if isinstance(t, (list, tuple)) and len(t) > 1 else ""
                flow.append(Paragraph(f"• <b>{title}</b> — {body}", styles["AP_Body"]))
        else:
            flow.append(Paragraph("No relationship tips available.", styles["AP_Body"]))
        flow.append(Spacer(1,8))

        # Health suggestions
        flow.append(Paragraph("Health — diet & lifestyle suggestions", styles["AP_Heading"]))
        if health_recs:
            for d in health_recs.get("diet", []):
                flow.append(Paragraph(f"• {_neutralize_personal_tone(d)}", styles["AP_Bullet"]))
            for l in health_recs.get("lifestyle", []):
                flow.append(Paragraph(f"• {_neutralize_personal_tone(l)}", styles["AP_Bullet"]))
            herbs = health_recs.get("herbs", [])
            if herbs:
                flow.append(Paragraph("Herbs & cautions:", styles["AP_Body"]))
                for h in herbs:
                    flow.append(Paragraph(f"• {_neutralize_personal_tone(h)}", styles["AP_Bullet"]))
        else:
            flow.append(Paragraph("No health suggestions available.", styles["AP_Body"]))
        flow.append(Spacer(1,8))

        # Appendix
        if include_appendix and wow:
            flow.append(PageBreak())
            flow.append(Paragraph("APPENDIX — Transformation Plan", styles["AP_Heading"]))
            flow.append(Spacer(1,6))
            if wow.get("plan"):
                for line in wow.get("plan", "").split("\n"):
                    if line.strip():
                        flow.append(Paragraph(_neutralize_personal_tone(line.strip()), styles["AP_Body"]))
                flow.append(Spacer(1,6))
            if wow.get("habit_stack"):
                flow.append(Paragraph("Daily habit stack", styles["AP_Heading"]))
                for line in wow.get("habit_stack", "").split("\n"):
                    if line.strip():
                        flow.append(Paragraph(_neutralize_personal_tone(line.strip()), styles["AP_Body"]))
                flow.append(Spacer(1,6))
            if wow.get("checklist"):
                flow.append(Paragraph("One-page checklist", styles["AP_Heading"]))
                for line in wow.get("checklist", "").split("\n"):
                    if line.strip():
                        flow.append(Paragraph(_neutralize_personal_tone(line.strip()), styles["AP_Body"]))
                flow.append(Spacer(1,6))

        # Doctor highlighted note
        if doctor_note:
            flow.append(Spacer(1, 8))
            docnote_clean = _neutralize_personal_tone(doctor_note)
            boxed = Table([[Paragraph(docnote_clean, styles["AP_Body"])]], colWidths=[A4[0] - 36 * mm])
            boxed.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#FFF8B3")), ("BOX",(0,0),(-1,-1),0.75,colors.HexColor("#CCCC66")), ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8), ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6)]))
            flow.append(boxed)
            flow.append(Spacer(1,8))

        # contact/footer small block
        flow.append(Spacer(1,12))
        contact_par = f"{BRAND.get('clinic_name')} — {BRAND.get('doctor')} — {BRAND.get('phone')}"
        flow.append(Paragraph(contact_par, styles["AP_Small"]))
        flow.append(Paragraph(BRAND.get("address", ""), styles["AP_Small"]))

        # watermark & footer draw
        def _draw_page_footer_and_watermark(canvas_obj, doc_obj):
            try:
                canvas_obj.saveState()
                W, H = A4
                try:
                    canvas_obj.setFont("Helvetica-Bold", 36)
                except Exception:
                    canvas_obj.setFont("Helvetica-Bold", 36)
                opacity = float(wconf.get("watermark_opacity", 0.06))
                try:
                    canvas_obj.setFillAlpha(opacity)
                except Exception:
                    canvas_obj.setFillColorRGB(0.85, 0.85, 0.85)
                canvas_obj.translate(W / 2.0, H / 2.0)
                canvas_obj.rotate(30)
                canvas_obj.drawCentredString(0, 0, wconf.get("watermark_text", BRAND.get("clinic_name", "")))
                canvas_obj.restoreState()
            except Exception:
                logger.exception("Watermark draw failed")

            try:
                canvas_obj.saveState()
                footer_y = 18 * mm
                canvas_obj.setStrokeColor(colors.lightgrey)
                canvas_obj.setLineWidth(0.5)
                canvas_obj.line(18 * mm, footer_y + 8, (A4[0] - 18 * mm), footer_y + 8)
                logo_path_local = APP_DIR / "logo.png"
                x = 20 * mm
                if wconf.get("show_footer_logo", True) and logo_path_local.exists():
                    try:
                        reader = RLImage(str(logo_path_local), width=0, height=0)
                        # drawImage via canvas directly
                        canvas_obj.drawImage(str(logo_path_local), x, footer_y - 2, width=20 * mm, height=8 * mm, mask="auto")
                        x += 20 * mm + 4
                    except Exception:
                        logger.exception("Footer logo draw error")
                try:
                    canvas_obj.setFont("Helvetica", 8)
                except Exception:
                    canvas_obj.setFont("Helvetica", 8)
                contact_line = f"{BRAND.get('clinic_name','')} — {BRAND.get('phone','')}"
                # shorten if too long
                if len(contact_line) > 90:
                    contact_line = f"{BRAND.get('clinic_name','')} — {BRAND.get('phone','')}"
                canvas_obj.setFillColor(colors.HexColor("#444444"))
                canvas_obj.drawString(18 * mm if x < 18 * mm + 2 else x, footer_y, contact_line)
                fmt = wconf.get("page_number_format", "Page {page}")
                try:
                    page_num = canvas_obj.getPageNumber()
                except Exception:
                    page_num = doc_obj.page
                page_text = fmt.format(page=page_num)
                canvas_obj.drawRightString(A4[0] - 18 * mm, footer_y, page_text)
                canvas_obj.restoreState()
            except Exception:
                logger.exception("Footer drawing failed")

        # build document
        doc.build(flow, onFirstPage=_draw_page_footer_and_watermark, onLaterPages=_draw_page_footer_and_watermark)
        buf.seek(0)

        # cleanup temporary images
        for p in [p1, p2, p3, radar]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

        return buf

    except Exception:
        tb = traceback.format_exc()
        logger.exception("Platypus build failed: %s", tb)
        snippet = tb[:1200]
        # fallback minimal PDF
        try:
            from reportlab.pdfgen import canvas
            fallback_buf = BytesIO()
            c = canvas.Canvas(fallback_buf, pagesize=A4)
            left = 18 * mm
            top = A4[1] - 18 * mm
            y = top
            c.setFont("Helvetica-Bold", 13)
            c.drawString(left, y - 6, BRAND.get('clinic_name', ''))
            y -= 24
            c.setFont("Helvetica", 9)
            c.drawString(left, y, f"Patient: {patient.get('name','')}")
            c.drawString(left + 220, y, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
            y -= 16
            c.setFont("Helvetica-Bold", 10)
            c.drawString(left, y, "Prakriti:")
            y -= 12
            c.setFont("Helvetica", 9)
            for k, v in (prakriti_pct or {}).items():
                c.drawString(left + 6, y, f"{k}: {v} %")
                y -= 10
                if y < 60 * mm:
                    c.showPage()
                    y = top
            c.save()
            fallback_buf.seek(0)
            return fallback_buf
        except Exception:
            logger.exception("Fallback PDF generation also failed")
            raise

# End of file
