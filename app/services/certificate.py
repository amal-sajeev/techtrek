import io
import json
import os
import urllib.request

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas

_REGISTERED_FONTS: set[str] = set()

FONT_FAMILIES = {
    "arial": {
        "regular": ("Arial", "C:/Windows/Fonts/arial.ttf"),
        "bold": ("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"),
        "italic": ("Arial-Italic", "C:/Windows/Fonts/ariali.ttf"),
        "bold_italic": ("Arial-BoldItalic", "C:/Windows/Fonts/arialbi.ttf"),
    },
    "georgia": {
        "regular": ("Georgia", "C:/Windows/Fonts/georgia.ttf"),
        "bold": ("Georgia-Bold", "C:/Windows/Fonts/georgiab.ttf"),
        "italic": ("Georgia-Italic", "C:/Windows/Fonts/georgiai.ttf"),
        "bold_italic": ("Georgia-BoldItalic", "C:/Windows/Fonts/georgiaz.ttf"),
    },
    "times": {
        "regular": ("TimesNewRoman", "C:/Windows/Fonts/times.ttf"),
        "bold": ("TimesNewRoman-Bold", "C:/Windows/Fonts/timesbd.ttf"),
        "italic": ("TimesNewRoman-Italic", "C:/Windows/Fonts/timesi.ttf"),
        "bold_italic": ("TimesNewRoman-BoldItalic", "C:/Windows/Fonts/timesbi.ttf"),
    },
    "verdana": {
        "regular": ("Verdana", "C:/Windows/Fonts/verdana.ttf"),
        "bold": ("Verdana-Bold", "C:/Windows/Fonts/verdanab.ttf"),
        "italic": ("Verdana-Italic", "C:/Windows/Fonts/verdanai.ttf"),
        "bold_italic": ("Verdana-BoldItalic", "C:/Windows/Fonts/verdanaz.ttf"),
    },
    "trebuchet": {
        "regular": ("Trebuchet", "C:/Windows/Fonts/trebuc.ttf"),
        "bold": ("Trebuchet-Bold", "C:/Windows/Fonts/trebucbd.ttf"),
        "italic": ("Trebuchet-Italic", "C:/Windows/Fonts/trebucit.ttf"),
        "bold_italic": ("Trebuchet-BoldItalic", "C:/Windows/Fonts/trebucbi.ttf"),
    },
    "courier": {
        "regular": ("CourierNew", "C:/Windows/Fonts/cour.ttf"),
        "bold": ("CourierNew-Bold", "C:/Windows/Fonts/courbd.ttf"),
        "italic": ("CourierNew-Italic", "C:/Windows/Fonts/couri.ttf"),
        "bold_italic": ("CourierNew-BoldItalic", "C:/Windows/Fonts/courbi.ttf"),
    },
    "comic": {
        "regular": ("ComicSans", "C:/Windows/Fonts/comic.ttf"),
        "bold": ("ComicSans-Bold", "C:/Windows/Fonts/comicbd.ttf"),
        "italic": ("ComicSans-Italic", "C:/Windows/Fonts/comici.ttf"),
        "bold_italic": ("ComicSans-BoldItalic", "C:/Windows/Fonts/comicz.ttf"),
    },
    "calibri": {
        "regular": ("Calibri", "C:/Windows/Fonts/calibri.ttf"),
        "bold": ("Calibri-Bold", "C:/Windows/Fonts/calibrib.ttf"),
        "italic": ("Calibri-Italic", "C:/Windows/Fonts/calibrii.ttf"),
        "bold_italic": ("Calibri-BoldItalic", "C:/Windows/Fonts/calibriz.ttf"),
    },
    "palatino": {
        "regular": ("Palatino", "C:/Windows/Fonts/pala.ttf"),
        "bold": ("Palatino-Bold", "C:/Windows/Fonts/palab.ttf"),
        "italic": ("Palatino-Italic", "C:/Windows/Fonts/palai.ttf"),
        "bold_italic": ("Palatino-BoldItalic", "C:/Windows/Fonts/palabi.ttf"),
    },
    "candara": {
        "regular": ("Candara", "C:/Windows/Fonts/Candara.ttf"),
        "bold": ("Candara-Bold", "C:/Windows/Fonts/Candarab.ttf"),
        "italic": ("Candara-Italic", "C:/Windows/Fonts/Candarai.ttf"),
        "bold_italic": ("Candara-BoldItalic", "C:/Windows/Fonts/Candaraz.ttf"),
    },
}

_BUILTIN_FALLBACKS = {
    "regular": "Helvetica",
    "bold": "Helvetica-Bold",
    "italic": "Helvetica-Oblique",
    "bold_italic": "Helvetica-BoldOblique",
}


def _register_fonts():
    for family_key, variants in FONT_FAMILIES.items():
        for variant_key, (name, path) in variants.items():
            if name in _REGISTERED_FONTS:
                continue
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    _REGISTERED_FONTS.add(name)
                except Exception:
                    pass


def _font(name: str, fallback: str) -> str:
    return name if name in _REGISTERED_FONTS else fallback


def _resolve_font(family: str, bold: bool = False, italic: bool = False) -> str:
    """Return the registered font name for the given family + style, falling back to Helvetica."""
    family = (family or "arial").lower()
    variants = FONT_FAMILIES.get(family, FONT_FAMILIES["arial"])
    if bold and italic:
        variant_key = "bold_italic"
    elif bold:
        variant_key = "bold"
    elif italic:
        variant_key = "italic"
    else:
        variant_key = "regular"
    name = variants[variant_key][0]
    if name in _REGISTERED_FONTS:
        return name
    return _BUILTIN_FALLBACKS[variant_key]


COLOR_SCHEMES = {
    "teal": {
        "border": "#0e7490",
        "accent": "#00d4ff",
        "gold":   "#d4a853",
        "heading": "#0a1628",
        "brand":  "#0e7490",
        "session": "#0e7490",
    },
    "navy": {
        "border": "#1e3a5f",
        "accent": "#4a90d9",
        "gold":   "#c5a55a",
        "heading": "#0f172a",
        "brand":  "#1e3a5f",
        "session": "#1e3a5f",
    },
    "emerald": {
        "border": "#065f46",
        "accent": "#34d399",
        "gold":   "#d4a853",
        "heading": "#0a1628",
        "brand":  "#065f46",
        "session": "#065f46",
    },
    "royal": {
        "border": "#4c1d95",
        "accent": "#a78bfa",
        "gold":   "#d4a853",
        "heading": "#1e1b4b",
        "brand":  "#4c1d95",
        "session": "#4c1d95",
    },
    "crimson": {
        "border": "#991b1b",
        "accent": "#f87171",
        "gold":   "#d4a853",
        "heading": "#1c1917",
        "brand":  "#991b1b",
        "session": "#991b1b",
    },
}


def _get_colors(scheme_name: str | None) -> dict:
    scheme = COLOR_SCHEMES.get(scheme_name or "teal", COLOR_SCHEMES["teal"])
    return {k: colors.HexColor(v) for k, v in scheme.items()}


# ── Border style drawing functions ────────────────────────────────────────────

def _diamond_path(c, cx, cy, r):
    """Return a filled diamond (rhombus) path centred at (cx, cy) with radius r."""
    p = c.beginPath()
    p.moveTo(cx,     cy + r)
    p.lineTo(cx + r, cy)
    p.lineTo(cx,     cy - r)
    p.lineTo(cx - r, cy)
    p.close()
    return p


def _border_classic(c, page_w, page_h, clr, bw=1.0):
    """Classic academic-diploma style: three square-cornered parallel rules
    with bold gold corner medallions (square plate + brand diamond + accent dot).
    All ornament dimensions scale proportionally with bw."""
    b  = max(0.25, bw)
    m1 = 10 * mm   # outer rule margin
    m2 = 15 * mm   # middle rule
    m3 = 20 * mm   # inner rule

    # Outer rect — thickest, brand color, SQUARE corners
    c.setStrokeColor(clr["border"])
    c.setLineWidth(2.5 * b)
    c.rect(m1, m1, page_w - 2 * m1, page_h - 2 * m1)

    # Middle rect — gold
    c.setStrokeColor(clr["gold"])
    c.setLineWidth(0.8 * b)
    c.rect(m2, m2, page_w - 2 * m2, page_h - 2 * m2)

    # Inner rect — accent, thinnest
    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.5 * b)
    c.rect(m3, m3, page_w - 2 * m3, page_h - 2 * m3)

    # Corner medallions — size scales with bw
    cap = (5.5 + 3.5 * b) * mm   # half-size of the square plate
    ds  = cap * 0.62              # diamond radius within plate
    for cx, cy in [
        (m1, page_h - m1), (page_w - m1, page_h - m1),
        (m1, m1),           (page_w - m1, m1),
    ]:
        # Gold square plate
        c.setFillColor(clr["gold"])
        c.setStrokeColor(clr["border"])
        c.setLineWidth(0.5 * b)
        c.rect(cx - cap, cy - cap, 2 * cap, 2 * cap, fill=1, stroke=1)
        # Brand-color inset diamond
        c.setFillColor(clr["border"])
        c.drawPath(_diamond_path(c, cx, cy, ds), fill=1, stroke=0)
        # Tiny gold center dot
        c.setFillColor(clr["gold"])
        c.circle(cx, cy, cap * 0.22, fill=1, stroke=0)


def _border_modern(c, page_w, page_h, clr, bw=1.0):
    """Bold solid-slab frame with inner bevel highlight."""
    margin = 10 * mm
    c.setStrokeColor(clr["border"])
    c.setLineWidth(16 * bw)
    c.roundRect(margin, margin,
                page_w - 2 * margin, page_h - 2 * margin, 12 * mm)
    inner = margin + 8
    c.setStrokeColor(clr["accent"])
    c.setLineWidth(1.25 * bw)
    c.roundRect(inner, inner,
                page_w - 2 * inner, page_h - 2 * inner, 10 * mm)


def _border_elegant(c, page_w, page_h, clr, bw=1.0):
    """Elegant luxury filigree: two hairline rounded borders with wide gap,
    delicate corner crosshair ornaments (cross + gold tip dots + center diamond),
    and elongated mid-side diamonds with flanking accent dots.
    All ornament dimensions scale proportionally with bw."""
    b  = max(0.25, bw)
    m1 = 10 * mm   # outer rule
    m2 = 21 * mm   # inner rule — wide gap is the visual signature

    # Outer hairline — brand color, gently rounded
    c.setStrokeColor(clr["border"])
    c.setLineWidth(0.9 * b)
    c.roundRect(m1, m1, page_w - 2 * m1, page_h - 2 * m1, 4 * mm)

    # Inner hairline — accent color
    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.5 * b)
    c.roundRect(m2, m2, page_w - 2 * m2, page_h - 2 * m2, 2 * mm)

    # Corner crosshair ornaments — all sizes scale with bw
    arm = (4.5 + 2.5 * b) * mm   # arm half-length
    cr  = arm * 0.16              # tip dot radius
    dr  = arm * 0.28              # center diamond radius
    for cx, cy in [
        (m1, page_h - m1), (page_w - m1, page_h - m1),
        (m1, m1),           (page_w - m1, m1),
    ]:
        # Cross lines in accent color
        c.setStrokeColor(clr["accent"])
        c.setLineWidth(0.6 * b)
        c.line(cx - arm, cy, cx + arm, cy)
        c.line(cx, cy - arm, cx, cy + arm)
        # Gold tip dots at each arm end
        c.setFillColor(clr["gold"])
        for dx, dy in [(arm, 0), (-arm, 0), (0, arm), (0, -arm)]:
            c.circle(cx + dx, cy + dy, cr, fill=1, stroke=0)
        # Small gold diamond at center
        c.drawPath(_diamond_path(c, cx, cy, dr), fill=1, stroke=0)

    # Mid-side elongated diamonds + flanking dots — sizes scale with bw
    r_long  = (5.5 + 3.0 * b) * mm  # long radius (oriented along the edge)
    r_short = r_long * 0.35          # short radius (perpendicular to edge)
    dot_r   = r_long * 0.13          # flanking dot radius
    dot_d   = r_long * 1.45          # flanking dot distance from center
    for cx, cy, horiz in [
        (page_w / 2, page_h - m1, True),
        (page_w / 2, m1,          True),
        (m1,         page_h / 2,  False),
        (page_w - m1, page_h / 2, False),
    ]:
        # Elongated diamond (long axis oriented along the edge)
        c.setFillColor(clr["gold"])
        p = c.beginPath()
        if horiz:
            p.moveTo(cx, cy + r_short); p.lineTo(cx + r_long, cy)
            p.lineTo(cx, cy - r_short); p.lineTo(cx - r_long, cy)
        else:
            p.moveTo(cx + r_short, cy); p.lineTo(cx, cy + r_long)
            p.lineTo(cx - r_short, cy); p.lineTo(cx, cy - r_long)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        # Flanking accent dots
        c.setFillColor(clr["accent"])
        if horiz:
            c.circle(cx - dot_d, cy, dot_r, fill=1, stroke=0)
            c.circle(cx + dot_d, cy, dot_r, fill=1, stroke=0)
        else:
            c.circle(cx, cy - dot_d, dot_r, fill=1, stroke=0)
            c.circle(cx, cy + dot_d, dot_r, fill=1, stroke=0)


def _border_minimal(c, page_w, page_h, clr, bw=1.0):
    """Top and bottom filled bands only — no side borders."""
    margin = 14 * mm
    bar_h  = 5 * mm * bw
    c.setFillColor(clr["border"])
    c.rect(margin, page_h - margin - bar_h,
           page_w - 2 * margin, bar_h, fill=1, stroke=0)
    c.rect(margin, margin,
           page_w - 2 * margin, bar_h, fill=1, stroke=0)
    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.5 * bw)
    c.line(margin, page_h - margin - 2 * mm,
           page_w - margin, page_h - margin - 2 * mm)
    c.line(margin, margin + bar_h - 2 * mm,
           page_w - margin, margin + bar_h - 2 * mm)


def _border_ornate(c, page_w, page_h, clr, bw=1.0):
    """Triple-border with filled diamond corners and mid-side ornaments."""
    m1, m2, m3 = 10 * mm, 14 * mm, 18 * mm
    c.setStrokeColor(clr["border"])
    c.setLineWidth(2 * bw)
    c.roundRect(m1, m1, page_w - 2 * m1, page_h - 2 * m1, 5 * mm)
    c.setStrokeColor(clr["gold"])
    c.setLineWidth(1 * bw)
    c.roundRect(m2, m2, page_w - 2 * m2, page_h - 2 * m2, 4 * mm)
    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.5 * bw)
    c.roundRect(m3, m3, page_w - 2 * m3, page_h - 2 * m3, 3 * mm)

    # Large filled diamonds at the corners of the middle rect
    r_corner = 6 * mm
    c.setFillColor(clr["gold"])
    for cx, cy in [
        (m2,           page_h - m2),
        (page_w - m2,  page_h - m2),
        (m2,           m2),
        (page_w - m2,  m2),
    ]:
        c.drawPath(_diamond_path(c, cx, cy, r_corner), fill=1, stroke=0)

    # Smaller filled diamonds at the midpoint of each side of the middle rect
    r_mid = 3 * mm
    for cx, cy in [
        (page_w / 2,          page_h - m2),
        (page_w / 2,          m2),
        (m2,                  page_h / 2),
        (page_w - m2,         page_h / 2),
    ]:
        c.drawPath(_diamond_path(c, cx, cy, r_mid), fill=1, stroke=0)


def _border_none(c, page_w, page_h, clr, bw=1.0):
    """No border at all."""
    pass


BORDER_STYLES = {
    "classic": _border_classic,
    "modern": _border_modern,
    "elegant": _border_elegant,
    "minimal": _border_minimal,
    "ornate": _border_ornate,
    "none": _border_none,
}


def _elem_offsets(elem_style):
    """Return (x_offset, y_offset) from per-element padding."""
    if not elem_style:
        return 0, 0
    p = elem_style.get("padding") or {}
    return (
        float(p.get("left", 0)) - float(p.get("right", 0)),
        float(p.get("bottom", 0)) - float(p.get("top", 0)),
    )


def _draw_centered_text(c, text, y, font_name, font_size, color, page_w):
    c.setFont(font_name, font_size)
    c.setFillColor(color)
    c.drawCentredString(page_w / 2, y, text)


def _draw_styled_centered(c, text, y, page_w, elem_style, default_font, default_size, default_color):
    """Draw centered text using per-element style overrides. Handles underline flag and element padding."""
    font_name = _resolve_font(
        elem_style.get("font", "arial"),
        elem_style.get("bold", False),
        elem_style.get("italic", False),
    ) if elem_style else default_font
    font_size = elem_style.get("size", default_size) if elem_style else default_size
    try:
        raw_color = elem_style.get("color") if elem_style else None
        color = colors.HexColor(raw_color) if raw_color else default_color
    except Exception:
        color = default_color

    x_off, y_off = _elem_offsets(elem_style)
    cx = page_w / 2 + x_off
    ay = y + y_off

    c.setFont(font_name, font_size)
    c.setFillColor(color)
    c.drawCentredString(cx, ay, text)

    if elem_style and elem_style.get("underline"):
        tw = c.stringWidth(text, font_name, font_size)
        c.setStrokeColor(color)
        c.setLineWidth(0.75)
        c.line(cx - tw / 2, ay - 2, cx + tw / 2, ay - 2)


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


def _make_qr_image(data: str):
    if not data:
        return None
    try:
        import qrcode as _qrcode
        qr_img = _qrcode.make(data)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)
    except Exception:
        return None


_DEFAULT_ELEM_PAD = {"top": 0, "right": 0, "bottom": 0, "left": 0}

DEFAULT_STYLE = {
    "border_style": "classic",
    "border_width": 1.0,
    "bg_size": "cover",
    "bg_offset_x": 0,
    "bg_offset_y": 0,
    "elements": {
        "brand":     {"font": "arial", "size": 30, "color": "#0e7490", "bold": True,  "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "title":     {"font": "arial", "size": 28, "color": "#0a1628", "bold": True,  "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "subtitle":  {"font": "arial", "size": 12, "color": "#475569", "bold": False, "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "name":      {"font": "arial", "size": 50, "color": "#0a1628", "bold": True,  "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "attending": {"font": "arial", "size": 15, "color": "#475569", "bold": False, "italic": True,  "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "session":   {"font": "arial", "size": 22, "color": "#0e7490", "bold": True,  "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "details":   {"font": "arial", "size": 16, "color": "#334155", "bold": False, "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "venue":     {"font": "arial", "size": 16, "color": "#334155", "bold": False, "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "signer":    {"font": "arial", "size": 11, "color": "#0a1628", "bold": True,  "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
        "footer":    {"font": "arial", "size": 8,  "color": "#94a3b8", "bold": False, "italic": False, "underline": False, "padding": {**_DEFAULT_ELEM_PAD}},
    },
}


def _parse_cert_style(lecture) -> dict:
    """Parse cert_style JSON from lecture, merging with defaults."""
    raw = getattr(lecture, "cert_style", None) or ""
    style = {}
    if raw:
        try:
            style = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            style = {}
    merged = {
        "border_style": style.get("border_style", DEFAULT_STYLE["border_style"]),
        "border_width": float(style.get("border_width", DEFAULT_STYLE["border_width"])),
        "bg_size": style.get("bg_size", DEFAULT_STYLE["bg_size"]),
        "bg_offset_x": float(style.get("bg_offset_x", 0)),
        "bg_offset_y": float(style.get("bg_offset_y", 0)),
        "elements": {},
    }
    for key, defaults in DEFAULT_STYLE["elements"].items():
        elem = style.get("elements", {}).get(key, {})
        elem_merged = {**defaults, **elem}
        elem_merged["padding"] = {**_DEFAULT_ELEM_PAD, **(elem.get("padding") or {})}
        merged["elements"][key] = elem_merged
    return merged


def generate_certificate_pdf(booking, user, lecture, auditorium) -> bytes:
    _register_fonts()

    cert_title      = getattr(lecture, "cert_title", None) or "CERTIFICATE OF ATTENDANCE"
    cert_subtitle   = getattr(lecture, "cert_subtitle", None) or "This certificate is proudly presented to"
    cert_footer_txt = getattr(lecture, "cert_footer", None) or "\u00a9 2026 TechTrek. All rights reserved."
    signer_name     = (getattr(lecture, "cert_signer_name", None) or "").strip()
    signer_desg     = (getattr(lecture, "cert_signer_designation", None) or "").strip()
    signature_url   = getattr(lecture, "cert_signature_url", None) or ""
    logo_url        = getattr(lecture, "cert_logo_url", None) or ""
    bg_url          = getattr(lecture, "cert_bg_url", None) or ""
    color_scheme    = getattr(lecture, "cert_color_scheme", None)

    clr = _get_colors(color_scheme)
    sty = _parse_cert_style(lecture)
    elems = sty["elements"]

    attendee_name = user.full_name or user.username
    session_title = lecture.title
    speaker_name  = lecture.speaker
    session_date  = lecture.start_time.strftime("%d %B %Y")
    venue         = (
        f"{auditorium.name}, {auditorium.location}" if auditorium else "TechTrek Venue"
    )
    cert_id = f"CERT-{booking.booking_ref}"
    qr_data = getattr(booking, "qr_code_data", None) or cert_id

    page_w, page_h = landscape(A4)
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=landscape(A4))

    # ── Background image ──────────────────────────────────────────────────────
    bg_img = _try_load_image(bg_url)
    if bg_img:
        iw, ih = bg_img.getSize()
        bg_mode = sty.get("bg_size", "cover")
        if bg_mode == "contain":
            scale = min(page_w / iw, page_h / ih)
        elif bg_mode == "stretch":
            scale = None
        else:
            scale = max(page_w / iw, page_h / ih)

        if scale is None:
            draw_w, draw_h = page_w, page_h
            draw_x, draw_y = 0, 0
        else:
            draw_w, draw_h = iw * scale, ih * scale
            draw_x = (page_w - draw_w) / 2
            draw_y = (page_h - draw_h) / 2

        draw_x += sty.get("bg_offset_x", 0)
        draw_y += sty.get("bg_offset_y", 0)
        c.drawImage(bg_img, draw_x, draw_y, width=draw_w, height=draw_h, mask="auto")

    # ── Border ────────────────────────────────────────────────────────────────
    border_fn = BORDER_STYLES.get(sty.get("border_style", "classic"), _border_classic)
    border_width = max(0.25, sty.get("border_width", 1.0))
    border_fn(c, page_w, page_h, clr, bw=border_width)

    inner_margin = 14 * mm + 4 * mm
    content_x1 = inner_margin + 10
    content_x2 = page_w - inner_margin - 10

    # ── HEADER ZONE ───────────────────────────────────────────────────────────
    brand_s = elems.get("brand", {})
    brand_font = _resolve_font(brand_s.get("font", "arial"), brand_s.get("bold", True), brand_s.get("italic", False))
    brand_size = brand_s.get("size", 30)
    try:
        brand_color = colors.HexColor(brand_s.get("color", "#0e7490"))
    except Exception:
        brand_color = clr["brand"]

    brand_xo, brand_yo = _elem_offsets(brand_s)
    logo_img = _try_load_image(logo_url)
    if logo_img:
        iw, ih = logo_img.getSize()
        logo_h = 40
        logo_w = min(logo_h * (iw / ih) if ih else 40, 120)
        combined_w = logo_w + 6 + c.stringWidth("TECHTREK", brand_font, brand_size)
        sx = (page_w - combined_w) / 2 + brand_xo
        c.drawImage(logo_img, sx, 480 + brand_yo, width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask="auto")
        c.setFont(brand_font, brand_size)
        c.setFillColor(brand_color)
        c.drawString(sx + logo_w + 6, 490 + brand_yo, "TECHTREK")
    else:
        _draw_styled_centered(c, "TECHTREK", 490, page_w, brand_s, brand_font, brand_size, brand_color)

    if brand_s.get("underline") and not logo_img:
        pass  # already handled by _draw_styled_centered

    c.setStrokeColor(clr["accent"])
    c.setLineWidth(0.75)
    rule_w = (content_x2 - content_x1) * 0.80
    rule_x = (page_w - rule_w) / 2
    c.line(rule_x, 478 + brand_yo, rule_x + rule_w, 478 + brand_yo)

    # ── TITLE ZONE ────────────────────────────────────────────────────────────
    _draw_styled_centered(c, cert_title.upper(), 420, page_w,
                          elems.get("title"), "Helvetica-Bold", 28, clr["heading"])

    title_xo, title_yo = _elem_offsets(elems.get("title"))
    c.setStrokeColor(clr["gold"])
    c.setLineWidth(0.75)
    c.line(page_w / 2 - 100, 405 + title_yo, page_w / 2 + 100, 405 + title_yo)

    _draw_styled_centered(c, cert_subtitle, 390, page_w,
                          elems.get("subtitle"), "Helvetica", 12, colors.HexColor("#475569"))

    # ── NAME ZONE ─────────────────────────────────────────────────────────────
    name_s = elems.get("name", {})
    name_font = _resolve_font(name_s.get("font", "arial"), name_s.get("bold", True), name_s.get("italic", False))
    name_font_size = name_s.get("size", 50)
    if c.stringWidth(attendee_name, name_font, name_font_size) > 600:
        name_font_size = max(name_font_size - 10, 20)
    try:
        name_color = colors.HexColor(name_s.get("color", "#0a1628"))
    except Exception:
        name_color = clr["heading"]

    name_xo, name_yo = _elem_offsets(name_s)
    name_y = 312 + name_yo
    _draw_styled_centered(c, attendee_name, 312, page_w, {**name_s, "size": name_font_size}, name_font, name_font_size, name_color)

    name_w = c.stringWidth(attendee_name, name_font, name_font_size)
    ncx = page_w / 2 + name_xo
    line_x1 = ncx - name_w / 2 - 10
    line_x2 = ncx + name_w / 2 + 10
    c.setStrokeColor(clr["gold"])
    c.setLineWidth(1.5)
    c.line(line_x1, 298 + name_yo, line_x2, 298 + name_yo)

    _draw_styled_centered(c, "for attending the session", 267, page_w,
                          elems.get("attending"), "Helvetica-Oblique", 15, colors.HexColor("#475569"))

    display_title = f"\u201c{session_title}\u201d"
    _draw_styled_centered(c, display_title, 239, page_w,
                          elems.get("session"), "Helvetica-Bold", 22, clr["session"])

    # ── DETAILS ZONE ──────────────────────────────────────────────────────────
    details_s = elems.get("details", {})
    details_font = _resolve_font(details_s.get("font", "arial"), details_s.get("bold", False), details_s.get("italic", False))
    details_size = details_s.get("size", 16)
    try:
        details_color = colors.HexColor(details_s.get("color", "#334155"))
    except Exception:
        details_color = colors.HexColor("#334155")

    details_xo, details_yo = _elem_offsets(details_s)
    _draw_detail_pair(c, f"Speaker: {speaker_name}", f"Date: {session_date}",
                      152 + details_yo, details_font, details_size, details_color, page_w,
                      x_offset=details_xo)
    if details_s.get("underline"):
        c.setStrokeColor(details_color)
        c.setLineWidth(0.5)
        _underline_detail_pair(c, f"Speaker: {speaker_name}", f"Date: {session_date}",
                               152 + details_yo, details_font, details_size, page_w,
                               x_offset=details_xo)

    venue_s = elems.get("venue", {})
    _draw_styled_centered(c, f"Venue: {venue}", 120, page_w,
                          venue_s, "Helvetica", 16, colors.HexColor("#334155"))

    # ── BOTTOM ZONE ───────────────────────────────────────────────────────────
    signer_s = elems.get("signer", {})
    signer_xo, signer_yo = _elem_offsets(signer_s)
    if signer_name:
        signer_font = _resolve_font(signer_s.get("font", "arial"), signer_s.get("bold", True), signer_s.get("italic", False))
        signer_size = signer_s.get("size", 11)
        try:
            signer_color = colors.HexColor(signer_s.get("color", "#0a1628"))
        except Exception:
            signer_color = clr["heading"]

        sx1 = content_x1 + signer_xo

        sig_img = _try_load_image(signature_url)
        if sig_img:
            siw, sih = sig_img.getSize()
            sig_max_w, sig_max_h = 120, 50
            sig_scale = min(sig_max_w / siw, sig_max_h / sih) if siw and sih else 1
            sig_draw_w = siw * sig_scale
            sig_draw_h = sih * sig_scale
            c.drawImage(sig_img, sx1, 98 + signer_yo, width=sig_draw_w, height=sig_draw_h,
                        preserveAspectRatio=True, mask="auto")

        c.setStrokeColor(signer_color)
        c.setLineWidth(1)
        c.line(sx1, 96 + signer_yo, sx1 + 120, 96 + signer_yo)
        c.setFont(signer_font, signer_size)
        c.setFillColor(signer_color)
        c.drawString(sx1, 84 + signer_yo, signer_name)
        if signer_desg:
            desg_font = _resolve_font(signer_s.get("font", "arial"), False, True)
            c.setFont(desg_font, max(signer_size - 2, 7))
            c.setFillColor(colors.HexColor("#475569"))
            c.drawString(sx1, 72 + signer_yo, signer_desg)

    footer_s = elems.get("footer", {})
    footer_font = _resolve_font(footer_s.get("font", "arial"), footer_s.get("bold", False), footer_s.get("italic", False))
    footer_size = footer_s.get("size", 8)
    try:
        footer_color = colors.HexColor(footer_s.get("color", "#94a3b8"))
    except Exception:
        footer_color = colors.HexColor("#94a3b8")

    _draw_styled_centered(c, f"Certificate ID: {cert_id}", 72, page_w,
                          footer_s, footer_font, footer_size, footer_color)
    _draw_styled_centered(c, cert_footer_txt, 60, page_w,
                          footer_s, footer_font, footer_size, footer_color)

    footer_xo, footer_yo = _elem_offsets(footer_s)
    qr_reader = _make_qr_image(qr_data)
    if qr_reader:
        qr_size = 70
        qr_x = content_x2 - qr_size
        qr_y = 88 + footer_yo
        c.drawImage(qr_reader, qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")
        c.setFont(footer_font, 7)
        c.setFillColor(footer_color)
        c.drawCentredString(qr_x + qr_size / 2, qr_y - 11, "Scan to verify")

    c.save()
    return buf.getvalue()


def _draw_detail_pair(c, left_text, right_text, y, font_name, font_size, color, page_w, x_offset=0):
    gap = 20 * mm
    c.setFont(font_name, font_size)
    c.setFillColor(color)
    left_w = c.stringWidth(left_text, font_name, font_size)
    right_w = c.stringWidth(right_text, font_name, font_size)
    total_w = left_w + gap + right_w
    start_x = (page_w - total_w) / 2 + x_offset
    c.drawString(start_x, y, left_text)
    c.drawString(start_x + left_w + gap, y, right_text)


def _underline_detail_pair(c, left_text, right_text, y, font_name, font_size, page_w, x_offset=0):
    gap = 20 * mm
    left_w = c.stringWidth(left_text, font_name, font_size)
    right_w = c.stringWidth(right_text, font_name, font_size)
    total_w = left_w + gap + right_w
    start_x = (page_w - total_w) / 2 + x_offset
    c.line(start_x, y - 2, start_x + left_w, y - 2)
    c.line(start_x + left_w + gap, y - 2, start_x + total_w, y - 2)
