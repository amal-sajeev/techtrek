import io
import ipaddress
import json
import os
import socket
import urllib.request
import urllib.parse

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

    # Corner medallions — purely multiplicative: cap scales directly with bw
    cap = max(3 * mm, 9 * mm * b)   # half-size of the square plate
    ds  = cap * 0.62                 # diamond radius within plate
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

    # Corner crosshair ornaments — purely multiplicative: all sizes scale directly with bw
    arm = max(2 * mm, 7 * mm * b)   # arm half-length
    cr  = arm * 0.16                 # tip dot radius
    dr  = arm * 0.28                 # center diamond radius
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

    # Mid-side elongated diamonds + flanking dots — purely multiplicative
    r_long  = max(2.5 * mm, 8.5 * mm * b)   # long radius (oriented along the edge)
    r_short = r_long * 0.35                   # short radius (perpendicular to edge)
    dot_r   = r_long * 0.13                   # flanking dot radius
    dot_d   = r_long * 1.45                   # flanking dot distance from center
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


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # unique local IPv6
]
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def _is_private_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # can't resolve → treat as unsafe
    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
            if any(addr in net for net in _PRIVATE_NETWORKS):
                return True
        except ValueError:
            return True
    return False


def _load_uploaded_image(image_id: int):
    """Load an UploadedImage from the database by id."""
    try:
        from app.database import SessionLocal
        from app.models.uploaded_image import UploadedImage
        db = SessionLocal()
        try:
            img = db.query(UploadedImage).filter(UploadedImage.id == image_id).first()
            if img and img.data:
                return ImageReader(io.BytesIO(img.data))
        finally:
            db.close()
    except Exception:
        pass
    return None


def _try_load_image(url: str):
    if not url:
        return None

    import re as _re
    m = _re.match(r'^/uploads/(\d+)$', url)
    if m:
        return _load_uploaded_image(int(m.group(1)))

    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            return None
        host = parsed.hostname or ""
        if not host or _is_private_ip(host):
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "TechTrek/1.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None
        data = resp.read(_MAX_IMAGE_BYTES + 1)
        if len(data) > _MAX_IMAGE_BYTES:
            return None
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
        "border_color_primary": style.get("border_color_primary") or "",
        "border_color_secondary": style.get("border_color_secondary") or "",
        "border_color_tertiary": style.get("border_color_tertiary") or "",
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


# ── cert_style v2 (freeform layout) ───────────────────────────────────────────
# JSON shape (Event.cert_style):
#   version: 2, layout: "freeform"
#   page: { widthPt, heightPt }     # default landscape A4 ≈ 842 × 595
#   border_style, border_width, border_color_{primary,secondary,tertiary},
#   bg_size, bg_offset_x, bg_offset_y  — same semantics as legacy top-level keys
#   layers: [
#     { id, type, zIndex,
#       type "text":   variable, text, xPt, yPt, widthPt, heightPt, rotation,
#                      font, fontSize (alias: size), color, bold, italic, align, underline
#       type "image":  imageRole logo|signature|custom, url (when custom), xPt, yPt, widthPt, heightPt, rotation
#       type "qr":     xPt, yPt, widthPt, heightPt, rotation, showCaption?
#       type "line":   xPt, yPt, x2Pt, y2Pt, lineWidth, color
#       type "rect":   xPt, yPt, widthPt, heightPt, fillColor?, strokeColor?, strokeWidth?, rotation
#     }, ...
#   ]
#
# Variable → resolved string (_build_cert_variable_context keys):
#   static (use text only), attendee_name, event_name, event_date, venue, cert_id, booking_ref,
#   title_text, subtitle_text, footer_text, signer_name, signer_designation,
#   event_session_title, attending_line, brand_text, details_line, venue_line, cert_id_line, speaker_name

CERT_STYLE_VERSION_FREEFORM = 2


def _raw_cert_style_dict(cert_source) -> dict:
    raw = getattr(cert_source, "cert_style", None) or ""
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def is_freeform_cert_style(d: dict) -> bool:
    """True when JSON declares v2 freeform (layers key must be a list; may be empty)."""
    if not isinstance(d, dict):
        return False
    return (
        int(d.get("version") or 0) == CERT_STYLE_VERSION_FREEFORM
        and str(d.get("layout") or "").lower() == "freeform"
        and isinstance(d.get("layers"), list)
    )


def should_render_certificate_as_freeform(d: dict) -> bool:
    """PDF uses freeform only when there is at least one layer (avoids legacy fallback for broken saves)."""
    return is_freeform_cert_style(d) and len(d.get("layers") or []) > 0


def default_freeform_cert_style_dict() -> dict:
    pw, ph = landscape(A4)

    def tb(var, z, x, y_bottom, w, h, fs, color, bold, italic,
           align="center", font="arial"):
        return {
            "id": f"t-{var}-{z}",
            "type": "text",
            "zIndex": z,
            "variable": var,
            "text": "",
            "xPt": x,
            "yPt": y_bottom,
            "widthPt": w,
            "heightPt": h,
            "font": font,
            "fontSize": fs,
            "color": color,
            "bold": bold,
            "italic": italic,
            "align": align,
            "underline": False,
            "rotation": 0,
        }

    return {
        "version": CERT_STYLE_VERSION_FREEFORM,
        "layout": "freeform",
        "page": {"widthPt": pw, "heightPt": ph},
        "border_style": "minimal",
        "border_width": float(DEFAULT_STYLE["border_width"]),
        "bg_size": DEFAULT_STYLE["bg_size"],
        "bg_offset_x": 0.0,
        "bg_offset_y": 0.0,
        "layers": [
            tb("brand_text",          10, 121, 508, 600, 24, 13, "#555555", False, False),
            tb("title_text",          11, 121, 460, 600, 38, 28, "#1a1a1a", True,  False),
            tb("subtitle_text",       12, 171, 432, 500, 22, 11, "#888888", False, False),
            tb("attendee_name",       20,  71, 348, 700, 68, 52, "#1a1a1a", True,  False),
            tb("attending_line",      21, 171, 320, 500, 20, 12, "#555555", False, True),
            tb("event_session_title", 22, 121, 280, 600, 32, 20, "#1a1a1a", True,  False),
            tb("details_line",        23, 121, 252, 600, 22, 12, "#555555", False, False),
            tb("venue_line",          24, 121, 228, 600, 22, 12, "#555555", False, False),
            tb("signer_name",         30,  50, 105, 220, 20, 11, "#1a1a1a", True,  False, align="left"),
            tb("signer_designation",  31,  50,  87, 220, 18,  9, "#888888", False, True,  align="left"),
            tb("cert_id_line",        35, 280,  78, 300, 16,  8, "#aaaaaa", False, False),
            tb("footer_text",         36, 280,  60, 300, 16,  8, "#aaaaaa", False, False),
            {
                "id": "qr-1",
                "type": "qr",
                "zIndex": 40,
                "xPt": 697.0,
                "yPt": 65.0,
                "widthPt": 78.0,
                "heightPt": 78.0,
                "rotation": 0,
                "showCaption": True,
            },
        ],
    }


def _normalize_cert_scalar_raw(value) -> str | None:
    """Treat None, blank, and literal 'none'/'null' as missing (bad imports / ORM artifacts)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() in ("none", "null"):
        return None
    return s


def merge_cert_scalar_from_template(template_value, event_value):
    """
    When applying a library certificate template: copy a scalar from the template only if it is
    meaningful; otherwise keep the event's existing value (visual-only templates often have NULLs).
    """
    t = _normalize_cert_scalar_raw(template_value)
    if t is not None:
        return t
    return event_value


def normalize_cert_scalar_for_storage(value) -> str | None:
    """Normalize form/API values before persisting to cert_* columns."""
    return _normalize_cert_scalar_raw("" if value is None else value)


def _freeform_top_level(raw: dict) -> dict:
    """Border / background keys for v2 (mirrors legacy merged top-level)."""
    return {
        "border_style": raw.get("border_style", DEFAULT_STYLE["border_style"]),
        "border_width": float(raw.get("border_width", DEFAULT_STYLE["border_width"])),
        "border_color_primary": raw.get("border_color_primary") or "",
        "border_color_secondary": raw.get("border_color_secondary") or "",
        "border_color_tertiary": raw.get("border_color_tertiary") or "",
        "bg_size": raw.get("bg_size", DEFAULT_STYLE["bg_size"]),
        "bg_offset_x": float(raw.get("bg_offset_x", 0)),
        "bg_offset_y": float(raw.get("bg_offset_y", 0)),
    }


def _build_cert_variable_context(booking, user, event, auditorium, cert_source) -> dict:
    cert_title = _normalize_cert_scalar_raw(getattr(cert_source, "cert_title", None)) or "CERTIFICATE OF ATTENDANCE"
    cert_subtitle = (
        _normalize_cert_scalar_raw(getattr(cert_source, "cert_subtitle", None))
        or "This certificate is proudly presented to"
    )
    cert_footer_txt = (
        _normalize_cert_scalar_raw(getattr(cert_source, "cert_footer", None))
        or "\u00a9 2026 TechTrek. All rights reserved."
    )
    signer_name = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signer_name", None)) or ""
    signer_desg = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signer_designation", None)) or ""

    attendee_name = user.full_name or user.username
    session_title = getattr(event, "name", "Event") if event else "Event"
    speaker_name = ""
    session_date = event.start_date.strftime("%d %B %Y") if event and event.start_date else ""
    venue = f"{auditorium.name}, {auditorium.location}" if auditorium else "TechTrek Venue"
    cert_id = f"CERT-{booking.booking_ref}"
    booking_ref = str(getattr(booking, "booking_ref", "") or "")

    left = f"Speaker: {speaker_name}"
    right = f"Date: {session_date}"
    details_combined = f"{left}    {right}"

    return {
        "static": "",
        "attendee_name": attendee_name,
        "event_name": session_title,
        "event_date": session_date,
        "venue": venue,
        "cert_id": cert_id,
        "booking_ref": booking_ref,
        "title_text": cert_title.upper(),
        "subtitle_text": cert_subtitle,
        "footer_text": cert_footer_txt,
        "signer_name": signer_name,
        "signer_designation": signer_desg,
        "event_session_title": f"\u201c{session_title}\u201d",
        "attending_line": "for attending the session",
        "brand_text": "TECHTREK",
        "details_line": details_combined,
        "venue_line": f"Venue: {venue}",
        "cert_id_line": f"Certificate ID: {cert_id}",
        "speaker_name": speaker_name,
    }


def _resolve_freeform_layer_text(layer: dict, ctx: dict) -> str:
    var = (layer.get("variable") or "static")
    var = str(var).strip().lower().replace("-", "_")
    static_text = layer.get("text")
    if static_text is None:
        static_text = ""
    if var in ("", "static", "none"):
        return str(static_text)
    if var in ctx:
        return str(ctx[var])
    return str(static_text)


def _freeform_font_size(layer: dict) -> float:
    v = layer.get("fontSize")
    if v is None:
        v = layer.get("size")
    return float(v if v is not None else 12)


def _wrap_lines_canvas(c, text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    words = text.replace("\n", " ").split()
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if not cur or c.stringWidth(trial, font_name, font_size) <= max_width:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def _draw_freeform_text_layer(c, layer: dict, text: str) -> None:
    fs = _freeform_font_size(layer)
    font_name = _resolve_font(
        layer.get("font", "arial"),
        bool(layer.get("bold")),
        bool(layer.get("italic")),
    )
    try:
        color = colors.HexColor(layer.get("color") or "#000000")
    except Exception:
        color = colors.black

    x = float(layer.get("xPt", 0))
    y = float(layer.get("yPt", 0))
    w = float(layer.get("widthPt") or 400)
    h = float(layer.get("heightPt") or fs * 1.5)
    rot = float(layer.get("rotation") or 0)
    align = str(layer.get("align") or "left").lower()

    cx = x + w / 2
    cy = y + h / 2

    c.saveState()
    if rot:
        c.translate(cx, cy)
        c.rotate(-rot)
        c.translate(-cx, -cy)

    max_w = max(w - 4, 8)
    lines = _wrap_lines_canvas(c, text, font_name, fs, max_w)
    leading = fs * 1.2
    n = min(len(lines), max(1, int(h // max(leading, 1)) + 2))
    lines = lines[:n]
    total_text_h = len(lines) * leading
    y_top = y + h
    start_baseline = y_top - fs * 0.22 - max(0, (h - min(total_text_h, h)) / 2)

    c.setFont(font_name, fs)
    c.setFillColor(color)

    for i, line in enumerate(lines):
        baseline = start_baseline - i * leading
        if baseline < y:
            break
        tw = c.stringWidth(line, font_name, fs)
        if align == "center":
            tx = x + (w - tw) / 2
        elif align == "right":
            tx = x + w - tw - 2
        else:
            tx = x + 2
        c.drawString(tx, baseline, line)
        if layer.get("underline") and line:
            c.setStrokeColor(color)
            c.setLineWidth(0.75)
            c.line(tx, baseline - 2, tx + tw, baseline - 2)

    c.restoreState()


def _draw_freeform_background(c, page_w: float, page_h: float, bg_url: str, sty_top: dict) -> None:
    bg_img = _try_load_image(bg_url)
    if not bg_img:
        return
    iw, ih = bg_img.getSize()
    bg_mode = sty_top.get("bg_size", "cover")
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

    draw_x += sty_top.get("bg_offset_x", 0)
    draw_y += sty_top.get("bg_offset_y", 0)
    c.drawImage(bg_img, draw_x, draw_y, width=draw_w, height=draw_h, mask="auto")


def _generate_certificate_freeform(
    booking,
    user,
    cert_source,
    event,
    auditorium,
    raw: dict,
) -> bytes:
    logo_url = _normalize_cert_scalar_raw(getattr(cert_source, "cert_logo_url", None)) or ""
    signature_url = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signature_url", None)) or ""
    color_scheme = getattr(cert_source, "cert_color_scheme", None)
    qr_data = getattr(booking, "qr_code_data", None) or f"CERT-{booking.booking_ref}"

    page = raw.get("page") or {}
    pw, ph = landscape(A4)
    page_w = float(page.get("widthPt", pw))
    page_h = float(page.get("heightPt", ph))

    clr = _get_colors(color_scheme)
    top = _freeform_top_level(raw)
    if top.get("border_color_primary"):
        try:
            clr["border"] = colors.HexColor(top["border_color_primary"])
        except Exception:
            pass
    if top.get("border_color_secondary"):
        try:
            clr["gold"] = colors.HexColor(top["border_color_secondary"])
        except Exception:
            pass
    if top.get("border_color_tertiary"):
        try:
            clr["accent"] = colors.HexColor(top["border_color_tertiary"])
        except Exception:
            pass

    ctx = _build_cert_variable_context(booking, user, event, auditorium, cert_source)

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(page_w, page_h))

    raw_bg = _normalize_cert_scalar_raw(raw.get("background_image_url"))
    fallback_bg = _normalize_cert_scalar_raw(getattr(cert_source, "cert_bg_url", None)) or ""
    bg_url = (raw_bg or "") or fallback_bg
    _draw_freeform_background(c, page_w, page_h, bg_url, top)

    border_fn = BORDER_STYLES.get(top.get("border_style", "classic"), _border_classic)
    border_width = max(0.25, top.get("border_width", 1.0))
    border_fn(c, page_w, page_h, clr, bw=border_width)

    layers = list(raw.get("layers") or [])
    layers.sort(key=lambda L: int(L.get("zIndex", 0) or 0))

    for layer in layers:
        t = str(layer.get("type") or "text").lower()

        if t == "text":
            resolved = _resolve_freeform_layer_text(layer, ctx)
            _draw_freeform_text_layer(c, layer, resolved)
            continue

        if t == "image":
            role = str(layer.get("imageRole") or "custom").lower()
            layer_url = (layer.get("url") or "").strip()
            if role == "logo":
                url = layer_url or logo_url
            elif role == "signature":
                url = layer_url or signature_url
            else:
                url = layer_url
            img = _try_load_image(url)
            if not img:
                continue
            x = float(layer.get("xPt", 0))
            y = float(layer.get("yPt", 0))
            w = float(layer.get("widthPt") or 80)
            h = float(layer.get("heightPt") or 80)
            rot = float(layer.get("rotation") or 0)
            cx = x + w / 2
            cy = y + h / 2
            c.saveState()
            if rot:
                c.translate(cx, cy)
                c.rotate(-rot)
                c.translate(-cx, -cy)
            # Match certificate-designer.js (Fabric scales image to fill widthPt×heightPt; no letterboxing).
            c.drawImage(img, x, y, width=w, height=h, preserveAspectRatio=False, mask="auto")
            c.restoreState()
            continue

        if t == "qr":
            qr_reader = _make_qr_image(qr_data)
            if not qr_reader:
                continue
            x = float(layer.get("xPt", 0))
            y = float(layer.get("yPt", 0))
            size = float(layer.get("widthPt") or layer.get("heightPt") or 70)
            rot = float(layer.get("rotation") or 0)
            cx = x + size / 2
            cy = y + size / 2
            c.saveState()
            if rot:
                c.translate(cx, cy)
                c.rotate(-rot)
                c.translate(-cx, -cy)
            c.drawImage(qr_reader, x, y, width=size, height=size, mask="auto")
            c.restoreState()
            if layer.get("showCaption", True):
                ff = _resolve_font("arial", False, False)
                fc = colors.HexColor("#94a3b8")
                c.setFont(ff, 7)
                c.setFillColor(fc)
                c.drawCentredString(x + size / 2, y - 11, "Scan to verify")
            continue

        if t == "line":
            x1 = float(layer.get("xPt", 0))
            y1 = float(layer.get("yPt", 0))
            x2 = float(layer.get("x2Pt", x1 + 100))
            y2 = float(layer.get("y2Pt", y1))
            lw = float(layer.get("lineWidth") or 1)
            try:
                lc = colors.HexColor(layer.get("color") or "#000000")
            except Exception:
                lc = colors.black
            c.saveState()
            c.setStrokeColor(lc)
            c.setLineWidth(lw)
            c.line(x1, y1, x2, y2)
            c.restoreState()
            continue

        if t == "rect":
            x = float(layer.get("xPt", 0))
            y = float(layer.get("yPt", 0))
            w = float(layer.get("widthPt") or 10)
            h = float(layer.get("heightPt") or 10)
            rot = float(layer.get("rotation") or 0)
            sw = float(layer.get("strokeWidth") or 1)
            fill_c = layer.get("fillColor")
            stroke_c = layer.get("strokeColor")
            cx = x + w / 2
            cy = y + h / 2
            c.saveState()
            if rot:
                c.translate(cx, cy)
                c.rotate(-rot)
                c.translate(-cx, -cy)
            if fill_c:
                try:
                    c.setFillColor(colors.HexColor(fill_c))
                    c.rect(x, y, w, h, fill=1, stroke=0)
                except Exception:
                    pass
            if stroke_c and sw > 0:
                try:
                    c.setStrokeColor(colors.HexColor(stroke_c))
                    c.setLineWidth(sw)
                    c.rect(x, y, w, h, fill=0, stroke=1)
                except Exception:
                    pass
            c.restoreState()

    c.save()
    return buf.getvalue()


def legacy_cert_style_to_freeform_dict(cert_source) -> dict:
    """Approximate current fixed template as v2 layers; preserves per-element typography from merged legacy style."""
    sty = _parse_cert_style(cert_source)
    elems = sty["elements"]
    pw, ph = landscape(A4)
    m = 14 * mm + 4 * mm
    content_x1 = m + 10
    content_x2 = pw - m - 10
    qr_size = 70.0
    qr_x = content_x2 - qr_size

    def es_of(key: str) -> dict:
        return elems.get(key, {})

    def text_layer(lid: str, var: str, z: int, y_baseline: float, width: float, elem_key: str, x_off: float = 0):
        e = es_of(elem_key)
        fs = float(e.get("size", 12))
        h = max(fs * 1.4, 18)
        y_bottom = y_baseline - fs * 0.35
        return {
            "id": lid,
            "type": "text",
            "zIndex": z,
            "variable": var,
            "text": "",
            "xPt": (pw - width) / 2 + x_off,
            "yPt": y_bottom,
            "widthPt": width,
            "heightPt": h,
            "font": e.get("font", "arial"),
            "fontSize": fs,
            "color": e.get("color", "#0a1628"),
            "bold": bool(e.get("bold")),
            "italic": bool(e.get("italic")),
            "align": "center",
            "underline": bool(e.get("underline")),
            "rotation": 0,
        }

    layers: list[dict] = [
        text_layer("l-title", "title_text", 11, 420, 600, "title"),
        text_layer("l-sub", "subtitle_text", 12, 390, 600, "subtitle"),
        text_layer("l-name", "attendee_name", 20, 312, 600, "name"),
        text_layer("l-att", "attending_line", 21, 267, 600, "attending"),
        text_layer("l-sess", "event_session_title", 22, 239, 600, "session"),
        text_layer("l-det", "details_line", 23, 152, 600, "details"),
        text_layer("l-ven", "venue_line", 24, 120, 600, "venue"),
        text_layer("l-cid", "cert_id_line", 30, 72, 600, "footer"),
        text_layer("l-foot", "footer_text", 31, 60, 600, "footer"),
    ]

    brand_e = es_of("brand")
    brand_fs = float(brand_e.get("size", 30))
    layers.insert(
        0,
        {
            "id": "l-brand",
            "type": "text",
            "zIndex": 10,
            "variable": "brand_text",
            "text": "",
            "xPt": (pw - 500) / 2,
            "yPt": 490 - brand_fs * 0.35,
            "widthPt": 500,
            "heightPt": max(brand_fs * 1.3, 28),
            "font": brand_e.get("font", "arial"),
            "fontSize": brand_fs,
            "color": brand_e.get("color", "#0e7490"),
            "bold": bool(brand_e.get("bold", True)),
            "italic": bool(brand_e.get("italic")),
            "align": "center",
            "underline": bool(brand_e.get("underline")),
            "rotation": 0,
        },
    )

    signer_e = es_of("signer")
    signer_fs = float(signer_e.get("size", 11))
    layers.extend(
        [
            {
                "id": "l-signer",
                "type": "text",
                "zIndex": 25,
                "variable": "signer_name",
                "text": "",
                "xPt": content_x1,
                "yPt": 84 - signer_fs * 0.25,
                "widthPt": 200,
                "heightPt": max(signer_fs * 1.3, 16),
                "font": signer_e.get("font", "arial"),
                "fontSize": signer_fs,
                "color": signer_e.get("color", "#0a1628"),
                "bold": bool(signer_e.get("bold", True)),
                "italic": bool(signer_e.get("italic")),
                "align": "left",
                "underline": bool(signer_e.get("underline")),
                "rotation": 0,
            },
            {
                "id": "l-signer-d",
                "type": "text",
                "zIndex": 26,
                "variable": "signer_designation",
                "text": "",
                "xPt": content_x1,
                "yPt": 72 - max(signer_fs - 2, 7) * 0.25,
                "widthPt": 200,
                "heightPt": 24,
                "font": signer_e.get("font", "arial"),
                "fontSize": max(signer_fs - 2, 7),
                "color": "#475569",
                "bold": False,
                "italic": True,
                "align": "left",
                "underline": False,
                "rotation": 0,
            },
        ]
    )

    layers.append(
        {
            "id": "l-qr",
            "type": "qr",
            "zIndex": 40,
            "xPt": qr_x,
            "yPt": 88,
            "widthPt": qr_size,
            "heightPt": qr_size,
            "rotation": 0,
            "showCaption": True,
        }
    )

    out = {
        "version": CERT_STYLE_VERSION_FREEFORM,
        "layout": "freeform",
        "page": {"widthPt": pw, "heightPt": ph},
        "border_style": sty.get("border_style", DEFAULT_STYLE["border_style"]),
        "border_width": float(sty.get("border_width", DEFAULT_STYLE["border_width"])),
        "bg_size": sty.get("bg_size", DEFAULT_STYLE["bg_size"]),
        "bg_offset_x": float(sty.get("bg_offset_x", 0)),
        "bg_offset_y": float(sty.get("bg_offset_y", 0)),
        "layers": layers,
    }
    if sty.get("border_color_primary"):
        out["border_color_primary"] = sty["border_color_primary"]
    if sty.get("border_color_secondary"):
        out["border_color_secondary"] = sty["border_color_secondary"]
    if sty.get("border_color_tertiary"):
        out["border_color_tertiary"] = sty["border_color_tertiary"]

    raw_prev = _raw_cert_style_dict(cert_source)
    if raw_prev and not is_freeform_cert_style(raw_prev):
        out["legacy"] = raw_prev
    return out


def generate_certificate_pdf(booking, user, cert_source, event, auditorium) -> bytes:
    _register_fonts()
    raw = _raw_cert_style_dict(cert_source)
    if should_render_certificate_as_freeform(raw):
        return _generate_certificate_freeform(booking, user, cert_source, event, auditorium, raw)
    return _generate_certificate_legacy(booking, user, cert_source, event, auditorium)


def _generate_certificate_legacy(booking, user, cert_source, event, auditorium) -> bytes:
    _register_fonts()

    cert_title = _normalize_cert_scalar_raw(getattr(cert_source, "cert_title", None)) or "CERTIFICATE OF ATTENDANCE"
    cert_subtitle = (
        _normalize_cert_scalar_raw(getattr(cert_source, "cert_subtitle", None))
        or "This certificate is proudly presented to"
    )
    cert_footer_txt = (
        _normalize_cert_scalar_raw(getattr(cert_source, "cert_footer", None))
        or "\u00a9 2026 TechTrek. All rights reserved."
    )
    signer_name = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signer_name", None)) or ""
    signer_desg = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signer_designation", None)) or ""
    signature_url = _normalize_cert_scalar_raw(getattr(cert_source, "cert_signature_url", None)) or ""
    logo_url = _normalize_cert_scalar_raw(getattr(cert_source, "cert_logo_url", None)) or ""
    bg_url = _normalize_cert_scalar_raw(getattr(cert_source, "cert_bg_url", None)) or ""
    color_scheme    = getattr(cert_source, "cert_color_scheme", None)

    clr = _get_colors(color_scheme)
    sty = _parse_cert_style(cert_source)

    if sty.get("border_color_primary"):
        try:
            clr["border"] = colors.HexColor(sty["border_color_primary"])
        except Exception:
            pass
    if sty.get("border_color_secondary"):
        try:
            clr["gold"] = colors.HexColor(sty["border_color_secondary"])
        except Exception:
            pass
    if sty.get("border_color_tertiary"):
        try:
            clr["accent"] = colors.HexColor(sty["border_color_tertiary"])
        except Exception:
            pass

    elems = sty["elements"]

    attendee_name = user.full_name or user.username
    session_title = getattr(event, "name", "Event") if event else "Event"
    speaker_name  = ""
    session_date  = event.start_date.strftime("%d %B %Y") if event and event.start_date else ""
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
