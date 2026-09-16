import os
from typing import Optional

import requests

PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "none").lower()  # wave | orange | none


class WaveAPI:
    BASE_URL = "https://api.wave.com/v1"

    def __init__(self):
        self.client_id = os.getenv("WAVE_CLIENT_ID")
        self.client_secret = os.getenv("WAVE_CLIENT_SECRET")
        self.access_token = None

    def auth(self) -> Optional[str]:
        res = requests.post(
            f"{self.BASE_URL}/oauth/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
        )
        if res.ok:
            self.access_token = res.json()["access_token"]
        return self.access_token

    def request_payment(self, amount_fcf: int, currency: str = "XOF", mobile: str = "") -> Optional[str]:
        """Crée une demande de paiement. Retourne le payment_url."""
        if not self.access_token:
            self.auth()
        res = requests.post(
            f"{self.BASE_URL}/checkout/sessions",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json={
                "amount": {"currency": currency, "amount": str(amount_fcf)},
                "mobile_money_number": mobile,
                "success_redirect_url": os.getenv("WAVE_SUCCESS_URL", ""),
            },
        )
        if res.ok:
            return res.json().get("checkout_session_url")
        return None


class OrangeMoneyAPI:
    BASE_URL = "https://api.orange.com/omarizal"

    def __init__(self):
        self.client_id = os.getenv("ORANGE_CLIENT_ID")
        self.client_secret = os.getenv("ORANGE_CLIENT_SECRET")
        self.access_token = None

    def auth(self) -> Optional[str]:
        import base64

        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        res = requests.post(
            "https://api.orange.com/oauth/v2/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
        )
        if res.ok:
            self.access_token = res.json()["access_token"]
        return self.access_token

    def request_payment(self, msisdn: str, amount_fcf: int) -> Optional[str]:
        if not self.access_token:
            self.auth()
        res = requests.post(
            f"{self.BASE_URL}/v1/transactions/token",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "X-Request-ID": os.getenv("ORANGE_REQUEST_ID", "popaixbot"),
                "Content-Type": "application/json",
            },
            json={
                "phoneNumber": msisdn,
                "callBackUrl": os.getenv("ORANGE_CALLBACK_URL", ""),
                "amount": {"unit": amount_fcf, "currency": "XOF"},
            },
        )
        if res.ok:
            return res.json().get("token")
        return None


def request_payment(provider: str, mobile: str, amount_fcf: int):
    """Dispatch vers le provider configuré. Retourne un lien/instructions ou None."""
    provider = (provider or PAYMENT_PROVIDER).lower()
    if provider == "wave":
        return WaveAPI().request_payment(amount_fcf, mobile=mobile)
    if provider in ("orange", "orange_money"):
        return OrangeMoneyAPI().request_payment(mobile, amount_fcf)
    return None


def payment_instructions(prebooking_id: int, amount_fcf: int) -> str:
    """Instructions de paiement envoyées au client après la pré-réservation."""
    url = request_payment(PAYMENT_PROVIDER, "", amount_fcf)
    base = (
        f"💰 Pré-réservation #{prebooking_id} : {amount_fcf:,} FCFA\n"
        "Paiement en espèces, Wave, Orange Money ou MTN Money.\n"
    )
    if url:
        return base + f"🔗 Payez ici : {url}"
    return base + "📞 L'équipe vous appellera au 01 42 30 84 84 pour le paiement."