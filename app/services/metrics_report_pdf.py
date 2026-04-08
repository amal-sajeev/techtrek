"""Platform metrics PDF: A4, letter-style margins, ReportLab charts + tables + AI narrative."""

from __future__ import annotations

import io
import re
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.event_report import (
    _draw_h_bars,
    _draw_pie,
    _draw_rating_dist,
    _draw_v_bars,
    _esc,
    _register_fonts,
    _styled_table,
)

_PAGE_W, _PAGE_H = A4
_MARGIN = inch
_CONTENT_W = _PAGE_W - 2 * _MARGIN
_HALF_W = (_CONTENT_W - 12) / 2


def _md_paragraphs(md: str | None, style) -> list:
    if not md or not str(md).strip():
        return []
    out = []
    for block in str(md).split("\n\n"):
        block = block.strip()
        if not block:
            continue
        parts = re.split(r"(\*\*.+?\*\*)", block)
        chunks = []
        for p in parts:
            if p.startswith("**") and p.endswith("**") and len(p) > 4:
                chunks.append("<b>" + xml_escape(p[2:-2]) + "</b>")
            else:
                chunks.append(xml_escape(p))
        out.append(Paragraph("".join(chunks), style))
        out.append(Spacer(1, 6))
    return out


def _narrative_for_tab(narrative: dict | None, tab: str) -> tuple[str, str]:
    if not narrative:
        return "", ""
    for sec in narrative.get("sections") or []:
        if (sec.get("tab") or "").lower() == tab.lower():
            return sec.get("title") or tab.title(), sec.get("body_markdown") or ""
    return tab.title(), ""


def generate_platform_metrics_report_pdf(
    bundle: dict[str, Any],
    narrative: dict[str, Any] | None = None,
) -> bytes:
    _register_fonts()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "MRTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=12,
        textColor=colors.HexColor("#0a1628"),
        alignment=TA_CENTER,
    )
    body = ParagraphStyle(
        "MRBody",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        alignment=TA_LEFT,
    )
    h2 = ParagraphStyle(
        "MRH2",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#0369a1"),
    )
    small = ParagraphStyle(
        "MRSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#4b5563"),
    )

    elems: list = []

    elems.append(Spacer(1, 36))
    rk = bundle.get("report_kind") or "quarterly_brief"
    if rk == "focused_report":
        doc_title = "TechTrek — Focused metrics report"
        scope_subtitle = (
            "Analysis and figures below are scoped to the filters listed. "
            "They are not platform-wide totals unless the filter lines say so."
        )
    else:
        doc_title = "TechTrek — Platform quarterly brief"
        scope_subtitle = (
            "Executive-style snapshot using **all historical data** in the product to date "
            "(full platform; not limited to one calendar quarter). "
            "Apply filters on the Metrics page for a narrower slice."
        )
    elems.append(Paragraph(_esc(doc_title), title))
    elems.append(Spacer(1, 8))
    elems.append(Paragraph(_esc(f"Generated: {bundle.get('generated_at', '')}"), small))
    elems.append(Spacer(1, 6))
    elems.extend(_md_paragraphs(scope_subtitle, small))
    elems.append(Spacer(1, 16))
    for line in bundle.get("filter_summary") or []:
        elems.append(Paragraph(_esc(str(line)), body))
    elems.append(Spacer(1, 20))

    kpi_rows = [
        ["Total users", f"{bundle.get('total_users', 0):,}"],
        ["Total revenue (INR)", f"{float(bundle.get('total_revenue') or 0):,.0f}"],
        ["Paid bookings", f"{bundle.get('total_bookings', 0):,}"],
        ["Check-in rate", f"{bundle.get('checkin_rate', 0)}%"],
        ["Avg rating", f"{bundle.get('avg_rating', 0)}/5"],
    ]
    kt = Table(kpi_rows, colWidths=[_CONTENT_W * 0.55, _CONTENT_W * 0.45])
    kt.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9fafb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elems.append(kt)
    elems.append(Spacer(1, 8))
    src = (narrative or {}).get("narrative_source") if narrative else None
    if src == "openai":
        note = "Commentary: AI-assisted narrative, checked against a numeric digest of this bundle."
    elif src == "fallback":
        note = (
            "Commentary: auto-generated from the metrics below (OpenAI unavailable, failed, or returned no usable text)."
        )
    elif not narrative:
        note = (
            "Note: No narrative object was supplied. Charts and tables reflect live metrics only."
        )
    else:
        note = "Charts and tables reflect live metrics; see section prose for interpretation."
    elems.append(Paragraph(_esc(note), small))
    diag = (narrative or {}).get("ai_diagnostic")
    if diag:
        elems.append(Spacer(1, 4))
        elems.append(
            Paragraph(
                _esc(f"AI diagnostic (check server logs for full detail): {diag}"),
                small,
            )
        )
    elems.append(PageBreak())

    exec_md = (narrative or {}).get("executive_summary") if narrative else None
    if exec_md:
        elems.append(Paragraph("<b>Executive summary</b>", h2))
        elems.extend(_md_paragraphs(exec_md, body))
        elems.append(Spacer(1, 12))

    fig_n = [0]

    def fig_num():
        fig_n[0] += 1
        return fig_n[0]

    # --- Overview ---
    t_title, t_body = _narrative_for_tab(narrative, "overview")
    elems.append(Paragraph(_esc(f"1. {t_title or 'Overview'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))

    bt = bundle.get("booking_trend") or []
    if bt:
        lbls = [x.get("label", "")[:12] for x in bt[-18:]]
        vals = [int(x.get("count", 0)) for x in bt[-18:]]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Bookings over time"), small))
        elems.append(
            _draw_v_bars(lbls, vals, width=_CONTENT_W, height=120, bar_color=colors.HexColor("#00a3cc"))
        )
        elems.append(Spacer(1, 6))

    rt = bundle.get("revenue_trend") or []
    if rt:
        lbls = [x.get("label", "")[:12] for x in rt[-18:]]
        vals = [float(x.get("value", 0)) for x in rt[-18:]]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Revenue over time"), small))
        elems.append(
            _draw_v_bars(lbls, vals, width=_CONTENT_W, height=120, bar_color=colors.HexColor("#059669"))
        )
        elems.append(Spacer(1, 6))

    bs = bundle.get("booking_statuses") or {}
    if bs:
        labels = [str(k).title() for k in bs.keys()]
        values = [int(v) for v in bs.values()]
        pie = _draw_pie(labels, values, width=_HALF_W, height=140)
        if pie:
            elems.append(Paragraph(_esc(f"Figure {fig_num()} — Booking payment status"), small))
            elems.append(pie)
            elems.append(Spacer(1, 6))

    rd = bundle.get("rating_dist") or {}
    if rd:
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Rating distribution"), small))
        elems.append(_draw_rating_dist({int(k): v for k, v in rd.items()}, width=_CONTENT_W, height=100))
        elems.append(Spacer(1, 8))

    elems.append(PageBreak())

    # --- Users ---
    t_title, t_body = _narrative_for_tab(narrative, "users")
    elems.append(Paragraph(_esc(f"2. {t_title or 'Users'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))

    reg = bundle.get("reg_trend") or []
    if reg:
        lbls = [x.get("label", "")[:12] for x in reg[-18:]]
        vals = [int(x.get("count", 0)) for x in reg[-18:]]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — User registrations"), small))
        elems.append(_draw_v_bars(lbls, vals, width=_CONTENT_W, height=110))
        elems.append(Spacer(1, 6))

    yos = bundle.get("yos_dist") or []
    if yos:
        lbls = [f"Y{r.get('year')}" for r in yos]
        vals = [int(r.get("count", 0)) for r in yos]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Year of study"), small))
        elems.append(_draw_v_bars(lbls, vals, width=_CONTENT_W, height=100))
        elems.append(Spacer(1, 6))

    ac = bundle.get("auth_counts") or {}
    if ac:
        pie = _draw_pie(["OAuth", "Password"], [int(ac.get("oauth", 0)), int(ac.get("password", 0))], _HALF_W, 120)
        if pie:
            elems.append(Paragraph(_esc(f"Figure {fig_num()} — Auth method"), small))
            elems.append(pie)
            elems.append(Spacer(1, 6))

    rc = bundle.get("role_counts") or {}
    rows = [["Role", "Count"], ["Active", rc.get("active", 0)], ["Admins", rc.get("admins", 0)],
            ["Supervisors", rc.get("supervisors", 0)], ["Deleted accounts", rc.get("deleted", 0)]]
    elems.append(_styled_table(rows, col_widths=[200, 80]))
    elems.append(PageBreak())

    # --- Events ---
    t_title, t_body = _narrative_for_tab(narrative, "events")
    elems.append(Paragraph(_esc(f"3. {t_title or 'Events'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))

    spe = bundle.get("sessions_per_event") or []
    if spe:
        top = spe[:12]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Sessions per event (top {len(top)})"), small))
        elems.append(
            _draw_h_bars(
                [x.get("name", "")[:28] for x in top],
                [int(x.get("count", 0)) for x in top],
                width=_CONTENT_W,
                height=min(200, 24 * len(top)),
            )
        )
        elems.append(Spacer(1, 8))

    ebc = bundle.get("events_by_city") or []
    if ebc:
        rows = [["City", "Events"]] + [[x.get("name", ""), x.get("count", 0)] for x in ebc]
        elems.append(_styled_table(rows, col_widths=[260, 60]))

    teb = bundle.get("top_events_by_bookings") or []
    if teb:
        rows = [["#", "Event", "Paid bookings"]] + [
            [str(i + 1), x.get("name", ""), x.get("count", 0)] for i, x in enumerate(teb)
        ]
        elems.append(Spacer(1, 6))
        elems.append(_styled_table(rows, col_widths=[28, 240, 72]))

    tew = bundle.get("top_events_by_waitlist") or []
    if tew:
        rows = [["#", "Event", "Waitlist"]] + [
            [str(i + 1), x.get("name", ""), x.get("count", 0)] for i, x in enumerate(tew)
        ]
        elems.append(Spacer(1, 6))
        elems.append(_styled_table(rows, col_widths=[28, 240, 72]))

    elems.append(PageBreak())

    # --- Revenue ---
    t_title, t_body = _narrative_for_tab(narrative, "revenue")
    elems.append(Paragraph(_esc(f"4. {t_title or 'Revenue'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))

    if bundle.get("single_event_selected"):
        sd = bundle.get("seat_distribution") or {}
        segs = sd.get("segments") or []
        labels = [s.get("label", "") for s in segs]
        values = [int(s.get("count", 0)) for s in segs]
        if int(sd.get("unsold") or 0) > 0:
            labels.append("Unsold")
            values.append(int(sd["unsold"]))
        if values and sum(values) > 0:
            pie = _draw_pie(labels, values, _CONTENT_W * 0.9, 130)
            if pie:
                elems.append(Paragraph(_esc(f"Figure {fig_num()} — Seat distribution"), small))
                elems.append(pie)
                elems.append(Spacer(1, 6))
    else:
        rt2 = bundle.get("revenue_trend") or []
        if rt2:
            lbls = [x.get("label", "")[:12] for x in rt2[-18:]]
            vals = [float(x.get("value", 0)) for x in rt2[-18:]]
            elems.append(Paragraph(_esc(f"Figure {fig_num()} — Revenue trend"), small))
            elems.append(_draw_v_bars(lbls, vals, width=_CONTENT_W, height=110, bar_color=colors.HexColor("#059669")))
            elems.append(Spacer(1, 6))

    rbe = bundle.get("revenue_by_event") or []
    if rbe:
        rows = [["#", "Event", "Revenue (INR)", "Bookings"]] + [
            [str(i + 1), x.get("name", ""), f"{float(x.get('revenue', 0)):,.0f}", x.get("bookings", 0)]
            for i, x in enumerate(rbe)
        ]
        elems.append(_styled_table(rows, col_widths=[24, 200, 72, 52]))

    rbs = bundle.get("revenue_by_seat_type") or []
    if rbs:
        rows = [["Seat type", "Revenue (INR)", "Bookings"]] + [
            [x.get("display_label", x.get("type", "")), f"{float(x.get('revenue', 0)):,.0f}", x.get("count", 0)]
            for x in rbs
        ]
        elems.append(Spacer(1, 6))
        elems.append(_styled_table(rows, col_widths=[160, 80, 60]))

    rs = bundle.get("refund_stats") or {}
    elems.append(Spacer(1, 8))
    elems.append(
        _styled_table(
            [
                ["Refunds", "Value"],
                ["Refund count", rs.get("count", 0)],
                ["Refund total (INR)", f"{float(rs.get('total', 0)):,.0f}"],
                ["Cancel fees (INR)", f"{float(rs.get('cancel_fees', 0)):,.0f}"],
                ["Shared tickets", rs.get("shared", 0)],
            ],
            col_widths=[200, 120],
        )
    )
    elems.append(PageBreak())

    # --- Feedback ---
    t_title, t_body = _narrative_for_tab(narrative, "feedback")
    elems.append(Paragraph(_esc(f"5. {t_title or 'Feedback'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))
    fs = bundle.get("feedback_stats") or {}
    elems.append(
        _styled_table(
            [
                ["Metric", "Value"],
                ["Submitted", fs.get("submitted", 0)],
                ["Response rate %", fs.get("rate", 0)],
                ["With comments", fs.get("with_comments", 0)],
                ["Featured", fs.get("featured", 0)],
            ],
            col_widths=[200, 100],
        )
    )
    bsess = bundle.get("best_sessions") or []
    if bsess:
        rows = [["Session", "Avg", "N"]] + [[x.get("title", "")[:40], x.get("avg", ""), x.get("count", "")] for x in bsess]
        elems.append(Spacer(1, 6))
        elems.append(_styled_table(rows, col_widths=[220, 40, 40]))
    elems.append(PageBreak())

    # --- Sessions ---
    t_title, t_body = _narrative_for_tab(narrative, "sessions")
    elems.append(Paragraph(_esc(f"6. {t_title or 'Sessions & operations'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))
    ch = bundle.get("checkin_hours") or []
    if ch:
        lbls = [str(x.get("hour", "")) for x in ch]
        vals = [int(x.get("count", 0)) for x in ch]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Check-ins by hour"), small))
        elems.append(_draw_v_bars(lbls, vals, width=_CONTENT_W, height=100))
        elems.append(Spacer(1, 6))
    vs = bundle.get("venue_stats") or {}
    elems.append(
        _styled_table(
            [
                ["Venue", "Value"],
                ["Total seats", vs.get("total_seats", 0)],
                ["Bookable", vs.get("bookable", 0)],
                ["Booked (distinct)", vs.get("booked", 0)],
                ["Occupancy %", vs.get("occupancy", 0)],
            ],
            col_widths=[200, 100],
        )
    )
    elems.append(PageBreak())

    # --- System ---
    t_title, t_body = _narrative_for_tab(narrative, "system")
    elems.append(Paragraph(_esc(f"7. {t_title or 'System'}"), h2))
    elems.extend(_md_paragraphs(t_body, body))
    st = bundle.get("subscriber_trend") or []
    if st:
        lbls = [x.get("label", "")[:12] for x in st[-18:]]
        vals = [int(x.get("count", 0)) for x in st[-18:]]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Newsletter subscribers"), small))
        elems.append(_draw_v_bars(lbls, vals, width=_CONTENT_W, height=100))
        elems.append(Spacer(1, 6))
    abc = bundle.get("activity_by_cat") or []
    if abc:
        lbls = [str(x.get("category", ""))[:20] for x in abc]
        vals = [int(x.get("count", 0)) for x in abc]
        elems.append(Paragraph(_esc(f"Figure {fig_num()} — Activity log categories"), small))
        elems.append(_draw_h_bars(lbls, vals, width=_CONTENT_W, height=min(180, 20 * len(abc))))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
    )

    def _footer(c, doc_obj):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#6b7280"))
        c.drawString(_MARGIN, 0.45 * inch, "TechTrek — Platform metrics (confidential)")
        c.drawRightString(_PAGE_W - _MARGIN, 0.45 * inch, f"Page {doc_obj.page}")
        c.restoreState()

    doc.build(elems, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
