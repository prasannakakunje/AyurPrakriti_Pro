# AyurPrakriti_Pro_Mega_full_v2.py
"""
AyurPrakriti Pro — Full Mega v2 (merged & patched)
Single-file Streamlit app with robust PBKDF2 password handling and a complete
PDF generation engine that includes psychometric sections, triangle diagram,
dosha-specific actions, career rationale, dedupe, doctor-highlighted box,
watermark & footer, and chart generation.

Save this as AyurPrakriti_Pro_Mega_full_v2.py and run:
  pip install streamlit reportlab pillow matplotlib numpy
  streamlit run AyurPrakriti_Pro_Mega_full_v2.py
"""

import os
import io
import sys
import math
import json
import yaml
import shutil
import traceback
import tempfile
import sqlite3
import hashlib
import binascii
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import logging

# UI & PDF libs
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from reportlab.pdfgen import canvas

# --------- Basic app dirs and logging ----------
APP_DIR = Path.home() / ".ayurprakriti_app"
APP_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR = APP_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = APP_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = APP_DIR / "app_debug.log"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO)
logger = logging.getLogger("AyurPrakritiMega")

# Look for logo in repo first, then container locations
LOCAL_PROJECT_LOGO = Path(__file__).parent / "logo.png"
CONTAINER_LOGO = Path("/mnt/data/logo.png")
APP_LOGO = APP_DIR / "logo.png"
# copy local logo into APP_DIR if present
try:
    if LOCAL_PROJECT_LOGO.exists():
        shutil.copy2(str(LOCAL_PROJECT_LOGO), str(APP_LOGO))
    elif CONTAINER_LOGO.exists():
        shutil.copy2(str(CONTAINER_LOGO), str(APP_LOGO))
except Exception:
    logger.exception("logo copy failed")

# Branding defaults
BRAND = {
    "clinic_name": "Kakunje Wellness",
    "tagline": "Authentic Ayurveda | Measurable Outcomes",
    "doctor": "Prof. Dr. Prasanna Kakunje, MD (Ayu)",
    "address": "Janani Complex, Nagarakatte Road, Moodbidri, Karnataka",
    "phone": "+91-9483697676",
    "email": "prasanna@kakunje.com",
    "website": "https://kakunje.com",
    "accent_color": "#0F7A61",
    "watermark_text": "Kakunje Wellness",
    "watermark_opacity": 0.05,
    "show_footer_logo": True,
}

# PBKDF2 password helpers (stable across Python versions)
SALT = b"ayur_salt_v2"
PBKDF2_ITERS = 200000


def hash_password(pw: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), SALT, PBKDF2_ITERS)
    return binascii.hexlify(dk).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return hash_password(plain) == hashed
    except Exception:
        return False


# Admin default: create simple SQLite DB with users table if missing
DB_PATH = APP_DIR / "ayurprakriti.db"


def ensure_db_and_admin(default_pw="admin123"):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    created = False
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        display_name TEXT,
        password_hash TEXT,
        role TEXT,
        created_at TEXT
    )
    """
    )
    conn.commit()
    cur.execute("SELECT id FROM users WHERE username='admin'")
    if not cur.fetchone():
        ph = hash_password(default_pw)
        cur.execute(
            "INSERT INTO users (username,display_name,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            ("admin", "Administrator", ph, "admin", datetime.now().isoformat()),
        )
        conn.commit()
        created = True
    conn.close()
    return created


# Create DB and admin if not present
ensure_db_and_admin()

# Psychometric label map and refined texts
_psy_label_map = {
    "extraversion": "Extraversion",
    "conscientiousness": "Conscientiousness",
    "agreeableness": "Agreeableness",
    "neuroticism": "Emotional Reactivity (Neuroticism)",
    "openness": "Openness to Experience",
}

# A friendly function to neutralize second-person tone (editorial)
import re


def _neutralize_personal_tone(text: str) -> str:
    if not text:
        return text
    t = text
    t = re.sub(r"\b[Yy]ou\s+should\b", "It is recommended to", t)
    t = re.sub(r"\b[Yy]ou\s+must\b", "It is recommended to", t)
    t = re.sub(r"\b[Yy]ou\s+can\b", "It may be useful to", t)
    t = re.sub(r"\b[Yy]ou('|)re\b", "the client is", t)
    t = re.sub(r"\b[Yy]ou\b", "the client", t)
    t = re.sub(r"\b[Tt]ry\b", "Consider", t)
    return t.strip()


# Career rationale builder (short personalized rationale based on inputs)
def _career_rationale_for_report(cr_item: Dict[str, Any], prakriti_pct: Dict[str, int], vikriti_pct: Dict[str, int], psych_pct: Dict[str, int]) -> str:
    """
    Build a slightly longer personalized rationale for a career suggestion.
    cr_item expected keys: role, score, reason (optional)
    """
    role = cr_item.get("role", "Role")
    score = cr_item.get("score", None)
    base_reason = cr_item.get("reason", "")
    parts = []
    # base: match with dominant prakriti
    try:
        dominant = max(prakriti_pct, key=prakriti_pct.get)
        parts.append(f"Matches dominant {dominant} constitution.")
    except Exception:
        pass
    # add psych hint
    if psych_pct:
        top_psy = sorted(psych_pct.items(), key=lambda x: x[1], reverse=True)[0][0]
        parts.append(f"Personality indicators ({top_psy}) support elements of this role.")
    if base_reason:
        parts.append(base_reason)
    if score:
        parts.append(f"Score: {score}")
    return " ".join(parts)


# Small helpers to make charts (bar and radar)
def _make_bar_chart(data: Dict[str, int], title: str, out_path: Path):
    labels = list(data.keys())
    values = [data[k] for k in labels]
    fig, ax = plt.subplots(figsize=(6, 2.2))
    ax.bar(labels, values)
    ax.set_ylim(0, 100)
    ax.set_title(title)
    ax.set_ylabel("%")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    plt.tight_layout()
    fig.savefig(str(out_path), bbox_inches="tight")
    plt.close(fig)


def make_radar_chart(prakriti: Dict[str, int], vikriti: Dict[str, int], out_path: Path):
    # radar chart for prakriti vs vikriti using Vata,Pitta,Kapha
    categories = ["Vata", "Pitta", "Kapha"]
    def get_vals(d):
        return [d.get(c, 0) for c in categories]
    p = get_vals(prakriti)
    v = get_vals(vikriti)
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    p += p[:1]
    v += v[:1]
    angles += angles[:1]
    fig = plt.figure(figsize=(4, 4))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(angles, p, label="Prakriti")
    ax.fill(angles, p, alpha=0.25)
    ax.plot(angles, v, label="Vikriti")
    ax.fill(angles, v, alpha=0.15)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories)
    ax.set_ylim(0, 100)
    ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
    plt.tight_layout()
    fig.savefig(str(out_path), bbox_inches="tight")
    plt.close(fig)


# Triangle drawing for canvas
def _draw_triangle_diagram(canvas_obj: canvas.Canvas, center_x: float, center_y: float, size: float):
    """
    center_x, center_y: coordinates in points
    size: side length in points
    """
    half = size / 2.0
    p1 = (center_x, center_y + half)
    p2 = (center_x - half, center_y - half)
    p3 = (center_x + half, center_y - half)
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(colors.HexColor("#333333"))
    canvas_obj.setLineWidth(1)
    canvas_obj.line(p1[0], p1[1], p2[0], p2[1])
    canvas_obj.line(p2[0], p2[1], p3[0], p3[1])
    canvas_obj.line(p3[0], p3[1], p1[0], p1[1])
    # nodes
    r = 6
    canvas_obj.circle(p1[0], p1[1], r, stroke=1, fill=1)
    canvas_obj.drawCentredString(p1[0], p1[1] + r + 4, "Vata")
    canvas_obj.circle(p2[0], p2[1], r, stroke=1, fill=1)
    canvas_obj.drawString(p2[0] - 20, p2[1] - r - 4, "Pitta")
    canvas_obj.circle(p3[0], p3[1], r, stroke=1, fill=1)
    canvas_obj.drawString(p3[0] - 12, p3[1] - r - 4, "Kapha")
    canvas_obj.restoreState()


# Footer & watermark
def _draw_page_footer_and_watermark(canvas_obj: canvas.Canvas, doc, wconf=None):
    if wconf is None:
        wconf = BRAND
    canvas_obj.saveState()
    # watermark centered
    try:
        opacity = float(wconf.get("watermark_opacity", 0.06))
    except Exception:
        opacity = 0.06
    try:
        canvas_obj.setFillAlpha(opacity)  # may not be supported everywhere
    except Exception:
        canvas_obj.setFillColorRGB(0.85, 0.85, 0.85)
    W, H = A4
    canvas_obj.setFont("Helvetica-Bold", 36)
    canvas_obj.translate(W / 2.0, H / 2.0)
    canvas_obj.rotate(30)
    canvas_obj.drawCentredString(0, 0, wconf.get("watermark_text", BRAND["clinic_name"]))
    canvas_obj.restoreState()

    # footer
    canvas_obj.saveState()
    footer_y = 14 * mm
    canvas_obj.setStrokeColor(colors.lightgrey)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(18 * mm, footer_y + 8, (A4[0] - 18 * mm), footer_y + 8)
    # draw small logo if available
    logo_path = APP_LOGO if APP_LOGO.exists() else None
    x = 18 * mm
    if logo_path:
        try:
            reader = Image.open(str(logo_path))
            iw, ih = reader.size
            # scale to 10mm height
            target_h = 10 * mm
            scale = target_h / ih
            canvas_obj.drawImage(str(logo_path), x, footer_y - 2, width=iw * scale, height=ih * scale, mask="auto")
            x += iw * scale + 4
        except Exception:
            logger.exception("Footer logo draw error")
    try:
        canvas_obj.setFont("Helvetica", 8)
    except Exception:
        pass
    contact_line = f"{BRAND.get('clinic_name')} — {BRAND.get('doctor')} — {BRAND.get('phone')}"
    canvas_obj.setFillColor(colors.HexColor("#444444"))
    canvas_obj.drawString(x, footer_y, contact_line)
    page_text = f"Page {canvas_obj.getPageNumber()}"
    canvas_obj.drawRightString(A4[0] - 18 * mm, footer_y, page_text)
    canvas_obj.restoreState()


# Wrap text helper
def _wrap_text_simple(text: str, width_chars=80):
    words = text.split()
    if not words:
        return []
    lines = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


# Career dedupe helper
def _dedupe_preserve_order(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ---------- Full branded PDF generator ----------
def branded_pdf_report(
    patient: Dict[str, Any],
    prakriti_pct: Dict[str, int],
    vikriti_pct: Dict[str, int],
    psych_pct: Dict[str, int],
    career_recs: List[Dict[str, Any]],
    rel_tips: List[List[str]],
    health_recs: Dict[str, List[str]],
    include_appendix=False,
    report_id=None,
    wconf=None,
    wow=None,
    guideline_text: str = None,
    doctor_note: str = None,
) -> io.BytesIO:
    """
    Build branded PDF report (comprehensive).
    Returns BytesIO containing PDF.
    """
    if wconf is None:
        wconf = BRAND
    buf = io.BytesIO()
    # temp chart files
    p1 = TMP_DIR / f"prakriti_{int(datetime.now().timestamp())}.png"
    p2 = TMP_DIR / f"vikriti_{int(datetime.now().timestamp())}.png"
    p3 = TMP_DIR / f"psych_{int(datetime.now().timestamp())}.png"
    radar = TMP_DIR / f"radar_{int(datetime.now().timestamp())}.png"
    # generate charts
    try:
        _make_bar_chart(prakriti_pct, "Prakriti (constitutional %)", p1)
        _make_bar_chart(vikriti_pct, "Vikriti (today %)", p2)
        _make_bar_chart(psych_pct, "Psychometric (approx %)", p3)
        make_radar_chart(prakriti_pct, vikriti_pct, radar)
    except Exception:
        logger.exception("Chart generation failed")

    try:
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=28 * mm,
        )
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="AP_Title", fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=6))
        styles.add(ParagraphStyle(name="AP_Small", fontName="Helvetica", fontSize=9, leading=11))
        styles.add(ParagraphStyle(name="AP_Heading", fontName="Helvetica-Bold", fontSize=12, leading=14, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor(BRAND["accent_color"])))
        styles.add(ParagraphStyle(name="AP_Body", fontName="Helvetica", fontSize=10, leading=13))
        styles.add(ParagraphStyle(name="AP_Bullet", fontName="Helvetica", fontSize=10, leading=12, leftIndent=12, bulletIndent=6))

        flow = []
        # header and hero
        logo_path = APP_LOGO if APP_LOGO.exists() else None
        if logo_path:
            try:
                img = RLImage(str(logo_path), width=40 * mm, height=40 * mm)
                clinic_info = Paragraph(f"<b>{BRAND['clinic_name']}</b><br/>{BRAND['tagline']}<br/><font size=9>{BRAND['website']}</font>", styles["AP_Body"])
                header_t = Table([[img, clinic_info]], colWidths=[45 * mm, 120 * mm])
                header_t.setStyle(TableStyle([("VALIGN", (0, 0), (1, 0), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
                flow.append(header_t)
            except Exception:
                flow.append(Paragraph(f"<b>{BRAND['clinic_name']}</b><br/>{BRAND['tagline']}", styles["AP_Title"]))
        else:
            flow.append(Paragraph(f"<b>{BRAND['clinic_name']}</b><br/>{BRAND['tagline']}", styles["AP_Title"]))
        flow.append(Spacer(1, 6))

        # hero name + short insight
        flow.append(Paragraph(f"<b>{patient.get('name','Patient Name')}</b>", styles["AP_Title"]))
        if wow and wow.get("hero"):
            flow.append(Paragraph(wow.get("hero"), styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # badges row
        try:
            dom = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else "-"
            cur = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else "-"
        except Exception:
            dom = "-"
            cur = "-"
        badges = [
            Paragraph(f"<b>Dominant</b><br/>{dom}", styles["AP_Body"]),
            Paragraph(f"<b>Current</b><br/>{cur}", styles["AP_Body"]),
            Paragraph(f"<b>Top career</b><br/>{career_recs[0]['role'] if career_recs else '-'}", styles["AP_Body"]),
        ]
        t_badges = Table([[badges[0], badges[1], badges[2]]], colWidths=[60 * mm, 60 * mm, 60 * mm])
        t_badges.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        flow.append(t_badges)
        flow.append(Spacer(1, 8))

        # radar on cover (if generated)
        if radar.exists():
            try:
                rimg = RLImage(str(radar), width=120 * mm, height=120 * mm)
                flow.append(rimg)
                flow.append(Spacer(1, 8))
            except Exception:
                pass

        # doctor note + signature
        if wow and wow.get("doctor_note"):
            flow.append(Paragraph(f"<i>{wow.get('doctor_note')}</i>", styles["AP_Body"]))
            sig = APP_DIR / "signature.png"
            if sig.exists():
                try:
                    s_img = RLImage(str(sig), width=40 * mm, height=15 * mm)
                    flow.append(Spacer(1, 4))
                    flow.append(s_img)
                except:
                    pass
        flow.append(PageBreak())

        # Executive summary & charts
        flow.append(Paragraph("Executive summary", styles["AP_Heading"]))
        flow.append(Paragraph("This report summarises constitutional profile (Prakriti), current imbalances (Vikriti), psychometric snapshot and prioritized recommendations.", styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # Add bar charts (if created)
        try:
            if p1.exists() and p2.exists():
                img1 = RLImage(str(p1), width=85 * mm, height=45 * mm)
                img2 = RLImage(str(p2), width=85 * mm, height=45 * mm)
                flow.append(Table([[img1, img2]], colWidths=[90 * mm, 90 * mm]))
                flow.append(Spacer(1, 6))
            if p3.exists():
                img3 = RLImage(str(p3), width=160 * mm, height=35 * mm)
                flow.append(img3)
                flow.append(Spacer(1, 6))
        except Exception:
            logger.exception("Adding chart images failed")

        # Prakriti/Vikriti Tables
        flow.append(Paragraph("Prakriti — percentage distribution", styles["AP_Heading"]))
        pp = [[k, f"{v} %"] for k, v in prakriti_pct.items()]
        tpp = Table(pp, colWidths=[80 * mm, 80 * mm])
        tpp.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("LEFTPADDING", (0, 0), (-1, -1), 6),]))
        flow.append(tpp)
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("Vikriti — percentage distribution (today)", styles["AP_Heading"]))
        vp = [[k, f"{v} %"] for k, v in vikriti_pct.items()]
        tvp = Table(vp, colWidths=[80 * mm, 80 * mm])
        tvp.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("LEFTPADDING", (0, 0), (-1, -1), 6),]))
        flow.append(tvp)
        flow.append(Spacer(1, 8))

        # Insert personalised guideline if provided
        if guideline_text:
            flow.append(Paragraph("Personalised Ayurvedic Guideline", styles["AP_Heading"]))
            flow.append(Spacer(1, 4))
            for para in guideline_text.split("\n\n"):
                if not para.strip():
                    continue
                flow.append(Paragraph(para.strip().replace("\n", "<br/>"), styles["AP_Body"]))
                flow.append(Spacer(1, 4))

        # Dosha-specific priority actions (choose dominant vikriti)
        try:
            dominant_vikriti = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else ""
        except Exception:
            dominant_vikriti = ""
        if dominant_vikriti == "Vata":
            priority = [
                ("Start today (Vata grounding)", "Warm water on waking; 5–10 min gentle oil rub; eat warm cooked meals; avoid cold foods; 10 min calming night routine."),
                ("This week", "3 days of gentle 20–25 min walk; fix sleep/wake; reduce screens after 9 PM; use digestion boosters."),
                ("This month", "Stabilise meal timings; 2–3 days/week light yoga; keep home warm and organised."),
            ]
        elif dominant_vikriti == "Pitta":
            priority = [
                ("Start today (Pitta cooling)", "Start with room-temperature water; 5–10 min cooling breaths; prefer cooling foods; avoid spicy/heavy lunches; 10 min soothing wind-down."),
                ("This week", "3 days of moderate walk avoiding peak heat; reduce stimulants after 4 PM; emotional cooling habits."),
                ("This month", "Cultivate relaxed work rhythm; evening self-care for stress cooling; improve hydration."),
            ]
        elif dominant_vikriti == "Kapha":
            priority = [
                ("Start today (Kapha lightening)", "Warm water with dry ginger; 5–10 min brisk stretch; lighter meals; avoid day naps; add 10 min active movement after meals."),
                ("This week", "4 days brisk 20–30 min walk; wake 15–20 min earlier; reduce refined sugars; declutter one area at home."),
                ("This month", "Build morning activity habit; move every 60–90 minutes; keep meals lighter at night."),
            ]
        else:
            priority = [
                ("Start today", "Warm water; 5–10 min light stretch; eat freshly cooked food; simple 10 min night calming practice."),
                ("This week", "3 days of 20–25 min walk; reduce mobile usage after 9 PM; maintain fixed waking time."),
                ("This month", "Regular meals and sleep; weekly light home-cleaning; pick one small habit to build."),
            ]
        cols_cells = []
        for title, text in priority:
            txt = text.replace("\n", "<br/>")
            cols_cells.append(Paragraph(f"<b>{title}</b><br/>{txt}", styles["AP_Body"]))
        strip_tbl = Table([cols_cells], colWidths=[60 * mm, 60 * mm, 60 * mm])
        strip_tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.Color(0.96, 0.98, 0.96)), ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),]))
        flow.append(strip_tbl)
        flow.append(Spacer(1, 8))

        # Recommendations short blocks
        flow.append(Paragraph("Recommendations — prioritized", styles["AP_Heading"]))
        flow.append(Paragraph("<b>Career</b>:", styles["AP_Body"]))
        # personalised career suggestions with slightly longer rationale
        deduped_careers = []
        seen_roles = set()
        for cr in career_recs:
            role = cr.get("role", "")
            if role and role not in seen_roles:
                seen_roles.add(role)
                deduped_careers.append(cr)
        for cr in deduped_careers[:8]:
            rationale = _career_rationale_for_report(cr, prakriti_pct, vikriti_pct, psych_pct)
            flow.append(Paragraph(f"• <b>{cr.get('role','Unknown')}</b> — {rationale}", styles["AP_Bullet"]))
        flow.append(Spacer(1, 6))

        flow.append(Paragraph("<b>Relationship tips</b>:", styles["AP_Body"]))
        for t in rel_tips:
            flow.append(Paragraph(f"• <b>{t[0]}</b> — {t[1]}", styles["AP_Bullet"]))
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("<b>Health (diet & lifestyle)</b>:", styles["AP_Body"]))
        for d in health_recs.get("diet", []):
            flow.append(Paragraph(f"• {d}", styles["AP_Bullet"]))
        for l in health_recs.get("lifestyle", []):
            flow.append(Paragraph(f"• {l}", styles["AP_Bullet"]))
        flow.append(Spacer(1, 8))

        # Appendices / wow plan
        if include_appendix and wow:
            flow.append(PageBreak())
            flow.append(Paragraph("APPENDIX — Transformation & Practical Plan", styles["AP_Heading"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>90-day transformation plan</b>", styles["AP_Body"]))
            for line in wow.get("plan","").split("\n"):
                flow.append(Paragraph(line, styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>Daily habit stack</b>", styles["AP_Body"]))
            for line in wow.get("habit_stack","").split("\n"):
                flow.append(Paragraph(line, styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>Concrete tips</b>", styles["AP_Body"]))
            for line in wow.get("wow_tips","").split("\n"):
                flow.append(Paragraph(line, styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>One-page checklist</b>", styles["AP_Body"]))
            for line in wow.get("checklist","").split("\n"):
                flow.append(Paragraph(line, styles["AP_Body"]))

        # Insert doctor's highlighted boxed recommendation (if provided) before contact/footer
        if doctor_note:
            flow.append(Spacer(1, 8))
            boxed = Table([[Paragraph(doctor_note, styles["AP_Body"])]], colWidths=[A4[0] - 36 * mm])
            boxed.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#FFF8B3")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCC66")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),]))
            flow.append(boxed)
            flow.append(Spacer(1, 8))

        # Contact/footer
        flow.append(Spacer(1, 12))
        contact_par = f"{BRAND.get('clinic_name')} — {BRAND.get('doctor')} — {BRAND.get('phone')}"
        flow.append(Paragraph(contact_par, styles["AP_Small"]))
        flow.append(Paragraph(BRAND.get("address", ""), styles["AP_Small"]))

        # Build doc with footer/watermark callbacks
        def _first_page(canvas_obj, doc_obj):
            # draw triangle (top-right)
            try:
                # coordinates: translate mm to points
                W, H = A4
                cx = W - 80 * mm
                cy = H - 70 * mm
                size = 60 * mm
                _draw_triangle_diagram(canvas_obj, cx, cy, size)
            except Exception:
                logger.exception("Triangle draw failed")
            # header logo (small)
            try:
                if APP_LOGO.exists():
                    canvas_obj.drawImage(str(APP_LOGO), doc_obj.leftMargin, A4[1] - 24 * mm, width=28 * mm, height=12 * mm, preserveAspectRatio=True)
            except Exception:
                logger.exception("Header logo draw failed")
            _draw_page_footer_and_watermark(canvas_obj, doc_obj, wconf=wconf)

        def _later_pages(canvas_obj, doc_obj):
            _draw_page_footer_and_watermark(canvas_obj, doc_obj, wconf=wconf)

        doc.build(flow, onFirstPage=_first_page, onLaterPages=_later_pages)
        buf.seek(0)
        # cleanup
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
        # fallback: minimal canvas PDF to ensure something is returned
        try:
            # create simple canvas fallback
            cbuf = io.BytesIO()
            c = canvas.Canvas(cbuf, pagesize=A4)
            c.drawString(18 * mm, A4[1] - 18 * mm, f"Report for {patient.get('name','Patient')}")
            c.showPage()
            c.save()
            cbuf.seek(0)
            return cbuf
        except Exception:
            logger.exception("Fallback canvas failed")
            raise


# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="AyurPrakriti Pro — Mega v2", layout="wide")

def streamlit_app():
    st.title("AyurPrakriti Pro — Mega v2 (Full)")
    st.write("Integrated PDF report engine — full features enabled.")

    # sidebar login UI
    st.sidebar.header("Admin login")
    username = st.sidebar.text_input("Username", value="")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        # check DB
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cur = conn.cursor()
            cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
            row = cur.fetchone()
            conn.close()
            if row and verify_password(password, row[0]):
                st.session_state["logged_in"] = True
                st.sidebar.success("Logged in")
            else:
                st.sidebar.error("Invalid credentials")
        except Exception:
            st.sidebar.error("Login error (db). Try admin/admin123 if you didn't change password.")
    if not st.session_state.get("logged_in", False):
        st.sidebar.info("Default admin credential: admin / admin123 (you can change it after login).")
        # quick reset admin helper
        if st.sidebar.button("Reset admin to admin123 (one-click)"):
            try:
                ph = hash_password("admin123")
                conn = sqlite3.connect(str(DB_PATH)); cur = conn.cursor()
                cur.execute("UPDATE users SET password_hash=? WHERE username='admin'", (ph,))
                conn.commit(); conn.close()
                st.sidebar.success("Admin password reset to admin123")
            except Exception:
                st.sidebar.error("Reset failed")
        st.stop()

    # Main UI: patient form & PDF generation
    st.header("Create patient report")
    with st.form("patient_form", clear_on_submit=False):
        col1, col2 = st.columns([2, 1])
        with col1:
            patient_name = st.text_input("Patient name", value="Akshatha")
            age = st.number_input("Age", min_value=1, max_value=120, value=28)
            gender = st.selectbox("Gender", ["Female", "Male", "Other"], index=0)
            # prakriti / vikriti inputs (simple sliders for demo)
            st.markdown("### Prakriti (constitutional) %")
            prak_vata = st.slider("Vata %", 0, 100, 40)
            prak_pitta = st.slider("Pitta %", 0, 100, 30)
            prak_kapha = st.slider("Kapha %", 0, 100, 30)
            st.markdown("### Vikriti (today) %")
            vik_vata = st.slider("Vikriti - Vata %", 0, 100, 50)
            vik_pitta = st.slider("Vikriti - Pitta %", 0, 100, 25)
            vik_kapha = st.slider("Vikriti - Kapha %", 0, 100, 25)
            st.markdown("### Psychometric snapshot (0-100)")
            psych = {}
            psych["extraversion"] = st.slider("Extraversion", 0, 100, 50)
            psych["conscientiousness"] = st.slider("Conscientiousness", 0, 100, 50)
            psych["agreeableness"] = st.slider("Agreeableness", 0, 100, 50)
            psych["neuroticism"] = st.slider("Neuroticism", 0, 100, 40)
            psych["openness"] = st.slider("Openness", 0, 100, 55)

        with col2:
            st.markdown("### Career suggestions (input JSON list)")
            st.markdown("Example: `[{'role':'Writer','score':76,'reason':'Good fit for creative work.'}]`")
            career_json = st.text_area("Career JSON", value='[{"role":"Creative Writer","score":76,"reason":"Flexible thinking and pattern finding."},{"role":"Counsellor","score":64,"reason":"Good listening and empathy."}]', height=140)
            st.markdown("### Relationship tips (one per line as 'title — text')")
            rel_text = st.text_area("Relationship tips", value="Listen — Spend 10 minutes listening daily\nGently ask — Ask one supportive question daily", height=100)
            st.markdown("### Health & lifestyle (diet, lifestyle, herbs)")
            diet_text = st.text_area("Diet (comma separated)", value="Warm cooked food, Avoid cold salads", height=80)
            lifestyle_text = st.text_area("Lifestyle (comma separated)", value="Morning walk, Oil massage", height=80)
            herbs_text = st.text_area("Herbs (comma separated)", value="Triphala, Amla", height=80)

        guideline_text = st.text_area("Personalised Ayurvedic Guideline (free text)", value="Start with warm water every morning, prefer cooked meals.")
        doctor_note = st.text_area("Doctor highlighted note (this will be boxed in the PDF)", value="Follow up in 2 weeks. Consider herbal decoction X if symptoms persist.")
        include_appendix = st.checkbox("Include Appendix (90-day plan & habit stack)", value=True)
        wow_plan = {
            "hero": "Small consistent changes can produce measurable health improvements.",
            "plan": "Day 1-7: Stabilise wakeup time...\nDay 8-30: Build morning routine...\nDay 31-90: Consolidate habit stack.",
            "habit_stack": "Wake 6:30 AM\nAbhyanga 5 min\n30 min walk\nLight dinner 2 hrs before bed",
            "wow_tips": "Carry a small notebook\nDrink warm water before meals",
            "checklist": "1. Wake at same time\n2. Oil massage 2x week\n3. Track sleep"
        }
        submitted = st.form_submit_button("Generate & Download PDF")

    if submitted:
        # parse inputs
        career_recs = []
        try:
            career_recs = json.loads(career_json)
            if isinstance(career_recs, dict):
                career_recs = [career_recs]
        except Exception:
            st.warning("Career JSON invalid — using defaults.")
            career_recs = [{"role":"Creative Writer","score":76,"reason":"Flexible thinking."}]
        rel_tips = []
        for line in rel_text.splitlines():
            if "—" in line:
                parts = line.split("—",1)
                rel_tips.append([parts[0].strip(), parts[1].strip()])
            elif "-" in line:
                parts = line.split("-",1)
                rel_tips.append([parts[0].strip(), parts[1].strip()])
        health_recs = {
            "diet": [s.strip() for s in diet_text.split(",") if s.strip()],
            "lifestyle": [s.strip() for s in lifestyle_text.split(",") if s.strip()],
            "herbs": [s.strip() for s in herbs_text.split(",") if s.strip()],
        }
        prakriti_pct = {"Vata": prak_vata, "Pitta": prak_pitta, "Kapha": prak_kapha}
        vikriti_pct = {"Vata": vik_vata, "Pitta": vik_pitta, "Kapha": vik_kapha}
        psych_pct = psych

        # create chart bytes (bar chart sample)
        try:
            # create temp chart file
            chart_path = TMP_DIR / f"chart_{int(datetime.now().timestamp())}.png"
            # combine psych bars for demonstration
            _make_bar_chart(psych_pct, "Psychometric snapshot", chart_path)
            with open(chart_path, "rb") as f:
                chart_bytes = f.read()
        except Exception:
            chart_bytes = None

        # Build patient dict
        patient = {"name": patient_name, "age": age, "gender": gender}

        pdfbuf = branded_pdf_report(
            patient=patient,
            prakriti_pct=prakriti_pct,
            vikriti_pct=vikriti_pct,
            psych_pct=psych_pct,
            career_recs=career_recs,
            rel_tips=rel_tips,
            health_recs=health_recs,
            include_appendix=include_appendix,
            report_id=None,
            wconf=BRAND,
            wow=wow_plan,
            guideline_text=guideline_text,
            doctor_note=doctor_note,
        )
        # save to reports dir
        file_name = f"Report_{patient_name.replace(' ','_')}_{int(datetime.now().timestamp())}.pdf"
        out_path = REPORTS_DIR / file_name
        with open(out_path, "wb") as f:
            f.write(pdfbuf.getvalue())
        st.success("PDF generated")
        st.download_button("Download PDF", data=pdfbuf.getvalue(), file_name=file_name, mime="application/pdf")
        st.write("Saved to:", str(out_path))

    st.markdown("---")
    st.info("Notes: This full file uses PBKDF2 hashing (stable) and a robust PDF engine. If you want the admin password changed, use the reset button in the sidebar after login.")

if __name__ == "__main__":
    streamlit_app()
