# Déploiement — Guide pas à pas

## 1. Pousser le code sur GitHub

Créez un repo vide sur github.com (ex : `popaix-bot`, ne **pas** cocher README), puis :

```bash
cd popaix-bot
git remote add origin https://github.com/VOTRE_USER/popaix-bot.git
git branch -M main
git push -u origin main
```

Si `Permission denied (publickey)` : générez une clé et ajoutez-la à GitHub.
```bash
ssh-keygen -t ed25519 -C "votre@email.com"   # tout par défaut
cat ~/.ssh/id_ed25519.pub                    # coller dans github.com → Settings → SSH keys
```
Puis `git push -u origin main`.

## 2. Déployer sur Render

1. Rendez-vous sur https://render.com → **New → Blueprint**
2. Choisissez le repo `popaix-bot` **public**
3. Render détecte automatiquement `render.yaml` et crée :
   - **popaix-bot-api** (web) → `uvicorn main:app --port $PORT`
   - **popaix-telegram** (worker) → `python telegram_bot.py`
   - **popaix-db** (PostgreSQL gratuit)
4. Dans chaque service, renseignez les **secrets** promis par le blueprint :

| Clé | Web | Worker | Description |
|---|---|---|---|
| MISTRAL_API_KEY | ✅ | ✅ | Clé API Mistral (console.mistral.ai) |
| ANTHROPIC_API_KEY | ✅ | ✅ | Clé API Claude (console.anthropic.com) |
| WHATSAPP_TOKEN | ✅ | — | Token d'accès Meta **System User** (scopes `whatsapp_business_messaging` + `whatsapp_business_management`) |
| WHATSAPP_PHONE_ID | ✅ | — | Numéro téléphone WhatsApp Business |
| WABA_ID | ✅ | — | WhatsApp Business Account ID (Flows) |
| WA_FLOW_NAME | ✅ | — | Nom du Flow (défaut `popaix_dates`) |
| WHATSAPP_REDIRECT_NUMBER | ✅ | — | Numéro `wa.me` de retour (défaut `2250702391982`) |
| VERIFY_TOKEN | ✅ | — | Votre code secret (ex `popaix2026`) |
| TELEGRAM_TOKEN | ✅ | ✅ | Token du bot via @BotFather |
| TELEGRAM_BOT_USERNAME | ✅ | — | Username Telegram (lien `t.me/<username>`) |
| PUBLIC_BASE_URL | ✅ | ✅ | Base des liens `/booking/<id>` (URL Render) |
| BOOKING_MAX_MONTHS | ✅ | ✅ | Horizon de réservation (défaut `12`) |
| PAYDUNYA_MASTER_KEY | ✅ | ✅ | Clé PayDunya (test ou live) |
| PAYDUNYA_PRIVATE_KEY | ✅ | ✅ | Clé privée PayDunya |
| PAYDUNYA_TOKEN | ✅ | ✅ | Token application PayDunya |
| PAYDUNYA_ENV | ✅ | ✅ | `test` (sandbox) ou `live` |
| PAYDUNYA_CALLBACK_URL | ✅ | — | `https://popaix-bot-api.onrender.com/webhook/paydunya` |

> ⚠️ Sur le **plan gratuit**, Render fait dormir le web service après 15 min d'inactivité
> (réveil = ~30s la première fois). Le worker Telegram, lui, tourne en continu.

## 3. Configurer WhatsApp Cloud API (Meta)

1. https://developers.facebook.com/apps → créer app **Business**
2. Ajouter produit **WhatsApp** → obtenez le **Token** et le **Phone number ID**
3. Testez : `curl "https://graph.facebook.com/v19.0/<PHONENUMID>/messages" -H "Authorization: Bearer <TOKEN>"` (200 = ok)
4. **Webhook** (l'URL de votre service Render) :
   - Callback URL : `https://popaix-bot-api.onrender.com/webhook`
   - Verify token : `popaix2026` (ou votre `VERIFY_TOKEN`)
5. Abonnez l'événement **messages** dans la config du webhook
6. **Flows** (calendrier + chambres) : le token doit avoir les scopes
   `whatsapp_business_management` + `whatsapp_business_messaging`.
   Le Flow est créé/republié automatiquement au démarrage.
   Si l'API Flows est indisponible, le bot bascule sur le **repli**
   (saisie texte des dates + liste des chambres + cartes images).

Pour une mise en prod : ouvrez le **numéro de test** via Configuration du téléphone
(touches WhatsApp Business API — valide 30 jours pour tester).

## 4. Créer le bot Telegram

1. Ouvrez [@BotFather](tg://resolve?domain=botfather), ` /newbot `, choisissez un nom.
2. Copiez le **token** → collage dans les secrets Render (`TELEGRAM_TOKEN`).
3. Le worker le démarre automatiquement (polling).

## 5. Vérification

- API : `https://popaix-bot-api.onrender.com/health` → `{"status":"ok"}`
- Admin : `https://popaix-bot-api.onrender.com/admin`
- WhatsApp : envoyez « bonjour » au numéro du test
- Telegram : envoyez `/start` à votre bot
- Paiement : après une réservation, le client reçoit le **lien PayDunya** ; une fois payé,
  le callback `/webhook/paydunya` marque la réservation `paid`, envoie la confirmation
  **+ le voucher PDF avec QR** (à présenter à la réception).
  - Page voucher : `https://popaix-bot-api.onrender.com/booking/<id>`
  - PDF : `/booking/<id>/pdf` · QR : `/booking/<id>/qr.png`
  Test : `curl -X POST https://popaix-bot-api.onrender.com/webhook/paydunya \
   -d "data[status]=completed" -d "data[hash]=..." -d "data[invoice][token]=test_xxx"`

## 6. Passer en PRODUCTION

1. Achetez le numéro WhatsApp Business officiel
2. `AI_PROVIDER=claude` + remplissez `ANTHROPIC_API_KEY`
3. Paiement PayDunya : `PAYMENT_PROVIDER=paydunya`, `PAYDUNYA_ENV=live` et
   les clés LIVE (`PAYDUNYA_LIVE_MASTER_KEY`, `PAYDUNYA_LIVE_PRIVATE_KEY`,
   `PAYDUNYA_LIVE_TOKEN`) dans les **secrets Render** (web + worker).
   Le **callback** `PAYDUNYA_CALLBACK_URL=https://popaix-bot-api.onrender.com/webhook/paydunya`
   doit pointer vers votre web service Render.