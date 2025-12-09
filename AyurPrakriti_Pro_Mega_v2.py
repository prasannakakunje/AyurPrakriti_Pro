# AyurPrakriti_Pro_Mega_v2.py
"""
AyurPrakriti Pro — Mega v2.0 (cleaned single-file)
Focus: corrected PDF generator (triangle diagram, dedupe work domains,
flowable chart + legend, safe footer, proper wrapping and spacing).
"""

import os
import io
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import logging

import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    KeepTogether,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ----------------- Basic config & assets -----------------
APP_DIR = Path.cwd()  # project folder by default
# On Streamlit Cloud container, common logo location can be /mnt/data/logo.png
CONTAINER_LOGO = Path("/mnt/data/logo.png")
LOCAL_LOGO = APP_DIR / "logo.png"
LOG_PATH = APP_DIR / "app_debug.log"

# Logging
logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO)
logger = logging.getLogger("ayurprakriti_mega")

# Branding defaults (editable in-app)
BRAND = {
    "clinic_name": "Kakunje Wellness",
    "tagline": "Authentic Ayurveda | Modern Precision",
    "doctor": "Prof. Dr. Prasanna Kakunje, MD (Ayu)",
    "address": "Janani Complex, Nagarakatte Road, Moodbidri, Karnataka",
    "phone": "+91-9483697676",
    "email": "prasanna@kakunje.com",
    "website": "https://kakunje.com",
    "accent_color": "#0F7A61",
}

# Psychometric label map (display labels used by legend)
_psy_label_map = {
    "extraversion": "Extraversion",
    "conscientiousness": "Conscientiousness",
    "agreeableness": "Agreeableness",
    "neuroticism": "Neuroticism",
    "openness": "Openness (Openness to experience)",
}

# Utility: neutralize second-person phrasing
import re


def _neutralize_personal_tone(text: str) -> str:
    """Convert common second-person phrasing to neutral third-person clinical phrasing."""
    if not text:
        return text
    t = str(text)
    # common replacements (order matters)
    t = re.sub(r"\b[Yy]ou\s+should\b", "It is recommended to", t)
    t = re.sub(r"\b[Yy]ou\s+must\b", "It is recommended to", t)
    t = re.sub(r"\b[Yy]ou\s+can\b", "It may be useful to", t)
    t = re.sub(r"\b[Yy]ou('|)re\b", "the client is", t)
    t = re.sub(r"\b[Yy]ou\b", "the client", t)
    t = re.sub(r"\b[Tt]ry\b", "Consider", t)
    t = re.sub(r"\bthe client is the client\b", "the client", t)
    return t.strip()


# ----------------- PDF helpers -----------------


def _get_logo_path() -> Path:
    """Return path to logo (container location if present else local file)"""
    if CONTAINER_LOGO.exists():
        return CONTAINER_LOGO
    if LOCAL_LOGO.exists():
        return LOCAL_LOGO
    return None


def _draw_triangle_diagram(c: canvas.Canvas, x_mm: float, y_mm: float, size_mm: float):
    """
    Draw a small triangle diagram with 3 labeled nodes (Vata, Pitta, Kapha).
    x_mm, y_mm center coordinates in mm.
    size_mm side length in mm.
    """
    x = x_mm * mm
    y = y_mm * mm
    size = size_mm * mm
    half = size / 2
    c.saveState()
    c.setStrokeColor(colors.HexColor("#333333"))
    c.setLineWidth(1)
    # triangle points (isosceles)
    p1 = (x, y + half)
    p2 = (x - half, y - half)
    p3 = (x + half, y - half)
    # draw triangle
    c.line(p1[0], p1[1], p2[0], p2[1])
    c.line(p2[0], p2[1], p3[0], p3[1])
    c.line(p3[0], p3[1], p1[0], p1[1])
    # nodes
    node_r = 5 * mm
    # Vata top
    c.setFillColor(colors.HexColor("#f0f0f0"))
    c.circle(p1[0], p1[1], node_r, stroke=1, fill=1)
    c.drawCentredString(p1[0], p1[1] + (node_r + 2), "Vata")
    # Pitta left
    c.circle(p2[0], p2[1], node_r, stroke=1, fill=1)
    c.drawString(p2[0] - 6 * mm, p2[1] - (node_r + 8), "Pitta")
    # Kapha right
    c.circle(p3[0], p3[1], node_r, stroke=1, fill=1)
    c.drawString(p3[0] - 6 * mm, p3[1] - (node_r + 8), "Kapha")
    c.restoreState()


def _draw_page_footer(c: canvas.Canvas, doc):
    """Draw footer on every page at bottom margin."""
    footer_y = 12 * mm
    c.saveState()
    c.setFont("Helvetica", 8)
    clinic = BRAND.get("clinic_name", "")
    phone = BRAND.get("phone", "")
    website = BRAND.get("website", "")
    text = f"{clinic} — {phone} — {website}"
    c.setFillColor(colors.HexColor("#444444"))
    c.drawString(doc.leftMargin, footer_y, text)
    # small logo if available (draw on right)
    logo = _get_logo_path()
    if logo:
        try:
            # Draw small logo scaled to width 28mm
            w = 28 * mm
            c.drawImage(str(logo), doc.leftMargin + doc.width - w, footer_y - 2 * mm, width=w, height=10 * mm, preserveAspectRatio=True)
        except Exception:
            logger.exception("Failed to draw footer logo")
    c.restoreState()


def _build_legend_paragraph(styles, psy_map: Dict[str, str]) -> Paragraph:
    """Create a Paragraph (HTML-style) containing legend lines from psy_map."""
    items = []
    for key, label in psy_map.items():
        items.append(f"<b>{label}</b>")
    # join with separators / line breaks
    legend_html = "<br/>".join(items)
    return Paragraph(legend_html, styles["small"])


def _dedupe_preserve_order(seq: List[str]) -> List[str]:
    """Remove exact duplicates while preserving order."""
    seen = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ----------------- Branded PDF reporter -----------------


def branded_pdf_report(
    patient_name: str,
    age: int,
    gender: str,
    findings: str,
    guideline_text: str,
    recommended_domains: List[str],
    chart_image_bytes: bytes = None,
    output_filename: str = "AyurPrakriti_Report.pdf",
) -> bytes:
    """
    Build a multi-page PDF report using ReportLab Platypus.
    Returns PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=22 * mm, bottomMargin=28 * mm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="small", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="normal", fontSize=10, leading=12))
    styles.add(ParagraphStyle(name="heading", fontSize=16, leading=18, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="center_big", fontSize=20, leading=22, alignment=TA_CENTER))

    flow = []

    # Header
    flow.append(Paragraph(BRAND.get("clinic_name", "AyurPrakriti Pro"), styles["center_big"]))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(BRAND.get("tagline", ""), styles["normal"]))
    flow.append(Spacer(1, 6 * mm))

    # Patient summary table
    patient_table_data = [
        ["Name", patient_name],
        ["Age", str(age)],
        ["Gender", gender],
        ["Date", datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    t = Table(patient_table_data, colWidths=[35 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6 * mm))

    # Findings and guideline (neutralize second-person)
    findings = _neutralize_personal_tone(findings)
    guideline_text = _neutralize_personal_tone(guideline_text)

    flow.append(Paragraph("<b>Clinical Findings</b>", styles["heading"]))
    flow.append(Spacer(1, 2 * mm))
    flow.append(Paragraph(findings or "—", styles["normal"]))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("<b>Guidance & Advice</b>", styles["heading"]))
    flow.append(Spacer(1, 2 * mm))
    flow.append(Paragraph(guideline_text or "—", styles["normal"]))
    flow.append(Spacer(1, 6 * mm))

    # Chart (if provided) as Flowable image (prevents overlap)
    if chart_image_bytes:
        try:
            # write image to temp bytes buffer for RLImage
            img_buf = io.BytesIO(chart_image_bytes)
            # use RLImage as a Flowable
            rl_img = RLImage(img_buf)
            # scale to fit width: allow 120mm wide
            rl_img.drawWidth = 120 * mm
            rl_img.drawHeight = rl_img.drawWidth * rl_img.imageHeight / rl_img.imageWidth
            flow.append(rl_img)
            flow.append(Spacer(1, 3 * mm))
        except Exception:
            logger.exception("Failed to attach chart image to PDF flowables")

    # Legend from psy map (single source of truth)
    legend_para = _build_legend_paragraph(styles, _psy_label_map)
    flow.append(legend_para)
    flow.append(Spacer(1, 4 * mm))

    # Recommended work domains (dedupe)
    flow.append(Paragraph("<b>Recommended work domains (ranked)</b>", styles["heading"]))
    deduped = _dedupe_preserve_order(recommended_domains or [])
    if not deduped:
        flow.append(Paragraph("—", styles["normal"]))
    else:
        for i, item in enumerate(deduped, 1):
            # each item is a normal paragraph; keep together with small spacer
            p = Paragraph(f"• {item}", styles["normal"])
            flow.append(p)
        flow.append(Spacer(1, 6 * mm))

    # Personality block (keep together)
    personality_block = []
    personality_block.append(Paragraph("<b>Personality Snapshot</b>", styles["heading"]))
    # Here we show a few items (example)
    personality_block.append(Paragraph("Extraversion: Moderate", styles["normal"]))
    personality_block.append(Paragraph("Start today: Begin morning oil massage (Abhyanga) for 5–10 minutes.", styles["normal"]))
    personality_block.append(Paragraph("This week: Focus on three light meals and restful sleep routine.", styles["normal"]))
    flow.append(KeepTogether(personality_block))
    flow.append(Spacer(1, 6 * mm))

    # Reserve space for triangle diagram by adding an empty Spacer and draw actual triangle in page hook
    flow.append(Spacer(1, 30 * mm))

    # Footer note / signature area as Flowable
    flow.append(Spacer(1, 12 * mm))
    flow.append(Paragraph("Prepared by: " + BRAND.get("doctor", ""), styles["normal"]))
    flow.append(Paragraph(BRAND.get("address", ""), styles["small"]))
    flow.append(Spacer(1, 6 * mm))

    # Build: define page callbacks
    def _on_first_page(c: canvas.Canvas, doc):
        # draw triangle diagram at top-right area
        _draw_triangle_diagram(c, x_mm=150, y_mm=240, size_mm=60)
        # draw header logo if present
        logo = _get_logo_path()
        if logo:
            try:
                c.drawImage(str(logo), doc.leftMargin, A4[1] - 24 * mm, width=28 * mm, height=12 * mm, preserveAspectRatio=True)
            except Exception:
                logger.exception("failed to draw header logo")
        _draw_page_footer(c, doc)

    def _on_later_pages(c: canvas.Canvas, doc):
        _draw_page_footer(c, doc)

    try:
        doc.build(flow, onFirstPage=_on_first_page, onLaterPages=_on_later_pages)
        pdf_bytes = buf.getvalue()
    except Exception as e:
        logger.exception("Failed to build PDF")
        raise

    return pdf_bytes


# ----------------- Simple Streamlit UI -----------------


def app():
    st.set_page_config(page_title="AyurPrakriti Pro — Mega v2.0", layout="wide")
    st.title("AyurPrakriti Pro — Mega v2.0 (Demo)")

    # Simple auth (demo)
    st.sidebar.header("Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    login_btn = st.sidebar.button("Login")

    logged_in = False
    if login_btn:
        if username == "admin" and password == "admin123":
            st.sidebar.success("Welcome administrator")
            st.session_state["logged_in"] = True
        else:
            st.sidebar.error("Invalid credentials")

    if st.session_state.get("logged_in"):
        logged_in = True

    if not logged_in:
        st.info("Please login as admin (default admin/admin123).")
        return

    # Main app: patient form and generate PDF
    with st.form("patient_form"):
        st.header("Patient details")
        patient_name = st.text_input("Patient name", "John Doe")
        age = st.number_input("Age", min_value=1, max_value=120, value=35)
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
        findings = st.text_area("Clinical findings", "Client presents with ...")
        guideline_text = st.text_area("Guideline / Advice", "Drink warm water in the morning daily.")
        st.markdown("---")
        st.subheader("Recommended work domains (enter one per line)")
        recommended_domains_text = st.text_area("Domains", "Creative writing\nCounselling\nConsulting")
        recommended_domains = [x.strip() for x in recommended_domains_text.splitlines() if x.strip()]

        submitted = st.form_submit_button("Generate PDF Report")

    if submitted:
        # For demo: create a simple chart-like image (placeholder)
        chart_img_bytes = None
        try:
            # create a small PIL image as placeholder chart
            img = Image.new("RGB", (800, 320), color=(30, 40, 50))
            # draw simple bars
            from PIL import ImageDraw, ImageFont

            draw = ImageDraw.Draw(img)
            # bars sample
            bars = [60, 40, 70, 50, 55]
            bw = 60
            gap = 20
            x0 = 60
            for i, v in enumerate(bars):
                h = int((v / 100.0) * 200)
                draw.rectangle([x0 + i * (bw + gap), 260 - h, x0 + i * (bw + gap) + bw, 260], fill=(200, 100, 60))
            # convert to bytes
            b = io.BytesIO()
            img.save(b, format="PNG")
            chart_img_bytes = b.getvalue()
        except Exception:
            logger.exception("failed to create demo chart image")

        pdf_bytes = branded_pdf_report(
            patient_name=patient_name,
            age=int(age),
            gender=gender,
            findings=findings,
            guideline_text=guideline_text,
            recommended_domains=recommended_domains,
            chart_image_bytes=chart_img_bytes,
        )

        st.success("PDF generated")
        st.download_button("Download Report (PDF)", data=pdf_bytes, file_name=f"{patient_name}_AyurReport.pdf", mime="application/pdf")


if __name__ == "__main__":
    app()
