"""Calendrier inline Telegram (recette API InlineKeyboard + callback_data).

RenderThread du composant OpenUI `DateRangePicker` pour le canal Telegram :
un calendrier plein mois avec navigation ◀ ▶, jours passés désactivés et
raccourci « Aujourd'hui ». La sélection est renvoyée par CallbackQuery.

Format des callback_data (≤ 64 octets, fiable) :
    cal:{cal_id}:nav:{±1}
    cal:{cal_id}:day:{YYYY-MM-DD}
    cal:{cal_id}:today
    cal:{cal_id}:cancel
    cal:{cal_id}:blank
"""

from calendar import monthrange
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
WEEKDAYS_FR = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"]


def _cmd(cal_id: str, action: str, value: str = "") -> str:
    if value:
        return f"cal:{cal_id}:{action}:{value}"
    return f"cal:{cal_id}:{action}"


def first_day_of_month(ref: date) -> date:
    return ref.replace(day=1)


def shift_month(ref: date, delta: int) -> date:
    month = ref.month - 1 + delta
    year = ref.year + month // 12
    return ref.replace(year=year, month=month % 12 + 1, day=1)


def build_date_calendar(
    year: int,
    month: int,
    min_date: date,
    max_date: date,
    cal_id: str = "dates",
    today_shortcut: bool = True,
) -> InlineKeyboardMarkup:
    """Clavier calendrier pour un mois donné.

    - Jour passé (< min_date) ou au-delà de max_date → bouton « · » inactif.
    - min_date/max_date bornent l'étendue choisissable.
    """
    today = date.today()
    first = date(year, month, 1)
    nb_days = monthrange(year, month)[1]
    buttons: list[list[InlineKeyboardButton]] = []

    # Navigation ◀  Mois Année  ▶
    prev = shift_month(first, -1)
    nxt = shift_month(first, 1)
    buttons.append(
        [
            InlineKeyboardButton("◀", callback_data=_cmd(cal_id, "nav", "-1")),
            InlineKeyboardButton(f"{MONTHS_FR[month - 1]} {year}", callback_data=_cmd(cal_id, "blank")),
            InlineKeyboardButton("▶", callback_data=_cmd(cal_id, "nav", "1")),
        ]
    )

    # Jours de la semaine (lundi → dimanche)
    buttons.append(
        [InlineKeyboardButton(d, callback_data=_cmd(cal_id, "blank")) for d in WEEKDAYS_FR]
    )

    # Grille des jours (python weekday(): lundi=0 … dimanche=6)
    start_dow = first.weekday()
    row: list[InlineKeyboardButton] = [InlineKeyboardButton(" ", callback_data=_cmd(cal_id, "blank"))] * start_dow
    for day in range(1, nb_days + 1):
        d = date(year, month, day)
        if d < min_date or d > max_date:
            row.append(InlineKeyboardButton("·", callback_data=_cmd(cal_id, "blank")))
        else:
            row.append(
                InlineKeyboardButton(
                    str(day),
                    callback_data=_cmd(
                        cal_id,
                        "day" if d >= min_date else "today",
                        d.isoformat(),
                    ),
                )
            )
        if len(row) == 7:
            buttons.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(" ", callback_data=_cmd(cal_id, "blank")))
        buttons.append(row)

    # Ligne d'actions
    actions = []
    if today_shortcut and min_date <= today <= max_date:
        actions.append(
            InlineKeyboardButton("✅ Aujourd'hui", callback_data=_cmd(cal_id, "today"))
        )
    actions.append(InlineKeyboardButton("❌ Annuler", callback_data=_cmd(cal_id, "cancel")))
    buttons.append(actions)

    return InlineKeyboardMarkup(buttons)


def parse_cal_callback(data: str) -> tuple[str, str, object] | None:
    """Parse un callback cal:... → (cal_id, action, value).

    value : date, int (delta nav) ou None (blank/cancel/today).
    """
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "cal":
        return None
    cal_id = parts[1]
    action = parts[2]
    value = parts[3] if len(parts) > 3 else None
    if action == "nav":
        return cal_id, action, int(value)
    if action == "day":
        return cal_id, action, date.fromisoformat(value)
    return cal_id, action, None


def calendar_for_booking(
    min_date: date,
    max_date: date,
    current_month: date | None = None,
    cal_id: str = "dates",
) -> InlineKeyboardMarkup:
    """Calendrier ouvert sur le mois courant (ou celui sélectionné)."""
    ref = current_month or date.today()
    return build_date_calendar(
        ref.year, ref.month, min_date, max_date, cal_id=cal_id
    )


def booking_limits(max_months: int = 12) -> tuple[date, date]:
    """Bornes de réservation : aujourd'hui → +N mois (défaut 12)."""
    from calendar import monthrange

    def add_months(d: date, months: int) -> date:
        month = d.month - 1 + months
        year = d.year + month // 12
        month = month % 12 + 1
        last = monthrange(year, month)[1]
        return date(year, month, min(d.day, last))

    today = date.today()
    return today, add_months(today, max_months)