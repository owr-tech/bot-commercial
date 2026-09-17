"""Voucher PDF + QR de confirmation — bilingue FR/EN (chartre graphique Pôpaix).

Envoyé au client dès que PayDunya confirme le paiement, puis récupérable sur
PUBLIC_BASE_URL/booking/<id> (HTML) & /booking/<id>/pdf.
Le QR pointe vers l'URL du voucher : scanné à la réception pour valider.
"""

import io
import os
from datetime import datetime

from fpdf import FPDF

from flows import compute_nights
from rooms import ROOM_INFO

PALETTE = {
    "green": (14, 59, 44),
    "green2": (26, 82, 64),
    "gold": (176, 138, 47),
    "gold_soft": (230, 216, 174),
    "cream": (246, 241, 230),
    "ink": (23, 32, 26),
    "muted": (117, 103, 79),
}

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

_REPLACEMENTS = {
    "—": "-", "–": "-", "…": "..", "’": "'", "‘": "'",
    "“": '"', "”": '"', "•": "*", "·": ".", "✅": "", "🛏️": "",
}


def _fit(value) -> str:
    """Adapte le texte aux polices latin-1 de fpdf2 (accents OK, em-dash non)."""
    s = str(value) if value is not None else ""
    for src, dst in _REPLACEMENTS.items():
        s = s.replace(src, dst)
    return s.encode("latin-1", "replace").decode("latin-1")


def qr_payload(booking_id: int) -> str:
    return f"{PUBLIC_BASE_URL}/booking/{booking_id}"


def qr_code_png(payload: str) -> bytes:
    """PNG du QR code (lib qrcode + Pillow), carré 420 px, bordures blanches."""
    import io as _io

    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fmt_fcf(value: int) -> str:
    return f"{value:,}".replace(",", ".") + " FCFA"


def _is_paid(book) -> bool:
    """Vrai si la réservation est effectivement réglée (statut, date ou montant)."""
    status = (book.status or "").lower()
    due = book.amount_due or 0
    paid = book.amount_paid or 0
    return status == "paid" or bool(book.paid_at) or (due > 0 and paid >= due)


def _status_label(book) -> str:
    status = (book.status or "").lower()
    if _is_paid(book):
        return "PAID · PAYÉ"
    labels = {
        "confirmed": "CONFIRMED",
        "awaiting_payment": "EN ATTENTE DE PAIEMENT",
    }
    return labels.get(status, "RÉSERVÉ · BOOKED")


def booking_pdf(booking) -> bytes:
    """Génère le voucher A4 (bytes) pour une pré-réservation."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()

    g, gold, ink, muted = PALETTE["green"], PALETTE["gold"], PALETTE["ink"], PALETTE["muted"]

    # ---- Bandeau tête : fond vert + liseré or ----
    pdf.set_fill_color(*g)
    pdf.rect(0, 0, 210, 34, "F")
    pdf.set_fill_color(*gold)
    pdf.rect(0, 34, 210, 1.6, "F")

    pdf.set_xy(15, 8)
    pdf.set_text_color(255, 246, 233)
    pdf.set_font("helvetica", "B", 20)
    pdf.cell(0, 8, "PO PAIX HOTEL ET EXPERIENCES", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(*PALETTE["gold_soft"])
    pdf.cell(0, 5, "GBÔKLE · FRESCO · CÔTE D'IVOIRE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(190, 210, 196)
    pdf.cell(0, 5, _fit("SEJOUR VOUCHER — BILLET DE CONFIRMATION"), new_x="LMARGIN", new_y="NEXT")

    # ---- Badge statut ----
    status = _status_label(booking)
    pdf.set_fill_color(*gold)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(150, 9)
    w_status = pdf.get_string_width(status) + 8
    pdf.rect(160 - w_status, 9, w_status, 8, "F")
    pdf.set_xy(160 - w_status, 10.7)
    pdf.cell(w_status, 5, status, align="C")

    # ---- Référence ----
    pdf.set_xy(15, 44)
    pdf.set_text_color(*ink)
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 9, f"RÉSERVATION N° {booking.id}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(*muted)
    if booking.created_at:
        pdf.cell(0, 5, "Émise le " + booking.created_at.strftime("%d/%m/%Y à %H:%M"), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)

    # ---- Détails du séjour ----
    pdf.set_draw_color(*gold)
    pdf.set_fill_color(*PALETTE["cream"])

    room = (booking.room_type or "").upper()
    room_label = ROOM_INFO.get(room, {}).get("title", room or "—")

    nights = compute_nights(booking.check_in, booking.check_out) or 1
    total = booking.amount_paid or booking.amount_due or 0
    total_label = "TOTAL RÉGLÉ / PAID" if _is_paid(booking) else "TOTAL À PAYER / DUE"

    rows = [
        ("CLIENT / GUEST", booking.name or "—"),
        ("ARRIVÉE / CHECK-IN", f"{booking.check_in or '—'}  ·  dès 10:00"),
        ("DÉPART / CHECK-OUT", f"{booking.check_out or '—'}  ·  avant 13:00"),
        ("CHAMBRE / ROOM", room_label),
        ("NUITÉS / NIGHTS", str(nights)),
        (total_label, _fmt_fcf(total)),
    ]

    y = pdf.get_y()
    for label, value in rows:
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*muted)
        pdf.set_xy(15, y)
        pdf.cell(90, 7, _fit(label))
        pdf.set_font("helvetica", "B", 10.5)
        pdf.set_text_color(*ink)
        pdf.set_xy(105, y)
        pdf.cell(0, 7, _fit(value))
        pdf.set_draw_color(*PALETTE["gold_soft"])
        if label != rows[-1][0]:
            pdf.line(15, y + 7.6, 195, y + 7.6)
        y += 9.4

    pdf.set_y(y + 2)

    # ---- QR ----
    qr_os = ""
    try:
        import base64 as _b64

        qr_os = _b64.b64encode(qr_code_png(qr_payload(booking.id))).decode()
    except Exception as e:
        print(f"[PDF][WARN] QR introuvable: {e}")

    if qr_os:
        pdf.set_fill_color(*PALETTE["gold_soft"])
        pdf.rect(63, pdf.get_y(), 84, 84, "F")
        pdf.set_draw_color(*gold)
        pdf.rect(63, pdf.get_y(), 84, 84, "D")
        try:
            pdf.image("data://image/png;base64," + qr_os, x=71, y=pdf.get_y() + 8, w=68)
        except Exception as e:
            print(f"[PDF][WARN] insertion QR: {e}")
        pdf.set_y(pdf.get_y() + 90)
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(*muted)
        pdf.cell(0, 6, _fit("Présentez ce code à la réception."), align="C", new_x="LMARGIN", new_y="NEXT")
        url = qr_payload(booking.id)
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*gold)
        pdf.cell(0, 5, url, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # ---- Signature réception ----
    pdf.set_text_color(*muted)
    pdf.set_font("helvetica", "", 9)
    pdf.set_draw_color(*PALETTE["gold_soft"])
    pdf.line(15, pdf.get_y() + 14, 105, pdf.get_y() + 14)
    pdf.set_xy(15, pdf.get_y() + 16)
    pdf.cell(0, 5, "CACHET RÉCEPTION / RECEPTION STAMP", new_x="LMARGIN", new_y="NEXT")

    # ---- Pied de page ----
    pdf.set_y(-24)
    pdf.set_fill_color(*g)
    pdf.rect(0, 271, 210, 26, "F")
    pdf.set_fill_color(*gold)
    pdf.rect(0, 271, 210, 1.4, "F")
    pdf.set_xy(15, 278)
    pdf.set_text_color(255, 246, 233)
    pdf.set_font("helvetica", "", 7.5)
    pdf.cell(
        0, 4,
        _fit("PO PAIX HOTEL ET EXPERIENCES · +225 0702391982 · @hotelpopaix · Fresco, Côte d'Ivoire"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("helvetica", "I", 7)
    pdf.set_text_color(*PALETTE["gold_soft"])
    pdf.cell(0, 4, "Voucher généré automatiquement par popaix-bot", new_x="LMARGIN", new_y="NEXT")

    return io.BytesIO(pdf.output()).getvalue()


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from database import get_prebooking

    book = get_prebooking(int(sys.argv[1])) if len(sys.argv) > 1 else None
    if not book:
        print("Usage: python booking_pdf.py <prebooking_id>")
    else:
        data = booking_pdf(book)
        with open("voucher_sample.pdf", "wb") as f:
            f.write(data)
        print(f"OK — voucher_sample.pdf ({len(data)} octets)")