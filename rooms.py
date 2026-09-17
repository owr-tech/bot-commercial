"""Cartes des chambres T1-T4 — image + description (source unique pour tous les canaux).

Photographies libres (Unsplash, licence gratuite) hébergées sur le CDN
https://images.unsplash.com — url stables, aucun binaire dans le dépôt.
"""

# T1-T4 : affichage bilingue FR / EN + prix (FCFA/nuit) + points forts + image
ROOM_INFO = {
    "T1": {
        "title": "T1 — Standard",
        "fr": "Chambre standard climatisée, lit queen, douche, WiFi",
        "en": "Air-conditioned standard room, queen bed, shower, WiFi",
        "price": 25000,
        "price_label": "25.000 F",
        "tags": ["Clim", "Douche", "WiFi", "Balcon"],
        "image": (
            "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85"
            "?w=900&q=80&fm=jpg&fit=crop"
        ),
    },
    "T2": {
        "title": "T2 — Supérieure",
        "fr": "Chambre supérieure avec coin salon et vue jardin",
        "en": "Superior room with sitting area and garden view",
        "price": 30000,
        "price_label": "30.000 F",
        "tags": ["Clim", "Coin salon", "WiFi", "Balcon"],
        "image": (
            "https://images.unsplash.com/photo-1618773928121-c32242e63f39"
            "?w=900&q=80&fm=jpg&fit=crop"
        ),
    },
    "T3": {
        "title": "T3 — Deluxe",
        "fr": "Deluxe spacieuse, literie premium, vue lagune",
        "en": "Spacious Deluxe, premium bedding, lagoon view",
        "price": 35000,
        "price_label": "35.000 F",
        "tags": ["Literie premium", "Vue lagune", "Balcon", "Clim"],
        "image": (
            "https://images.unsplash.com/photo-1611892440504-42a792e24d32"
            "?w=900&q=80&fm=jpg&fit=crop"
        ),
    },
    "T4": {
        "title": "T4 — Suite Prestige",
        "fr": "Suite prestige avec salon séparé et terrasse face plage",
        "en": "Prestige suite with separate lounge and beach terrace",
        "price": 40000,
        "price_label": "40.000 F",
        "tags": ["Salon", "Terrasse", "Face plage", "Room service"],
        "image": (
            "https://images.unsplash.com/photo-1590490360182-c33d57733427"
            "?w=900&q=80&fm=jpg&fit=crop"
        ),
    },
}

IMAGE_URLS = {key: info["image"] for key, info in ROOM_INFO.items()}


def room_caption(room: str, lang: str = "fr", with_price: bool = True) -> str:
    """Légende 'carte' d'une chambre (ex : légende photo / carte WhatsApp)."""
    info = ROOM_INFO[room]
    desc = info[lang] if lang in info else info["fr"]
    header = f"{info['title']}"
    lines = [header, desc]
    if with_price:
        lines.append("💵 " + info["price_label"] + "/nuit")
    return "\n".join(lines)


def room_short_label(room: str) -> str:
    return f"{room} - {ROOM_INFO[room]['price_label']}/nuit"


def room_image(room: str) -> str:
    return ROOM_INFO[room]["image"]