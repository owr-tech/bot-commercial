import os
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

USER_LOCKS: dict[str, threading.Lock] = {}
USER_LOCKS_GUARD = threading.Lock()


def get_user_lock(key: str) -> threading.Lock:
    with USER_LOCKS_GUARD:
        if key not in USER_LOCKS:
            USER_LOCKS[key] = threading.Lock()
        return USER_LOCKS[key]

from ai_provider import ask_ai
from database import (
    get_recent_history,
    get_stats,
    get_all_prebookings,
    save_conversation,
    update_prebooking_status,
)
from flows import handle_message, build_whatsapp_interactive_rooms

app = FastAPI(title="Hôtel Pôpaix Bot")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "popaix2026")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
GRAPH_URL = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"

os.makedirs("templates", exist_ok=True)


# ---------------------------------------------------------------- WhatsApp
@app.get("/webhook")
def verify_webhook(mode: str = "", token: str = "", challenge: str = ""):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge
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


def handle_whatsapp_message(phone: str, text: str):
    # Sérialisation : empêche le désordre des messages d'un même client
    with get_user_lock(f"whatsapp:{phone}"):
        history = [
            (c.user_message, c.bot_reply)
            for c in get_recent_history("whatsapp", phone, limit=6)
        ]

        # 1) Bouton chambre choisi
        if text in ("ROOM_T1", "ROOM_T2", "ROOM_T3", "ROOM_T4"):
            text = "chambre " + text.replace("ROOM_", "")

        # 2) Flow pré-réservation
        reply = handle_message("whatsapp", phone, text)
        if reply:
            if reply.startswith("3️⃣") and "Quel type de chambre" in reply:
                send_whatsapp_text(phone, "2️⃣")
                send_whatsapp_interactive(phone, build_whatsapp_interactive_rooms())
                return
            send_whatsapp_text(phone, reply)
            save_conversation("whatsapp", phone, text, reply)
            return

        # 3) Chat libre via IA
        reply = ask_ai(text, history)
        send_whatsapp_text(phone, reply)
        save_conversation("whatsapp", phone, text, reply)


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
                    threading.Thread(
                        target=handle_whatsapp_message, args=(phone, text)
                    ).start()
    except Exception as e:
        print(f"[ERROR] WhatsApp webhook: {e}")
    return {"status": "ok"}


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
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in get_all_prebookings()
    ]


@app.post("/api/prebookings/{prebooking_id}/status")
async def api_update_status(prebooking_id: int, request: Request):
    body = await request.json()
    status = body.get("status")
    if status not in ("pending", "confirmed", "paid", "cancelled"):
        raise HTTPException(status_code=400, detail="Statut invalide")
    update_prebooking_status(prebooking_id, status)
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "popaix-bot"}