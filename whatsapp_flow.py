"""WhatsApp Business Flows — composant natif (rendu du composant OpenUI
`DateRangePicker` + `RoomCard` sur WhatsApp).

Écrans Flow (version 5.0) :
    DATES  →  deux DatePicker (arrivée / départ, min/max YYYY-MM-DD)
    ROOM   →  images + Dropdown des chambres T1-T4
Puis `complete` renvoie {checkin, checkout, room} au bot.

Aucun endpoint requis : les données circulent via références `${form.…}`
et `${data.…}` (fluides entre écrans).
"""

import json
import os
import uuid
from datetime import date, timedelta
from typing import Optional

import requests

from rooms import ROOM_INFO

FLOW_VERSION = "5.0"
FLOW_NAME = os.getenv("WA_FLOW_NAME", "popaix_dates")
FLOW_ID = os.getenv("WA_FLOW_ID", "").strip()
GRAPH = "https://graph.facebook.com/v21.0"


def _add_months(d: date, months: int) -> date:
    from calendar import monthrange

    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def booking_window(max_months: int = 12) -> tuple[str, str]:
    """(min, max) dates ISO YYYY-MM-DD pour les pickers d'arrivée/départ."""
    today = date.today()
    return today.isoformat(), _add_months(today, max_months).isoformat()


# ---------------------------------------------------------------- JSON du Flow
def _image_block(room: str) -> dict:
    info = ROOM_INFO[room]
    return {
        "type": "Image",
        "url": info["image"],
        "title": info["title"],
        "alt": info["title"],
    }


def _text_block(room: str) -> dict:
    info = ROOM_INFO[room]
    return {
        "type": "TextBody",
        "text": f"{info['fr']}\n💵 {info['price_label']}/nuit",
    }


def build_flow_json(
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    single_screen: bool = False,
) -> dict:
    """Construit le JSON du Flow WhatsApp (v5.0, 2 écrans ou 1 écran)."""
    min_date = min_date or booking_window()[0]
    max_date = max_date or booking_window()[1]

    if single_screen:
        return {
            "version": FLOW_VERSION,
            "screens": [
                {
                    "id": "BOOKING",
                    "title": "Pré-réservation",
                    "terminal": "true",
                    "success": "true",
                    "data": {},
                    "layout": {
                        "type": "SingleColumnLayout",
                        "children": [
                            {"type": "TextHeading", "text": "🗓️ Votre séjour"},
                            {"type": "TextSubheading", "text": "Arrivée, départ et chambre"},
                            {
                                "type": "Form",
                                "name": "booking",
                                "children": [
                                    {
                                        "type": "DatePicker",
                                        "name": "checkin",
                                        "label": "Date d'arrivée",
                                        "min-date": min_date,
                                        "max-date": max_date,
                                    },
                                    {
                                        "type": "DatePicker",
                                        "name": "checkout",
                                        "label": "Date de départ",
                                        "min-date": min_date,
                                        "max-date": max_date,
                                    },
                                ],
                            },
                            {"type": "TextHeading", "text": "🛏️ Choisissez votre chambre"},
                            *[
                                c
                                for room in ["T1", "T2", "T3", "T4"]
                                for c in (_image_block(room), _text_block(room))
                            ],
                            {
                                "type": "Dropdown",
                                "name": "room",
                                "label": "Type de chambre",
                                "options": [
                                    {"id": r, "title": f"{ROOM_INFO[r]['title']} · {ROOM_INFO[r]['price_label']}/nuit"}
                                    for r in ["T1", "T2", "T3", "T4"]
                                ],
                            },
                            {
                                "type": "Footer",
                                "label": "Confirmer ma réservation",
                                "on-click-action": {
                                    "name": "complete",
                                    "payload": {
                                        "checkin": "${form.booking.checkin}",
                                        "checkout": "${form.booking.checkout}",
                                        "room": "${form.booking.room}",
                                    },
                                },
                            },
                        ],
                    },
                }
            ],
        }

    # ---- 2 écrans : ROOM (offre) → DATES --------------------------------
    return {
        "version": FLOW_VERSION,
        "screens": [
            {
                "id": "ROOM",
                "title": "Votre chambre",
                "terminal": "false",
                "data": {},
                "routing_model": {"ROOM": ["DATES"]},
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {"type": "TextHeading", "text": "🛏️ Choisissez votre chambre"},
                        {"type": "TextSubheading", "text": "Choisissez d'abord votre offre"},
                        *[
                            c
                            for room in ["T1", "T2", "T3", "T4"]
                            for c in (_image_block(room), _text_block(room))
                        ],
                        {
                            "type": "Dropdown",
                            "name": "room",
                            "label": "Type de chambre",
                            "options": [
                                {"id": r, "title": f"{ROOM_INFO[r]['title']} · {ROOM_INFO[r]['price_label']}/nuit"}
                                for r in ["T1", "T2", "T3", "T4"]
                            ],
                        },
                        {
                            "type": "Footer",
                            "label": "Choisir les dates →",
                            "on-click-action": {
                                "name": "navigate",
                                "payload": {
                                    "screen": "DATES",
                                    "data": {"room": "${form.room}"},
                                },
                            },
                        },
                    ],
                },
            },
            {
                "id": "DATES",
                "title": "Vos dates",
                "terminal": "true",
                "success": "true",
                "data": {
                    "room": {"type": "string", "__example__": "T2"},
                },
                "layout": {
                    "type": "SingleColumnLayout",
                    "children": [
                        {"type": "TextHeading", "text": "🗓️ Choisissez vos dates"},
                        {"type": "TextSubheading", "text": "Arrivée & départ (Format YYYY-MM-DD)"},
                        {
                            "type": "Form",
                            "name": "dates",
                            "children": [
                                {
                                    "type": "DatePicker",
                                    "name": "checkin",
                                    "label": "Date d'arrivée",
                                    "min-date": min_date,
                                    "max-date": max_date,
                                },
                                {
                                    "type": "DatePicker",
                                    "name": "checkout",
                                    "label": "Date de départ",
                                    "min-date": min_date,
                                    "max-date": max_date,
                                },
                            ],
                        },
                        {
                            "type": "Footer",
                            "label": "✅ Confirmer ma réservation",
                            "on-click-action": {
                                "name": "complete",
                                "payload": {
                                    "checkin": "${form.dates.checkin}",
                                    "checkout": "${form.dates.checkout}",
                                    "room": "${data.room}",
                                },
                            },
                        },
                    ],
                },
            },
        ],
    }


# ---------------------------------------------------------------- Graph API
def ensure_flow(
    token: str = "",
    waba_id: str = "",
    flow_name: str = FLOW_NAME,
    force: bool = False,
) -> str:
    """Trouve ou crée le Flow sur le WABA. Retourne l'ID du Flow (ou '')."""
    token = token or os.getenv("WHATSAPP_TOKEN", "")
    waba_id = waba_id or os.getenv("WABA_ID", "")
    if FLOW_ID:
        return FLOW_ID
    if not token or not waba_id:
        return ""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(f"{GRAPH}/{waba_id}/flows", headers=headers, timeout=30)
        if res.ok:
            for f in res.json().get("data", []):
                if f.get("name") == flow_name:
                    return str(f.get("id", ""))
    except Exception as e:
        print(f"[WA-FLOW][WARN] listing flows failed: {e}")

    # Création (si non trouvé)
    body = {
        "name": flow_name,
        "categories": json.dumps(["APPOINTMENT_BOOKING"]),
        "flow_json": json.dumps(build_flow_json()),
        "publish": "true",
    }
    try:
        res = requests.post(
            f"{GRAPH}/{waba_id}/flows", headers=headers, data=body, timeout=30
        )
        if res.ok:
            flow_id = str(res.json().get("id", ""))
            print(f"[WA-FLOW] ✅ Flow créé, id={flow_id}")
            return flow_id
        print(f"[WA-FLOW][WARN] création échouée: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[WA-FLOW][WARN] création exception: {e}")
    return ""


def refresh_flow_json(flow_id: str = "", token: str = ""):
    """Republie le JSON du Flow (dates mises à jour : aujourd'hui → +12 mois)."""
    flow_id = flow_id or FLOW_ID
    token = token or os.getenv("WHATSAPP_TOKEN", "")
    if not flow_id or not token:
        return False
    body = {
        "flow_json": json.dumps(build_flow_json()),
        "publish": "true",
    }
    try:
        res = requests.post(
            f"{GRAPH}/{flow_id}",
            headers={"Authorization": f"Bearer {token}"},
            data=body,
            timeout=30,
        )
        ok = res.ok
        if ok:
            print(f"[WA-FLOW] ✅ JSON republié (flow {flow_id})")
        else:
            print(f"[WA-FLOW][WARN] refresh: {res.status_code} {res.text}")
        return ok
    except Exception as e:
        print(f"[WA-FLOW][WARN] refresh exception: {e}")
        return False


# ---------------------------------------------------------------- Envoi
def send_dates_flow(
    to: str,
    phone_id: str = "",
    token: str = "",
    flow_ctx: Optional[dict] = None,
    flow_token: str = "",
) -> bool:
    """Envoie le message interactif 'flow' (calendrier + chambres)."""
    token = token or os.getenv("WHATSAPP_TOKEN", "")
    phone_id = phone_id or os.getenv("WHATSAPP_PHONE_ID", "") or os.getenv("PHONE_ID", "")
    if not token or not phone_id:
        print(f"[SEND][flow→{to}] (clés WhatsApp manquantes)")
        return False
    flow_ctx = flow_ctx or {}
    flow_token = flow_token or f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
    min_date, max_date = booking_window()
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "🛏️ Choisissez votre offre"},
            "body": {
                "text": "PO PAIX HOTEL ET EXPERIENCES 🌴 — choisissez votre chambre, puis vos dates."
            },
            "footer": {"text": "Paiement confirmé ensuite par PayDunya"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": flow_token,
                    "flow_cta": "Choisir",
                    "flow_action": "navigate",
                    "flow_action_payload": {
                        "screen": "ROOM",
                        "data": json.dumps({"min_date": min_date, "max_date": max_date}),
                    },
                },
            },
        },
    }
    if flow_ctx.get("id"):
        payload["interactive"]["action"]["parameters"]["flow_id"] = flow_ctx["id"]
    else:
        payload["interactive"]["action"]["parameters"]["flow_name"] = flow_ctx.get(
            "name", FLOW_NAME
        )
    try:
        res = requests.post(
            f"{GRAPH}/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=30,
        )
        if not res.ok:
            print(f"[WA-FLOW][ERROR] envoi flow: {res.status_code} {res.text}")
        return res.ok
    except Exception as e:
        print(f"[WA-FLOW][ERROR] envoi flow exception: {e}")
        return False


# ---------------------------------------------------------------- Réception
def parse_flow_completion(msg: dict) -> Optional[dict]:
    """Extrait la réponse d'un 'complete' Flow depuis le webhook WhatsApp.

    Structure possible (v21) : msg["flow"]["flow_reply"] = JSON string.
    """
    flow = msg.get("flow") or msg.get("flow_reply") or {}
    raw = (
        flow.get("flow_reply")
        or flow.get("response")
        or flow.get("message_response")
        or flow.get("payload")
    )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    # Normalise d'éventuels sous-objets (payload / message_response)
    for key in ("payload", "message_response", "answer", "flow_reply"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            raw = nested
            break
    return raw or None


def _iso_to_dmy(value) -> str:
    """'2026-09-20' → '20/09' (format interne 'jour/mois')."""
    if isinstance(value, str) and "-" in value:
        parts = value.split("-")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return f"{int(parts[2]):02d}/{int(parts[1]):02d}"
    return str(value)


def extract_booking(response: dict) -> dict:
    """Mappe la réponse du Flow vers les clés du bot (check_in, check_out, room_type)."""
    out = {}
    checkin = response.get("checkin") or response.get("check_in")
    checkout = response.get("checkout") or response.get("check_out")
    room = response.get("room") or response.get("room_type")
    if checkin:
        out["check_in"] = _iso_to_dmy(checkin)
    if checkout:
        out["check_out"] = _iso_to_dmy(checkout)
    if room:
        out["room_type"] = str(room).upper().strip()
    return out


if __name__ == "__main__":
    print(json.dumps(build_flow_json(), ensure_ascii=False, indent=2))