import io
import os
import urllib.request

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas

_FONT_REGISTERED = False


def _register_fonts():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    _FONT_REGISTERED = True
    candidates = [
        ("Arial", "C:/Windows/Fonts/arial.ttf"),
        ("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"),
        ("Arial-Italic", "C:/Windows/Fonts/ariali.ttf"),
    ]
    for name, path in candidates:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont(name, path))


COLOR_SCHEMES = {
    "teal": {
        "border": "#0e7490",
        "accent": "#00d4ff",
        "gold": "#d4a853",
        "heading": "#0a1628",
        "brand": "#0e7490",
        "session": "#0e7490",
    },
    "navy": {
        "border": "#1e3a5f",
        "accent": "#4a90d9",
        "gold": "#c5a55a",
        "heading": "#0f172a",
        "brand": "#1e3a5f",
        "session": "#1e3a5f",
    },
    "emerald": {
        "border": "#065f46",
        "accent": "#34d399",
        "gold": "#d4a853",
        "heading": "#0a1628",
        "brand": "#065f46",
        "session": "#065f46",
    },
    "royal": {
        "border": "#4c1d95",
        "accent": "#a78bfa",
        "gold": "#d4a853",
        "heading": "#1e1b4b",
        "brand": "#4c1d95",
        "session": "#4c1d95",
    },
    "crimson": {
        "border": "#991b1b",
        "accent": "#f87171",
        "gold": "#d4a853",
        "heading": "#1c1917",
        "brand": "#991b1b",
        "session": "#991b1b",
    },
}


def _get_colors(scheme_name: str | None) -> dict:
    scheme = COLOR_SCHEMES.get(scheme_name or "teal", COLOR_SCHEMES["teal"])
    return {k: colors.HexColor(v) for k, v in scheme.items()}


def _draw_centered_text(c, text, y, font_name, font_size, color, page_w):
    c.setFont(font_name, font_size)
    c.setFillColor(color)
    c.drawCentredString(page_w / 2, y, text)


def _try_load_image(url: str):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TechTrek/1.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = resp.read()
        return ImageReader(io.BytesIO(data))
    except Exception:
        return None


def generate_certificate_pdf(booking, user, lecture, auditorium) -> bytes:
    _register_fonts()
    font = "Arial" if _FONT_REGISTERED else "Helvetica"
    font_bold = "Arial-Bold" if _FONT_REGISTERED else "Helvetica-Bold"
    font_italic = "Arial-Italic" if _FONT_REGISTERED else "Helvetica-Oblique"

    cert_title = getattr(lecture, "cert_title", None) or "CERTIFICATE OF ATTENDANCE"
    cert_subtitle = getattr(lecture, "cert_subtitle", None) or "This certificate is proudly presented to"
    cert_footer_text = getattr(lecture, "cert_footer", None) or "\u00a9 2026 TechTrek. All rights reserved."
    signer_name = getattr(lecture, "cert_signer_name", None) or ""
    signer_designation = getattr(lecture, "cert_signer_designation", None) or ""
    logo_url = getattr(lecture, "cert_logo_url", None) or ""
    bg_url = getattr(lecture, "cert_bg_url", None) or ""
    color_scheme = getattr(lecture, "cert_color_scheme", None)

    clr = _get_colors(color_scheme)

    page_w, page_h = landscape(A4)
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=landscape(A4))

    # Background image (full page, behind everything)
    bg_img = _try_load_image(bg_url)
    if bg_img:
        c.drawImage(bg_img, 0, 0, width=page_w, height=page_h,
                     preserveAspectRatio=True, anchor="c", mask="auto")

    # --- Decorative borders ---
    border_margin = 14 * mm
    inner_margin = border_margin + 4 * mm

    c.setStrokeColor(clr["border"])
    c.setLineWidth(2.5)
    c.roundRect(border_margin, border_margin,
                page_w - 2 * border_margin, page_h - 2 * border_margin,
                6 * mm)

    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.75)
    c.roundRect(inner_margin, inner_margin,
                page_w - 2 * inner_margin, page_h - 2 * inner_margin,
                4 * mm)

    # Gold corner accents - positioned outside the inner border
    corner_len = 18 * mm
    c.setStrokeColor(clr["gold"])
    c.setLineWidth(1.5)
    inset = border_margin + 6 * mm
    tl = (inset, page_h - inset)
    tr = (page_w - inset, page_h - inset)
    bl = (inset, inset)
    br = (page_w - inset, inset)
    # Top-left: right + down
    c.line(tl[0], tl[1], tl[0] + corner_len, tl[1])
    c.line(tl[0], tl[1], tl[0], tl[1] - corner_len)
    # Top-right: left + down
    c.line(tr[0], tr[1], tr[0] - corner_len, tr[1])
    c.line(tr[0], tr[1], tr[0], tr[1] - corner_len)
    # Bottom-left: right + up
    c.line(bl[0], bl[1], bl[0] + corner_len, bl[1])
    c.line(bl[0], bl[1], bl[0], bl[1] + corner_len)
    # Bottom-right: left + up
    c.line(br[0], br[1], br[0] - corner_len, br[1])
    c.line(br[0], br[1], br[0], br[1] + corner_len)

    # --- Content data ---
    attendee_name = user.full_name or user.username
    session_title = lecture.title
    speaker_name = lecture.speaker
    session_date = lecture.start_time.strftime("%d %B %Y")
    session_time = lecture.start_time.strftime("%I:%M %p")
    duration = f"{lecture.duration_minutes} minutes"
    venue = f"{auditorium.name}, {auditorium.location}" if auditorium else "TechTrek Venue"
    cert_id = f"CERT-{booking.booking_ref}"

    has_signer = bool(signer_name.strip())

    # --- Calculate vertical layout ---
    # Usable vertical area (inside borders with padding)
    content_top = page_h - border_margin - 20 * mm
    content_bottom = border_margin + 14 * mm

    # Element heights and gaps
    elements = []
    elements.append(("brand", 14))
    elements.append(("gap", 6))
    elements.append(("heading", 28))
    elements.append(("gap", 10))
    elements.append(("subtitle", 12))
    elements.append(("gap", 14))
    elements.append(("name", 24))
    elements.append(("gap", 10))
    elements.append(("for_text", 12))
    elements.append(("gap", 6))
    elements.append(("session_title", 15))
    elements.append(("gap", 16))
    elements.append(("detail_line_1", 12))
    elements.append(("gap", 6))
    elements.append(("detail_line_2", 12))
    elements.append(("gap", 6))
    elements.append(("detail_line_3", 12))
    if has_signer:
        elements.append(("gap", 18))
        elements.append(("signer_line", 1))
        elements.append(("gap", 6))
        elements.append(("signer_name", 12))
        elements.append(("gap", 3))
        elements.append(("signer_desg", 10))
    elements.append(("gap", 14))
    elements.append(("cert_id", 8))
    elements.append(("gap", 3))
    elements.append(("footer", 8))

    total_height = sum(h for _, h in elements)
    start_y = (content_top + content_bottom) / 2 + total_height / 2

    # --- Draw content from top to bottom ---
    y = start_y
    text_color = colors.HexColor("#475569")
    detail_color = colors.HexColor("#334155")
    footer_color = colors.HexColor("#94a3b8")

    for el_type, el_height in elements:
        if el_type == "gap":
            y -= el_height
            continue

        if el_type == "brand":
            # Logo image next to brand text, or just brand text
            logo_img = _try_load_image(logo_url)
            if logo_img:
                logo_h = 14
                logo_w = 14
                c.drawImage(logo_img, page_w / 2 - 50, y - logo_h + 2,
                            width=logo_w, height=logo_h,
                            preserveAspectRatio=True, mask="auto")
                _draw_centered_text(c, "TECHTREK", y, font_bold, 14, clr["brand"], page_w + 20)
            else:
                _draw_centered_text(c, "TECHTREK", y, font_bold, 14, clr["brand"], page_w)

        elif el_type == "heading":
            _draw_centered_text(c, cert_title.upper(), y, font_bold, 28, clr["heading"], page_w)

        elif el_type == "subtitle":
            _draw_centered_text(c, cert_subtitle, y, font, 12, text_color, page_w)

        elif el_type == "name":
            _draw_centered_text(c, attendee_name, y, font_bold, 24, clr["heading"], page_w)
            # Decorative line under name
            name_w = c.stringWidth(attendee_name, font_bold, 24)
            line_x1 = (page_w - name_w) / 2 - 10
            line_x2 = (page_w + name_w) / 2 + 10
            c.setStrokeColor(clr["accent"])
            c.setLineWidth(0.5)
            c.line(line_x1, y - 5, line_x2, y - 5)

        elif el_type == "for_text":
            _draw_centered_text(c, "for attending the session", y, font, 12, text_color, page_w)

        elif el_type == "session_title":
            display_title = f"\u201c{session_title}\u201d"
            _draw_centered_text(c, display_title, y, font_bold, 15, clr["session"], page_w)

        elif el_type == "detail_line_1":
            left_text = f"Speaker: {speaker_name}"
            right_text = f"Date: {session_date}"
            _draw_detail_pair(c, left_text, right_text, y, font, 10, detail_color, page_w)

        elif el_type == "detail_line_2":
            left_text = f"Duration: {duration}"
            right_text = f"Time: {session_time}"
            _draw_detail_pair(c, left_text, right_text, y, font, 10, detail_color, page_w)

        elif el_type == "detail_line_3":
            _draw_centered_text(c, f"Venue: {venue}", y, font, 10, detail_color, page_w)

        elif el_type == "signer_line":
            line_w = 50 * mm
            c.setStrokeColor(clr["heading"])
            c.setLineWidth(0.5)
            c.line(page_w / 2 - line_w / 2, y, page_w / 2 + line_w / 2, y)

        elif el_type == "signer_name":
            _draw_centered_text(c, signer_name, y, font_bold, 11, clr["heading"], page_w)

        elif el_type == "signer_desg":
            _draw_centered_text(c, signer_designation, y, font_italic, 9, text_color, page_w)

        elif el_type == "cert_id":
            _draw_centered_text(c, f"Certificate ID: {cert_id}", y, font, 8, footer_color, page_w)

        elif el_type == "footer":
            _draw_centered_text(c, cert_footer_text, y, font, 8, footer_color, page_w)

        y -= el_height

    c.save()
    return buf.getvalue()


def _draw_detail_pair(c, left_text, right_text, y, font_name, font_size, color, page_w):
    center = page_w / 2
    gap = 20 * mm
    c.setFont(font_name, font_size)
    c.setFillColor(color)
    c.drawRightString(center - gap / 2, y, left_text)
    c.drawString(center + gap / 2, y, right_text)
