import hashlib
import hmac
import os
from typing import Optional

import requests

PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "none").lower()  # none | paydunya


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


class PayDunyaAPI:
    """Client de l'agrégateur PayDunya (Wave / Orange Money / MTN / espèces, carte)."""

    BASE_SANDBOX = "https://app.paydunya.com/sandbox-api/v1"
    BASE_LIVE = "https://app.paydunya.com/api/v1"

    def __init__(self):
        self.env = _env("PAYDUNYA_ENV", "test").lower()
        self.master_key = _env(
            f"PAYDUNYA_{'LIVE' if self.env == 'live' else 'TEST'}_MASTER_KEY"
        ) or _env("PAYDUNYA_MASTER_KEY")
        self.private_key = _env(
            f"PAYDUNYA_{'LIVE' if self.env == 'live' else 'TEST'}_PRIVATE_KEY"
        ) or _env("PAYDUNYA_PRIVATE_KEY")
        self.token = _env(
            f"PAYDUNYA_{'LIVE' if self.env == 'live' else 'TEST'}_TOKEN"
        ) or _env("PAYDUNYA_TOKEN")
        self.store_name = _env("PAYDUNYA_STORE_NAME", "HOTEL POPAIX")

    @property
    def base_url(self) -> str:
        return self.BASE_LIVE if self.env == "live" else self.BASE_SANDBOX

    def configured(self) -> bool:
        return bool(self.master_key and self.private_key and self.token)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "PAYDUNYA-MASTER-KEY": self.master_key,
            "PAYDUNYA-PRIVATE-KEY": self.private_key,
            "PAYDUNYA-TOKEN": self.token,
        }

    def create_invoice(
        self,
        total_fcf: int,
        description: str,
        name: str = "",
        phone: str = "",
        email: str = "",
        items: Optional[dict] = None,
        custom_data: Optional[dict] = None,
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Crée une facture PayDunya. Retourne (checkout_url, invoice_token).

        `return_url` / `cancel_url` : URLs spécifiques à cette facture
        (les paramètres par défaut .env restent utilisés si non précisées).
        """
        if not self.configured():
            return None, None
        default_return = _env("PAYDUNYA_RETURN_URL")
        default_cancel = _env("PAYDUNYA_RETURN_URL")
        payload = {
            "invoice": {
                "total_amount": int(total_fcf),
                "description": description,
                "customer": {"name": name, "phone": phone, "email": email},
                "items": items or {},
            },
            "store": {"name": self.store_name},
            "custom_data": custom_data or {},
            "actions": {
                "return_url": return_url or default_return,
                "cancel_url": cancel_url or default_cancel,
                "callback_url": _env("PAYDUNYA_CALLBACK_URL"),
            },
        }
        res = requests.post(
            f"{self.base_url}/checkout-invoice/create",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        if res.ok and res.json().get("response_code") == "00":
            return res.json().get("response_text"), res.json().get("token")
        print(f"[PAYDUNYA][ERROR] create: {res.status_code} {res.text}")
        return None, None

    def confirm(self, invoice_token: str) -> dict:
        """Vérifie le statut d'une facture : pending | completed | cancelled | failed."""
        if not self.configured():
            return {}
        res = requests.get(
            f"{self.base_url}/checkout-invoice/confirm/{invoice_token}",
            headers=self._headers(),
            timeout=30,
        )
        return res.json() if res.ok else {}

    def verify_hash(self, hash_value: str) -> bool:
        """Vérifie la signature du callback PayDunya : SHA-512 du MasterKey."""
        if not hash_value:
            return False
        expected = hashlib.sha512(self.master_key.encode()).hexdigest()
        return hmac.compare_digest(hash_value.lower(), expected.lower())


def request_payment(
    total_fcf: int,
    description: str,
    name: str = "",
    phone: str = "",
    email: str = "",
    custom_data: Optional[dict] = None,
    return_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Point d'entrée unique : crée le paiement. Retourne (checkout_url, invoice_token)."""
    if PAYMENT_PROVIDER != "paydunya":
        return None, None
    return PayDunyaAPI().create_invoice(
        total_fcf,
        description,
        name=name,
        phone=phone,
        email=email,
        custom_data=custom_data,
        return_url=return_url,
        cancel_url=cancel_url,
    )


def build_items(room_label: str, price_per_night: int, nights: int) -> dict:
    """Items affichés sur la page de paiement PayDunya."""
    return {
        "item_0": {
            "name": f"Séjour PO PAIX HOTEL ET EXPERIENCES - {room_label}",
            "quantity": nights,
            "unit_price": str(price_per_night),
            "total_price": str(price_per_night * nights),
            "description": f"{room_label} pour {nights} nuit(s)",
        }
    }