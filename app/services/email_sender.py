"""Send the ticket email over SMTP (blocking; intended to run inside the Celery worker)."""
import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from app.core.config import (
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USE_SSL,
    SMTP_USER,
    TICKET_TIMEZONE,
)
from app.services.tickets import TicketData

logger = logging.getLogger(__name__)


def _build_message(t: TicketData, pdf_bytes: bytes, from_email: str) -> EmailMessage:
    start = t.start_time.astimezone(ZoneInfo(TICKET_TIMEZONE))
    when = f"{start.strftime('%A, %d %B %Y')} at {start.strftime('%I:%M %p').lstrip('0')} {start.tzname()}"
    where = f"{t.venue_name}, {t.venue_city}"

    msg = EmailMessage()
    msg["Subject"] = f"Your ticket for {t.event_title}"
    msg["From"] = formataddr((SMTP_FROM_NAME, from_email))
    msg["To"] = t.attendee_email

    msg.set_content(
        f"Your booking is confirmed!\n\n"
        f"Event: {t.event_title}\n"
        f"When:  {when}\n"
        f"Venue: {where}\n"
        f"Seat:  {t.seat_number}\n\n"
        f"Your ticket is attached as a PDF. Show the QR code at the entrance.\n"
        f"Booking reference: #{t.booking_id}\n"
    )

    e = html.escape
    msg.add_alternative(
        f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#111827;">
  <h2 style="color:#1f2a44;margin-bottom:4px;">Your booking is confirmed 🎟️</h2>
  <p style="margin-top:0;">Your ticket is attached as a PDF. Show the QR code at the entrance.</p>
  <table cellpadding="6" style="border-collapse:collapse;">
    <tr><td style="color:#6b7280;">Event</td><td><b>{e(t.event_title)}</b></td></tr>
    <tr><td style="color:#6b7280;">When</td><td>{e(when)}</td></tr>
    <tr><td style="color:#6b7280;">Venue</td><td>{e(where)}</td></tr>
    <tr><td style="color:#6b7280;">Seat</td><td><b>{e(t.seat_number)}</b></td></tr>
    <tr><td style="color:#6b7280;">Booking ref</td><td>#{t.booking_id}</td></tr>
  </table>
</body></html>
""",
        subtype="html",
    )

    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"ticket-{t.booking_id}.pdf",
    )
    return msg


def send_ticket_email(t: TicketData, pdf_bytes: bytes) -> None:
    if not SMTP_HOST:
        raise RuntimeError("SMTP_HOST is not configured - cannot send ticket email.")
    from_email = SMTP_FROM_EMAIL or SMTP_USER
    if not from_email:
        raise RuntimeError("Set SMTP_FROM_EMAIL (or SMTP_USER) - cannot send ticket email.")

    msg = _build_message(t, pdf_bytes, from_email)
    context = ssl.create_default_context()

    if SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30, context=context)
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)

    with server:
        if not SMTP_USE_SSL and SMTP_STARTTLS:
            server.starttls(context=context)
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

    logger.info("Ticket email sent for booking %s to %s", t.booking_id, t.attendee_email)