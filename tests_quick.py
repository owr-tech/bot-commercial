"""Tests rapides — calcul du montant séjour et flux de réservation."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, timedelta

from flows import (
    compute_nights,
    compute_total,
    parse_room_type,
    parse_dates,
    validate_check_in_date,
)


def test_nights():
    assert compute_nights("20/12", "25/12") == 5
    assert compute_nights("25/12", "02/01") == 8
    assert compute_nights("01/02", "28/02") == 27
    assert compute_nights("20/12", None) == 1
    assert compute_nights("20/12", "20/12") == 1


def test_total():
    assert compute_total("T1", "10/03", "12/03") == 50000  # 25.000 x 2
    assert compute_total("T2", "25/12", "02/01") == 240000  # 30.000 x 8
    assert compute_total("T4", "01/01", "02/01") == 40000
    assert compute_total("T9", "01/01", "02/01") == 0  # chambre inconnue


def test_parsers():
    assert parse_room_type("je veux une T3") == "T3"
    assert parse_room_type("chambre T1 svp") == "T1"
    assert parse_dates("du 20 au 25 décembre") == ("20/12", "25/12")
    assert parse_dates("20/12 au 25/12") == ("20/12", "25/12")
    assert parse_dates("17/09") == ("17/09", None)  # une seule date ne crashe pas


def test_date_restriction():
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    # Date du jour → OK
    assert validate_check_in_date("", f"{today.day:02d}/{today.month:02d}") is None
    # Demain → OK
    assert validate_check_in_date("", f"{tomorrow.day:02d}/{tomorrow.month:02d}") is None
    # Hier (même mois) → REFUSÉ
    if yesterday.month == today.month:
        assert (
            validate_check_in_date(
                "", f"{yesterday.day:02d}/{yesterday.month:02d}"
            )
            is not None
        )
    # Année explicite passée → REFUSÉ
    assert validate_check_in_date("du 17/09/2020 au 20/09/2020", "17/09") is not None
    # Année explicite dans le futur → OK
    assert validate_check_in_date("du 17/09/2027", "17/09") is None
    # Mois futur dans l'année → OK
    future_month = "12" if today.month < 12 else "12"
    assert validate_check_in_date("", f"20/{future_month}") is None
    # Mois passé → interprété l'année suivante → OK
    past_month = f"{today.month - 1:02d}" if today.month > 1 else "12"
    assert validate_check_in_date("", f"20/{past_month}") is None


def test_flow_booking():
    # Parcours complet via le flow (sans clés PayDunya → fallback manuel)
    from flows import handle_message
    from database import clear_session_state

    channel, user_id = "test", "u-flow-1"
    clear_session_state(channel, user_id)

    # Nouvel ordre : OFFRE (chambre) → DATES → NOM → TÉLÉPHONE (juste avant paiement)
    r = handle_message(channel, user_id, "je veux pré-réserver")
    assert "offre" in r.lower()
    r = handle_message(channel, user_id, "T2")
    assert "DATES" in r
    r = handle_message(channel, user_id, "du 20 au 25 décembre")
    assert "NOM" in r  # le nom est demandé seulement maintenant, avant le paiement
    r = handle_message(channel, user_id, "Jean Kouassi")
    assert "téléphone" in r
    r = handle_message(channel, user_id, "0709112233")
    assert "150" in r and "Total séjour" in r
    assert "équipe" in r  # fallback manuel car pas de clés PayDunya
    clear_session_state(channel, user_id)
    return r


def test_presentation():
    from presentation import (
        HOTEL_NAME,
        full_presentation_text,
        room_card_caption,
        services_text,
    )

    assert HOTEL_NAME == "PO PAIX HOTEL ET EXPERIENCES"
    txt = full_presentation_text()
    assert "PO PAIX HOTEL ET EXPERIENCES" in txt
    assert "RESTAURANT ANWUKWA" in txt
    # carte chambre « booking.com » : standard + prix + CTA
    card = room_card_caption("T1")
    assert "T1" in card and "25.000 F" in card
    # services visuellement séparés par catégories
    svc = services_text()
    for section in ("CONFORT", "DÉTENTE", "PRATIQUE", "BON À SAVOIR"):
        assert section in svc


def test_date_range_validation():
    from flows import _validate_date_range
    # Départ avant arrivée → refusé
    assert _validate_date_range("25/09", "20/09") is not None
    # Départ même jour → refusé
    assert _validate_date_range("20/09", "20/09") is not None
    # Plage valide → OK
    assert _validate_date_range("20/09", "25/09") is None


def test_picker_api():
    from datetime import date
    from telegram_picker import (
        booking_limits,
        build_date_calendar,
        parse_cal_callback,
    )

    lo, hi = booking_limits(12)
    assert lo <= date.today() <= hi
    kb = build_date_calendar(lo.year, lo.month, lo, hi)
    assert len(kb.inline_keyboard) >= 3
    assert parse_cal_callback("cal:dates:day:2026-09-20")[1] == "day"
    assert parse_cal_callback("cal:dates:nav:-1")[2] == -1
    assert parse_cal_callback("cal:dates:cancel")[1] == "cancel"
    assert parse_cal_callback("nope") is None


def test_whatsapp_flow():
    from whatsapp_flow import (
        build_flow_json,
        booking_window,
        extract_booking,
        parse_flow_completion,
    )
    import json

    fj = build_flow_json()
    assert [s["id"] for s in fj["screens"]] == ["ROOM", "DATES"]
    assert fj["version"] == "5.0"
    # Les 4 chambres ont une image dans l'écran ROOM (offre d'abord)
    room_json = json.dumps(fj["screens"][0])
    for room in ("T1", "T2", "T3", "T4"):
        assert room in room_json
    assert "images.unsplash.com" in room_json
    min_d, max_d = booking_window()
    assert min_d < max_d
    # Conversion ISO → j/m
    assert extract_booking({"checkin": "2026-09-20", "checkout": "2026-09-25", "room": "t2"}) == {
        "check_in": "20/09",
        "check_out": "25/09",
        "room_type": "T2",
    }
    parsed = parse_flow_completion(
        {"flow": {"flow_reply": json.dumps({"checkin": "2026-12-20", "checkout": "2026-12-25", "room": "T4"})}}
    )
    assert parsed["room"] == "T4"


def test_flow_api_booking():
    from database import clear_session_state
    from flows import apply_flow_booking, handle_message

    ch, u = "test", "u-flow-booking"
    clear_session_state(ch, u)
    handle_message(ch, u, "je veux pré-réserver")
    # Le Flow WA fournit chambre + dates d'un coup → on demande ensuite le NOM
    r = apply_flow_booking(ch, u, {"checkin": "2026-12-20", "checkout": "2026-12-25", "room": "T4"})
    assert "NOM" in r
    r = handle_message(ch, u, "Awa Diallo")
    assert "téléphone" in r
    r = handle_message(ch, u, "0709112233")
    assert "équipe" in r or "payez" in r
    clear_session_state(ch, u)


def test_voucher_status():
    from booking_pdf import _is_paid, _status_label

    class B:
        def __init__(self, status, due, paid, paid_at=None):
            self.status = status
            self.amount_due = due
            self.amount_paid = paid
            self.paid_at = paid_at

    assert _status_label(B("paid", 150000, 150000)) == "PAID · PAYÉ"
    # Cas réel : objet chargé avant le marquage « paid » → statut périmé mais montant réglé
    assert _status_label(B("awaiting_payment", 150000, 150000)) == "PAID · PAYÉ"
    assert _status_label(B("awaiting_payment", 150000, 0)) == "EN ATTENTE DE PAIEMENT"
    assert _status_label(B("pending", 150000, 0)) == "RÉSERVÉ · BOOKED"
    assert _is_paid(B("pending", 150000, 150000)) is True
    assert _is_paid(B("awaiting_payment", 150000, 0)) is False


def test_rooms_cards():
    from rooms import IMAGE_URLS, ROOM_INFO, room_caption

    for room in ("T1", "T2", "T3", "T4"):
        assert room in ROOM_INFO
        assert ROOM_INFO[room]["image"].startswith("https://")
    assert len(IMAGE_URLS) == 4
    assert "T2" in room_caption("T2") and "30.000" in room_caption("T2")


def test_voucher_pdf():
    from booking_pdf import booking_pdf, qr_code_png, qr_payload
    from datetime import datetime

    class B:
        id = 999
        name = "Test Client"
        check_in = "20/12"
        check_out = "25/12"
        room_type = "T2"
        status = "paid"
        amount_paid = 150000
        amount_due = 150000
        created_at = datetime(2026, 9, 17, 12, 0)

    pdf = booking_pdf(B())
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 3000
    png = qr_code_png(qr_payload(999))
    assert png[:4] == b"\x89PNG"


if __name__ == "__main__":
    test_nights()
    test_total()
    test_parsers()
    test_date_restriction()
    test_date_range_validation()
    test_picker_api()
    test_whatsapp_flow()
    test_presentation()
    test_voucher_status()
    test_rooms_cards()
    test_voucher_pdf()
    test_flow_api_booking()
    print("test_flow_booking →", test_flow_booking().replace("\n", " | "))
    print("\n✅ TOUS LES TESTS PASSENT")