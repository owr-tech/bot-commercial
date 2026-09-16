import json
import re

from database import clear_session_state, get_session_state, save_prebooking, set_session_state

VALID_ROOMS = ["T1", "T2", "T3", "T4"]

ROOM_LABELS = {
    "T1": "T1 - Standard (25.000 F/nuit)",
    "T2": "T2 - Supérieure (30.000 F/nuit)",
    "T3": "T3 - Deluxe (35.000 F/nuit)",
    "T4": "T4 - Suite prestige (40.000 F/nuit)",
}


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
    # Formats : "20/12 au 25/12", "20 décembre au 25 décembre", "20-25 décembre", "20 au 25"
    days = re.findall(r"(\d{1,2})\s*(?:/\s*\d{1,2}(?:/\d{2,4})?)?", text)
    months = re.findall(
        r"(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
        r"septembre|octobre|novembre|décembre|decembre)",
        text,
        re.IGNORECASE,
    )
    month_map = {
        "janvier": "01", "février": "02", "fevrier": "02", "mars": "03",
        "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
        "août": "08", "aout": "08", "septembre": "09", "octobre": "10",
        "novembre": "11", "décembre": "12", "decembre": "12",
    }
    if not months:
        if days:
            if len(days) >= 2:
                return days[0], days[1]
            return days[0], None
        return None, None
    month = month_map[months[0].lower()]
    if days:
        if len(days) >= 2:
            return f"{days[0]}/{month}", f"{days[1]}/{month}"
        return f"{days[0]}/{month}", None
    return None, None


def format_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        digits = "01" + digits
    return digits or text


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
    Retourne la réponse à envoyer à l'utilisateur."""
    state = get_session_state(channel, user_id)
    current_state = state.state if state else None
    data = get_booking_data(channel, user_id)

    msg = text.strip().lower()

    # Démarrage / en dehors du flow
    if current_state is None:
        if any(w in msg for w in ["pré-réserver", "prereserver", "reserver", "pré-réservation", "reserver une", "réserver", "reserver"]):
            set_session_state(channel, user_id, "collect_name", data)
            return (
                "Avec plaisir ! 🎉 Pour débuter, quel est votre NOM COMPLET ? "
                "(Ex : Jean Kouassi)"
            )
        return None

    # Étape 1 : nom
    if current_state == "collect_name":
        data["name"] = text.strip()
        set_session_state(channel, user_id, "collect_dates", data)
        return (
            f"Merci {data['name']} ! 🙏\n"
            "2️⃣ Maintenant, quelles sont vos DATES ?\n"
            "(Ex : 'du 20 au 25 décembre' ou '20/12 au 25/12')"
        )

    # Étape 2 : dates
    if current_state == "collect_dates":
        check_in, check_out = parse_dates(text)
        if not check_in:
            return (
                "Je n'ai pas bien compris les dates 😅\n"
                "Exemple : 'du 20 au 25 décembre' ou '20/12/2026 au 25/12/2026'. Réessayez ?"
            )
        data["check_in"] = check_in
        data["check_out"] = check_out
        set_session_state(channel, user_id, "collect_room", data)
        return (
            "Parfait ! 📅\n"
            f"Arrivée : {check_in}" + (f" · Départ : {check_out}" if check_out else "")
            + "\n\n"
            "3️⃣ Quel type de chambre ?\n"
            "🛏️ T1 = 25.000 F · T2 = 30.000 F · T3 = 35.000 F · T4 = 40.000 F"
        )

    # Étape 3 : type chambre
    if current_state == "collect_room":
        room = parse_room_type(text)
        if not room:
            return (
                "Choisissez un type de chambre 😊\n"
                "T1 (25.000F), T2 (30.000F), T3 (35.000F) ou T4 (40.000F). "
                "Ex : 'T2'"
            )
        data["room_type"] = room
        set_session_state(channel, user_id, "collect_phone", data)
        return (
            f"Excellent choix ! {ROOM_LABELS[room]} ✨\n"
            "4️⃣ Votre NUMÉRO de téléphone pour la confirmation ? "
            "(Ex : 0747123456)"
        )

    # Étape 4 : téléphone
    if current_state == "collect_phone":
        phone = format_phone(text)
        data["phone"] = phone
        book = save_prebooking(
            channel=channel,
            user_id=user_id,
            name=data.get("name"),
            check_in=data.get("check_in"),
            check_out=data.get("check_out"),
            room_type=data.get("room_type"),
            phone=phone or None,
            notes="Pré-réservation via le bot",
        )
        clear_session_state(channel, user_id)
        price = {
            "T1": "25.000 F", "T2": "30.000 F", "T3": "35.000 F", "T4": "40.000 F",
        }.get(data.get("room_type"), "?")
        return (
            f"🎉 Pré-réservation confirmée #{book.id} !\n\n"
            f"👤 {data.get('name')}\n"
            f"📅 {data.get('check_in')}" + (f" au {data.get('check_out')}" if data.get("check_out") else "")
            + f"\n🛏️ {data.get('room_type')} ({price}/nuit)\n"
            f"📞 {phone or 'non renseigné'}\n\n"
            "💰 Paiement : espèces, Wave, Orange Money ou MTN Money.\n"
            "📞 Notre équipe vous confirmera au 01 42 30 84 84.\n"
            "Merci, à bientôt au Pôpaix ! 🌴"
        )

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
            "footer": {"text": "Hôtel Pôpaix 🌴"},
            "action": {
                "button": "Voir les chambres",
                "sections": [{"title": "Types de chambre", "rows": rows}],
            },
        },
    }