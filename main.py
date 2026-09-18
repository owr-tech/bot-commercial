import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()

USER_LOCKS: dict[str, threading.Lock] = {}
USER_LOCKS_GUARD = threading.Lock()


def get_user_lock(key: str) -> threading.Lock:
    with USER_LOCKS_GUARD:
        if key not in USER_LOCKS:
            USER_LOCKS[key] = threading.Lock()
        return USER_LOCKS[key]

from ai_provider import ask_ai
from database import (
    clear_session_state,
    get_recent_history,
    get_session_state,
    get_stats,
    get_all_prebookings,
    get_prebooking,
    save_conversation,
    update_prebooking_status,
    mark_prebooking_paid,
)
from flows import handle_message, build_whatsapp_interactive_rooms, apply_flow_booking
from payments import PayDunyaAPI
from rooms import ROOM_INFO
from whatsapp_flow import (
    ensure_flow,
    parse_flow_completion,
    refresh_flow_json,
    send_dates_flow,
)

app = FastAPI(title="Hôtel Pôpaix Bot")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "popaix2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = (
    os.getenv("WHATSAPP_PHONE_ID") or os.getenv("PHONE_NUMBER_ID") or os.getenv("PHONE_ID") or ""
)
WABA_ID = os.getenv("WABA_ID", "")
GRAPH_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
GRAPH_MEDIA_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/media"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

WHATSAPP_REDIRECT_NUMBER = "".join(
    c for c in os.getenv("WHATSAPP_REDIRECT_NUMBER", "2250702391982") if c.isdigit()
) or "2250702391982"
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "popaixbot")

# Flow WhatsApp (calendrier + chambres) — résolu au démarrage
FLOW_CTX: dict = {"id": os.getenv("WA_FLOW_ID", "").strip(), "name": os.getenv("WA_FLOW_NAME", "popaix_dates")}

try:
    os.makedirs("templates", exist_ok=True)
except OSError as e:
    # FS en lecture seule (serverless) : les templates sont déjà bundlés.
    print(f"[WARN] templates/ non créé: {e}")


def send_telegram_text(chat_id: str, text: str):
    if not TELEGRAM_TOKEN:
        print(f"[SEND][telegram→{chat_id}] {text}")
        return
    import requests

    res = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=20,
    )
    if not res.ok:
        print(f"[ERROR] Telegram send failed: {res.status_code} {res.text}")


# ---------------------------------------------------------------- WhatsApp
@app.get("/webhook")
def verify_webhook(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


def send_whatsapp_text(to: str, text: str):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[SEND][whatsapp→{to}] {text}")
        return
    import requests

    res = requests.post(
        GRAPH_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": to, "text": {"body": text}},
    )
    if not res.ok:
        print(f"[ERROR] WhatsApp send failed: {res.status_code} {res.text}")


def send_whatsapp_interactive(to: str, payload: dict):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[SEND][interactive→{to}] {payload}")
        return
    import requests

    body = {"messaging_product": "whatsapp", "to": to, **payload}
    res = requests.post(
        GRAPH_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json=body,
    )
    if not res.ok:
        print(f"[ERROR] WhatsApp interactive failed: {res.status_code} {res.text}")


def send_whatsapp_image(to: str, image_url: str, caption: str = ""):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[SEND][image→{to}] {caption or image_url}")
        return
    import requests

    res = requests.post(
        GRAPH_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url, "caption": caption},
        },
        timeout=30,
    )
    if not res.ok:
        print(f"[ERROR] WhatsApp image failed: {res.status_code} {res.text}")


def upload_whatsapp_media(data: bytes, filename: str, mime: str = "application/pdf"):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        return None
    import requests

    res = requests.post(
        GRAPH_MEDIA_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, data, mime)},
        timeout=60,
    )
    if res.ok:
        return res.json().get("id")
    print(f"[ERROR] WhatsApp media upload: {res.status_code} {res.text}")
    return None


def send_whatsapp_document(to: str, data: bytes, filename: str, caption: str = ""):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[SEND][document→{to}] {filename} ({len(data)} o)")
        return
    media_id = upload_whatsapp_media(data, filename)
    if not media_id:
        return
    import requests

    res = requests.post(
        GRAPH_URL,
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {"id": media_id, "filename": filename, "caption": caption},
        },
        timeout=30,
    )
    if not res.ok:
        print(f"[ERROR] WhatsApp document send: {res.status_code} {res.text}")


def send_telegram_document(chat_id: str, data: bytes, filename: str, caption: str = ""):
    if not TELEGRAM_TOKEN:
        print(f"[SEND][telegram doc→{chat_id}] {filename} ({len(data)} o)")
        return
    import requests

    res = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
        data={"chat_id": chat_id, "caption": caption},
        files={"document": (filename, data, "application/pdf")},
        timeout=60,
    )
    if not res.ok:
        print(f"[ERROR] Telegram document failed: {res.status_code} {res.text}")


def handle_whatsapp_message(phone: str, text: str):
    # Sérialisation : empêche le désordre des messages d'un même client
    with get_user_lock(f"whatsapp:{phone}"):
        history = [
            (c.user_message, c.bot_reply)
            for c in get_recent_history("whatsapp", phone, limit=6)
        ]

        # 1) Bouton chambre choisi (liste interactive)
        if text in ("ROOM_T1", "ROOM_T2", "ROOM_T3", "ROOM_T4"):
            text = text.replace("ROOM_", "")

        # 2) Flow pré-réservation : OFFRE → NOM → DATES → TÉLÉPHONE
        reply = handle_message("whatsapp", phone, text)
        if reply:
            send_whatsapp_text(phone, reply)
            save_conversation("whatsapp", phone, text, reply)
            state = get_session_state("whatsapp", phone)
            if state and state.state == "collect_room":
                _send_whatsapp_room_cards(phone)
            elif state and state.state == "collect_dates":
                _send_whatsapp_dates_flow(phone)
            return

        # 3) Nouvelle discussion sans historique → présentation d'accueil
        if not history:
            send_whatsapp_presentation(phone)
            save_conversation("whatsapp", phone, text, "[présentation envoyée]")
            return

        # 4) Chat libre via IA
        reply = ask_ai(text, history)
        send_whatsapp_text(phone, reply)
        save_conversation("whatsapp", phone, text, reply)


def send_whatsapp_presentation(phone: str):
    """Présentation PO PAIX HOTEL ET EXPERIENCES (hôtel, chambres, restaurant, services)."""
    from presentation import (
        HOTEL_INTRO,
        RESTAURANT_TEXT,
        room_card_caption,
        services_text,
    )

    send_whatsapp_text(phone, HOTEL_INTRO)
    for room in ["T1", "T2", "T3", "T4"]:
        send_whatsapp_image(phone, ROOM_INFO[room]["image"], room_card_caption(room))
    send_whatsapp_text(phone, RESTAURANT_TEXT)
    send_whatsapp_text(phone, services_text())
    send_whatsapp_interactive(phone, build_whatsapp_interactive_rooms())


def _send_whatsapp_dates_flow(phone: str):
    """Envoie le Flow natif (calendrier + chambres). Repli silencieux si indispo."""
    ensure_flow_ready()
    ok = send_dates_flow(
        to=phone,
        phone_id=WHATSAPP_PHONE_ID,
        token=WHATSAPP_TOKEN,
        flow_ctx=FLOW_CTX,
    )
    if not ok:
        send_whatsapp_text(
            phone,
            "Vous pouvez aussi m'écrire vos dates, ex : 'du 20 au 25 décembre'.",
        )


def _send_whatsapp_room_cards(phone: str):
    """Cartes chambres (image + description) puis liste interactive de choix."""
    from presentation import room_card_caption

    for room in ["T1", "T2", "T3", "T4"]:
        send_whatsapp_image(phone, ROOM_INFO[room]["image"], room_card_caption(room))
    send_whatsapp_interactive(phone, build_whatsapp_interactive_rooms())


def handle_whatsapp_flow_reply(phone: str, msg: dict):
    """Traite la soumission d'un Flow WhatsApp (dates + chambre)."""
    from database import get_session_state

    state = get_session_state("whatsapp", phone)
    if not state or state.state != "collect_dates":
        send_whatsapp_text(
            phone,
            "Merci ! Pour réserver, dites 'pré-réserver' et je vous guide. 🌴",
        )
        return

    with get_user_lock(f"whatsapp:{phone}"):
        payload = parse_flow_completion(msg)
        if not payload:
            send_whatsapp_text(
                phone,
                "Je n'ai pas reçu vos choix 😅 Réessayez ou écrivez vos dates "
                "(ex : 'du 20 au 25 décembre').",
            )
            return
        reply = apply_flow_booking("whatsapp", phone, payload)
        send_whatsapp_text(phone, reply)
        save_conversation("whatsapp", phone, "[flow-dates-chambre]", reply)


@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    phone = msg.get("from")
                    if not phone:
                        continue
                    if msg.get("type") == "flow":
                        handle_whatsapp_flow_reply(phone, msg)
                        continue
                    if msg.get("type") == "text":
                        text = msg["text"]["body"]
                    elif msg.get("type") == "interactive":
                        inter = msg["interactive"]
                        if inter.get("type") == "list_reply":
                            text = inter["list_reply"]["id"]
                        elif inter.get("type") == "button_reply":
                            text = inter["button_reply"]["id"]
                        else:
                            continue
                    else:
                        continue
                    handle_whatsapp_message(phone, text)
    except Exception as e:
        print(f"[ERROR] WhatsApp webhook: {e}")
    return {"status": "ok"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Webhook Telegram (mode serverless, remplace le polling)."""
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        data = await request.json()
    except Exception as e:
        print(f"[ERROR] Telegram webhook JSON: {e}")
        return {"ok": True}
    try:
        from telegram_bot import process_telegram_update

        await process_telegram_update(data)
    except Exception as e:
        print(f"[ERROR] Telegram webhook: {e}")
    return {"ok": True}


@app.get("/admin/set-telegram-webhook")
def set_telegram_webhook(secret: str = ""):
    """Enregistre l'URL du webhook Telegram (une seule fois après déploiement)."""
    admin_secret = os.getenv("ADMIN_SECRET", "")
    if not admin_secret or secret != admin_secret:
        raise HTTPException(status_code=403, detail="forbidden")
    if not TELEGRAM_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_TOKEN manquant")
    import requests

    payload = {
        "url": f"{PUBLIC_BASE_URL}/webhook/telegram",
        "allowed_updates": ["message", "callback_query"],
    }
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if webhook_secret:
        payload["secret_token"] = webhook_secret
    res = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
        json=payload,
        timeout=30,
    )
    return res.json()


# ---------------------------------------------------------------- PayDunya
@app.post("/webhook/paydunya")
async def paydunya_webhook(request: Request):
    """Callback IPN PayDunya — confirmé uniquement si signature valide."""
    from urllib.parse import parse_qs

    try:
        raw = await request.body()
    except Exception as e:
        print(f"[PAYDUNYA][ERROR] lecture corps: {e}")
        return {"status": "ignored", "reason": "bad_body"}

    # PayDunya poste x-www-form-urlencoded : data[field][sub]=value...
    parsed = parse_qs(raw.decode("utf-8", errors="replace"))

    def _unflatten():
        root = {}
        for key, values in parsed.items():
            keys = [k.rstrip("]") for k in key.split("[")]
            keys = [k for k in keys if k]
            if len(keys) == 1:
                root[keys[0]] = values[0]
                continue
            node = root
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = values[0]
        return root

    data = _unflatten().get("data", {})
    api = PayDunyaAPI()

    # 1) Vérification de la signature (SHA-512 du MasterKey)
    if not api.verify_hash(str(data.get("hash", ""))):
        print(f"[PAYDUNYA][WARN] Webhook rejeté — hash invalide. data={data}")
        return {"status": "ignored", "reason": "bad_hash"}

    invoice_token = (
        data.get("invoice", {}).get("token")
        or data.get("invoice_token")
        or data.get("token")
    )

    # 2) Confirmation serveur du statut réel (plus fiable que le callback seul)
    try:
        conf = api.confirm(invoice_token) if invoice_token else {}
    except Exception as e:
        print(f"[PAYDUNYA][ERROR] confirm: {e}")
        conf = {}

    status = (conf.get("status") or data.get("status") or "").lower()
    response_code = str(conf.get("response_code") or data.get("response_code") or "").strip()
    custom_data = conf.get("custom_data") or {}
    try:
        total_amount = int(
            float(conf.get("invoice", {}).get("total_amount") or data.get("total_amount") or 0)
        )
    except (TypeError, ValueError):
        total_amount = 0

    # 2bis) Le statut seul ne suffit pas : PayDunya doit renvoyer response_code "00"
    if response_code and response_code != "00":
        print(
            f"[PAYDUNYA][WARN] response_code={response_code} "
            f"(token={invoice_token}) — non finalisé."
        )
        return {"status": "ok", "transaction_status": status or "unknown"}

    if status != "completed":
        print(f"[PAYDUNYA] Webhook statut '{status}' (token={invoice_token}) — non finalisé.")
        return {"status": "ok", "transaction_status": status}

    if not response_code:
        print(
            f"[PAYDUNYA][INFO] response_code absent (token={invoice_token}) "
            f"— statut '{status}' retenu."
        )

    prebooking_id = custom_data.get("prebooking_id")
    if not prebooking_id and data.get("custom_data"):
        prebooking_id = data["custom_data"].get("prebooking_id")
    try:
        prebooking_id = int(prebooking_id)
    except (TypeError, ValueError):
        prebooking_id = None

    # 3) On cherche la pré-réservation via la référence si pas de custom_data
    book = get_prebooking(prebooking_id) if prebooking_id else None
    if not book:
        try:
            from database import SessionLocal, Prebooking

            db = SessionLocal()
            book = (
                db.query(Prebooking)
                .filter(Prebooking.payment_ref == invoice_token)
                .first()
            )
            db.close()
        except Exception:
            book = None

    if not book:
        print(f"[PAYDUNYA][WARN] Aucune pré-réservation pour token={invoice_token}")
        return {"status": "ok", "transaction_status": "completed", "warn": "booking_not_found"}

    # 4) Idempotence : un callback déjà traité ne renvoie pas le voucher une 2e fois
    from booking_pdf import _is_paid

    if _is_paid(book):
        print(f"[PAYDUNYA] Réservation #{book.id} déjà payée — callback ignoré.")
        return {
            "status": "ok",
            "transaction_status": "completed",
            "prebooking_id": book.id,
            "already_paid": True,
        }

    # 4bis) Garde-fou montant : paiement partiel signalé (mais traité si PayDunya "completed")
    amount_due = book.amount_due or 0
    if total_amount and amount_due and total_amount < amount_due:
        print(
            f"[PAYDUNYA][WARN] Montant reçu {total_amount} < dû {amount_due} "
            f"pour #{book.id} — à vérifier."
        )

    # 5) Marquage payé + notification client
    mark_prebooking_paid(book.id, total_amount or book.amount_due or 0)
    update_prebooking_status(book.id, "paid")

    # 5bis) Libère la session : le client n'est plus bloqué en attente de paiement
    clear_session_state(book.channel, book.user_id)

    recap = (
        f"✅ PAIEMENT CONFIRMÉ — Réservation #{book.id} finalisée !\n\n"
        f"👤 {book.name}\n"
        f"📅 {book.check_in}" + (f" au {book.check_out}" if book.check_out else "")
        + f"\n🛏️ {book.room_type}\n"
        f"💵 Total réglé : {total_amount or book.amount_due or 0:,} FCFA\n\n"
        "🎉 Votre chambre est désormais réservée au PO PAIX HOTEL ET EXPERIENCES. À bientôt ! 🌴"
    )
    if book.channel == "telegram":
        send_telegram_text(book.user_id, recap)
    elif book.channel == "whatsapp":
        send_whatsapp_text(book.user_id, recap)
    else:
        print(f"[PAYDUNYA] Paiement #{book.id} confirmé (canal {book.channel}) :\n{recap}")

    # 6) Message de succès déjà envoyé ci-dessus → puis voucher PDF + QR
    notify_voucher(book)

    print(f"[PAYDUNYA] ✅ Réservation #{book.id} payée et confirmée.")
    return {"status": "ok", "transaction_status": "completed", "prebooking_id": book.id}


def notify_voucher(book):
    """Génère et envoie le voucher PDF (QR) sur le canal du client."""
    try:
        from booking_pdf import booking_pdf, qr_payload

        # Recharge l'état à jour (statut/paie) — évite un PDF « en attente » après paiement
        fresh = get_prebooking(book.id)
        if fresh:
            book = fresh

        pdf_bytes = booking_pdf(book)
        url = qr_payload(book.id)
        caption = (
            f"🎫 Voucher de séjour #{book.id} — PO PAIX HOTEL ET EXPERIENCES\n"
            f"Présentez le QR à la réception. Détails : {url}"
        )
        filename = f"popaix-reservation-{book.id}.pdf"
        if book.channel == "telegram":
            send_telegram_document(book.user_id, pdf_bytes, filename, caption)
            print(f"[VOUCHER] ✅ PDF #{book.id} envoyé ({len(pdf_bytes)} o) → telegram/{book.user_id}")
        elif book.channel == "whatsapp":
            send_whatsapp_document(book.user_id, pdf_bytes, filename, caption)
            print(f"[VOUCHER] ✅ PDF #{book.id} envoyé ({len(pdf_bytes)} o) → whatsapp/{book.user_id}")
        else:
            print(f"[VOUCHER] PDF #{book.id} généré ({len(pdf_bytes)} o) — canal {book.channel}, non envoyé")
        return pdf_bytes
    except Exception as e:
        print(f"[VOUCHER][ERROR] {e}")
        return None


# ---------------------------------------------------------------- Voucher & Flow
_FLOW_READY = False


def ensure_flow_ready():
    """Prépare le Flow au premier besoin (lazy) — compatible serverless."""
    global _FLOW_READY
    if _FLOW_READY or FLOW_CTX.get("id"):
        return
    _FLOW_READY = True
    _prepare_flow()


def _prepare_flow():
    """Prépare/republie le Flow WhatsApp (dates ajustées à aujourd'hui)."""
    global FLOW_CTX
    try:
        flow_id = ensure_flow(WHATSAPP_TOKEN or "", WABA_ID)
        if flow_id:
            FLOW_CTX["id"] = flow_id
            refresh_flow_json(flow_id, WHATSAPP_TOKEN or "")
            print(f"[WA-FLOW] ✅ prêt (id={flow_id})")
        else:
            print("[WA-FLOW] non disponible — repli texte/liste/images actif")
    except Exception as e:
        print(f"[WA-FLOW][WARN] préparation: {e}")


def _booking_context(book) -> dict:
    from urllib.parse import quote

    from booking_pdf import _is_paid
    from flows import compute_nights

    nights = compute_nights(book.check_in, book.check_out) or 1
    total = book.amount_paid or book.amount_due or 0
    room = ROOM_INFO.get((book.room_type or "").upper(), {})
    name = book.name or "Client"
    wa_text = f"Bonjour, je viens de payer ma réservation PO PAIX HOTEL ET EXPERIENCES #{book.id}"
    booking_url = f"{PUBLIC_BASE_URL}/booking/{book.id}"
    pdf_url = f"{PUBLIC_BASE_URL}/booking/{book.id}/pdf"
    qr_url = f"{PUBLIC_BASE_URL}/booking/{book.id}/qr.png"

    # Restriction : QR + voucher PDF uniquement une fois le paiement confirmé
    paid = _is_paid(book)
    if paid:
        status_class = ""
        status_badge = "Paiement confirmé"
        sub_text = (
            f"Merci {name} — votre séjour est confirmé. "
            "Présentez le QR ci-dessous à la réception."
        )
        total_label = "Total réglé"
        qr_section = (
            '<div class="qrwrap">'
            f'<img src="{qr_url}" alt="QR réservation">'
            "<p>Scannez ce code à l'arrivée pour valider votre séjour.</p>"
            "</div>"
        )
        pdf_action = f'<a class="btn primary" href="{pdf_url}">Télécharger le voucher PDF</a>'
    else:
        status_class = "pending"
        status_badge = "En attente de paiement"
        sub_text = (
            f"Bonjour {name} — votre réservation est enregistrée mais pas encore réglée. "
            "Le QR code et le voucher seront disponibles dès confirmation du paiement."
        )
        total_label = "Total à payer"
        qr_section = (
            '<div class="notice">🔒 QR code et voucher disponibles '
            "après confirmation du paiement.</div>"
        )
        pdf_action = (
            '<span class="btn ghost disabled">Voucher PDF — en attente de paiement</span>'
        )

    return {
        "booking_id": str(book.id),
        "name": name,
        "check_in": book.check_in or "-",
        "check_out": book.check_out or "-",
        "room_title": room.get("title", book.room_type or "-"),
        "room_desc": room.get("fr", ""),
        "room_image": room.get("image", ""),
        "nights": str(nights),
        "total": f"{total:,}".replace(",", "."),
        "status": book.status or "-",
        "paid": paid,
        "status_class": status_class,
        "status_badge": status_badge,
        "sub_text": sub_text,
        "total_label": total_label,
        "qr_section": qr_section,
        "pdf_action": pdf_action,
        "booking_url": booking_url,
        "pdf_url": pdf_url,
        "qr_url": qr_url,
        "wa_link": f"https://wa.me/{WHATSAPP_REDIRECT_NUMBER}?text={quote(wa_text)}",
        "tg_link": f"https://t.me/{TELEGRAM_BOT_USERNAME}",
    }


def _render_booking(book) -> str:
    with open(os.path.join("templates", "booking.html"), encoding="utf-8") as f:
        html = f.read()
    for key, value in _booking_context(book).items():
        html = html.replace("{{" + key + "}}", str(value))
    return html


@app.get("/booking/{booking_id}", response_class=HTMLResponse)
def booking_page(booking_id: int):
    book = get_prebooking(booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Réservation introuvable")
    return _render_booking(book)


@app.get("/booking/{booking_id}/pdf")
def booking_pdf_route(booking_id: int):
    book = get_prebooking(booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Réservation introuvable")
    from booking_pdf import _is_paid, booking_pdf

    if not _is_paid(book):
        raise HTTPException(status_code=403, detail="Voucher disponible après paiement")

    return Response(
        content=booking_pdf(book),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="popaix-reservation-{book.id}.pdf"'
        },
    )


@app.get("/booking/{booking_id}/qr.png")
def booking_qr_route(booking_id: int):
    book = get_prebooking(booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Réservation introuvable")
    from booking_pdf import _is_paid, qr_code_png, qr_payload

    if not _is_paid(book):
        raise HTTPException(status_code=403, detail="QR disponible après paiement")

    return Response(content=qr_code_png(qr_payload(book.id)), media_type="image/png")


@app.get("/api/booking/{booking_id}")
def api_booking(booking_id: int):
    book = get_prebooking(booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Réservation introuvable")
    return _booking_context(book)


# ---------------------------------------------------------------- Admin
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    with open(os.path.join("templates", "admin.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/stats")
def api_stats():
    return get_stats()


@app.get("/api/prebookings")
def api_prebookings():
    return [
        {
            "id": b.id,
            "channel": b.channel,
            "user_id": b.user_id,
            "name": b.name,
            "check_in": b.check_in,
            "check_out": b.check_out,
            "room_type": b.room_type,
            "phone": b.phone,
            "status": b.status,
            "amount_due": b.amount_due,
            "amount_paid": b.amount_paid,
            "payment_ref": b.payment_ref,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "paid_at": b.paid_at.isoformat() if b.paid_at else None,
        }
        for b in get_all_prebookings()
    ]


@app.post("/api/prebookings/{prebooking_id}/status")
async def api_update_status(prebooking_id: int, request: Request):
    body = await request.json()
    status = body.get("status")
    if status not in ("pending", "awaiting_payment", "confirmed", "paid", "cancelled"):
        raise HTTPException(status_code=400, detail="Statut invalide")
    update_prebooking_status(prebooking_id, status)
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "popaix-bot"}