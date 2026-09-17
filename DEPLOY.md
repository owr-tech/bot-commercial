# Déploiement — Guide pas à pas (Railway + Neon)

## 1. Pousser le code sur GitHub

Repo : `https://github.com/revivaltent91-bot/popaix-bot`

```bash
git add -A && git commit -m "..." && git push origin main
```

## 2. Base de données — Neon

1. https://neon.tech → créer un projet.
2. Récupérer la chaîne **pooled** (hostname suffixé `-pooler`) :
   `postgresql://...-pooler.../neondb?sslmode=require`
3. Le schéma (3 tables) est créé automatiquement au premier démarrage.

## 3. Déployer sur Railway

### Via la CLI

```bash
npm i -g @railway/cli
railway login
railway init --name popaix-bot
railway add --service popaix-bot
# injecter les variables (voir tableau ci-dessous), puis :
railway up --service popaix-bot
```

### Via le dashboard

**New Project → Deploy from GitHub repo** (`popaix-bot`). Railway détecte le `Dockerfile`.

- Un **seul service** suffit : `start.sh` lance l'API FastAPI **et** le bot Telegram (polling).
- Exposer le port : Railway injecte `PORT`, `start.sh` l'utilise.
- Générer un domaine : `railway domain --service popaix-bot`.

### Variables d'environnement

| Clé | Description |
|---|---|
| AI_PROVIDER | `mistral` (test) ou `claude` (prod) |
| MISTRAL_API_KEY | Clé API Mistral |
| ANTHROPIC_API_KEY | Clé API Claude (si `AI_PROVIDER=claude`) |
| WHATSAPP_TOKEN | Token Meta **System User** (scopes messaging + management) |
| WHATSAPP_PHONE_ID | Numéro WhatsApp Business |
| WABA_ID | WhatsApp Business Account ID (Flows) |
| WA_FLOW_NAME | Nom du Flow (défaut `popaix_dates`) |
| WHATSAPP_REDIRECT_NUMBER | Numéro `wa.me` de retour |
| VERIFY_TOKEN | Secret webhook Meta (ex `popaix2026`) |
| TELEGRAM_TOKEN | Token BotFather |
| TELEGRAM_BOT_USERNAME | Username Telegram |
| DATABASE_URL | Chaîne **pooled** Neon |
| PUBLIC_BASE_URL | `https://<service>.up.railway.app` |
| BOOKING_MAX_MONTHS | `12` |
| PAYMENT_PROVIDER | `paydunya` |
| PAYDUNYA_ENV | `test` ou `live` |
| PAYDUNYA_MASTER_KEY / PRIVATE_KEY / TOKEN | Clés PayDunya |
| PAYDUNYA_CALLBACK_URL | `https://<service>.up.railway.app/webhook/paydunya` |
| PAYDUNYA_RETURN_URL | `https://<service>.up.railway.app` |
| ADMIN_SECRET | Protège `/admin/set-telegram-webhook` |

> `PUBLIC_BASE_URL`, `PAYDUNYA_CALLBACK_URL` et `PAYDUNYA_RETURN_URL` doivent utiliser
> le domaine Railway. Après modification d'une variable : `railway redeploy -y`.

## 4. Configurer WhatsApp Cloud API (Meta)

1. https://developers.facebook.com/apps → app **Business** → produit **WhatsApp**.
2. Récupérer le **Token** et le **Phone number ID**.
3. **Webhook** :
   - Callback URL : `https://<service>.up.railway.app/webhook`
   - Verify token : valeur de `VERIFY_TOKEN`
4. S'abonner à l'événement **messages**.
5. **Flows** : scopes `whatsapp_business_management` + `whatsapp_business_messaging`.
   Le Flow est créé/republié automatiquement. Si l'API Flows est indisponible, le bot
   bascule sur le **repli** (saisie texte des dates + liste des chambres + cartes images).

## 5. Telegram

Rien à configurer : le bot tourne en **polling** (`python telegram_bot.py`) dans `start.sh`.
Éviter de lancer un second process polling avec le même token (conflit `getUpdates`).

## 6. Vérification

- Santé : `https://<service>.up.railway.app/health` → `{"status":"ok"}`
- Admin : `https://<service>.up.railway.app/admin`
- Telegram : `/start` au bot → présentation + cartes chambres
- WhatsApp : « bonjour » au numéro de test
- Paiement : le client reçoit le **lien PayDunya** ; le callback `/webhook/paydunya`
  marque la réservation `paid` puis envoie la confirmation **+ le voucher PDF (QR)**.
  - Voucher : `/booking/<id>` · PDF : `/booking/<id>/pdf` · QR : `/booking/<id>/qr.png`

## 7. Passer en PRODUCTION

1. Acheter le numéro WhatsApp Business officiel.
2. `AI_PROVIDER=claude` + `ANTHROPIC_API_KEY`.
3. PayDunya : `PAYDUNYA_ENV=live` + clés LIVE, puis mettre à jour
   `PAYDUNYA_CALLBACK_URL` vers le domaine Railway et `railway redeploy -y`.
