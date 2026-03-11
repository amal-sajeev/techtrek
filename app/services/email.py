import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, html_body: str, *, invoice_pdf: bytes | None = None, invoice_filename: str = "invoice.pdf") -> bool:
    """Returns True if the email was sent successfully, False otherwise."""
    if not settings.smtp_host:
        logger.info("SMTP not configured — email to %s skipped: %s", to_email, subject)
        return False

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
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


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


def send_group_booking_confirmation(email: str, username: str, session_title: str, tickets: list, total_amount: float, invoice_pdf: bytes | None = None):
    """tickets: list of dicts with keys seat_label, ticket_id, booking_ref, amount"""
    count = len(tickets)
    ticket_rows = ""
    for i, t in enumerate(tickets):
        bg = "background:#f8fafc;" if i % 2 == 0 else ""
        ticket_rows += f"""<tr style="{bg}">
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;">{t['seat_label']}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;font-family:monospace;font-size:12px;">{t['ticket_id']}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;font-family:monospace;font-size:12px;">{t['booking_ref']}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;text-align:right;">&#8377;{t['amount']:.0f}</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#0e7490;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">{count} Tickets Confirmed!</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#cffafe;">Your seats for {session_title} are secured.</p>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 20px;">Hi <strong>{username}</strong>,</p>
          <p style="margin:0 0 20px;">Your group booking of {count} ticket(s) has been confirmed. Here are your details:</p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 4px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
            <tr style="background:#ecfdf5;">
              <td style="padding:10px 16px;font-weight:600;color:#065f46;border-bottom:1px solid #e2e8f0;">Seat</td>
              <td style="padding:10px 16px;font-weight:600;color:#065f46;border-bottom:1px solid #e2e8f0;">Ticket ID</td>
              <td style="padding:10px 16px;font-weight:600;color:#065f46;border-bottom:1px solid #e2e8f0;">Ref</td>
              <td style="padding:10px 16px;font-weight:600;color:#065f46;border-bottom:1px solid #e2e8f0;text-align:right;">Amount</td>
            </tr>
            {ticket_rows}
            <tr style="background:#ecfdf5;">
              <td colspan="3" style="padding:12px 16px;font-weight:700;color:#065f46;">Total</td>
              <td style="padding:12px 16px;font-weight:700;color:#065f46;text-align:right;font-size:16px;">&#8377;{total_amount:.0f}</td>
            </tr>
          </table>
          <p style="margin:16px 0 24px;color:#475569;">Show your ticket IDs or QR codes at the venue for check-in.</p>
          <p style="margin:0 0 8px;">
            <a href="https://techtrek.in/booking/my" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;padding:10px 24px;border-radius:6px;font-weight:600;font-size:14px;">View My Bookings &rarr;</a>
          </p>
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="margin:0;font-size:12px;color:#64748b;">Cancellation policy: Rs. 100 fee per ticket, remainder refunded. Invoice attached.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    ref = tickets[0]['booking_ref'] if tickets else "group"
    _send(email, f"{count} Tickets Confirmed — {session_title}", html, invoice_pdf=invoice_pdf, invoice_filename=f"invoice-{ref}.pdf")


def send_cancellation_confirmation(email: str, username: str, session_title: str, seat_label: str, booking_ref: str, amount_paid: float, cancellation_fee: float, refund_amount: float, invoice_pdf: bytes | None = None):
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
    _send(email, f"Booking Cancelled — {session_title}", html, invoice_pdf=invoice_pdf, invoice_filename=f"credit-note-{booking_ref}.pdf")


def send_group_cancellation_confirmation(email: str, username: str, session_title: str, items: list, total_fees: float, total_refund: float, invoice_pdf: bytes | None = None):
    seat_rows = ""
    for item in items:
        seat_rows += f"""<tr>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;">{item['seat_label']}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#1e293b;text-align:right;">&#8377;{item['amount_paid']:.0f}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#dc2626;text-align:right;">&#8377;{item['fee']:.0f}</td>
              <td style="padding:10px 16px;border-bottom:1px solid #e2e8f0;color:#166534;text-align:right;font-weight:600;">&#8377;{item['refund']:.0f}</td>
            </tr>"""

    total_paid = sum(i['amount_paid'] for i in items)
    count = len(items)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#dc2626;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">{count} Tickets Cancelled</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#fecaca;">Group cancellation for {session_title}</p>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 20px;">Hi <strong>{username}</strong>,</p>
          <p style="margin:0 0 20px;">Your group booking of {count} ticket(s) has been cancelled. Here's the breakdown:</p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
            <tr style="background:#fef2f2;">
              <td style="padding:10px 16px;font-weight:600;color:#991b1b;border-bottom:1px solid #e2e8f0;">Seat</td>
              <td style="padding:10px 16px;font-weight:600;color:#991b1b;border-bottom:1px solid #e2e8f0;text-align:right;">Paid</td>
              <td style="padding:10px 16px;font-weight:600;color:#991b1b;border-bottom:1px solid #e2e8f0;text-align:right;">Fee</td>
              <td style="padding:10px 16px;font-weight:600;color:#991b1b;border-bottom:1px solid #e2e8f0;text-align:right;">Refund</td>
            </tr>
            {seat_rows}
            <tr style="background:#f0fdf4;">
              <td style="padding:12px 16px;font-weight:700;color:#166534;">Total</td>
              <td style="padding:12px 16px;font-weight:600;color:#1e293b;text-align:right;">&#8377;{total_paid:.0f}</td>
              <td style="padding:12px 16px;font-weight:600;color:#dc2626;text-align:right;">&#8377;{total_fees:.0f}</td>
              <td style="padding:12px 16px;font-weight:700;color:#166534;text-align:right;font-size:16px;">&#8377;{total_refund:.0f}</td>
            </tr>
          </table>
          <p style="margin:0 0 24px;color:#475569;">Your refund of <strong>&#8377;{total_refund:.0f}</strong> will be processed within 5-7 business days.</p>
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
    _send(email, f"{count} Tickets Cancelled — {session_title}", html, invoice_pdf=invoice_pdf, invoice_filename="credit-note.pdf")


def send_speaker_invite(email: str, speaker_name: str, invite_url: str):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:32px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
        <tr><td style="background:#0e7490;padding:28px 32px;">
          <h1 style="margin:0;font-size:22px;color:#ffffff;font-weight:700;">You're Invited to TechTrek!</h1>
          <p style="margin:6px 0 0;font-size:14px;color:#cffafe;">Manage your sessions as a speaker</p>
        </td></tr>
        <tr><td style="padding:28px 32px;color:#1e293b;font-size:15px;line-height:1.6;">
          <p style="margin:0 0 16px;">Hi <strong>{speaker_name}</strong>,</p>
          <p style="margin:0 0 16px;">You've been invited to join TechTrek as a speaker. Accept the invite below to create your account (or link your existing one) and start managing your session details, agenda, and profile.</p>
          <p style="margin:0 0 24px;">
            <a href="{invite_url}" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;padding:12px 28px;border-radius:6px;font-weight:600;font-size:14px;">Accept Invite &rarr;</a>
          </p>
          <p style="margin:0;font-size:13px;color:#64748b;">This invite link expires in 7 days.</p>
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;">
          <p style="margin:0;font-size:12px;color:#64748b;">If you did not expect this invitation, you can safely ignore this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return _send(email, "You're Invited to TechTrek as a Speaker!", html)
