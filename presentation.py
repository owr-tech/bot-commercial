"""Présentation commerciale PO PAIX HOTEL ET EXPERIENCES.

Contenu unique (source de vérité) réutilisé par tous les canaux :
chat IA, Telegram (album + clavier inline), WhatsApp (images + listes).

Convention des cartes chambres : inspirée des cartes booking.com
(image + standard + description + prix + bouton « Réserver »).
"""

from rooms import ROOM_INFO

HOTEL_NAME = "PO PAIX HOTEL ET EXPERIENCES"

LINE = "━━━━━━━━━━━━━━━━━━━━"

HOTEL_INTRO = (
    f"🌴✨ {HOTEL_NAME} ✨🌴\n"
    f"{LINE}\n"
    "Votre havre de paix sur le front lagunaire, à Fresco (Gbôkle), "
    "Côte d'Ivoire.\n\n"
    "🏨 23 chambres climatisées face plage/lagune Koyiri\n"
    "💦 Nouvelle piscine · plage privée · rooftop · jardin\n"
    "🍽️ Restaurant ANWUKWA (cuisine halal)\n"
    "🎉 Réservations OUVERTES dès aujourd'hui\n\n"
    "Découvrez ci-dessous nos chambres, notre restaurant et nos services."
)

ROOMS_HEADER = (
    f"🛏️ NOS CHAMBRES T1 À T4\n{LINE}\n"
    "Chaque chambre a son standard et son prix. Choisissez votre offre 👇"
)

RESTAURANT_TEXT = (
    f"🍽️ RESTAURANT ANWUKWA\n{LINE}\n"
    "🧊 Sorbets — 2.000 F\n"
    "🍕 Pizza Margherita — 4.000 F + boisson\n"
    "🍕 Pizza Royale — 5.000 F + boisson\n"
    f"{LINE}\n"
    "🌍 Cuisine africaine / caribéenne / française — 100% halal"
)

# Chaque catégorie est un bloc visuellement distinct (icône + titre + séparateur)
SERVICE_SECTIONS = [
    {
        "icon": "🛎️",
        "title": "CONFORT & RÉCEPTION",
        "items": [
            "WiFi gratuit · climatisation · réception 24h/24",
            "Room service 24h/24 · conciergerie · lave-linge",
        ],
    },
    {
        "icon": "💆",
        "title": "DÉTENTE & LOISIRS",
        "items": [
            "Piscine · plage privée · rooftop · jardin",
            "Bar / lounge · casino · salle de jeux (arcade)",
            "Pêche · randonnée · barbecue (BBQ)",
            "Pataugeoire & aire de jeux enfants",
        ],
    },
    {
        "icon": "🚗",
        "title": "PRATIQUE & DÉCOUVERTE",
        "items": [
            "Parking gratuit · salle de réunion",
            "Assistance visites & billets · conciergerie",
        ],
    },
    {
        "icon": "🐾",
        "title": "BON À SAVOIR",
        "items": [
            "Animaux acceptés · établissement non-fumeur",
            "Check-in 10:00 · Check-out 13:00",
        ],
    },
]

CTA_TEXT = (
    f"{LINE}\n"
    "👉 PRÊT À RÉSERVER ? Choisissez votre chambre T1-T4 ci-dessous ⬇️\n"
    "💳 Paiement sécurisé (Wave, Orange Money, MTN, carte) ou espèces sur place."
)


def room_card_caption(room: str, lang: str = "fr") -> str:
    """Légende « carte booking.com » d'une chambre : standard + prix + CTA."""
    info = ROOM_INFO[room]
    desc = info.get(lang) or info["fr"]
    tags = " · ".join(info.get("tags", []))
    lines = [
        f"🏨 {info['title']}  ({room})",
        desc,
        f"💵 {info['price_label']} / nuit",
    ]
    if tags:
        lines.append(f"✅ {tags}")
    lines.append("👉 Réservez avec le bouton ci-dessous")
    return "\n".join(lines)


def room_button_label(room: str) -> str:
    info = ROOM_INFO[room]
    return f"Réserver {room} · {info['price_label']}"


def services_text() -> str:
    parts = [f"🎯 NOS SERVICES\n{LINE}"]
    for section in SERVICE_SECTIONS:
        block = [f"\n{section['icon']} {section['title']}"]
        block.extend(f"• {item}" for item in section["items"])
        parts.append("\n".join(block))
    return "\n".join(parts)


def full_presentation_text() -> str:
    """Présentation complète en un seul message (fallback IA / test)."""
    lines = [HOTEL_INTRO, "", ROOMS_HEADER]
    for room in ("T1", "T2", "T3", "T4"):
        lines.append("")
        lines.append(room_card_caption(room))
    lines += ["", RESTAURANT_TEXT, "", services_text(), "", CTA_TEXT]
    return "\n".join(lines)
