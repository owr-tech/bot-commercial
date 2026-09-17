"""Source de données externe : page tiket.com de l'Hôtel Pôpaix.

Rafraîchit et fusionne les données Booking dans la connaissance du bot,
avec cache local (JSON) et valeurs de secours validées.

URL : https://www.tiket.com/en-us/hotel/cote-divoire/hotel-popaix-707001721942024071
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime

import requests

from knowledge import POPAIX_KNOWLEDGE

TIKET_KNOWLEDGE = POPAIX_KNOWLEDGE["tiket"]

TIKET_URL = "https://www.tiket.com/en-us/hotel/cote-divoire/hotel-popaix-707001721942024071"
# Sur Vercel le FS projet est en lecture seule → cache dans /tmp (éphémère).
CACHE_FILE = os.getenv("TIKET_CACHE_FILE") or os.path.join(
    tempfile.gettempdir(), ".tiket_cache.json"
)
TTL_SECONDS = 6 * 3600  # rafraîchit au plus toutes les 6h

# --- Extraction best-effort depuis le HTML/texte de la page -----------------
def _extract_time(text: str, label: str) -> str | None:
    match = re.search(rf"{label}\s*(\d{{1,2}}:\d{{2}})", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_amenities(text: str) -> list[str] | None:
    known = [
        "wifi", "parking", "restaurant", "bar", "piscine", "jacuzzi", "spa",
        "bbq", "climatisation", "clim", "balcon", "jardin", "plage privée",
        "salle de réunion", "hiking", "arcade", "pêche", "casino",
    ]
    found = []
    for item in known:
        if re.search(rf"\b{item}", text, re.IGNORECASE):
            found.append(item.title())
    return list(dict.fromkeys(found)) or None


def fetch_tiket_page(timeout: int = 15) -> dict:
    """Récupère la page et en extrait les infos exploitables."""
    res = requests.get(TIKET_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    res.raise_for_status()
    text = res.text
    data = {}
    check_in = _extract_time(text, "Check-in")
    check_out = _extract_time(text, "Check-out")
    if check_in:
        data["check_in"] = check_in
    if check_out:
        data["check_out"] = check_out
    amenities = _extract_amenities(text)
    if amenities:
        data["amenities"] = amenities
    return data


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict):
    data["_fetched_at"] = datetime.utcnow().isoformat()
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        # FS en lecture seule (serverless) → le cache est optionnel, on continue.
        print(f"[TIKET][WARN] cache non écrit: {e}")


def get_tiket_data(force_refresh: bool = False) -> dict:
    """Retourne les données tiket fusionnées (défaut + cache à jour)."""
    merged = dict(TIKET_KNOWLEDGE)
    cache = _load_cache()
    fetched = cache.get("_fetched_at", "")

    fresh = False
    if fetched:
        try:
            fresh = (datetime.utcnow() - datetime.fromisoformat(fetched)).total_seconds() < TTL_SECONDS
        except ValueError:
            fresh = False

    if not fresh or force_refresh:
        try:
            live = fetch_tiket_page()
            if live:
                merged.update(live)
        except Exception as e:
            print(f"[TIKET] refresh failed, fallback: {e}")
        # Conserve en priorité les données live déjà connues (plus riches)
        cached_data = {k: v for k, v in cache.items() if k != "_fetched_at"}
        if cached_data:
            merged.update(cached_data)
        _save_cache(merged)  # horodatage → évite de retenter à chaque message
    else:
        merged.update({k: v for k, v in cache.items() if k != "_fetched_at"})
    return merged


if __name__ == "__main__":
    print(json.dumps(get_tiket_data(force_refresh=True), ensure_ascii=False, indent=2))