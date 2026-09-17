"""Spec UI générative (standard OpenUI — https://www.openui.com).

Le DSL est décrit composant par composant : chaque composant est un objet
`{type, id, args}` (composants Thesys). `build()` retourne l'arbre `Root`
décrivant l'étape de réservation du bot. Chaque renderer de canal
(telegram_picker / whatsapp_flow / telegram_bot) le traduit en widgets natifs.

Exemple :

    >>> spec = build_booking_screen()
    >>> spec.components[0].type  == "DateRangePicker"
"""


class Component:
    def __init__(self, type: str, id: str, **args):
        self.type = type
        self.id = id
        self.args = args

    def to_dict(self) -> dict:
        return {"type": self.type, "id": self.id, **self.args}

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        return f"<{self.type} id={self.id!r} {args}>"


def Action(id: str, label: str, value: str) -> Component:
    return Component("Action", id, label=label, value=value)


def RoomCard(room: str, room_info: dict, lang: str = "fr") -> Component:
    """Carte OpenUI : image + description + prix + action de sélection."""
    return Component(
        "RoomCard",
        f"room_{room}",
        room=room,
        title=room_info["title"],
        description=room_info[lang] if lang in room_info else room_info["fr"],
        price=room_info["price_label"],
        image=room_info["image"],
        action=Action(f"select_{room}", f"Choisir {room}", room),
    )


def build_booking_screen(min_date: str, max_date: str, lang: str = "fr") -> Component:
    """Écran principal de réservation : DatesPicker + Grid de RoomCards."""
    from rooms import ROOM_INFO

    root = Component(
        "Root",
        "popaix_booking",
        screen="booking",
        lang=lang,
        components=[
            Component(
                "DateRangePicker",
                "dates",
                min_date=min_date,
                max_date=max_date,
                labels={
                    "check_in": "Arrivée" if lang == "fr" else "Check-in",
                    "check_out": "Départ" if lang == "fr" else "Check-out",
                },
            ),
            Component(
                "RoomGrid",
                "rooms",
                columns=2,
                components=[
                    RoomCard(room, ROOM_INFO[room], lang=lang)
                    for room in ["T1", "T2", "T3", "T4"]
                ],
            ),
        ],
    )
    return root


if __name__ == "__main__":
    import json

    from datetime import date, timedelta

    today = date.today()
    future = today + timedelta(days=365)
    spec = build_booking_screen(today.isoformat(), future.isoformat())
    print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))