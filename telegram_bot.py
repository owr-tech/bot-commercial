import asyncio
import os
import threading

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from ai_provider import ask_ai
from database import get_recent_history, save_conversation
from flows import handle_message

USER_LOCKS: dict[str, threading.Lock] = {}
USER_LOCKS_GUARD = threading.Lock()


def get_user_lock(key: str) -> threading.Lock:
    with USER_LOCKS_GUARD:
        if key not in USER_LOCKS:
            USER_LOCKS[key] = threading.Lock()
        return USER_LOCKS[key]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🏨 L'hôtel", "💰 Tarifs"],
        ["🛏️ Chambres", "🍕 Restaurant"],
        ["📅 Réouverture", "📞 Contact"],
        ["✅ Pré-réserver"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Bienvenue à l'Hôtel Pôpaix 🌴 23 chambres face plage à Fresco.\n"
        "Réouverture le 15 décembre 2026 avec piscine !\n"
        "Posez vos questions ou appuyez sur un bouton :",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Dites-moi ce que vous voulez : tarifs, chambres, réouverture, "
        "ou 'pré-réserver' pour commencer votre réservation.\n"
        "📞 Contact : 01 42 30 84 84 / @hotelpopaix"
    )


async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    # Mapping boutons du clavier
    button_map = {
        "🏨 L'hôtel": "Présente-moi l'hôtel",
        "💰 Tarifs": "Quels sont les tarifs ?",
        "🛏️ Chambres": "Quelles sont les chambres ?",
        "🍕 Restaurant": "Qu'est-ce que vous servez au restaurant ?",
        "📅 Réouverture": "Quand est la réouverture ?",
        "📞 Contact": "Quel est votre contact ?",
        "✅ Pré-réserver": "Je veux pré-réserver",
    }
    text = button_map.get(text, text)

    with get_user_lock(f"telegram:{user_id}"):
        history = [
            (c.user_message, c.bot_reply)
            for c in get_recent_history("telegram", user_id, limit=6)
        ]

        reply = handle_message("telegram", user_id, text)
        if reply:
            await update.message.reply_text(reply)
            save_conversation("telegram", user_id, text, reply)
            return

        reply = ask_ai(text, history)
        await update.message.reply_text(reply)
        save_conversation("telegram", user_id, text, reply)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from database import clear_session_state

    clear_session_state("telegram", str(update.effective_user.id))
    await update.message.reply_text("Réservation annulée ✅. Dites 'pré-réserver' pour recommencer.")


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))
    return app


def run_telegram():
    app = build_application()
    print("🤖 PopaixBot Telegram démarré (polling)...")
    app.run_polling()


if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN manquant. Voir .env.example")
    run_telegram()