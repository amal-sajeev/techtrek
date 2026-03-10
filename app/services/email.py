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
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;padding:2rem;">
      <h2 style="color:#00d4ff;">Welcome to TechTrek!</h2>
      <p>Hi <strong>{username}</strong>,</p>
      <p>Your TechTrek account has been created successfully. You can now browse
      upcoming sessions, book seats, and attend inspiring tech talks across India.</p>
      <p><a href="https://techtrek.in/sessions" style="color:#00d4ff;">Browse Sessions &rarr;</a></p>
      <hr style="border:none;border-top:1px solid #eee;margin:1.5rem 0;">
      <p style="font-size:.8rem;color:#888;">You received this email because you registered on TechTrek.</p>
    </div>
    """
    _send(email, "Welcome to TechTrek!", html)


def send_booking_confirmation(email: str, username: str, session_title: str, seat_label: str, ticket_id: str, booking_ref: str, invoice_pdf: bytes | None = None):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;padding:2rem;">
      <h2 style="color:#00d4ff;">Booking Confirmed!</h2>
      <p>Hi <strong>{username}</strong>,</p>
      <p>Your booking for <strong>{session_title}</strong> has been confirmed.</p>
      <table style="width:100%;border-collapse:collapse;margin:1rem 0;">
        <tr><td style="padding:.5rem;border-bottom:1px solid #eee;"><strong>Seat</strong></td><td style="padding:.5rem;border-bottom:1px solid #eee;">{seat_label}</td></tr>
        <tr><td style="padding:.5rem;border-bottom:1px solid #eee;"><strong>Ticket ID</strong></td><td style="padding:.5rem;border-bottom:1px solid #eee;">{ticket_id}</td></tr>
        <tr><td style="padding:.5rem;"><strong>Booking Ref</strong></td><td style="padding:.5rem;">{booking_ref}</td></tr>
      </table>
      <p>Show your ticket ID or QR code at the venue for check-in.</p>
      <p><a href="https://techtrek.in/booking/my" style="color:#00d4ff;">View My Bookings &rarr;</a></p>
      <hr style="border:none;border-top:1px solid #eee;margin:1.5rem 0;">
      <p style="font-size:.8rem;color:#888;">Cancellation policy: Rs.100 fee, remainder refunded.</p>
    </div>
    """
    _send(email, f"Booking Confirmed — {session_title}", html, invoice_pdf=invoice_pdf, invoice_filename=f"invoice-{booking_ref}.pdf")
