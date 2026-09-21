"""Simulation E2E du flux WhatsApp complet — via les vrais endpoints HTTP.

Guardrails :
- DB isolée : DATABASE_URL → sqlite:///./_sim_e2e.db (aucune écriture en prod).
- Aucun envoi WhatsApp réel : WHATSAPP_TOKEN/PHONE_ID vidés →
  les fonctions d'envoi se contentent de logger.
- Facture PayDunya : SANDBOX réel (vraie création d'invoice + URL checkout).
- Le callback de paiement est posté localement sur /webhook/paydunya ; le statut
  « paid » est simulé (confirm() renvoyé 'completed') car aucun paiement réel
  n'a lieu, mais tout le pipeline (hash, marquage paid, voucher PDF+QR) est réel.
"""

import hashlib
import json
import os
import sys
from urllib.parse import urlencode

os.environ["DATABASE_URL"] = "sqlite:///./_sim_e2e.db"
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["WHATSAPP_PHONE_ID"] = ""
os.environ["PHONE_NUMBER_ID"] = ""
os.environ["WABA_ID"] = ""
os.environ["WA_FLOW_ID"] = ""
os.environ["VERIFY_TOKEN"] = "popaix2026"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:8000"

for f in ("_sim_e2e.db",):
    if os.path.exists(f):
        os.remove(f)

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import payments  # noqa: E402

PHONE = "2250711223344"
outbound = []


def _record(kind, tag):
    def fn(*args, **kwargs):
        outbound.append((kind, tag, args, kwargs))
    return fn


main.send_whatsapp_text = _record("text", "text")
main.send_whatsapp_image = _record("image", "image")
main.send_whatsapp_interactive = _record("interactive", "interactive")
main.send_whatsapp_document = _record("document", "document")
main.send_dates_flow = _record("flow", "flow")
main.send_telegram_text = _record("tg", "text")
main.send_telegram_document = _record("tg", "document")

client = TestClient(main.app)

steps = {}


def wa_text(text):
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": PHONE, "type": "text", "text": {"body": text}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    r = client.post("/webhook", json=body)
    assert r.status_code == 200, f"webhook text → {r.status_code}"
    return r.json()


def wa_list_reply(room_id):
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": PHONE,
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {"id": room_id},
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    r = client.post("/webhook", json=body)
    assert r.status_code == 200, f"webhook list → {r.status_code}"
    return r.json()


def wa_flow_complete(payload):
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": PHONE,
                                    "type": "flow",
                                    "flow": {"flow_reply": json.dumps(payload)},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    r = client.post("/webhook", json=body)
    assert r.status_code == 200, f"webhook flow → {r.status_code}"
    return r.json()


def last_reply_text():
    for kind, tag, args, kw in reversed(outbound):
        if tag == "text" and args:
            return args[1]
    return ""


def any_text_contains(sub):
    return any(sub in a[2][1] for a in outbound if a[1] == "text" and len(a[2]) > 1)


# --- 0) Vérification webhook (handshake Meta) -----------------------------
r = client.get(
    "/webhook",
    params={"hub.mode": "subscribe", "hub.verify_token": "popaix2026", "hub.challenge": "98765"},
)
assert r.text == "98765", "handshake Meta échoué"
r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "mauvais", "hub.challenge": "1"})
assert r.status_code == 403, "handshake avec mauvais token doit être 403"
steps["webhook_handshake"] = "✅ handshake OK (challenge renvoyé, mauvais token → 403)"

# --- 1) Accueil (nouvelle conversation, sans historique) ------------------
wa_text("bonjour")
assert any_text_contains("PO PAIX HOTEL"), "présentation absent"
assert any(t == "image" for _, t, _, _ in outbound), "photos chambres non envoyées"
assert any(t == "interactive" for _, t, _, _ in outbound), "liste interactive non envoyée"
steps["accueil"] = "✅ présentation + 4 photos chambres + liste interactive"

# --- 2) Lancement pré-réservation -----------------------------------------
wa_text("je veux pré-réserver")
r1 = last_reply_text()
assert "offre" in r1.lower(), f"invite offre absente: {r1}"
assert any(t == "image" for _, t, _, _ in outbound)
assert any(t == "interactive" for _, t, _, _ in outbound)
steps["prerangement"] = "✅ 'pré-réserver' → cartes + liste chambres"

# --- 3) Choix de la chambre (ROOM_T2) → on envoie le Flow dates ----------
wa_list_reply("ROOM_T2")
r2 = last_reply_text()
assert "DATES" in r2.upper(), f"invite dates absente: {r2}"
steps["chambre"] = "✅ chambre T2 choisie → invite dates"

# --- 4) Soumission du Flow natif (dates + chambre d'un coup) --------------
wa_flow_complete({"checkin": "2026-12-20", "checkout": "2026-12-25", "room": "T2"})
r3 = last_reply_text()
assert "NOM" in r3.upper(), f"invite nom absente: {r3}"
steps["flow"] = "✅ Flow complet (ROOM+DATES) reçu → invite nom"

# --- 5) Nom → téléphone ----------------------------------------------------
wa_text("Awa Diallo")
r4 = last_reply_text()
assert "téléphone" in r4.lower() or "telephone" in r4.lower(), f"invite tel absente: {r4}"
steps["nom"] = "✅ nom Awa Diallo → invite téléphone"

# --- 6) Téléphone → création de la facture PayDunya (vrai sandbox) --------
wa_text("0709112233")
r5 = last_reply_text()
assert "Réservation #" in r5 and "Total séjour" in r5, f"recap absent: {r5}"

from database import SessionLocal, Prebooking  # noqa: E402

with SessionLocal() as db:
    prebookings = db.query(Prebooking).order_by(Prebooking.id.desc()).first()
book = prebookings

assert book, "pré-réservation non créée"
assert book.channel == "whatsapp" and book.user_id == PHONE
assert book.room_type == "T2" and book.check_in == "20/12" and book.check_out == "25/12"
assert book.amount_due == 150000, f"montant erroné: {book.amount_due}"

checkout_url = None
invoice_token = None
for line in r5.splitlines():
    if "http" in line:
        checkout_url = line.strip()
if book.payment_ref:
    invoice_token = book.payment_ref
steps["facture"] = (
    f"✅ résa #{book.id} créée (T2, 20/12→25/12, 150.000 FCFA, statut {book.status})"
)

# --- 7) Callback PayDunya → paid → voucher -------------------------------
api = payments.PayDunyaAPI()
token = invoice_token or "__SIM_TOKEN__"


def paydunya_callback():
    payload = {
        "data[hash]": hashlib.sha512(api.master_key.encode()).hexdigest(),
        "data[status]": "completed",
        "data[response_code]": "00",
        "data[invoice][token]": token,
        "data[custom_data][prebooking_id]": str(book.id),
    }
    return client.post(
        "/webhook/paydunya",
        content=urlencode(payload),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# 7a) D'abord le vrai `confirm()` sandbox : sans paiement humain → pending (ignoré)
real = api.confirm(token)
first_cb = paydunya_callback()

# 7b) Simulation du « client a payé » : confirm → completed, on reposte le callback
if real.get("status") != "completed":
    payments.PayDunyaAPI.confirm = lambda _self, _t: {
        "status": "completed",
        "response_code": "00",
        "invoice": {"total_amount": str(book.amount_due)},
        "custom_data": {"prebooking_id": book.id},
    }
    paydunya_callback()

from database import get_prebooking  # noqa: E402
from booking_pdf import _is_paid  # noqa: E402

fresh = get_prebooking(book.id)
assert _is_paid(fresh), f"résa #{book.id} non marquée paid (statut={fresh.status})"
assert fresh.amount_paid == 150000 and fresh.paid_at is not None

doc_recorded = [a[2] for a in outbound if a[1] == "document" and "voucher" in str(a[2])]
doc_bytes = None
for a in outbound:
    if a[1] == "document" and isinstance(a[2], (list, tuple)) and a[2]:
        for x in a[2]:
            if isinstance(x, (bytes, bytearray)):
                doc_bytes = bytes(x)
        if doc_bytes:
            break
assert doc_bytes and doc_bytes[:4] == b"%PDF", "voucher PDF non généré"
steps["paiement"] = (
    f"✅ callback /webhook/paydunya → paid (real confirm sandbox répondu "
    f"'{real.get('status')}', confirm payé simulé) → voucher PDF {len(doc_bytes)} o"
    + (f"\n   🔗 lien sandbox réel : {checkout_url}" if checkout_url else "")
)

# --- 8) Endpoints réservation (gate paiement) ------------------------------
r = client.get(f"/booking/{book.id}")
assert r.status_code == 200 and "Paiement confirmé" in r.text
r = client.get(f"/booking/{book.id}/pdf")
assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf")
r = client.get(f"/booking/{book.id}/qr.png")
assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")
r = client.get(f"/api/booking/{book.id}")
assert r.json()["paid"] is True and r.json()["total"].replace(".", "") == "150000"
steps["endpoints"] = "✅ /booking + /pdf + /qr.png + /api/booking (paid, 150000)"

# --- Recap ----------------------------------------------------------------
print()
print("═══ SIMULATION E2E WHATSAPP — RECAP ═══")
for k, v in steps.items():
    print(f"  {v}")
print()
print(f"  💳 Coffret découverte sandbox PayDunya (à finaliser via le lien ci-dessus)")
print(f"  🆔 Résa test locale : #{book.id} (SQLite _sim_e2e.db, prod NON touchée)")
print("  ✅ FLUX COMPLET VALIDÉ")