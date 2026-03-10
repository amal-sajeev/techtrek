import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, html_body: str, *, invoice_pdf: bytes | None = None, invoice_filename: str = "invoice.pdf"):
    if not settings.smtp_host:
        logger.info("SMTP not configured — email to %s skipped: %s", to_email, subject)
        return

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    if invoice_pdf:
        attachment = MIMEApplication(invoice_pdf, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=invoice_filename)
        msg.attach(attachment)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.ehlo()
            if settings.smtp_port != 25:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from_email, to_email, msg.as_string())
        logger.info("Email sent to %s: %s", to_email, subject)
    except Exception:
        logger.exception("Failed to send email to %s", to_email)


def send_signup_confirmation(email: str, username: str):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#0e7490;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">Welcome to TechTrek!</h1>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 16px;">Hi <strong>{username}</strong>,</p>
          <p style="margin:0 0 16px;">Your TechTrek account has been created successfully. You can now browse upcoming sessions, book seats, and attend inspiring tech talks across India.</p>
          <p style="margin:0 0 24px;">
            <a href="https://techtrek.in/sessions" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;padding:10px 24px;border-radius:6px;font-weight:600;font-size:14px;">Browse Sessions &rarr;</a>
          </p>
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="margin:0;font-size:12px;color:#64748b;">You received this email because you registered on TechTrek.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    _send(email, "Welcome to TechTrek!", html)


def send_booking_confirmation(email: str, username: str, session_title: str, seat_label: str, ticket_id: str, booking_ref: str, invoice_pdf: bytes | None = None):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#0e7490;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">Booking Confirmed!</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#cffafe;">Your seat for {session_title} is secured.</p>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 20px;">Hi <strong>{username}</strong>,</p>
          <p style="margin:0 0 20px;">Your booking has been confirmed. Here are your details:</p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
            <tr style="background:#f8fafc;">
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;width:40%;">Seat</td>
              <td style="padding:12px 16px;color:#1e293b;border-bottom:1px solid #e2e8f0;">{seat_label}</td>
            </tr>
            <tr>
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;">Ticket ID</td>
              <td style="padding:12px 16px;color:#1e293b;border-bottom:1px solid #e2e8f0;font-family:monospace;font-size:13px;">{ticket_id}</td>
            </tr>
            <tr style="background:#f8fafc;">
              <td style="padding:12px 16px;font-weight:600;color:#334155;">Booking Ref</td>
              <td style="padding:12px 16px;color:#1e293b;font-family:monospace;font-size:13px;">{booking_ref}</td>
            </tr>
          </table>
          <p style="margin:0 0 24px;color:#475569;">Show your ticket ID or QR code at the venue for check-in.</p>
          <p style="margin:0 0 8px;">
            <a href="https://techtrek.in/booking/my" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;padding:10px 24px;border-radius:6px;font-weight:600;font-size:14px;">View My Bookings &rarr;</a>
          </p>
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="margin:0;font-size:12px;color:#64748b;">Cancellation policy: Rs. 100 fee, remainder refunded. Invoice attached.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    _send(email, f"Booking Confirmed — {session_title}", html, invoice_pdf=invoice_pdf, invoice_filename=f"invoice-{booking_ref}.pdf")


def send_cancellation_confirmation(email: str, username: str, session_title: str, seat_label: str, booking_ref: str, amount_paid: float, cancellation_fee: float, refund_amount: float):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#dc2626;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">Booking Cancelled</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#fecaca;">Your ticket for {session_title} has been cancelled.</p>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 20px;">Hi <strong>{username}</strong>,</p>
          <p style="margin:0 0 20px;">We've processed the cancellation of your booking. Here's a summary:</p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
            <tr style="background:#f8fafc;">
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;width:40%;">Seat</td>
              <td style="padding:12px 16px;color:#1e293b;border-bottom:1px solid #e2e8f0;">{seat_label}</td>
            </tr>
            <tr>
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;">Booking Ref</td>
              <td style="padding:12px 16px;color:#1e293b;border-bottom:1px solid #e2e8f0;font-family:monospace;font-size:13px;">{booking_ref}</td>
            </tr>
            <tr style="background:#f8fafc;">
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;">Amount Paid</td>
              <td style="padding:12px 16px;color:#1e293b;border-bottom:1px solid #e2e8f0;">&#8377;{amount_paid:.0f}</td>
            </tr>
            <tr>
              <td style="padding:12px 16px;font-weight:600;color:#334155;border-bottom:1px solid #e2e8f0;">Cancellation Fee</td>
              <td style="padding:12px 16px;color:#dc2626;border-bottom:1px solid #e2e8f0;">&#8377;{cancellation_fee:.0f}</td>
            </tr>
            <tr style="background:#f0fdf4;">
              <td style="padding:12px 16px;font-weight:600;color:#166534;">Refund Amount</td>
              <td style="padding:12px 16px;color:#166534;font-weight:700;font-size:16px;">&#8377;{refund_amount:.0f}</td>
            </tr>
          </table>
          <p style="margin:0 0 24px;color:#475569;">Your refund will be processed within 5-7 business days.</p>
          <p style="margin:0 0 8px;">
            <a href="https://techtrek.in/booking/my" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;padding:10px 24px;border-radius:6px;font-weight:600;font-size:14px;">View My Bookings &rarr;</a>
          </p>
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="margin:0;font-size:12px;color:#64748b;">If you did not request this cancellation, please contact us immediately.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    _send(email, f"Booking Cancelled — {session_title}", html)
