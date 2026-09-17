import asyncio
import os
import threading
from datetime import date

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

from ai_provider import ask_ai
from database import (
    clear_session_state,
    get_recent_history,
    get_session_state,
    save_conversation,
    set_session_state,
)
from flows import BOOKING_MAX_MONTHS, get_booking_data, handle_message, set_dates, set_room
from presentation import (
    CTA_TEXT,
    HOTEL_INTRO,
    ROOMS_HEADER,
    RESTAURANT_TEXT,
    room_button_label,
    room_card_caption,
    services_text,
)
from rooms import IMAGE_URLS, ROOM_INFO
from telegram_picker import (
    build_date_calendar,
    booking_limits,
    parse_cal_callback,
    shift_month,
)

USER_LOCKS: dict[str, threading.Lock] = {}
USER_LOCKS_GUARD = threading.Lock()


def get_user_lock(key: str) -> threading.Lock:
    with USER_LOCKS_GUARD:
        if key not in USER_LOCKS:
            USER_LOCKS[key] = threading.Lock()
        return USER_LOCKS[key]


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

MIN_DATE, MAX_DATE = booking_limits(BOOKING_MAX_MONTHS)

ROOM_LIST_FALLBACK = "\n\n".join(room_card_caption(r) for r in ["T1", "T2", "T3", "T4"])


def _wants_room_cards(text: str) -> bool:
    """Le client demande à VOIR les chambres → cartes (album + boutons réserver)."""
    t = text.lower()
    return any(
        w in t
        for w in (
            "chambre", "chambres", "carte", "cartes",
            "photos", "photos des chambres", "voir les chambres",
            "tarif", "tarifs", "prix des chambres",
        )
    )


async def _send_media_group(context: ContextTypes.DEFAULT_TYPE, chat_id: str, media: list):
    """Album photo des chambres — repli texte si Telegram refuse l'envoi."""
    try:
        await context.bot.send_media_group(chat_id=chat_id, media=media)
    except Exception as e:
        print(f"[TELEGRAM][WARN] album échoué: {e} — repli texte", flush=True)
        await context.bot.send_message(
            chat_id,
            "🖼️ Nos chambres T1-T4 (images indisponibles pour l'instant) :\n\n"
            + ROOM_LIST_FALLBACK,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🏨 L'hôtel", "🍽️ Restaurant"],
        ["🛏️ Chambres", "💰 Tarifs"],
        ["📍 Localisation", "📞 Contact"],
        ["✅ Réserver"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Bienvenue à PO PAIX HOTEL ET EXPERIENCES 🌴\n"
        "23 chambres face plage à Fresco — réservations ouvertes.",
        reply_markup=reply_markup,
    )
    chat_id = str(update.effective_chat.id if update.effective_chat else update.effective_user.id)
    await send_presentation(context, chat_id, str(update.effective_user.id))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Dites-moi ce que vous voulez : chambres, tarifs, restaurant, services, "
        "ou choisissez directement une chambre pour réserver.\n"
        "📞 Contact : +225 0702391982 / @hotelpopaix"
    )


async def send_presentation(context: ContextTypes.DEFAULT_TYPE, chat_id: str, user_id: str):
    """Présentation d'accueil PO PAIX HOTEL ET EXPERIENCES.

    Ordre : hôtel → chambres (cartes) → restaurant & menus → services → réserver.
    Chaque bloc est visuellement séparé pour repérer facilement chaque service.
    """
    await context.bot.send_message(chat_id, HOTEL_INTRO)

    await context.bot.send_message(chat_id, ROOMS_HEADER)
    media = [
        InputMediaPhoto(media=IMAGE_URLS[room], caption=room_card_caption(room))
        for room in ["T1", "T2", "T3", "T4"]
    ]
    await _send_media_group(context, chat_id, media)

    await context.bot.send_message(chat_id, RESTAURANT_TEXT)
    await context.bot.send_message(chat_id, services_text())

    keyboard = [
        [InlineKeyboardButton(room_button_label(r), callback_data=f"room:{r}")]
        for r in ["T1", "T2", "T3", "T4"]
    ]
    await context.bot.send_message(
        chat_id, CTA_TEXT, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_room_cards(context: ContextTypes.DEFAULT_TYPE, chat_id: str, user_id: str):
    """Cartes chambres seules (bouton « Chambres »)."""
    await context.bot.send_message(chat_id, ROOMS_HEADER)
    media = [
        InputMediaPhoto(media=IMAGE_URLS[room], caption=room_card_caption(room))
        for room in ["T1", "T2", "T3", "T4"]
    ]
    await _send_media_group(context, chat_id, media)
    keyboard = [
        [InlineKeyboardButton(room_button_label(r), callback_data=f"room:{r}")]
        for r in ["T1", "T2", "T3", "T4"]
    ]
    await context.bot.send_message(
        chat_id, CTA_TEXT, reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------------------------------------------------------------- Picker UI
def _cal_state(data: dict) -> dict:
    cal = data.setdefault("_cal", {"role": "in", "m": date.today().isoformat()})
    return cal


async def send_calendar(context: ContextTypes.DEFAULT_TYPE, chat_id: str, user_id: str):
    """Envoie le calendrier inline (arrivée ou départ selon l'état du flow)."""
    data = get_booking_data("telegram", user_id)
    cal = _cal_state(data)
    set_session_state("telegram", user_id, "collect_dates", data)

    ref = date.fromisoformat(cal["m"])
    role_fr = "d'ARRIVÉE" if cal["role"] == "in" else "de DÉPART"
    await context.bot.send_message(
        chat_id,
        f"📅 Choisissez votre date {role_fr} :",
        reply_markup=build_date_calendar(
            ref.year, ref.month, MIN_DATE, MAX_DATE, cal_id="dates"
        ),
    )


async def send_room_chooser(context: ContextTypes.DEFAULT_TYPE, chat_id: str, user_id: str):
    """Album des chambres (cartes image + description) puis clavier inline."""
    media = [
        InputMediaPhoto(media=IMAGE_URLS[room], caption=room_card_caption(room))
        for room in ["T1", "T2", "T3", "T4"]
    ]
    await _send_media_group(context, chat_id, media)
    keyboard = [
        [InlineKeyboardButton(f"{ROOM_INFO[r]['title']}", callback_data=f"room:{r}")]
        for r in ["T1", "T2", "T3", "T4"]
    ]
    await context.bot.send_message(
        chat_id,
        "🛏️ Quelle chambre souhaitez-vous ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = str(update.effective_user.id)
    parsed = parse_cal_callback(q.data or "")
    if parsed is None:
        await q.answer("Oups 😅", show_alert=False)
        return

    cal_id, action, value = parsed
    data = get_booking_data("telegram", user_id)
    cal = data.get("_cal") or {"role": "in", "m": date.today().isoformat()}
    state = get_session_state("telegram", user_id)

    if action == "cancel":
        clear_session_state("telegram", user_id)
        await q.answer()
        await q.edit_message_text(
            "Réservation annulée ✅. Dites 'pré-réserver' pour recommencer."
        )
        return

    if state is None or state.state not in ("collect_dates", "collect_room"):
        await q.answer("Session expirée — dites 'pré-réserver'. 😊")
        return

    # Navigation mois précédent / suivant
    if action == "nav":
        ref = date.fromisoformat(cal["m"])
        new_month = shift_month(ref, value)
        cal["m"] = new_month.isoformat()
        set_session_state("telegram", user_id, "collect_dates", data)
        await q.answer()
        await q.edit_message_reply_markup(
            reply_markup=build_date_calendar(
                new_month.year, new_month.month, MIN_DATE, MAX_DATE, cal_id="dates"
            )
        )
        return

    if action == "blank":
        await q.answer()
        return

    # Sélection d'un jour (action "day" ou "today")
    selected = value  # date
    role = cal.get("role", "in")
    if role == "in":
        data["check_in"] = selected.strftime("%d/%m")
        cal["role"] = "out"
        cal["m"] = selected.replace(day=1).isoformat()
        set_session_state("telegram", user_id, "collect_dates", data)
        await q.answer(f"✅ Arrivée : {selected.strftime('%d/%m/%Y')}")
        await q.edit_message_text("📅 Choisissez votre date de DÉPART :")
        await q.edit_message_reply_markup(
            reply_markup=build_date_calendar(
                selected.year, selected.month, MIN_DATE, MAX_DATE, cal_id="dates"
            )
        )
        return

    # Départ sélectionné → validation de la plage + envoi des cartes chambres
    data["check_out"] = selected.strftime("%d/%m")
    reply = set_dates(
        "telegram", user_id, data["check_in"], data["check_out"], ""
    )
    if not reply.startswith("Parfait"):
        await q.answer("Dates invalides ⚠️")
        await q.edit_message_text(reply)
        await q.edit_message_reply_markup(
            reply_markup=build_date_calendar(
                selected.year, selected.month, MIN_DATE, MAX_DATE, cal_id="dates"
            )
        )
        return

    await q.answer(f"✅ Départ : {selected.strftime('%d/%m/%Y')}")
    await q.edit_message_text(reply)


async def room_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = str(update.effective_user.id)
    if not (q.data or "").startswith("room:"):
        await q.answer()
        return
    room = q.data.split(":", 1)[1]
    reply = set_room("telegram", user_id, room)
    if "Quelle offre" in reply:
        await q.answer("Chambre invalide 😊")
        return
    await q.answer(f"✅ {room} sélectionné")
    chat_id = str(update.effective_chat.id if update.effective_chat else user_id)
    sent = False
    if q.message:
        try:
            await q.edit_message_text(reply)
            sent = True
        except Exception:
            pass
    if not sent:
        await context.bot.send_message(chat_id=chat_id, text=reply)

    # Étape suivante : les dates → on envoie le calendrier
    state = get_session_state("telegram", user_id)
    if state and state.state == "collect_dates":
        await send_calendar(context, chat_id, user_id)


# ---------------------------------------------------------------- Messages
async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    # Mapping boutons du clavier
    button_map = {
        "🏨 L'hôtel": "__presentation__",
        "💰 Tarifs": "Quels sont les tarifs ?",
        "🛏️ Chambres": "__rooms__",
        "🍽️ Restaurant": "Qu'est-ce que vous servez au restaurant ?",
        "📞 Contact": "Quel est votre contact ?",
        "📍 Localisation": "Où êtes-vous situés ?",
        "✅ Réserver": "Je veux pré-réserver",
    }
    text = button_map.get(text, text)

    chat_id = str(update.effective_chat.id if update.effective_chat else user_id)

    with get_user_lock(f"telegram:{user_id}"):
        history = [
            (c.user_message, c.bot_reply)
            for c in get_recent_history("telegram", user_id, limit=6)
        ]

        # Boutons du menu : rejouer la présentation / les cartes chambres
        if text == "__presentation__":
            await send_presentation(context, chat_id, user_id)
            save_conversation("telegram", user_id, "[présentation]", "[présentation envoyée]")
            return
        if text == "__rooms__":
            await send_room_cards(context, chat_id, user_id)
            save_conversation("telegram", user_id, "[chambres]", "[cartes chambres envoyées]")
            return

        reply = handle_message("telegram", user_id, text)
        if reply:
            await update.message.reply_text(reply)
            save_conversation("telegram", user_id, text, reply)

            # Envoi du picker natif correspondant à l'étape courante
            state = get_session_state("telegram", user_id)
            if state and state.state == "collect_dates":
                await send_calendar(context, chat_id, user_id)
            elif state and state.state == "collect_room":
                await send_room_chooser(context, chat_id, user_id)
            return

        # Nouvelle discussion sans historique → présentation d'accueil
        if not history:
            await send_presentation(context, chat_id, user_id)
            save_conversation("telegram", user_id, text, "[présentation envoyée]")
            return

        # Demande de voir les chambres → cartes (album + boutons) au lieu du texte IA
        if _wants_room_cards(text):
            await send_room_cards(context, chat_id, user_id)
            save_conversation("telegram", user_id, text, "[cartes chambres envoyées]")
            return

        reply = ask_ai(text, history)
        await update.message.reply_text(reply)
        save_conversation("telegram", user_id, text, reply)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from database import clear_session_state

    clear_session_state("telegram", str(update.effective_user.id))
    await update.message.reply_text("Réservation annulée ✅. Dites 'pré-réserver' pour recommencer.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import traceback

    print(
        f"[TELEGRAM-ERROR] update={update.update_id if update else 'n/a'} — {context.error}",
        flush=True,
    )
    traceback.print_exc()


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN)
    app = (
        app
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern=r"^cal:"))
    app.add_handler(CallbackQueryHandler(room_callback, pattern=r"^room:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))
    app.add_error_handler(error_handler)
    return app


_APP: Application | None = None
_APP_LOCK = asyncio.Lock()


async def get_application() -> Application:
    """Application PTB partagée, initialisée une seule fois (mode webhook)."""
    global _APP
    async with _APP_LOCK:
        if _APP is None:
            _APP = build_application()
            await _APP.initialize()
        return _APP


async def process_telegram_update(data: dict) -> None:
    """Traite une mise à jour Telegram reçue par webhook (mode serverless)."""
    app = await get_application()
    update = Update.de_json(data, app.bot)
    if update is not None:
        await app.process_update(update)


def run_telegram():
    app = build_application()
    print("🤖 PopaixBot Telegram démarré (polling)...")
    app.run_polling()


if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN manquant. Voir .env.example")
    run_telegram()