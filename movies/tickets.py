import io
import qrcode
from django.core.signing import Signer, BadSignature
from django.conf import settings
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from .models import Booking

QR_SIGNER_SALT = 'bookmyseat-secure-ticket-qr-token'

def generate_ticket_token(booking_reference):
    signer = Signer(salt=QR_SIGNER_SALT)
    return signer.sign(booking_reference)

def verify_ticket_token(token):
    signer = Signer(salt=QR_SIGNER_SALT)
    try:
        booking_reference = signer.unsign(token)
        bookings = Booking.objects.filter(booking_reference=booking_reference)
        if not bookings.exists():
            return {'valid': False, 'error': 'No matching booking found for this reference.'}
        first = bookings.first()
        return {
            'valid': True,
            'booking_reference': booking_reference,
            'movie': first.movie.name,
            'theater': first.theater.name,
            'city': first.theater.city,
            'screen': first.theater.screen or first.theater.location,
            'time': first.theater.time,
            'seats': [b.seat.seat_number for b in bookings],
            'total_amount': sum(b.total_amount for b in bookings),
            'payment_status': first.payment_status,
            'booked_by': first.user.username,
            'booked_at': first.booked_at,
        }
    except BadSignature:
        return {'valid': False, 'error': 'Invalid or tampered ticket verification token.'}

def generate_ticket_qr_image(booking_reference):
    token = generate_ticket_token(booking_reference)
    # Verification URL or token
    verification_payload = f"VERIFY:BMS:{token}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=2,
    )
    qr.add_data(verification_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#111827", back_color="#ffffff")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer, token

def generate_ticket_pdf(booking_reference):
    bookings = Booking.objects.filter(booking_reference=booking_reference)
    if not bookings.exists():
        raise ValueError(f"Booking {booking_reference} not found.")

    first = bookings.first()
    movie = first.movie
    theater = first.theater
    seats = [b.seat.seat_number for b in bookings]
    total_paid = sum(b.total_amount for b in bookings)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TicketTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        textColor=colors.HexColor('#F84464'),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        'TicketSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#111827'),
        spaceAfter=4,
    )
    normal_style = ParagraphStyle(
        'TicketNormal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor('#374151'),
        leading=14,
    )
    meta_style = ParagraphStyle(
        'TicketMeta',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        textColor=colors.HexColor('#1F2937'),
        leading=15,
    )

    elements = []

    # Header Banner
    header_data = [
        [
            Paragraph("<b>BookMySeat</b>", title_style),
            Paragraph(f"<b>E-TICKET: {booking_reference}</b><br/><font color='#10B981'>STATUS: {first.payment_status.upper()}</font>", ParagraphStyle('HeadRight', parent=normal_style, alignment=2, fontName='Helvetica-Bold', fontSize=11))
        ]
    ]
    header_table = Table(header_data, colWidths=[3.5 * inch, 3.5 * inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LINEBELOW', (0, 0), (-1, -1), 1.5, colors.HexColor('#F84464')),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 14))

    # Movie & Theatre Section
    qr_buffer, token = generate_ticket_qr_image(booking_reference)
    qr_img = RLImage(qr_buffer, width=1.6 * inch, height=1.6 * inch)

    movie_info = [
        Paragraph(f"<b>{movie.name}</b> ({movie.age_rating})", subtitle_style),
        Paragraph(f"<b>Genre:</b> {movie.genre} | <b>Language:</b> {movie.language} | <b>Duration:</b> {movie.duration} mins", normal_style),
        Spacer(1, 8),
        Paragraph(f"<b>Theatre:</b> {theater.name} - {theater.location} ({theater.city})", meta_style),
        Paragraph(f"<b>Screen:</b> {theater.screen or 'Screen 1'}", normal_style),
        Paragraph(f"<b>Show Date & Time:</b> {theater.time.strftime('%A, %d %B %Y at %I:%M %p')}", meta_style),
        Spacer(1, 8),
        Paragraph(f"<b>Seats ({len(seats)}):</b> <font color='#F84464'><b>{', '.join(seats)}</b></font>", meta_style),
    ]

    body_table = Table([[movie_info, qr_img]], colWidths=[5.4 * inch, 1.8 * inch])
    body_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(body_table)
    elements.append(Spacer(1, 14))

    # Payment & Security Details Table
    payment_details = [
        [Paragraph("<b>Item / Detail</b>", normal_style), Paragraph("<b>Description</b>", normal_style)],
        [Paragraph("Booking Reference", normal_style), Paragraph(booking_reference, meta_style)],
        [Paragraph("Payment Method", normal_style), Paragraph(first.payment_method or "Online Payment", normal_style)],
        [Paragraph("Gateway Order ID", normal_style), Paragraph(first.gateway_order_id or "N/A", normal_style)],
        [Paragraph("Customer Name", normal_style), Paragraph(first.user.username, normal_style)],
        [Paragraph("Customer Email", normal_style), Paragraph(first.user.email or "Registered on account", normal_style)],
        [Paragraph("Booked At", normal_style), Paragraph(first.booked_at.strftime('%Y-%m-%d %H:%M:%S UTC'), normal_style)],
        [Paragraph("<b>Total Amount Paid</b>", meta_style), Paragraph(f"<b>INR {total_paid:.2f}</b>", ParagraphStyle('Amt', parent=meta_style, textColor=colors.HexColor('#F84464')))],
    ]
    pay_table = Table(payment_details, colWidths=[2.5 * inch, 4.5 * inch])
    pay_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(pay_table)
    elements.append(Spacer(1, 14))

    # Important Guidelines
    footer_text = Paragraph(
        "<font size='8' color='#6B7280'><b>IMPORTANT ENTRY TERMS:</b> Please arrive at least 15 minutes before showtime. "
        "Show this e-ticket on your mobile phone or as a printout along with a valid ID at the cinema entrance. "
        "The digital QR code above is cryptographically signed and verifies ticket authenticity with our entry gate system. "
        "Outside food and beverages are not permitted. Tickets subject to cinema terms and conditions.</font>",
        normal_style
    )
    elements.append(footer_text)

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
