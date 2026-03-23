"""Generates a comprehensive, chart-rich PDF report for a single event.

Uses ReportLab's Drawing/shapes for inline charts (horizontal bars, vertical
bars, pie charts) and Platypus for page flow with KeepTogether to prevent
awkward page splits.
"""

import io
import math
import os
from collections import Counter
from datetime import datetime

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

# ═══════════════════════════════════════════════════════════════════════
#  Font registration
# ═══════════════════════════════════════════════════════════════════════

_FONT_REGISTERED = False
_FONT_CHECKED = False


def _register_fonts():
    global _FONT_REGISTERED, _FONT_CHECKED
    if _FONT_CHECKED:
        return
    _FONT_CHECKED = True
    font_sets = [
        [("Arial", "C:/Windows/Fonts/arial.ttf"),
         ("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf")],
        [("Arial", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"),
         ("Arial-Bold", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf")],
        [("Arial", "/usr/share/fonts/dejavu/DejaVuSans.ttf"),
         ("Arial-Bold", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf")],
        [("Arial", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         ("Arial-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")],
    ]
    for candidates in font_sets:
        if all(os.path.exists(p) for _, p in candidates):
            for name, path in candidates:
                pdfmetrics.registerFont(TTFont(name, path))
            _FONT_REGISTERED = True
            return


def _font():
    return "Arial" if _FONT_REGISTERED else "Helvetica"


def _font_bold():
    return "Arial-Bold" if _FONT_REGISTERED else "Helvetica-Bold"


# ═══════════════════════════════════════════════════════════════════════
#  Colour palette — semantic, not decorative
# ═══════════════════════════════════════════════════════════════════════

_DARK = colors.HexColor("#0a1628")
_ACCENT = colors.HexColor("#00a3cc")
_GREEN = colors.HexColor("#059669")
_AMBER = colors.HexColor("#d97706")
_RED = colors.HexColor("#dc2626")
_MUTED = colors.HexColor("#6b7280")
_LIGHT_BG = colors.HexColor("#f3f4f6")
_STRIPE_BG = colors.HexColor("#e8eaed")
_GRID = colors.HexColor("#d1d5db")
_BAR_TRACK = colors.HexColor("#e5e7eb")
_WHITE = colors.white

_PIE_COLORS = [_ACCENT, colors.HexColor("#7c3aed"), _AMBER, _GREEN, _RED,
               colors.HexColor("#db2777"), colors.HexColor("#6366f1"),
               colors.HexColor("#0ea5e9")]

# ═══════════════════════════════════════════════════════════════════════
#  Page geometry
# ═══════════════════════════════════════════════════════════════════════

_PAGE_W, _PAGE_H = A4
_MARGIN = 20 * mm
_CONTENT_W = _PAGE_W - 2 * _MARGIN
_HALF_W = (_CONTENT_W - 12) / 2

# ═══════════════════════════════════════════════════════════════════════
#  Text helpers
# ═══════════════════════════════════════════════════════════════════════


def _esc(text) -> str:
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cur(val) -> str:
    try:
        return f"Rs.{float(val):,.0f}"
    except (TypeError, ValueError):
        return "Rs.0"


def _pct(part, total) -> str:
    if not total:
        return "0%"
    return f"{part / total * 100:.1f}%"


def _nice_ceil(v):
    """Round v up to a clean chart-axis value (e.g. 13->15, 27->30)."""
    if v <= 0:
        return 1
    if v <= 5:
        return 5
    if v <= 10:
        return 10
    if v <= 50:
        return int(math.ceil(v / 5) * 5)
    return int(math.ceil(v / 10) * 10)


# ═══════════════════════════════════════════════════════════════════════
#  Chart drawing helpers
# ═══════════════════════════════════════════════════════════════════════

def _draw_h_bars(labels, values, width, height, bar_color=_ACCENT,
                 fmt=str, max_items=12):
    """Horizontal bar chart in a Drawing.  Wide label area, no truncation."""
    labels = list(labels[:max_items])
    values = list(values[:max_items])
    d = Drawing(width, height)
    n = len(labels)
    if n == 0:
        return d

    max_val = max(values) if values else 1
    label_w = width * 0.45
    chart_w = width * 0.42
    bar_h = min((height - 8) / n * 0.68, 16)
    spacing = (height - 8) / n

    for i, (label, val) in enumerate(zip(labels, values)):
        y = height - (i + 1) * spacing
        d.add(String(label_w - 6, y + bar_h * 0.15, str(label),
                     fontName=_font(), fontSize=7, textAnchor="end", fillColor=_DARK))
        d.add(Rect(label_w, y, chart_w, bar_h,
                   fillColor=_BAR_TRACK, strokeColor=None))
        fill_w = (val / max_val) * chart_w if max_val > 0 else 0
        if fill_w > 0:
            d.add(Rect(label_w, y, fill_w, bar_h,
                       fillColor=bar_color, strokeColor=None))
        d.add(String(label_w + chart_w + 5, y + bar_h * 0.15, fmt(val),
                     fontName=_font(), fontSize=7, textAnchor="start", fillColor=_MUTED))
    return d


def _draw_v_bars(labels, values, width, height, bar_color=_ACCENT):
    """Vertical bar chart with clean axis gridlines."""
    d = Drawing(width, height)
    n = len(labels)
    if n == 0:
        return d

    raw_max = max(values) if values else 1
    max_val = _nice_ceil(raw_max)
    left = 30
    bottom = 28
    chart_w = width - left - 10
    chart_h = height - bottom - 12
    n_grid = 4

    for i in range(n_grid + 1):
        y = bottom + chart_h * i / n_grid
        val = max_val * i / n_grid
        d.add(Line(left, y, left + chart_w, y,
                   strokeColor=_BAR_TRACK, strokeWidth=0.4))
        d.add(String(left - 4, y - 3, str(int(val)),
                     fontName=_font(), fontSize=6, textAnchor="end", fillColor=_MUTED))

    d.add(Line(left, bottom, left, bottom + chart_h,
               strokeColor=_GRID, strokeWidth=0.5))

    gap = chart_w / n
    bar_w = max(gap * 0.72, 3)

    for i, (label, val) in enumerate(zip(labels, values)):
        x = left + i * gap + (gap - bar_w) / 2
        bar_h = (val / max_val * chart_h) if max_val > 0 else 0
        d.add(Rect(x, bottom, bar_w, bar_h,
                   fillColor=bar_color, strokeColor=None))
        show = n <= 18 or i % max(1, n // 12) == 0
        if show:
            d.add(String(x + bar_w / 2, bottom - 12, str(label),
                         fontName=_font(), fontSize=5, textAnchor="middle",
                         fillColor=_MUTED))
    return d


def _draw_pie(labels, values, width, height, pie_colors=None):
    """Pie chart with legend.  Returns None when data is too skewed (>85%)."""
    if not values or all(v == 0 for v in values):
        return None
    total = sum(values)
    if total > 0 and max(values) / total > 0.85:
        return None

    d = Drawing(width, height)
    clrs = pie_colors or _PIE_COLORS
    radius = min(width * 0.28, height * 0.40)
    cx = width * 0.30
    cy = height * 0.50

    pie = Pie()
    pie.x = cx - radius
    pie.y = cy - radius
    pie.width = radius * 2
    pie.height = radius * 2
    pie.data = values
    pie.labels = None
    pie.strokeColor = _WHITE
    pie.strokeWidth = 1.5

    for i in range(len(values)):
        pie.slices[i].fillColor = clrs[i % len(clrs)]

    d.add(pie)

    legend_x = width * 0.62
    legend_y = height - 16
    line_h = max(14, height / (len(labels) + 1))

    for i, (label, val) in enumerate(zip(labels, values)):
        y = legend_y - i * line_h
        c = clrs[i % len(clrs)]
        d.add(Rect(legend_x, y - 2, 8, 8, fillColor=c, strokeColor=None))
        pct = f" ({val / total * 100:.0f}%)" if total else ""
        d.add(String(legend_x + 12, y - 1, f"{label}: {val}{pct}",
                     fontName=_font(), fontSize=7, fillColor=_DARK))
    return d


def _draw_rating_dist(distribution, width, height):
    """5-row horizontal bar chart for 1-5 star rating distribution.
    Uses semantic colors: green for 4-5, amber for 3, red for 1-2."""
    d = Drawing(width, height)
    max_val = max(distribution.values()) if distribution else 1
    if max_val == 0:
        max_val = 1
    bar_h = min((height - 6) / 5 * 0.72, 16)
    spacing = (height - 6) / 5

    for star in range(5, 0, -1):
        i = 5 - star
        y = height - (i + 1) * spacing
        cnt = distribution.get(star, 0)

        d.add(String(30, y + bar_h * 0.15, f"{star} star",
                     fontName=_font(), fontSize=7, textAnchor="end", fillColor=_DARK))
        track_x = 36
        track_w = width - 80
        d.add(Rect(track_x, y, track_w, bar_h,
                   fillColor=_BAR_TRACK, strokeColor=None))
        fill_w = (cnt / max_val) * track_w if max_val > 0 else 0
        fill_color = _GREEN if star >= 4 else (_AMBER if star == 3 else _RED)
        if fill_w > 0:
            d.add(Rect(track_x, y, fill_w, bar_h,
                       fillColor=fill_color, strokeColor=None))
        d.add(String(track_x + track_w + 5, y + bar_h * 0.15, str(cnt),
                     fontName=_font(), fontSize=7, textAnchor="start", fillColor=_MUTED))
    return d


def _draw_stacked_bar(filled, total, width, height=24, fill_color=_GREEN):
    """Horizontal progress bar showing filled portion of total."""
    d = Drawing(width, height)
    bar_y = (height - 10) / 2
    bar_h = 10
    d.add(Rect(0, bar_y, width, bar_h, fillColor=_BAR_TRACK, strokeColor=None))
    if total > 0 and filled > 0:
        fill_w = max((filled / total) * width, 2)
        d.add(Rect(0, bar_y, fill_w, bar_h, fillColor=fill_color, strokeColor=None))
    return d


# ═══════════════════════════════════════════════════════════════════════
#  Styled table helper
# ═══════════════════════════════════════════════════════════════════════

def _styled_table(data, col_widths=None, *, has_header=True, extra_cmds=None):
    t = Table(data, colWidths=col_widths, repeatRows=1 if has_header else 0)
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), _font()),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _GRID),
    ]
    if has_header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), _DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), _WHITE),
            ("FONTNAME", (0, 0), (-1, 0), _font_bold()),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ]
    for i in range(1 if has_header else 0, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), _STRIPE_BG))
    if extra_cmds:
        cmds.extend(extra_cmds)
    t.setStyle(TableStyle(cmds))
    return t


def _kv_pairs(pairs, width=None):
    """Lightweight key-value display without a dark header row."""
    w = width or _HALF_W
    data = [[k, str(v)] for k, v in pairs]
    t = Table(data, colWidths=[w * 0.6, w * 0.4])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), _font_bold()),
        ("FONTNAME", (1, 0), (1, -1), _font()),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), _DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _GRID),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════════════
#  Metric card grid (single 2x4 table with unified accent)
# ═══════════════════════════════════════════════════════════════════════

def _metric_grid(top_metrics, bot_metrics, styles):
    """Two-row metric card grid.  Each metric is (value_str, label_str)."""
    n = len(top_metrics)
    col_w = _CONTENT_W / n

    rows = []
    for metrics in (top_metrics, bot_metrics):
        val_row = [Paragraph(
            f'<font color="{_ACCENT.hexval()}">{_esc(v)}</font>',
            styles["MetricVal"],
        ) for v, _ in metrics]
        lbl_row = [Paragraph(l, styles["MetricLbl"]) for _, l in metrics]
        rows.extend([val_row, lbl_row])

    t = Table(rows, colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, _GRID),
        ("LINEABOVE", (0, 0), (-1, 0), 3, _ACCENT),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, _GRID),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("TOPPADDING", (0, 2), (-1, 2), 8),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 1),
        ("TOPPADDING", (0, 3), (-1, 3), 0),
        ("BOTTOMPADDING", (0, 3), (-1, 3), 8),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════════════
#  Two-column layout helper
# ═══════════════════════════════════════════════════════════════════════

def _two_col(left_elements, right_elements):
    """Wrap two lists of flowables into a side-by-side Table."""
    from reportlab.platypus import Flowable

    class _Wrapper(Flowable):
        def __init__(self, flowables, w):
            super().__init__()
            self._flowables = flowables
            self.width = w
            self.height = 0
            self._heights = []

        def wrap(self, aw, ah):
            self._heights = []
            h = 0
            for f in self._flowables:
                _, fh = f.wrap(self.width, ah)
                self._heights.append(fh)
                h += fh
            self.height = h
            return self.width, h

        def draw(self):
            y = self.height
            for f, fh in zip(self._flowables, self._heights):
                y -= fh
                f.drawOn(self.canv, 0, y)

    half = _HALF_W
    left_w = _Wrapper(left_elements, half)
    right_w = _Wrapper(right_elements, half)

    t = Table([[left_w, right_w]], colWidths=[half + 6, half + 6])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════════════
#  Section header helpers (consistent style for sections + appendices)
# ═══════════════════════════════════════════════════════════════════════

def _section_header(num, title, styles):
    """Numbered section header with left accent border and shaded background."""
    t = Table(
        [[Paragraph(f"{num}. {_esc(title)}", styles["Sec"])]],
        colWidths=[_CONTENT_W],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 4, _ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 10)])


def _appendix_header(letter, title, styles):
    """Appendix header — same accent style as numbered sections."""
    t = Table(
        [[Paragraph(f"Appendix {letter} &mdash; {_esc(title)}", styles["AppxTitle"])]],
        colWidths=[_CONTENT_W],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 4, _ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 10)])


# ═══════════════════════════════════════════════════════════════════════
#  Main generator
# ═══════════════════════════════════════════════════════════════════════

def generate_event_report_pdf(db: DbSession, event_id: int) -> bytes:
    from app.models.booking import Booking
    from app.models.coupon import Coupon
    from app.models.event import Event
    from app.models.event_addon import BookingAddOn, EventAddOn
    from app.models.event_break import EventBreak
    from app.models.event_session import EventSession
    from app.models.feedback import Feedback, SessionRating
    from app.models.feedback_template import FeedbackResponse
    from app.models.poll import Poll, PollOption, PollVote
    from app.models.seat import Seat
    from app.models.session import Session
    from app.models.session_feedback import SessionFeedback
    from app.models.user import User
    from app.models.waitlist import Waitlist

    _register_fonts()
    font = _font()
    font_b = _font_bold()

    event = db.query(Event).get(event_id)
    if not event:
        raise ValueError(f"Event {event_id} not found")

    # ── Styles ─────────────────────────────────────────────────────────
    S = {}
    S["Title"] = ParagraphStyle("T", fontName=font_b, fontSize=18, textColor=_DARK,
                                spaceAfter=2, leading=22)
    S["Sub"] = ParagraphStyle("Sub", fontName=font, fontSize=9, textColor=_MUTED,
                              spaceAfter=2)
    S["Stamp"] = ParagraphStyle("Stamp", fontName=font, fontSize=7, textColor=_MUTED,
                                spaceAfter=2)
    S["Summary"] = ParagraphStyle("Sum", fontName=font, fontSize=9, textColor=_DARK,
                                  leading=14, spaceAfter=2, spaceBefore=2)
    S["Sec"] = ParagraphStyle("Sec", fontName=font_b, fontSize=13, textColor=_DARK,
                              spaceBefore=0, spaceAfter=0, keepWithNext=True)
    S["AppxTitle"] = ParagraphStyle("Appx", fontName=font_b, fontSize=13,
                                    textColor=_DARK, spaceBefore=0, spaceAfter=0,
                                    keepWithNext=True)
    S["SubSec"] = ParagraphStyle("SSec", fontName=font_b, fontSize=9.5, textColor=_DARK,
                                 spaceBefore=6, spaceAfter=3, keepWithNext=True)
    S["Body"] = ParagraphStyle("Bod", fontName=font, fontSize=8.5, textColor=colors.black,
                               spaceAfter=3, leading=12)
    S["Small"] = ParagraphStyle("Sm", fontName=font, fontSize=7.5, textColor=_MUTED,
                                leading=10)
    S["MetricVal"] = ParagraphStyle("MV", fontName=font_b, fontSize=18, textColor=_DARK,
                                    alignment=TA_CENTER, spaceAfter=0)
    S["MetricLbl"] = ParagraphStyle("ML", fontName=font, fontSize=7, textColor=_MUTED,
                                    alignment=TA_CENTER)
    S["Comment"] = ParagraphStyle("Cmt", fontName=font, fontSize=7.5, textColor=_DARK,
                                  leading=11, leftIndent=4, spaceAfter=1)
    S["CoverTitle"] = ParagraphStyle("CT", fontName=font_b, fontSize=22, textColor=_WHITE,
                                     leading=28, spaceAfter=0)
    S["CoverSub"] = ParagraphStyle("CS", fontName=font, fontSize=9.5,
                                   textColor=colors.HexColor("#94a3b8"), spaceAfter=0)
    S["CoverStamp"] = ParagraphStyle("CSt", fontName=font, fontSize=7,
                                     textColor=colors.HexColor("#475569"), spaceAfter=0)
    S["TOC"] = ParagraphStyle("TOC", fontName=font, fontSize=8, textColor=_MUTED,
                              leading=12, spaceAfter=0)
    S["Desc"] = ParagraphStyle("Desc", fontName=font, fontSize=8.5, textColor=_DARK,
                               leading=13, spaceAfter=2)

    elements = []

    # ===================================================================
    # PAGE 1 — COVER + EXECUTIVE SUMMARY + METRICS
    # ===================================================================

    # Cover banner
    parts = []
    if event.start_date:
        d = event.start_date.strftime("%B %d, %Y")
        if event.end_date and event.end_date != event.start_date:
            d += f" \u2013 {event.end_date.strftime('%B %d, %Y')}"
        parts.append(d)
    if event.auditorium:
        venue = event.auditorium.name
        if event.college:
            venue += f", {event.college.name}"
        parts.append(venue)
    parts.append(f"Status: {(event.status or 'draft').title()}")
    details_str = "  |  ".join(parts)
    timestamp_str = f"Report generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"

    banner_data = [
        [Paragraph(_esc(event.name), S["CoverTitle"])],
        [Paragraph(_esc(details_str), S["CoverSub"])],
        [Paragraph(_esc(timestamp_str), S["CoverStamp"])],
    ]
    banner = Table(banner_data, colWidths=[_CONTENT_W])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _DARK),
        ("TOPPADDING", (0, 0), (0, 0), 20),
        ("BOTTOMPADDING", (0, 0), (0, 0), 6),
        ("TOPPADDING", (0, 1), (0, 1), 2),
        ("BOTTOMPADDING", (0, 1), (0, 1), 4),
        ("TOPPADDING", (0, 2), (0, 2), 2),
        ("BOTTOMPADDING", (0, 2), (0, 2), 16),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]))
    elements.append(banner)
    elements.append(Spacer(1, 14))

    # ── Collect key metrics ────────────────────────────────────────────
    paid_q = db.query(Booking).filter(
        Booking.event_id == event_id, Booking.payment_status == "paid",
        Booking.is_shared_ticket == False,
    )
    total_bookings = paid_q.count()
    total_revenue = float(db.query(func.coalesce(func.sum(Booking.amount_paid), 0)).filter(
        Booking.event_id == event_id, Booking.payment_status == "paid",
        Booking.is_shared_ticket == False,
    ).scalar() or 0)
    checked_in = paid_q.filter(Booking.checked_in == True).count()
    checkin_pct = round(checked_in / total_bookings * 100) if total_bookings else 0
    waitlist_count = db.query(Waitlist).filter(Waitlist.event_id == event_id).count()
    poll_count = db.query(Poll).filter(Poll.event_id == event_id).count()
    fb_count = (
        db.query(FeedbackResponse).filter(FeedbackResponse.event_id == event_id).count()
        + db.query(Feedback).filter(Feedback.event_id == event_id).count()
    )
    session_count = db.query(EventSession).filter(EventSession.event_id == event_id).count()

    fb_responses = db.query(FeedbackResponse).filter(
        FeedbackResponse.event_id == event_id).all()
    fb_legacy = db.query(Feedback).filter(Feedback.event_id == event_id).all()
    all_ratings = [fr.overall_rating for fr in fb_responses if fr.overall_rating]
    all_ratings += [fl.rating for fl in fb_legacy if fl.rating]
    avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    # ── Executive summary ──────────────────────────────────────────────
    summary = f"This event attracted <b>{total_bookings}</b> paid attendees, "
    summary += f"generating <b>{_cur(total_revenue)}</b> in revenue "
    summary += f"with a <b>{checkin_pct}%</b> check-in rate across "
    summary += f"<b>{session_count}</b> sessions. "
    if all_ratings:
        summary += (f"<b>{len(all_ratings)}</b> feedback responses "
                    f"averaged <b>{avg_rating:.1f}/5</b> stars. ")
    if poll_count:
        summary += (f"<b>{poll_count}</b> polls collected audience insights"
                    f" from attendees.")
    if waitlist_count:
        summary += f" <b>{waitlist_count}</b> people joined the waitlist."
    summary_table = Table(
        [[Paragraph(summary, S["Summary"])]],
        colWidths=[_CONTENT_W - 8],
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBEFORE", (0, 0), (0, -1), 3, _ACCENT),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))

    # ── Metric cards (unified 2x4 grid) ───────────────────────────────
    metrics_top = [
        (str(total_bookings), "BOOKINGS"),
        (_cur(total_revenue), "REVENUE"),
        (f"{checkin_pct}%", "CHECK-IN RATE"),
        (str(session_count), "SESSIONS"),
    ]
    metrics_bot = [
        (f"{checked_in}/{total_bookings}", "CHECKED IN"),
        (str(poll_count), "POLLS"),
        (str(fb_count), "FEEDBACK"),
        (str(waitlist_count), "WAITLIST"),
    ]
    elements.append(_metric_grid(metrics_top, metrics_bot, S))
    elements.append(Spacer(1, 14))

    # ── Event description (if available) ──────────────────────────────
    desc = getattr(event, "description", None)
    if desc and str(desc).strip():
        elements.append(Paragraph("About This Event", S["SubSec"]))
        desc_text = str(desc).strip()
        if len(desc_text) > 600:
            desc_text = desc_text[:600] + "..."
        elements.append(Paragraph(_esc(desc_text), S["Desc"]))
        elements.append(Spacer(1, 12))

    # ── Table of contents ─────────────────────────────────────────────
    toc_text = (
        '<b>Contents:</b> '
        '1. Revenue &amp; Sales &nbsp;|&nbsp; '
        '2. Attendance &amp; Demographics &nbsp;|&nbsp; '
        '3. Feedback &amp; Engagement &nbsp;|&nbsp; '
        '4. Poll Results<br/>'
        '<b>Appendices:</b> A. Event Schedule &nbsp;|&nbsp; B. Attendee Roster'
    )
    toc_box = Table([[Paragraph(toc_text, S["TOC"])]], colWidths=[_CONTENT_W - 8])
    toc_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(toc_box)

    # ===================================================================
    # PAGE 2 — 1. REVENUE & SALES
    # ===================================================================
    elements.append(PageBreak())
    elements.append(_section_header(1, "Revenue & Sales", S))

    seat_rev = (
        db.query(Seat.seat_type, func.count(Booking.id), func.sum(Booking.amount_paid))
        .join(Booking, Booking.seat_id == Seat.id)
        .filter(Booking.event_id == event_id, Booking.payment_status == "paid",
                Booking.is_shared_ticket == False)
        .group_by(Seat.seat_type).all()
    )
    status_counts = dict(
        db.query(Booking.payment_status, func.count(Booking.id))
        .filter(Booking.event_id == event_id, Booking.is_shared_ticket == False)
        .group_by(Booking.payment_status).all()
    )

    rev_left = []
    rev_right = []

    if seat_rev:
        seat_labels = [(s or "standard").replace("_", " ").title() for s, _, _ in seat_rev]
        seat_vals = [float(r or 0) for _, _, r in seat_rev]
        shared_h = max(len(seat_labels) * 28, 80)
        rev_left.append(Paragraph("Revenue by Seat Type", S["SubSec"]))
        rev_left.append(_draw_h_bars(seat_labels, seat_vals,
                                     width=_HALF_W, height=shared_h,
                                     bar_color=_ACCENT, fmt=_cur))

    if status_counts:
        s_labels = [(k or "unknown").title() for k in status_counts.keys()]
        s_vals = list(status_counts.values())
        total_s = sum(s_vals)
        pie_h = shared_h if seat_rev else 120
        pie = _draw_pie(s_labels, s_vals, width=_HALF_W, height=pie_h)
        rev_right.append(Paragraph("Booking Status", S["SubSec"]))
        if pie is not None:
            rev_right.append(pie)
        else:
            for lbl, val in zip(s_labels, s_vals):
                pct = f"{val / total_s * 100:.0f}%" if total_s else "0%"
                rev_right.append(Paragraph(
                    f'<b>{_esc(lbl)}</b>: {val} ({pct})', S["Body"],
                ))

    if rev_left or rev_right:
        elements.append(KeepTogether([_two_col(rev_left, rev_right)]))
        elements.append(Spacer(1, 8))

    # ── Daily booking trend ────────────────────────────────────────────
    try:
        daily_rows = (
            db.query(func.date_trunc("day", Booking.booked_at).label("d"),
                     func.count(Booking.id))
            .filter(Booking.event_id == event_id, Booking.payment_status == "paid",
                    Booking.is_shared_ticket == False)
            .group_by("d").order_by("d").all()
        )
    except Exception:
        daily_rows = []

    if daily_rows:
        d_labels = [d.strftime("%b %d") if hasattr(d, "strftime") else str(d)[:5]
                    for d, _ in daily_rows]
        d_vals = [cnt for _, cnt in daily_rows]
        elements.append(KeepTogether([
            Paragraph("Daily Booking Trend", S["SubSec"]),
            _draw_v_bars(d_labels, d_vals, width=_CONTENT_W, height=120,
                         bar_color=_ACCENT),
        ]))
        elements.append(Spacer(1, 8))

    # ── Coupons + Add-ons (side by side) ───────────────────────────────
    coupons = db.query(Coupon).filter(Coupon.event_id == event_id).all()
    all_addons = db.query(EventAddOn).filter(EventAddOn.event_id == event_id).all()

    fin_left = []
    fin_right = []

    if coupons:
        fin_left.append(Paragraph("Coupon Usage", S["SubSec"]))
        rows = [["Code", "Discount", "Used", "Max"]]
        for c in coupons:
            disc = f"{float(c.discount_pct):g}%" if c.discount_pct else _cur(c.discount_amount)
            rows.append([c.code, disc, str(c.used_count or 0), str(c.max_uses or "-")])
        fin_left.append(_styled_table(rows, col_widths=[65, 55, 35, 35]))

    if all_addons:
        fin_right.append(Paragraph("Add-On Sales", S["SubSec"]))
        rows = [["Add-On", "Price", "Qty", "Revenue"]]
        for addon in all_addons:
            qty = int(db.query(func.coalesce(func.sum(BookingAddOn.quantity), 0))
                      .filter(BookingAddOn.addon_id == addon.id).scalar() or 0)
            rev = float(addon.price or 0) * qty
            title = str(addon.title or "")
            rows.append([Paragraph(_esc(title), S["Small"]),
                         _cur(addon.price), str(qty), _cur(rev)])
        fin_right.append(_styled_table(rows, col_widths=[110, 40, 25, 45]))

    if fin_left or fin_right:
        elements.append(KeepTogether([_two_col(fin_left, fin_right)]))
        elements.append(Spacer(1, 6))

    # ===================================================================
    # PAGE 3 — 2. ATTENDANCE & DEMOGRAPHICS
    # ===================================================================
    elements.append(PageBreak())
    elements.append(_section_header(2, "Attendance & Demographics", S))

    booked_user_ids = [
        r[0] for r in
        db.query(Booking.user_id)
        .filter(Booking.event_id == event_id, Booking.payment_status == "paid",
                Booking.is_shared_ticket == False)
        .distinct().all()
    ]

    # ── Check-in progress + waitlist (text-based, not pie) ─────────────
    if total_bookings:
        ci_left = []
        ci_right = []

        ci_left.append(Paragraph("Check-in Progress", S["SubSec"]))
        not_ci = total_bookings - checked_in
        ci_left.append(Paragraph(
            f'<b>{checked_in}</b> of <b>{total_bookings}</b> '
            f'attendees checked in (<b>{checkin_pct}%</b>)',
            S["Body"],
        ))
        ci_left.append(Spacer(1, 4))
        ci_left.append(_draw_stacked_bar(checked_in, total_bookings,
                                         width=_HALF_W - 10, fill_color=_GREEN))
        ci_left.append(Spacer(1, 4))
        ci_left.append(Paragraph(
            f'<font color="{_GREEN.hexval()}">\u25a0</font> Checked in: {checked_in} '
            f'&nbsp;&nbsp; '
            f'<font color="{_BAR_TRACK.hexval()}">\u25a0</font> Remaining: {not_ci}',
            S["Small"],
        ))

        if waitlist_count:
            notified = db.query(Waitlist).filter(
                Waitlist.event_id == event_id, Waitlist.notified == True
            ).count()
            wl_uids = [r[0] for r in db.query(Waitlist.user_id).filter(
                Waitlist.event_id == event_id).all()]
            converted = 0
            if wl_uids:
                converted = db.query(Booking).filter(
                    Booking.event_id == event_id, Booking.payment_status == "paid",
                    Booking.user_id.in_(wl_uids),
                ).distinct(Booking.user_id).count()
            ci_right.append(Paragraph("Waitlist", S["SubSec"]))
            ci_right.append(_kv_pairs([
                ("Total on waitlist", waitlist_count),
                ("Notified", notified),
                ("Converted to booking", converted),
            ], width=_HALF_W))

        elements.append(KeepTogether([_two_col(ci_left, ci_right)]))
        elements.append(Spacer(1, 10))

    # ── Demographics ───────────────────────────────────────────────────
    if booked_user_ids:
        users = db.query(User).filter(User.id.in_(booked_user_ids)).all()

        college_counts = Counter(u.college for u in users if u.college).most_common(8)
        disc_counts = Counter(u.discipline for u in users if u.discipline).most_common(8)
        year_counts = Counter(u.year_of_study for u in users if u.year_of_study)

        if college_counts:
            c_labels, c_vals = zip(*college_counts)
            is_uniform = max(c_vals) - min(c_vals) <= 1
            if is_uniform:
                rows = [["Rank", "College", "Attendees"]]
                for i, (lbl, val) in enumerate(zip(c_labels, c_vals), 1):
                    rows.append([str(i), str(lbl), str(val)])
                elements.append(KeepTogether([
                    Paragraph("Top Colleges", S["SubSec"]),
                    _styled_table(rows, col_widths=[30, _CONTENT_W - 80, 50]),
                ]))
            else:
                elements.append(KeepTogether([
                    Paragraph("Top Colleges", S["SubSec"]),
                    _draw_h_bars(
                        c_labels, c_vals,
                        width=_CONTENT_W,
                        height=min(len(c_labels) * 22 + 8, 200),
                        bar_color=_ACCENT,
                    ),
                ]))
            elements.append(Spacer(1, 6))

        d_left = []
        d_right = []

        if disc_counts:
            dl, dv = zip(*disc_counts)
            shared_demo_h = min(max(len(dl), len(year_counts)) * 22 + 8, 200)
            d_left.append(Paragraph("Disciplines", S["SubSec"]))
            d_left.append(_draw_h_bars(dl, dv, width=_HALF_W,
                                       height=shared_demo_h,
                                       bar_color=_ACCENT))

        if year_counts:
            yr_labels = [f"Year {yr}" for yr in sorted(year_counts.keys())]
            yr_vals = [year_counts[yr] for yr in sorted(year_counts.keys())]
            demo_h = shared_demo_h if disc_counts else min(len(yr_labels) * 28 + 8, 130)
            d_right.append(Paragraph("Year of Study", S["SubSec"]))
            d_right.append(_draw_h_bars(yr_labels, yr_vals, width=_HALF_W,
                                        height=demo_h,
                                        bar_color=_ACCENT))

        if d_left or d_right:
            elements.append(KeepTogether([_two_col(d_left, d_right)]))

    # ===================================================================
    # PAGE 4 — 3. FEEDBACK & ENGAGEMENT
    # ===================================================================
    elements.append(PageBreak())
    elements.append(_section_header(3, "Feedback & Engagement", S))

    if fb_responses or fb_legacy:
        if all_ratings:
            elements.append(Paragraph(
                f'Overall Average: <b>{avg_rating:.1f}</b> / 5 &nbsp; '
                f'<font color="#6b7280">({len(all_ratings)} ratings)</font>',
                S["Body"],
            ))
            elements.append(Spacer(1, 4))

            dist = {s: 0 for s in range(1, 6)}
            for r in all_ratings:
                if 1 <= r <= 5:
                    dist[int(r)] = dist.get(int(r), 0) + 1

            session_fb = (
                db.query(Session.title, func.avg(SessionFeedback.rating),
                         func.count(SessionFeedback.id))
                .join(SessionFeedback, SessionFeedback.session_id == Session.id)
                .filter(SessionFeedback.event_id == event_id,
                        SessionFeedback.rating.isnot(None))
                .group_by(Session.id, Session.title).all()
            )
            if not session_fb:
                session_fb = (
                    db.query(Session.title, func.avg(SessionRating.rating),
                             func.count(SessionRating.id))
                    .join(SessionRating, SessionRating.session_id == Session.id)
                    .join(Feedback, Feedback.id == SessionRating.feedback_id)
                    .filter(Feedback.event_id == event_id)
                    .group_by(Session.id, Session.title).all()
                )

            n_fb_rows = max(5, len(session_fb)) if session_fb else 5
            shared_fb_h = min(n_fb_rows * 22 + 8, 200)

            rd_left = [Paragraph("Rating Distribution", S["SubSec"]),
                       _draw_rating_dist(dist, width=_HALF_W, height=shared_fb_h)]

            rd_right = []
            if session_fb:
                s_labels = [title for title, _, _ in session_fb]
                s_vals = [round(float(avg_val), 1) for _, avg_val, _ in session_fb]
                rd_right.append(Paragraph("Session Ratings (avg)", S["SubSec"]))
                rd_right.append(_draw_h_bars(
                    s_labels, s_vals, width=_HALF_W,
                    height=shared_fb_h,
                    bar_color=_ACCENT, fmt=lambda v: f"{v:.1f}",
                ))

            elements.append(KeepTogether([_two_col(rd_left, rd_right)]))
            elements.append(Spacer(1, 10))

        # Selected comments (deduplicated, in a styled box)
        _seen = set()
        comments = []
        for src in (fb_responses, fb_legacy):
            for item in src:
                c = getattr(item, "comment", None)
                if c and c.strip() and c.strip() not in _seen:
                    _seen.add(c.strip())
                    comments.append(c.strip())
        if comments:
            comment_els = [Paragraph("Selected Comments", S["SubSec"])]
            cmt_data = []
            for c in comments[:6]:
                txt = c[:200] + ("..." if len(c) > 200 else "")
                cmt_data.append([Paragraph(
                    f'&mdash; <i>"{_esc(txt)}"</i>', S["Comment"],
                )])
            cmt_cmds = [
                ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
                ("LINEBEFORE", (0, 0), (0, -1), 2, _ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            if len(comments) > 6:
                cmt_data.append([Paragraph(
                    f'<font color="#6b7280"><i>...and {len(comments) - 6} more</i></font>',
                    S["Small"],
                )])
                last = len(cmt_data) - 1
                cmt_cmds.append(("LINEABOVE", (0, last), (-1, last), 0.5, _GRID))
                cmt_cmds.append(("TOPPADDING", (0, last), (-1, last), 5))
            cmt_box = Table(cmt_data, colWidths=[_CONTENT_W - 12])
            cmt_box.setStyle(TableStyle(cmt_cmds))
            comment_els.append(cmt_box)
            elements.append(KeepTogether(comment_els))
    else:
        elements.append(Paragraph("No feedback has been submitted for this event.", S["Body"]))

    # ===================================================================
    # PAGE 5+ — 4. POLL RESULTS
    # ===================================================================
    polls = (
        db.query(Poll).filter(Poll.event_id == event_id)
        .order_by(Poll.created_at).all()
    )
    if polls:
        elements.append(PageBreak())
        elements.append(_section_header(4, "Poll Results", S))

        for poll in polls:
            status_lbl = "Active" if poll.is_active else "Closed"
            total_votes = db.query(PollVote).filter(PollVote.poll_id == poll.id).count()

            poll_els = [
                Paragraph(_esc(poll.question), S["SubSec"]),
                Paragraph(
                    f'{status_lbl} &mdash; {total_votes} vote{"s" if total_votes != 1 else ""}',
                    S["Small"],
                ),
            ]

            options = (
                db.query(PollOption).filter(PollOption.poll_id == poll.id)
                .order_by(PollOption.order).all()
            )

            if poll.poll_type in ("multiple_choice", "yes_no") and options:
                o_labels = [o.option_text for o in options]
                o_vals = []
                for o in options:
                    o_vals.append(db.query(PollVote).filter(
                        PollVote.poll_id == poll.id, PollVote.option_id == o.id
                    ).count())
                chart_h = max(len(o_labels) * 26, 50)
                poll_els.append(_draw_h_bars(
                    o_labels, o_vals,
                    width=_CONTENT_W * 0.75,
                    height=chart_h,
                    bar_color=_ACCENT,
                ))
            elif poll.poll_type == "rating":
                rating_votes = db.query(PollVote.rating_value).filter(
                    PollVote.poll_id == poll.id,
                    PollVote.rating_value.isnot(None),
                ).all()
                avg_v = db.query(func.avg(PollVote.rating_value)).filter(
                    PollVote.poll_id == poll.id,
                    PollVote.rating_value.isnot(None),
                ).scalar()
                avg_s = f"{float(avg_v):.1f}" if avg_v else "N/A"
                poll_els.append(Paragraph(
                    f'Average: <b>{avg_s}</b> / 5', S["Body"],
                ))
                if rating_votes:
                    rdist = Counter(int(rv[0]) for rv in rating_votes if rv[0])
                    r_labels = [f"{i} star" for i in range(5, 0, -1)]
                    r_vals = [rdist.get(i, 0) for i in range(5, 0, -1)]
                    poll_els.append(_draw_h_bars(
                        r_labels, r_vals, width=_CONTENT_W * 0.6,
                        height=110, bar_color=_ACCENT,
                    ))
            elif poll.poll_type == "text":
                sample = (
                    db.query(PollVote.text_answer)
                    .filter(PollVote.poll_id == poll.id,
                            PollVote.text_answer.isnot(None))
                    .limit(5).all()
                )
                quote_data = []
                for (ans,) in sample:
                    if ans and ans.strip():
                        quote_data.append([Paragraph(
                            f'&mdash; <i>"{_esc(ans.strip()[:150])}"</i>',
                            S["Comment"],
                        )])
                if quote_data:
                    qt = Table(quote_data, colWidths=[_CONTENT_W * 0.7])
                    qt.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
                        ("LINEBEFORE", (0, 0), (0, -1), 2, _ACCENT),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]))
                    poll_els.append(qt)
            else:
                poll_els.append(Paragraph(f"Responses: {total_votes}", S["Body"]))

            elements.append(KeepTogether(poll_els))
            elements.append(Spacer(1, 10))

    # ===================================================================
    # APPENDIX A — EVENT SCHEDULE
    # ===================================================================
    ev_sessions = (
        db.query(EventSession)
        .filter(EventSession.event_id == event_id)
        .order_by(EventSession.order, EventSession.start_time).all()
    )
    ev_breaks = (
        db.query(EventBreak)
        .filter(EventBreak.event_id == event_id)
        .order_by(EventBreak.order, EventBreak.start_time).all()
    )

    agenda = []
    for es in ev_sessions:
        agenda.append({
            "order": es.order or 0, "start": es.start_time,
            "type": "Session",
            "title": es.session.title if es.session else "-",
            "detail": es.speaker_name or "",
            "dur": f"{es.session.duration_minutes} min" if es.session and es.session.duration_minutes else "",
        })
    for brk in ev_breaks:
        agenda.append({
            "order": brk.order or 0, "start": brk.start_time,
            "type": "Break",
            "title": brk.title,
            "detail": "",
            "dur": f"{brk.duration_minutes} min" if brk.duration_minutes else "",
        })
    agenda.sort(key=lambda x: (x["order"], x["start"] or datetime.min))

    if agenda:
        elements.append(PageBreak())
        elements.append(_appendix_header("A", "Event Schedule", S))

        rows = [["#", "Time", "Title", "Speaker", "Duration"]]
        break_indices = []
        for i, item in enumerate(agenda, 1):
            t_str = item["start"].strftime("%I:%M %p") if item["start"] else ""
            if item["type"] == "Break":
                break_indices.append(i)
                rows.append([
                    str(i), t_str,
                    Paragraph(f'<i>{_esc(item["title"])}</i>', S["Small"]),
                    "", item["dur"],
                ])
            else:
                rows.append([
                    str(i), t_str,
                    Paragraph(_esc(item["title"]), S["Small"]),
                    Paragraph(_esc(item["detail"]), S["Small"]),
                    item["dur"],
                ])
        extra = []
        for bi in break_indices:
            extra.append(("BACKGROUND", (0, bi), (-1, bi), colors.HexColor("#fef3c7")))
            extra.append(("TEXTCOLOR", (0, bi), (-1, bi), _MUTED))
        elements.append(_styled_table(
            rows, col_widths=[20, 55, 220, 130, 40], extra_cmds=extra,
        ))

    # ===================================================================
    # APPENDIX B — ATTENDEE ROSTER
    # ===================================================================
    roster = (
        db.query(Booking, User, Seat)
        .join(User, User.id == Booking.user_id)
        .join(Seat, Seat.id == Booking.seat_id)
        .filter(Booking.event_id == event_id, Booking.payment_status == "paid",
                Booking.is_shared_ticket == False)
        .order_by(User.full_name, User.username).all()
    )
    if roster:
        elements.append(PageBreak())
        elements.append(_appendix_header("B", "Attendee Roster", S))
        elements.append(Paragraph(
            f'{len(roster)} paid attendee{"s" if len(roster) != 1 else ""}',
            S["Small"],
        ))
        elements.append(Spacer(1, 4))

        rows = [["#", "Name", "College", "Ref", "Seat", "Paid", "Attended"]]
        for i, (bk, usr, seat) in enumerate(roster, 1):
            name = usr.full_name or usr.username or "-"
            college = usr.college or "-"
            rows.append([
                str(i),
                Paragraph(_esc(str(name)), S["Small"]),
                Paragraph(_esc(str(college)), S["Small"]),
                bk.booking_ref or "",
                seat.label or "",
                _cur(bk.amount_paid),
                "Y" if bk.checked_in else "",
            ])
        elements.append(_styled_table(
            rows, col_widths=[20, 100, 110, 58, 32, 52, 30],
        ))

        # Closing summary
        elements.append(Spacer(1, 10))
        elements.append(Paragraph(
            f'<b>Total:</b> {len(roster)} attendees &nbsp;|&nbsp; '
            f'{checked_in} checked in ({checkin_pct}%)',
            S["Small"],
        ))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph('<i>End of report</i>', S["Small"]))

    # ===================================================================
    # BUILD PDF
    # ===================================================================
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN, bottomMargin=22 * mm,
    )

    event_name = event.name

    def _on_page(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(_MARGIN, 8 * mm, f"{event_name} - Event Report")
        canvas.drawRightString(_PAGE_W - _MARGIN, 8 * mm, f"Page {doc_obj.page}")
        canvas.setStrokeColor(_GRID)
        canvas.setLineWidth(0.3)
        canvas.line(_MARGIN, 12 * mm, _PAGE_W - _MARGIN, 12 * mm)
        canvas.restoreState()

    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
