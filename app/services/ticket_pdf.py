"""Ticket PDF + QR code generation. Pure in-memory functions, no disk or network I/O."""
import io
from zoneinfo import ZoneInfo

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.core.config import TICKET_TIMEZONE
from app.services.tickets import TicketData

PAGE_W, PAGE_H = 200 * mm, 85 * mm
MARGIN = 4 * mm
HEADER_H = 20 * mm
STUB_W = 62 * mm

NAVY = colors.HexColor("#1f2a44")
GREY = colors.HexColor("#6b7280")
INK = colors.HexColor("#111827")
FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"


def _fit(text: str, font: str, size: float, max_width: float) -> str:
    """Truncate text with '...' so it fits within max_width."""
    if stringWidth(text, font, size) <= max_width:
        return text
    while text and stringWidth(text + "...", font, size) > max_width:
        text = text[:-1]
    return text + "..."


def make_qr_png(payload: str) -> bytes:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_ticket_pdf(t: TicketData) -> bytes:
    """Render a single-page ticket and return the PDF as bytes."""
    start = t.start_time.astimezone(ZoneInfo(TICKET_TIMEZONE))
    date_str = start.strftime("%a, %d %b %Y")
    time_str = f"{start.strftime('%I:%M %p').lstrip('0')} {start.tzname()}"

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"Ticket - {t.event_title}")

    left, right = MARGIN, PAGE_W - MARGIN
    bottom, top = MARGIN, PAGE_H - MARGIN
    tear_x = right - STUB_W
    pad = 6 * mm

    # Outer frame
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.2)
    c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)

    # Header band with event title
    c.setFillColor(NAVY)
    c.rect(left, top - HEADER_H, right - left, HEADER_H, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 17)
    c.drawString(left + pad, top - 11 * mm,
                 _fit(t.event_title, FONT_BOLD, 17, right - left - 2 * pad))
    c.setFont(FONT, 8)
    c.drawString(left + pad, top - 16.5 * mm, f"ADMIT ONE   |   BOOKING #{t.booking_id}")

    # Detail fields
    def field(x: float, y: float, label: str, value: str, max_w: float) -> None:
        c.setFillColor(GREY)
        c.setFont(FONT, 7.5)
        c.drawString(x, y, label)
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 12)
        c.drawString(x, y - 6 * mm, _fit(value, FONT_BOLD, 12, max_w))

    col1, col2 = left + pad, left + 62 * mm
    field(col1, 52 * mm, "DATE", date_str, 52 * mm)
    field(col2, 52 * mm, "TIME", time_str, tear_x - col2 - 4 * mm)
    field(col1, 36 * mm, "VENUE", f"{t.venue_name}, {t.venue_city}", tear_x - col1 - 4 * mm)
    field(col1, 20 * mm, "SEAT", t.seat_number, 52 * mm)
    field(col2, 20 * mm, "AMOUNT PAID", f"{t.currency} {t.amount:,.2f}", tear_x - col2 - 4 * mm)

    # Footer reference line
    c.setFillColor(GREY)
    c.setFont(FONT, 7)
    footer = f"Payment ref: {t.payment_ref}" if t.payment_ref else ""
    c.drawString(col1, 8 * mm, footer)

    # Perforation line between the ticket body and the QR stub
    c.setStrokeColor(GREY)
    c.setLineWidth(0.8)
    c.setDash(2, 2)
    c.line(tear_x, bottom, tear_x, top - HEADER_H)
    c.setDash()

    # QR stub
    qr_size = 40 * mm
    stub_cx = tear_x + STUB_W / 2
    c.drawImage(ImageReader(io.BytesIO(make_qr_png(t.ticket_code))),
                stub_cx - qr_size / 2, 17 * mm, qr_size, qr_size)
    c.setFillColor(INK)
    c.setFont("Courier", 6.5)
    c.drawCentredString(stub_cx, 12.5 * mm, t.ticket_code)
    c.setFillColor(GREY)
    c.setFont(FONT_BOLD, 7.5)
    c.drawCentredString(stub_cx, 8 * mm, "SCAN AT ENTRY")

    c.showPage()
    c.save()
    return buf.getvalue()