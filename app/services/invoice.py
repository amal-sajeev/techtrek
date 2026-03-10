import io
import uuid
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

from app.config import settings
from app.utils import now_ist


def _generate_invoice_number() -> str:
    now = now_ist()
    rand = uuid.uuid4().hex[:6].upper()
    return f"INV-{now.strftime('%Y%m%d')}-{rand}"


def generate_invoice_pdf(bookings, user, lecture, auditorium, seats) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Header", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#0a1628"), spaceAfter=2))
    styles.add(ParagraphStyle("SubHeader", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle("SectionTitle", parent=styles["Heading3"], fontSize=11, textColor=colors.HexColor("#0a1628"), spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#888888")))
    styles.add(ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER))
    styles.add(ParagraphStyle("Bold", parent=styles["Normal"], fontName="Helvetica-Bold"))

    elements = []
    gst_rate = settings.gst_rate

    # --- Header ---
    company_info = (
        f"<b>{settings.company_name}</b><br/>"
        f"{settings.company_address}<br/>"
        f"GSTIN: {settings.company_gstin} &nbsp;|&nbsp; PAN: {settings.company_pan}<br/>"
        f"Email: {settings.company_email} &nbsp;|&nbsp; Phone: {settings.company_phone}"
    )

    inv_number = bookings[0].invoice_number or "—"
    inv_date = bookings[0].booked_at.strftime("%d %b %Y, %I:%M %p") if bookings[0].booked_at else now_ist().strftime("%d %b %Y, %I:%M %p")

    header_data = [
        [Paragraph(company_info, styles["SubHeader"]),
         Paragraph(f"<b>TAX INVOICE</b><br/>Invoice #: {inv_number}<br/>Date: {inv_date}", ParagraphStyle("RightSub", parent=styles["SubHeader"], alignment=TA_RIGHT))],
    ]
    header_table = Table(header_data, colWidths=[doc.width * 0.6, doc.width * 0.4])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#00d4ff")),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8 * mm))

    # --- Bill To / Event Details ---
    bill_to = (
        f"<b>Bill To:</b><br/>"
        f"{user.full_name or user.username}<br/>"
        f"{user.email}"
    )
    if user.college:
        bill_to += f"<br/>{user.college}"

    event_info = (
        f"<b>Event Details:</b><br/>"
        f"{lecture.title}<br/>"
        f"Speaker: {lecture.speaker}<br/>"
        f"{lecture.start_time.strftime('%A, %d %b %Y at %I:%M %p')}<br/>"
        f"Venue: {auditorium.name}, {auditorium.location}"
    )

    info_data = [
        [Paragraph(bill_to, styles["Normal"]), Paragraph(event_info, styles["Normal"])],
    ]
    info_table = Table(info_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(info_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Line Items ---
    elements.append(Paragraph("Line Items", styles["SectionTitle"]))

    header_row = ["#", "Seat", "Type", "Base Price (₹)", f"GST {gst_rate:.0f}% (₹)", "Total (₹)"]
    table_data = [header_row]

    subtotal = 0.0
    gst_total = 0.0

    for i, (b, seat) in enumerate(zip(bookings, seats)):
        amount = float(b.amount_paid or 0)
        base_price = amount / (1 + gst_rate / 100)
        gst_amount = amount - base_price
        subtotal += base_price
        gst_total += gst_amount

        table_data.append([
            str(i + 1),
            seat.label,
            seat.seat_type.title(),
            f"{base_price:,.2f}",
            f"{gst_amount:,.2f}",
            f"{amount:,.2f}",
        ])

    grand_total = subtotal + gst_total

    table_data.append(["", "", "", Paragraph("<b>Subtotal</b>", styles["Right"]), "", f"{subtotal:,.2f}"])
    table_data.append(["", "", "", Paragraph(f"<b>GST ({gst_rate:.0f}%)</b>", styles["Right"]), "", f"{gst_total:,.2f}"])
    table_data.append(["", "", "", Paragraph("<b>Grand Total</b>", styles["Right"]), "", Paragraph(f"<b>₹{grand_total:,.2f}</b>", styles["Bold"])])

    col_widths = [doc.width * w for w in [0.05, 0.15, 0.15, 0.25, 0.2, 0.2]]
    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0a1628")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -4), 0.5, colors.HexColor("#cccccc")),
        ("LINEABOVE", (0, -3), (-1, -3), 1, colors.HexColor("#cccccc")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#0a1628")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 6 * mm))

    # --- Refund section (if any bookings are refunded) ---
    refunded = [b for b in bookings if b.payment_status == "refunded" and b.refund_amount]
    if refunded:
        elements.append(Paragraph("Refund Details", styles["SectionTitle"]))
        refund_data = [["Seat", "Cancellation Fee (₹)", "Refund Amount (₹)", "Status"]]
        for b in refunded:
            seat = next((s for s, bk in zip(seats, bookings) if bk.id == b.id), None)
            refund_data.append([
                seat.label if seat else "—",
                f"{float(b.cancellation_fee or 0):,.2f}",
                f"{float(b.refund_amount or 0):,.2f}",
                "Refunded",
            ])
        r_widths = [doc.width * w for w in [0.25, 0.25, 0.25, 0.25]]
        refund_table = Table(refund_data, colWidths=r_widths, repeatRows=1)
        refund_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f59e0b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(refund_table)
        elements.append(Spacer(1, 6 * mm))

    # --- Payment Details ---
    elements.append(Paragraph("Payment Details", styles["SectionTitle"]))
    b0 = bookings[0]
    payment_rows = [
        ["Payment Method", "Razorpay"],
        ["Booking Reference", b0.booking_ref or "—"],
    ]
    if b0.razorpay_order_id:
        payment_rows.append(["Razorpay Order ID", b0.razorpay_order_id])
    if b0.razorpay_payment_id:
        payment_rows.append(["Razorpay Payment ID", b0.razorpay_payment_id])
    if b0.booked_at:
        payment_rows.append(["Payment Date", b0.booked_at.strftime("%d %b %Y, %I:%M %p IST")])
    payment_rows.append(["Payment Status", b0.payment_status.title()])

    pay_table = Table(payment_rows, colWidths=[doc.width * 0.35, doc.width * 0.65])
    pay_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#333333")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#eeeeee")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(pay_table)
    elements.append(Spacer(1, 10 * mm))

    # --- Footer ---
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph("This is a computer-generated invoice and does not require a signature.", styles["Small"]))
    elements.append(Paragraph(f"© {now_ist().year} {settings.company_name}. All rights reserved.", styles["Small"]))

    doc.build(elements)
    return buf.getvalue()
