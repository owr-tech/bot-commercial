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
- Santé : `http://localhost:8000/health`

## Chat IA

`AI_PROVIDER` : `mistral` (test, gratuit) → `claude` (prod à partir du 15 déc).
Sans clé API, le bot répond avec une base de connaissance locale (fallback).

## Déploiement (Render / Railway)

- Build : `pip install -r requirements.txt`
- Start : `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Pour Telegram en polling sur Render : ajouter `python telegram_bot.py`
  comme service secondaire (ou utiliser un webhook Telegram).

## Paiement

`PAYMENT_PROVIDER=wave` ou `orange` pour activer les liens de paiement
Wave / Orange Money. Sans clés, le bot donne les instructions par téléphone.