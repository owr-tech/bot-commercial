# Hôtel Pôpaix — Bot Commercial WhatsApp + Telegram

Bot IA pour les pré-réservations et le service client de l'Hôtel Pôpaix
(Fresco, Côte d'Ivoire) sur **WhatsApp** (Cloud API) et **Telegram**.

## Installation

```bash
cd popaix-bot
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # puis remplir les clés
```

## Démarrage

```bash
# API + webhooks WhatsApp + admin (terminal 1)
uvicorn main:app --reload --port 8000

# Bot Telegram (terminal 2)
python telegram_bot.py
```

### Test local du webhook WhatsApp
```bash
ngrok http 8000
# Copier l'URL https, configurer le webhook Meta avec :
#   URL        : https://<ngrok>/webhook
#   Verify token : popaix2026 (ou VERIFY_TOKEN)
```

## Admin

- Dashboard : `http://localhost:8000/admin`
- Stats JSON : `http://localhost:8000/api/stats`
- Pré-réservations : `http://localhost:8000/api/prebookings`
- Voucher client : `http://localhost:8000/booking/<id>` (+ `/pdf`, `/qr.png`)
- Détail JSON : `http://localhost:8000/api/booking/<id>`
- Santé : `http://localhost:8000/health`

## Réservation (UI générative — standard OpenUI)

- **Dates** : chaque canal a son rendu du composant `DateRangePicker`.
  - Telegram : calendrier inline (mois ◀ ▶, jours passés désactivés).
  - WhatsApp : **Flow** natif v5.0 (2 écrans `DATES` → `ROOM`), repli en saisie texte.
  - Borne : aujourd'hui → `BOOKING_MAX_MONTHS` mois (défaut 12).
- **Chambres T1-T4** : cartes `RoomCard` (image + description + prix).
  - Telegram : album photo + clavier inline.
  - WhatsApp : images + liste interactive (ou images dans le Flow).

## Chat IA

`AI_PROVIDER` : `mistral` (test, gratuit) → `claude` (prod, qualité max).
Sans clé API, le bot répond avec une base de connaissance locale (fallback).

## Déploiement (Render / Railway)

- Build : `pip install -r requirements.txt`
- Start : `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Pour Telegram en polling sur Render : ajouter `python telegram_bot.py`
  comme service secondaire (ou utiliser un webhook Telegram).

## Paiement

`PAYMENT_PROVIDER=paydunya` + clés (`PAYDUNYA_MASTER_KEY`, `PAYDUNYA_PRIVATE_KEY`,
`PAYDUNYA_TOKEN`, `PAYDUNYA_CALLBACK_URL`) pour finaliser la réservation par
paiement en ligne sécurisé (Wave, Orange Money, MTN Money, carte) via **PayDunya**.
Le bot envoie un lien de paiement à la fin de la réservation ; le webhook
`/webhook/paydunya` confirme le règlement et passe la réservation au statut `paid`.
Sans clés, le bot donne les instructions par téléphone (espèces sur place).