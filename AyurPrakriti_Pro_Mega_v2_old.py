# AyurPrakriti_Pro_Mega_v2.py
# Mega v2.0 single-file Streamlit app
# Requirements: streamlit, reportlab, matplotlib, pandas, pillow, pyyaml
# Run: streamlit run AyurPrakriti_Pro_Mega_v2.py

import os
import sys
import json
import sqlite3
import logging
import traceback
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader

from PIL import Image

# -------------------- Basic config & paths --------------------
APP_DIR = Path.home() / ".ayurprakriti_app"
APP_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR = APP_DIR / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = APP_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "ayurprakriti.db"
LOG_PATH = APP_DIR / "app_debug.log"

# Attempt to copy logo from shared container path (/mnt/data/logo.png) if present.
# Useful for Streamlit Cloud where you can upload files in the GUI (they land under /mnt/data)
SRC_LOGO = Path("/mnt/data/logo.png")
LOCAL_LOGO = Path.cwd() / "logo.png"
TARGET_LOGO = APP_DIR / "logo.png"

try:
    if SRC_LOGO.exists():
        shutil.copy(str(SRC_LOGO), str(TARGET_LOGO))
    elif LOCAL_LOGO.exists():
        shutil.copy(str(LOCAL_LOGO), str(TARGET_LOGO))
except Exception:
    # Not fatal — we'll just proceed without a logo
    pass

# -------------------- Logging --------------------
logger = logging.getLogger("ayurprakriti_mega")
if not logger.handlers:
    fh = logging.FileHandler(str(LOG_PATH))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
logger.setLevel(logging.INFO)

# -------------------- Password hashing fallback --------------------
# Prefer passlib if available (strong hashing), otherwise use pbkdf2_hmac fallback.
# -------------------- Password hashing (PBKDF2) --------------------
# Use passlib PBKDF2 so code is compatible with Python 3.13 (bcrypt is broken)
try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    def hash_password(pw: str) -> str:
        """Return a pbkdf2_sha256 hash for storage."""
        return pwd_context.hash(pw)

    def verify_password(plain: str, hashed: str) -> bool:
        """Verify plain password against stored hash."""
        try:
            return pwd_context.verify(plain, hashed)
        except Exception:
            return False

except Exception:
    # Final fallback if passlib isn't available (very unlikely if requirements installed)
    import hashlib, binascii, os
    SALT = b"ayur_salt_v2"  # fixed salt for legacy fallback (not ideal for production)
    ITER = 200_000

    def hash_password(pw: str) -> str:
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), SALT, ITER)
        # store as hex with a prefix so we can recognize fallback format
        return "pbkdf2hex$" + binascii.hexlify(dk).decode("ascii")

    def verify_password(plain: str, hashed: str) -> bool:
        if hashed.startswith("pbkdf2hex$"):
            expected = hashed.split("$", 1)[1]
            dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), SALT, ITER)
            return binascii.hexlify(dk).decode("ascii") == expected
        return False

# -------------------- Database initialization --------------------
def init_db():
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
    );
    """
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        age INTEGER,
        gender TEXT,
        contact TEXT,
        created_at TEXT
    );
    """
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        assessor TEXT,
        data_json TEXT,
        created_at TEXT,
        FOREIGN KEY(patient_id) REFERENCES patients(id)
    );
    """
    )
    # create default admin if missing
    cur.execute("SELECT COUNT(1) FROM users")
    if cur.fetchone()[0] == 0:
        ph = hash_password("admin123")
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            ("admin", "Administrator", ph, "admin", datetime.now().isoformat()),
        )
    conn.commit()
    conn.close()

init_db()

# -------------------- Helpers to be placed 'near the top' --------------------

def _neutralize_personal_tone(text: str) -> str:
    """
    Convert second-person phrasing to neutral third-person clinical phrasing.
    e.g. "You should drink warm water" -> "Recommend warm water on waking."
    This is a simple rule-based normalizer; refine with more rules as needed.
    """
    if not text:
        return text
    t = str(text)
    # common phrase replacements
    rules = [
        (r"\b[Yy]ou\s+should\b", "Recommend"),
        (r"\b[Yy]ou\s+must\b", "Recommend"),
        (r"\b[Yy]ou\s+can\b", "Consider"),
        (r"\b[Yy]ou\s+may\b", "Consider"),
        (r"\b[Yy]ou\s+have\b", "The client presents with"),
        (r"\b[Yy]ou\s+are\b", "The client is"),
        (r"\b[Yy]our\b", "The client's"),
    ]
    import re

    for pat, rep in rules:
        t = re.sub(pat, rep, t)
    # clean duplicate spaces and stray punctuation
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t

# psychometric display label map (normalize keys -> display labels)
_psy_label_map = {
    "extraversion": "Extraversion",
    "neuroticism": "Neuroticism",
    "openness": "Openness",
    "conscientiousness": "Conscientiousness",
    "agreeableness": "Agreeableness",
    # custom anxiety / burnout / stress labels mapping
    "anxiety": "Anxiety",
    "burnout": "Burnout",
    "stress": "Stress",
}

def _psy_label_display(k: str) -> str:
    return _psy_label_map.get(k.lower(), k.title())

def _career_rationale_for_report(cr: dict, prakriti_pct: dict, vikriti_pct: dict, psych_pct: dict) -> str:
    """
    Return a slightly longer, personalized rationale for career suggestions.
    cr: dict with keys role, score, features (optional)
    """
    role = cr.get("role", "Role")
    score = cr.get("score", 0)
    reason = cr.get("reason", "")
    # infer dosha-based phrasing
    dominant = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else None
    vdom = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else None
    psych_note = ""
    if psych_pct:
        top_psy = max(psych_pct, key=psych_pct.get)
        psych_note = f" Psychometric note: higher {top_psy}."
    part = []
    if dominant:
        part.append(f"Matches dominant {dominant}.")
    if vdom and vdom != dominant:
        part.append(f"Current imbalance: {vdom}.")
    base = " ".join(part)
    if reason:
        base = (base + " ") if base else ""
        base += reason
    base = base + psych_note
    # ensure it is neutral/3rd-person
    return _neutralize_personal_tone(base).rstrip(" .") + f". Score: {score}"

# -------------------- Chart utilities --------------------
def _make_bar_chart(data_dict: dict, title: str, out_path: Path):
    keys = list(data_dict.keys())
    vals = [data_dict[k] for k in keys]
    fig, ax = plt.subplots(figsize=(6, 1.8))
    ax.barh(keys, vals)
    ax.set_xlim(0, 100)
    ax.set_xlabel("%")
    ax.set_title(title)
    ax.grid(axis="x", linestyle=":", linewidth=0.5)
    plt.tight_layout()
    fig.savefig(str(out_path), dpi=150)
    plt.close(fig)

def make_radar_chart(prakriti: dict, vikriti: dict, out_path: Path):
    # create radar for main three doshas if present
    labels = list(prakriti.keys())
    if not labels:
        return
    import math

    N = len(labels)
    vals1 = [prakriti.get(k, 0) for k in labels]
    vals2 = [vikriti.get(k, 0) for k in labels]
    angles = [n / float(N) * 2 * math.pi for n in range(N)]
    angles += angles[:1]
    vals1 += vals1[:1]
    vals2 += vals2[:1]
    fig = plt.figure(figsize=(4, 4))
    ax = fig.add_subplot(111, polar=True)
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)
    ax.plot(angles, vals1, linewidth=1, linestyle="solid", label="Prakriti")
    ax.fill(angles, vals1, alpha=0.25)
    ax.plot(angles, vals2, linewidth=1, linestyle="dashed", label="Vikriti")
    ax.fill(angles, vals2, alpha=0.15)
    ax.set_thetagrids([a * 180 / math.pi for a in angles[:-1]], labels)
    ax.set_rlabel_position(0)
    ax.set_ylim(0, 100)
    ax.legend(loc='upper right', bbox_to_anchor=(1.1, 1.1))
    plt.tight_layout()
    fig.savefig(str(out_path), dpi=150)
    plt.close(fig)

# -------------------- Dosha-specific priority actions --------------------
def dosha_priority_actions(vikriti_pct: dict):
    try:
        dominant_vikriti = max(vikriti_pct, key=vikriti_pct.get)
    except Exception:
        dominant_vikriti = ""
    if dominant_vikriti == "Vata":
        priority = [
            ("Start today (Vata grounding)",
             "Warm water on waking; 5–10 min gentle oil rub or slow stretch; Eat warm, cooked meals; Avoid cold/raw foods early."),
            ("This week",
             "Fix sleep time; 3 gentle walks; short calming breathing practice daily."),
            ("This month",
             "Regular meal timings; 2–3 light yoga sessions/week; declutter environment."),
        ]
    elif dominant_vikriti == "Pitta":
        priority = [
            ("Start today (Pitta cooling)",
             "Room-temp/warm water; 5–10 min cooling breath (Sheetali); prefer cooling foods; avoid heavy/spicy evening meals."),
            ("This week",
             "Reduce stimulants after 4 PM; 3 moderate walks avoiding heat; add cooling herbs like coriander."),
            ("This month",
             "Establish relaxed work rhythm; evening self-care for cooling; hydrate consistently."),
        ]
    elif dominant_vikriti == "Kapha":
        priority = [
            ("Start today (Kapha lightening)",
             "Warm water with pinch dry ginger; 5–10 min brisk stretch; choose lighter meals (soups, moong)."),
            ("This week",
             "4 brisk walks; reduce refined sugars; start morning activity habit."),
            ("This month",
             "Build regular morning routine; move every 60–90 minutes at work; add warming spices."),
        ]
    else:
        priority = [
            ("Start today",
             "Warm water; light stretching; freshly cooked meals; avoid heavy dinners."),
            ("This week",
             "3 x 20–25 min walks; fix wake-up time; reduce screen after 9 PM."),
            ("This month",
             "Regular meals & sleep; weekly clearing activity; small self-improvement habit."),
        ]
    return priority

# -------------------- PDF generation --------------------
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
    if wconf is None:
        wconf = {}
    # generate charts
    p1 = TMP_DIR / f"prakriti_{int(datetime.now().timestamp())}.png"
    p2 = TMP_DIR / f"vikriti_{int(datetime.now().timestamp())}.png"
    p3 = TMP_DIR / f"psych_{int(datetime.now().timestamp())}.png"
    radar = TMP_DIR / f"radar_{int(datetime.now().timestamp())}.png"
    try:
        _make_bar_chart(prakriti_pct, "Prakriti (constitutional %)", p1)
        _make_bar_chart(vikriti_pct, "Vikriti (today %)", p2)
        _make_bar_chart(psych_pct, "Psychometric (approx %)", p3)
        make_radar_chart(prakriti_pct, vikriti_pct, radar)
    except Exception:
        logger.exception("Chart generation failed")

    try:
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
        )
        styles = getSampleStyleSheet()
        base_font = "Helvetica"
        accent = colors.HexColor("#0F7A61")
        styles.add(ParagraphStyle(name="AP_Title", fontName=base_font, fontSize=18, leading=22, spaceAfter=6))
        styles.add(ParagraphStyle(name="AP_Small", fontName=base_font, fontSize=9, leading=11))
        styles.add(ParagraphStyle(name="AP_Heading", fontName=base_font, fontSize=12, leading=14, spaceBefore=8, spaceAfter=4, textColor=accent))
        styles.add(ParagraphStyle(name="AP_Body", fontName=base_font, fontSize=10, leading=13))
        styles.add(ParagraphStyle(name="AP_Bullet", fontName=base_font, fontSize=10, leading=12, leftIndent=12, bulletIndent=6))

        flow = []
        # Header / cover
        logo_path = TARGET_LOGO if TARGET_LOGO.exists() else None
        if logo_path:
            try:
                img = RLImage(str(logo_path), width=40 * mm, height=40 * mm)
                clinic_info = Paragraph(f"<b>Kakunje Wellness</b><br/>Authentic Ayurveda | Modern Precision<br/><font size=9>kakunje.com</font>", styles["AP_Body"])
                header_t = Table([[img, clinic_info]], colWidths=[45 * mm, 120 * mm])
                header_t.setStyle(TableStyle([("VALIGN", (0, 0), (1, 0), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
                flow.append(header_t)
            except Exception:
                flow.append(Paragraph("<b>Kakunje Wellness</b><br/>Authentic Ayurveda", styles["AP_Title"]))
        else:
            flow.append(Paragraph("<b>Kakunje Wellness</b><br/>Authentic Ayurveda", styles["AP_Title"]))
        flow.append(Spacer(1, 6))
        flow.append(Paragraph(f"<b>{patient.get('name','Patient Name')}</b>", styles["AP_Title"]))
        if wow and wow.get("hero"):
            flow.append(Paragraph(wow.get("hero"), styles["AP_Body"]))
        flow.append(Spacer(1, 8))

        # badges
        try:
            dom = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else "-"
            cur = max(vikriti_pct, key=vikriti_pct.get) if vikriti_pct else "-"
        except Exception:
            dom = cur = "-"
        badges = [
            Paragraph(f"<b>Dominant</b><br/>{dom}", styles["AP_Body"]),
            Paragraph(f"<b>Current</b><br/>{cur}", styles["AP_Body"]),
            Paragraph(f"<b>Top career</b><br/>{career_recs[0]['role'] if career_recs else '-'}", styles["AP_Body"]),
        ]
        t_badges = Table([[badges[0], badges[1], badges[2]]], colWidths=[60 * mm, 60 * mm, 60 * mm])
        t_badges.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BOX", (0,0), (-1,-1), 0.25, colors.lightgrey)]))
        flow.append(t_badges)
        flow.append(Spacer(1, 8))

        # radar image on cover
        if radar.exists():
            try:
                rimg = RLImage(str(radar), width=120 * mm, height=120 * mm)
                flow.append(rimg)
                flow.append(Spacer(1, 8))
            except Exception:
                pass

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

        flow.append(Paragraph("Prakriti — percentage distribution", styles["AP_Heading"]))
        pp = [[k, f"{v} %"] for k, v in prakriti_pct.items()]
        tpp = Table(pp, colWidths=[80 * mm, 80 * mm])
        tpp.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey), ("LEFTPADDING", (0,0), (-1,-1), 6)]))
        flow.append(tpp)
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("Vikriti — percentage distribution (today)", styles["AP_Heading"]))
        vp = [[k, f"{v} %"] for k, v in vikriti_pct.items()]
        tvp = Table(vp, colWidths=[80 * mm, 80 * mm])
        tvp.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey), ("LEFTPADDING", (0,0), (-1,-1), 6)]))
        flow.append(tvp)
        flow.append(Spacer(1, 8))

        # personalised guideline if provided
        if guideline_text:
            flow.append(Paragraph("Personalised Ayurvedic Guideline", styles["AP_Heading"]))
            flow.append(Spacer(1, 4))
            for para in guideline_text.split("\n\n"):
                if not para.strip():
                    continue
                flow.append(Paragraph(para.strip().replace("\n", "<br/>"), styles["AP_Body"]))
                flow.append(Spacer(1, 4))

        # Dosha-specific priority actions
        priority = dosha_priority_actions(vikriti_pct)
        cols_cells = []
        for title, text in priority:
            txt = text.replace("\n", "<br/>")
            cols_cells.append(Paragraph(f"<b>{title}</b><br/>{txt}", styles["AP_Body"]))
        strip_tbl = Table([cols_cells], colWidths=[60 * mm, 60 * mm, 60 * mm])
        strip_tbl.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.Color(0.96, 0.98, 0.96)), ("BOX", (0,0), (-1,-1), 0.5, colors.lightgrey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (0,0), (-1,-1), "LEFT"), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6)]))
        flow.append(strip_tbl)
        flow.append(Spacer(1, 8))

        # Recommendations short blocks
        flow.append(Paragraph("Recommendations — prioritized", styles["AP_Heading"]))
        flow.append(Paragraph("<b>Career</b>:", styles["AP_Body"]))
        seen_roles = set()
        for cr in career_recs[:12]:
            role = cr.get('role', 'Role')
            if role in seen_roles:
                continue
            seen_roles.add(role)
            rationale = _career_rationale_for_report(cr, prakriti_pct, vikriti_pct, psych_pct)
            flow.append(Paragraph(f"• <b>{role}</b> — {rationale}", styles["AP_Bullet"]))
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
            for line in wow.get("plan", "").split("\n"):
                if line.strip():
                    flow.append(Paragraph(line.strip(), styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>Daily habit stack</b>", styles["AP_Body"]))
            for line in wow.get("habit_stack", "").split("\n"):
                if line.strip():
                    flow.append(Paragraph(line.strip(), styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>Concrete tips</b>", styles["AP_Body"]))
            for line in wow.get("wow_tips", "").split("\n"):
                if line.strip():
                    flow.append(Paragraph(line.strip(), styles["AP_Body"]))
            flow.append(Spacer(1, 6))
            flow.append(Paragraph("<b>One-page checklist</b>", styles["AP_Body"]))
            for line in wow.get("checklist", "").split("\n"):
                if line.strip():
                    flow.append(Paragraph(line.strip(), styles["AP_Body"]))

        # doctor's highlighted boxed recommendation
        if doctor_note:
            flow.append(Spacer(1, 8))
            boxed = Table([[Paragraph(_neutralize_personal_tone(doctor_note), styles["AP_Body"])]], colWidths=[A4[0] - 36 * mm])
            boxed.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#FFF8B3")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCC66")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            flow.append(boxed)
            flow.append(Spacer(1, 8))

        # contact/footer
        flow.append(Spacer(1, 12))
        contact_par = "Kakunje Wellness — Prof. Dr. Prasanna Kakunje — +91-9483697676"
        flow.append(Paragraph(contact_par, styles["AP_Small"]))
        flow.append(Paragraph("Janani Complex, Nagarakatte Road, Moodbidri, Karnataka", styles["AP_Small"]))

        # footer & watermark drawer
        def _draw_page_footer_and_watermark(canvas_obj, doc_obj):
            try:
                canvas_obj.saveState()
                W, H = A4
                try:
                    canvas_obj.setFont("Helvetica-Bold", 36)
                except Exception:
                    canvas_obj.setFont("Helvetica-Bold", 36)
                opacity = float(wconf.get("watermark_opacity", 0.06)) if wconf else 0.06
                try:
                    canvas_obj.setFillAlpha(opacity)
                except Exception:
                    canvas_obj.setFillColorRGB(0.85, 0.85, 0.85)
                canvas_obj.translate(W / 2.0, H / 2.0)
                canvas_obj.rotate(30)
                canvas_obj.drawCentredString(0, 0, wconf.get("watermark_text", "Kakunje Wellness"))
                canvas_obj.restoreState()
            except Exception:
                logger.exception("Watermark draw failed")
            try:
                canvas_obj.saveState()
                footer_y = 18 * mm
                canvas_obj.setStrokeColor(colors.lightgrey)
                canvas_obj.setLineWidth(0.5)
                canvas_obj.line(18 * mm, footer_y + 8, (A4[0] - 18 * mm), footer_y + 8)
                logo_path_local = TARGET_LOGO if TARGET_LOGO.exists() else None
                x = 20 * mm
                if logo_path_local:
                    try:
                        reader = ImageReader(str(logo_path_local))
                        iw, ih = reader.getSize()
                        target_h = 10 * mm
                        scale = target_h / ih
                        canvas_obj.drawImage(str(logo_path_local), x, footer_y - 2, width=iw * scale, height=ih * scale, mask="auto")
                        x += (iw * scale) + 4
                    except Exception:
                        logger.exception("Footer logo draw error")
                canvas_obj.setFont("Helvetica", 8)
                contact_line = "Kakunje Wellness — Prof. Dr. Prasanna Kakunje — +91-9483697676 — prasanna@kakunje.com"
                canvas_obj.setFillColor(colors.HexColor("#444444"))
                canvas_obj.drawString(18 * mm if x < 18 * mm + 2 else x, footer_y, contact_line)
                fmt = "Page {page}"
                page_num = canvas_obj.getPageNumber()
                page_text = fmt.format(page=page_num)
                canvas_obj.drawRightString(A4[0] - 18 * mm, footer_y, page_text)
                canvas_obj.restoreState()
            except Exception:
                logger.exception("Footer drawing failed")

        doc.build(flow, onFirstPage=_draw_page_footer_and_watermark, onLaterPages=_draw_page_footer_and_watermark)
        buf.seek(0)
        # cleanup temp images
        for p in [p1, p2, p3, radar]:
            try:
                if p.exists():
                    p.unlink()
            except:
                pass
        return buf
    except Exception:
        tb = traceback.format_exc()
        logger.exception("Platypus build failed: %s", tb)
        # fallback simple PDF
        fallback = BytesIO()
        fallback.write(b"PDF generation failed. See logs.")
        fallback.seek(0)
        return fallback

# -------------------- Simple recommenders (placeholder logic) --------------------
def simple_career_recommender(prakriti_pct, vikriti_pct, psych_pct):
    # placeholder: return few jobs with scores and reasons
    dom = max(prakriti_pct, key=prakriti_pct.get) if prakriti_pct else "Vata"
    sample = [
        {"role": f"{dom} - Creative Consultant", "score": 70, "reason": f"Matches dominant {dom} and supports variety."},
        {"role": f"{dom} - Content Creator", "score": 65, "reason": f"Flexible thinking suits creative output."},
        {"role": f"{dom} - Research/Academia", "score": 60, "reason": "Structured thinking plus depth."},
    ]
    return sample

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="AyurPrakriti Pro Mega", layout="wide")
st.title("AyurPrakriti Pro — Mega v2.0 (Demo)")

# sidebar login
st.sidebar.header("Login")
if "user" not in st.session_state:
    st.session_state["user"] = None

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

def login_user(username, password):
    cur.execute("SELECT id, username, display_name, password_hash, role FROM users WHERE username=?", (username,))
    r = cur.fetchone()
    if not r:
        return None, "User not found"
    uid, un, dn, ph, role = r
    if verify_password(password, ph):
        return {"id": uid, "username": un, "display_name": dn, "role": role}, None
    return None, "Invalid password"

with st.sidebar.form("login_form"):
    u = st.text_input("Username", value="admin")
    p = st.text_input("Password", type="password", value="admin123")
    submitted = st.form_submit_button("Login")
    if submitted:
        user_obj, err = login_user(u.strip(), p.strip())
        if user_obj:
            st.session_state["user"] = user_obj
            st.sidebar.success(f"Welcome {user_obj['display_name']}")
        else:
            st.sidebar.error(err)

if not st.session_state.get("user"):
    st.info("Please login as admin (default admin/admin123).")
    st.stop()

# Main admin layout
tabs = st.tabs(["Patient Registry", "New Assessment", "Clinician Dashboard", "Config & Export"])
with tabs[0]:
    st.header("Patient Registry")
    # Create new patient
    with st.expander("Create new patient"):
        name = st.text_input("Name")
        age = st.number_input("Age", min_value=0, max_value=120, value=30)
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
        contact = st.text_input("Contact")
        if st.button("Create patient"):
            cur.execute("INSERT INTO patients (name, age, gender, contact, created_at) VALUES (?,?,?,?,?)", (name, int(age), gender, contact, datetime.now().isoformat()))
            conn.commit()
            st.success("Patient created")

    st.markdown("### All patients")
    df = pd.read_sql_query("SELECT * FROM patients ORDER BY created_at DESC", conn)
    st.dataframe(df)

with tabs[1]:
    st.header("New Assessment")
    # pick patient
    patients = pd.read_sql_query("SELECT id, name FROM patients ORDER BY name", conn)
    pid = st.selectbox("Select patient", options=[None] + patients["id"].tolist(), format_func=lambda x: "Select..." if x is None else patients[patients["id"]==x]["name"].values[0])
    if pid:
        pat_row = cur.execute("SELECT id, name, age, gender FROM patients WHERE id=?", (pid,)).fetchone()
        patient_obj = {"id": pat_row[0], "name": pat_row[1], "age": pat_row[2], "gender": pat_row[3]}
        st.write(f"Selected: **{patient_obj['name']}** (age {patient_obj['age']}, {patient_obj['gender']})")

        # Minimal questionnaire (expandable)
        st.subheader("Questionnaire (short demo)")
        # -- Prakriti prompts (placeholder)
        prakriti = {}
        prakriti["Vata"] = st.slider("Vata tendency (%)", 0, 100, 35)
        prakriti["Pitta"] = st.slider("Pitta tendency (%)", 0, 100, 35)
        prakriti["Kapha"] = st.slider("Kapha tendency (%)", 0, 100, 30)

        # -- Vikriti (current imbalance)
        vikriti = {}
        vikriti["Vata"] = st.slider("Vikriti - Vata (%)", 0, 100, 30)
        vikriti["Pitta"] = st.slider("Vikriti - Pitta (%)", 0, 100, 30)
        vikriti["Kapha"] = st.slider("Vikriti - Kapha (%)", 0, 100, 40)

        # -- psychometric (simple)
        psych = {}
        psych["extraversion"] = st.slider("Extraversion (%)", 0, 100, 50)
        psych["anxiety"] = st.slider("Anxiety (%)", 0, 100, 25)
        psych["burnout"] = st.slider("Burnout (%)", 0, 100, 10)

        # relationship & health free text
        rel_text = st.text_area("Relationship tips (free text - clinician)", height=80)
        health_diet = st.text_area("Health - Diet suggestions (simple bullets)", height=80)
        health_life = st.text_area("Health - Lifestyle suggestions (simple bullets)", height=80)

        include_appendix = st.checkbox("Include Appendix (90-day plan)", value=False)
        doctor_note = st.text_area("Doctor highlighted note (optional)", height=80)
        guideline_text = st.text_area("Full personalised guideline (optional)", height=140)
        custom_doctor = st.text_input("Assessor/Doctor name", value=st.session_state["user"]["display_name"])

        if st.button("Generate recommendations & PDF"):
            career_recs = simple_career_recommender(prakriti, vikriti, psych)
            rel_tips = [("Tip 1", "Be patient and listen"), ("Tip 2", "Schedule weekly check-ins")]
            health_recs = {"diet": health_diet.split("\n"), "lifestyle": health_life.split("\n")}
            wow = {
                "hero": "90-day plan for gentle restoration",
                "doctor_note": doctor_note,
                "plan": "Week 1-4: Stabilise routine\nWeek 5-8: Build activity\nWeek 9-12: Consolidate habits",
                "habit_stack": "Morning: warm water -> short oil rub -> walk\nEvening: cooling breath -> early sleep",
                "wow_tips": "Start with micro-habits. Avoid big changes.",
                "checklist": "1) Warm water\n2) Sleep time\n3) 20-min walk"
            }
            buf = branded_pdf_report(patient_obj, prakriti, vikriti, psych, career_recs, rel_tips, health_recs, include_appendix=include_appendix, wconf={"watermark_text":"Kakunje Wellness","watermark_opacity":0.04}, wow=wow, guideline_text=guideline_text, doctor_note=doctor_note)
            # save to reports dir
            fname = REPORTS_DIR / f"Report_{patient_obj['name'].replace(' ', '_')}_{int(datetime.now().timestamp())}.pdf"
            with open(fname, "wb") as f:
                f.write(buf.getvalue())
            st.success("Report generated")
            st.download_button("Download report", data=buf, file_name=fname.name, mime="application/pdf")
            # save assessment to DB
            payload = {
                "prakriti": prakriti,
                "vikriti": vikriti,
                "psych": psych,
                "career_recs": career_recs,
                "rel_tips": rel_tips,
                "health_recs": health_recs,
                "wow": wow,
                "doctor_note": doctor_note,
                "guideline_text": guideline_text,
            }
            cur.execute("INSERT INTO assessments (patient_id, assessor, data_json, created_at) VALUES (?,?,?,?)", (patient_obj["id"], custom_doctor, json.dumps(payload), datetime.now().isoformat()))
            conn.commit()
            st.info("Assessment saved to DB")

with tabs[2]:
    st.header("Clinician Dashboard")
    st.write("Recent assessments")
    df_as = pd.read_sql_query("SELECT a.id,a.patient_id,a.assessor,a.created_at,p.name FROM assessments a LEFT JOIN patients p ON a.patient_id=p.id ORDER BY a.created_at DESC", conn)
    st.dataframe(df_as)
    sel = st.selectbox("View assessment ID", options=[None] + df_as["id"].tolist())
    if sel:
        row = cur.execute("SELECT data_json FROM assessments WHERE id=?", (sel,)).fetchone()
        if row:
            data = json.loads(row[0])
            st.json(data)

with tabs[3]:
    st.header("Config & Export")
    st.write("Reports directory:", REPORTS_DIR)
    files = list(REPORTS_DIR.glob("*.pdf"))
    for f in files:
        st.write(f.name)
        st.download_button("Download", data=open(f, "rb").read(), file_name=f.name, mime="application/pdf")

# close DB
conn.close()
