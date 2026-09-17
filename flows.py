import json
import os
import re
from calendar import monthrange
from datetime import date, timedelta

from database import (
    clear_session_state,
    get_session_state,
    save_prebooking,
    set_session_state,
    update_prebooking_payment,
)

VALID_ROOMS = ["T1", "T2", "T3", "T4"]

ROOM_LABELS = {
    "T1": "T1 - Standard (25.000 F/nuit)",
    "T2": "T2 - Supérieure (30.000 F/nuit)",
    "T3": "T3 - Deluxe (35.000 F/nuit)",
    "T4": "T4 - Suite prestige (40.000 F/nuit)",
}

# Prix par nuit (FCFA) — source de vérité unique
ROOM_PRICES = {
    "T1": 25000,
    "T2": 30000,
    "T3": 35000,
    "T4": 40000,
}

MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
BOOKING_MAX_MONTHS = int(os.getenv("BOOKING_MAX_MONTHS", "12"))


def _split_date(value: str | None) -> tuple[int | None, int | None]:
    """'20/12' → (20, 12) ; '20' → (20, None)."""
    if not value:
        return None, None
    parts = value.split("/")
    day = int(parts[0]) if parts[0].isdigit() else None
    month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return day, month


def compute_nights(check_in: str | None, check_out: str | None) -> int:
    """Nombre de nuits entre deux dates 'j/m'. Gère le chevauchement de mois
    (ex : 25/12 → 02/01 = 8 nuits)."""
    in_day, in_month = _split_date(check_in)
    out_day, out_month = _split_date(check_out)
    if not in_day:
        return 1
    if not out_day or out_day == in_day:
        return 1
    if not out_month or not in_month or out_month == in_month:
        return max(out_day - in_day, 1)
    days_in_first = MONTH_DAYS[in_month - 1]
    return days_in_first - in_day + out_day


def compute_total(room_type: str | None, check_in: str | None, check_out: str | None) -> int:
    """Total du séjour en FCFA : prix chambre × nombre de nuits."""
    price = ROOM_PRICES.get(room_type or "", 0)
    if not price:
        return 0
    return price * compute_nights(check_in, check_out)


def parse_room_type(text: str) -> str | None:
    match = re.search(r"\bT([1-4])\b", text.upper())
    if match:
        room = f"T{match.group(1)}"
        if room in VALID_ROOMS:
            return room
    # tolérance : "chambre 2", "la 3"
    for room in VALID_ROOMS:
        if room.lower() in text.lower():
            return room
    return None


def parse_dates(text: str) -> tuple[str | None, str | None]:
    """Formats : '20/12 au 25/12', '20/12/2026 au 25/12/2026', '20 décembre au 25',
    'du 20 au 25 décembre', '20 au 25'. Retourne des dates 'j/m' ou jours seuls."""
    month_map = {
        "janvier": "01", "février": "02", "fevrier": "02", "mars": "03",
        "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
        "août": "08", "aout": "08", "septembre": "09", "octobre": "10",
        "novembre": "11", "décembre": "12", "decembre": "12",
    }

    # 1) Formats numériques : "20/12 au 25/12" ou "20/12/2026 au 25/12/2026"
    num_match = re.findall(
        r"(\d{1,2})\s*/\s*(\d{1,2})(?:/\d{2,4})?", text, re.IGNORECASE
    )
    if num_match:
        check_in = f"{num_match[0][0]}/{num_match[0][1]}"
        check_out = (
            f"{num_match[1][0]}/{num_match[1][1]}" if len(num_match) > 1 else None
        )
        return check_in, check_out

    # 2) Formats textuels : "20 décembre au 25", "du 20 au 25 décembre", "20-25 décembre"
    months = [
        month_map[m.lower()]
        for m in re.findall(
            r"(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
            r"septembre|octobre|novembre|décembre|decembre)",
            text,
            re.IGNORECASE,
        )
    ]
    day_like = [d for d in re.findall(r"(\d{1,2})", text) if 1 <= int(d) <= 31]
    if not day_like:
        return None, None
    if months and len(day_like) >= 2:
        month = months[0]
        return f"{day_like[0]}/{month}", f"{day_like[1]}/{month}"
    if months:
        return f"{day_like[0]}/{months[0]}", None
    if len(day_like) >= 2:
        return day_like[0], day_like[1]
    return day_like[0], None


def format_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        digits = "01" + digits
    return digits or text


def today_str() -> str:
    return date.today().strftime("%d/%m/%Y")


def _past_date_message() -> str:
    return (
        "🚫 Cette date est déjà passée !\n"
        f"Aujourd'hui nous sommes le {today_str()}. "
        "Veuillez choisir une date égale ou postérieure à aujourd'hui.\n"
        "Ex : 'du 20 au 25 décembre' ou '20/12 au 25/12'."
    )


# ---------------------------------------------------------------- Dates Picker API
def _resolve_date(day: int, month: int) -> date | None:
    """Transforme (jour, mois) en date avec année courante (mois passé = année+1)."""
    today = date.today()
    try:
        d = date(today.year, month, day)
        if d < today:
            d = date(today.year + 1, month, day)
        return d
    except ValueError:
        return None


def _booking_max_date() -> date:
    d = date.today()
    month = d.month - 1 + BOOKING_MAX_MONTHS
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def _validate_date_range(
    check_in: str | None,
    check_out: str | None,
    raw_text: str = "",
) -> str | None:
    """Valide la plage arrivée/départ. Retourne message d'erreur ou None."""
    err = validate_check_in_date(raw_text, check_in)
    if err:
        return err
    in_day, in_month = _split_date(check_in)
    out_day, out_month = _split_date(check_out)
    resolved_in = _resolve_date(in_day, in_month) if in_day and in_month else None
    resolved_out = _resolve_date(out_day, out_month) if out_day and out_month else None
    max_d = _booking_max_date()
    if resolved_in and resolved_in > max_d:
        return (
            "📅 Votre arrivée est trop éloignée !\n"
            f"Les réservations sont ouvertes jusqu'au {max_d.strftime('%d/%m/%Y')}."
        )
    if resolved_out and resolved_out > max_d:
        return (
            "📅 Votre départ est trop éloigné !\n"
            f"Les réservations sont ouvertes jusqu'au {max_d.strftime('%d/%m/%Y')}."
        )
    if resolved_in and resolved_out and resolved_out <= resolved_in:
        return "🚫 La date de départ doit être APRÈS la date d'arrivée."
    return None


def _room_prompt() -> str:
    return (
        "🛏️ Quelle offre choisissez-vous ?\n"
        "• T1 · 25.000 F  • T2 · 30.000 F  • T3 · 35.000 F  • T4 · 40.000 F\n"
        "Répondez par ex. « T2 »."
    )


def _dates_prompt(data: dict) -> str:
    room = data.get("room_type")
    label = ROOM_LABELS.get(room, room or "")
    head = f"Excellent choix ! {label} ✨\n" if room else ""
    return (
        head
        + "📅 Quelles sont vos DATES d'arrivée et de départ ?\n"
        "(Ex : 'du 20 au 25 décembre' ou '20/12 au 25/12')"
    )


def _name_prompt(data: dict) -> str:
    check_in = data.get("check_in")
    check_out = data.get("check_out")
    recap = ""
    if check_in:
        recap = "\nArrivée : " + check_in + (
            f" · Départ : {check_out}" if check_out else ""
        )
    return (
        "Parfait ! 📅" + recap + "\n\n"
        "👤 Quel est votre NOM COMPLET ? (Ex : Jean Kouassi)"
    )


def _phone_prompt(data: dict) -> str:
    name = data.get("name")
    head = f"Merci {name} ! 🙏\n" if name else ""
    return (
        head
        + "📞 Votre NUMÉRO de téléphone pour la confirmation ? (Ex : 0747123456)"
    )


def _next_step(data: dict) -> tuple[str, str]:
    """État + invite suivants : CHAMBRE → DATES → NOM → TÉLÉPHONE.

    Le nom et le numéro ne sont demandés qu'à la fin, juste avant le paiement.
    """
    if not data.get("room_type") or data.get("room_type") not in VALID_ROOMS:
        return "collect_room", _room_prompt()
    if not data.get("check_in"):
        return "collect_dates", _dates_prompt(data)
    if not data.get("name"):
        return "collect_name", _name_prompt(data)
    return "collect_phone", _phone_prompt(data)


def set_room(channel: str, user_id: str, room: str) -> str:
    """Enregistre l'offre choisie, puis demande les DATES (avant le nom)."""
    room = (room or "").upper().strip()
    if room not in VALID_ROOMS:
        return _room_prompt()
    data = get_booking_data(channel, user_id)
    data["room_type"] = room
    state, prompt = _next_step(data)
    set_session_state(channel, user_id, state, data)
    return prompt


def set_name(channel: str, user_id: str, name: str) -> str:
    """Enregistre le nom du client (après les dates), puis demande le téléphone."""
    data = get_booking_data(channel, user_id)
    data["name"] = name.strip()
    state, prompt = _next_step(data)
    set_session_state(channel, user_id, state, data)
    return prompt


def set_dates(channel: str, user_id: str, check_in: str, check_out: str, raw_text: str = "") -> str:
    """Enregistre les dates (calendrier ou flow) et demande le nom."""
    data = get_booking_data(channel, user_id)
    err = _validate_date_range(check_in, check_out, raw_text)
    if err:
        return err
    data["check_in"] = check_in
    data["check_out"] = check_out
    state, prompt = _next_step(data)
    set_session_state(channel, user_id, state, data)
    return prompt


def apply_flow_booking(channel: str, user_id: str, payload: dict) -> str:
    """Applique la réponse complète du Flow WA (dates + chambre)."""
    from whatsapp_flow import extract_booking

    fields = extract_booking(payload)
    check_in = fields.get("check_in")
    check_out = fields.get("check_out")
    room_type = fields.get("room_type")
    err = _validate_date_range(check_in, check_out)
    if err:
        return err
    if not room_type or room_type not in VALID_ROOMS:
        return _room_prompt()
    data = get_booking_data(channel, user_id)
    data["check_in"] = check_in
    data["check_out"] = check_out
    data["room_type"] = room_type
    state, prompt = _next_step(data)  # nom manquant → collect_name
    set_session_state(channel, user_id, state, data)
    return prompt


def validate_check_in_date(raw_text: str, check_in: str | None) -> str | None:
    """Vérifie que la date d'arrivée n'est pas antérieure à aujourd'hui.

    Règles :
    - 'j/m' sans année : le mois courant est interprété cette année,
      un mois passé est interprété l'année suivante (séjour lointain OK).
    - Si l'année est écrite explicitement (ex : 17/09/2026), comparaison directe.
    Retourne un message d'erreur, ou None si la date est valide.
    """
    if not check_in:
        return None
    day, month = _split_date(check_in)
    if not day or not month:
        return None  # date incomplète → pas de blocage

    today = date.today()

    # Année explicite dans le texte du client (ex : "15/09/2026")
    year_match = re.search(r"\b(20\d{2})\b", raw_text)
    if year_match:
        year = int(year_match.group(1))
        try:
            if date(year, month, day) < today:
                return _past_date_message()
        except ValueError:
            return None

    # Mois courant → même année, le jour doit être aujourd'hui ou plus tard
    if month == today.month:
        if date(today.year, month, day) < today:
            return _past_date_message()
        return None

    # Mois à venir dans l'année → OK
    # Mois déjà passé → interprété l'année suivante → OK
    return None


def get_booking_data(channel: str, user_id: str) -> dict:
    state = get_session_state(channel, user_id)
    if state and state.data:
        try:
            return json.loads(state.data)
        except json.JSONDecodeError:
            return {}
    return {}


def handle_message(channel: str, user_id: str, text: str) -> str:
    """Gère le flow de pré-réservation multi-étapes.
    Ordre : OFFRE (chambre T1-T4) → DATES → NOM → TÉLÉPHONE (juste avant paiement).
    Retourne la réponse à envoyer à l'utilisateur (ou None → IA)."""
    state = get_session_state(channel, user_id)
    current_state = state.state if state else None
    data = get_booking_data(channel, user_id)

    msg = text.strip().lower()

    # Démarrage / en dehors du flow
    if current_state is None:
        # Le client choisit directement une chambre (« T2 », bouton « Réserver »…)
        room = parse_room_type(text)
        if room:
            data["room_type"] = room
            state, prompt = _next_step(data)
            set_session_state(channel, user_id, state, data)
            return prompt
        if any(
            w in msg
            for w in [
                "pré-réserver", "prereserver", "reserver", "réserver",
                "pré-réservation", "réservation", "reservation",
            ]
        ):
            state, prompt = _next_step(data)  # → collect_room
            set_session_state(channel, user_id, state, data)
            return prompt
        return None

    # Étape 1 : offre (chambre) — demandée AVANT le nom et les dates
    if current_state == "collect_room":
        room = parse_room_type(text)
        if not room:
            return _room_prompt()
        data["room_type"] = room
        state, prompt = _next_step(data)
        set_session_state(channel, user_id, state, data)
        return prompt

    # Étape 2 : dates (offre déjà choisie, nom demandé plus tard)
    if current_state == "collect_dates":
        check_in, check_out = parse_dates(text)
        if not check_in:
            return (
                "Je n'ai pas bien compris les dates 😅\n"
                "Exemple : 'du 20 au 25 décembre' ou '20/12/2026 au 25/12/2026'. Réessayez ?"
            )
        error = validate_check_in_date(text, check_in)
        if error:
            return error
        data["check_in"] = check_in
        data["check_out"] = check_out
        state, prompt = _next_step(data)
        set_session_state(channel, user_id, state, data)
        return prompt

    # Étape 3 : nom (uniquement à la fin, juste avant le paiement)
    if current_state == "collect_name":
        name = text.strip()
        if len(name) < 2:
            return _name_prompt(data)
        data["name"] = name
        state, prompt = _next_step(data)
        set_session_state(channel, user_id, state, data)
        return prompt

    # Étape 4 : téléphone → création de la facture PayDunya + lien de paiement
    if current_state == "collect_phone":
        phone = format_phone(text)
        data["phone"] = phone
        room_type = data.get("room_type")
        check_in = data.get("check_in")
        check_out = data.get("check_out")
        total = compute_total(room_type, check_in, check_out)
        book = save_prebooking(
            channel=channel,
            user_id=user_id,
            name=data.get("name"),
            check_in=check_in,
            check_out=check_out,
            room_type=room_type,
            phone=phone or None,
            notes="Réservation via le bot",
            amount_due=total,
        )
        clear_session_state(channel, user_id)

        return_url = f"{PUBLIC_BASE_URL}/booking/{book.id}"
        cancel_url = f"{PUBLIC_BASE_URL}/booking/{book.id}"

        price_label = {
            "T1": "25.000 F", "T2": "30.000 F", "T3": "35.000 F", "T4": "40.000 F",
        }.get(room_type, "?")
        recap = (
            f"🎉 Réservation #{book.id} enregistrée !\n\n"
            f"👤 {data.get('name')}\n"
            f"📅 {check_in}" + (f" au {check_out}" if check_out else "")
            + f"\n🛏️ {room_type} ({price_label}/nuit)\n"
            f"📞 {phone or 'non renseigné'}\n\n"
            f"💵 Total séjour : {total:,} FCFA\n"
        )

        from payments import build_items, request_payment

        description = f"Séjour PO PAIX HOTEL ET EXPERIENCES #{book.id} — {room_type}, {check_in}" + (
            f" au {check_out}" if check_out else ""
        )
        checkout_url, invoice_token = request_payment(
            total_fcf=total,
            description=description,
            name=data.get("name") or "",
            phone=phone or "",
            custom_data={"prebooking_id": book.id},
            return_url=return_url,
            cancel_url=cancel_url,
        )

        if checkout_url and invoice_token:
            update_prebooking_payment(book.id, invoice_token, status="awaiting_payment")
            set_session_state(
                channel, user_id, "awaiting_payment",
                {"prebooking_id": book.id, "checkout_url": checkout_url},
            )
            return (
                recap
                + "\n💳 Pour FINALISER votre réservation, payez en ligne :\n"
                f"🔗 {checkout_url}\n\n"
                "💰 Virement Wave, Orange Money, MTN Money ou carte — sécurisé par PayDunya.\n"
                "⚠️ Tant que le paiement n'est pas confirmé, la chambre n'est pas réservée."
            )
        return (
            recap
            + "\n💰 Paiement à confirmer : espèces, Wave, Orange Money ou MTN Money.\n"
            "📞 Notre équipe vous appellera au +225 0702391982 pour finaliser.\n"
            "Merci, à bientôt au PO PAIX HOTEL ET EXPERIENCES ! 🌴"
        )

    # Étape 5 : en attente de paiement
    if current_state == "awaiting_payment":
        checkout_url = data.get("checkout_url")
        prebooking_id = data.get("prebooking_id")

        # Annulation explicite → libère la session
        if any(w in msg for w in ["annule", "annuler", "cancel"]):
            clear_session_state(channel, user_id)
            from database import update_prebooking_status

            if prebooking_id:
                update_prebooking_status(int(prebooking_id), "cancelled")
            return (
                "Réservation annulée ✅. "
                "Vous pouvez recommencer en disant 'pré-réserver'."
            )

        # Le client redemande le lien de paiement
        if any(
            w in msg
            for w in [
                "payer", "paiement", "lien", "paydunya", "régler", "regler",
                "finaliser", "règlement", "reglement",
            ]
        ):
            if checkout_url:
                return (
                    "💳 Finalisez votre paiement ici :\n"
                    f"🔗 {checkout_url}\n\n"
                    "Dès le paiement confirmé, je vous enverrai votre confirmation finale. "
                    "Dites 'annuler' pour abandonner la réservation."
                )
            clear_session_state(channel, user_id)
            return (
                "💰 Aucun paiement en ligne n'est requis pour cette réservation. "
                "Notre équipe vous appellera au +225 0702391982, "
                "ou réglez en espèces sur place."
            )

        # Le client veut repartir sur une nouvelle réservation
        if any(
            w in msg
            for w in [
                "pré-réserver", "prereserver", "reserver", "réserver",
                "réservation", "reservation", "nouvelle résa",
            ]
        ):
            hint = f"\n\n💳 Payez ici : 🔗 {checkout_url}" if checkout_url else ""
            return (
                "⏳ Vous avez déjà une réservation en attente de paiement."
                + hint
                + "\n\nDites 'annuler' pour l'abandonner et recommencer une réservation."
            )

        # Toute autre question → l'IA répond ; la session (et le lien) reste en mémoire
        return None

    # État inconnu : reset
    clear_session_state(channel, user_id)
    return None


def build_whatsapp_interactive_rooms() -> dict:
    """Boutons de choix de chambre pour WhatsApp."""
    rows = [
        {"id": "ROOM_T1", "title": "T1 - Standard 25.000F"},
        {"id": "ROOM_T2", "title": "T2 - Supérieure 30.000F"},
        {"id": "ROOM_T3", "title": "T3 - Deluxe 35.000F"},
        {"id": "ROOM_T4", "title": "T4 - Suite 40.000F"},
    ]
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "🚀 Pré-réservation"},
            "body": {"text": "Choisissez votre type de chambre :"},
            "footer": {"text": "PO PAIX HOTEL ET EXPERIENCES 🌴"},
            "action": {
                "button": "Voir les chambres",
                "sections": [{"title": "Types de chambre", "rows": rows}],
            },
        },
    }