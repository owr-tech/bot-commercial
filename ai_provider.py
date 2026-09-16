import json
import os

import requests

from knowledge import POPAIX_KNOWLEDGE

SYSTEM_PROMPT = None


def load_system_prompt() -> str:
    global SYSTEM_PROMPT
    if SYSTEM_PROMPT is not None:
        return SYSTEM_PROMPT
    try:
        with open("system_prompt.txt", "r", encoding="utf-8") as f:
            SYSTEM_PROMPT = f.read()
    except FileNotFoundError:
        SYSTEM_PROMPT = (
            "Tu es PopaixBot, assistant de l'Hôtel Pôpaix. "
            "Réponds en français ivoirien, court et chaleureux."
        )
    return SYSTEM_PROMPT


def build_context(history: list[tuple[str, str]] | None = None) -> str:
    lines = [f"KNOWLEDGE: {json.dumps(POPAIX_KNOWLEDGE, ensure_ascii=False)}"]
    if history:
        lines.append("\nHISTORIQUE DE LA CONVERSATION (récents d'abord):")
        for user_msg, bot_reply in reversed(history):
            lines.append(f"USER: {user_msg}")
            lines.append(f"BOT: {bot_reply}")
    return "\n".join(lines)


def ask_mistral(context: str, history: list[tuple[str, str]]) -> str:
    from mistralai import Mistral

    client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
    messages = [{"role": "system", "content": load_system_prompt()}]
    for user_msg, bot_reply in reversed(history or []):
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": bot_reply})
    messages.append({"role": "user", "content": context})
    resp = client.chat.complete(
        model=os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
        messages=messages,
        max_tokens=400,
    )
    return resp.choices[0].message.content


def ask_claude(context: str, history: list[tuple[str, str]]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    messages = []
    for user_msg, bot_reply in reversed(history or []):
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": bot_reply})
    messages.append({"role": "user", "content": context})
    msg = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=500,
        system=load_system_prompt(),
        messages=messages,
    )
    return msg.content[0].text


def ask_openai(context: str, history: list[tuple[str, str]]) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    messages = [{"role": "system", "content": load_system_prompt()}]
    for user_msg, bot_reply in reversed(history or []):
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": bot_reply})
    messages.append({"role": "user", "content": context})
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        max_tokens=400,
    )
    return resp.choices[0].message.content


def fallback_reply(user_message: str) -> str:
    msg = user_message.lower()
    if any(w in msg for w in ["prix", "tarif", "combien", "coût", "cout", "cher"]):
        return (
            "Nos chambres : 🛏️ T1 = 25.000 F · T2 = 30.000 F · T3 = 35.000 F · "
            "T4 = 40.000 F par nuit. 🍕 Sorbets 2.000 F, Pizza Margherita 4.000 F + boisson. "
            "Réouverture le 15 décembre 2026 🌴"
        )
    if any(w in msg for w in ["réouverture", "ouvre", "reouverture", "quand", "date"]):
        return (
            "On rouvre le 15 décembre 2026 à 16h ! 🎉 Nouveauté : une belle piscine. "
            "Les pré-réservations sont OUVERTES. Dites-moi 'pré-réserver' pour réserver votre chambre."
        )
    if any(w in msg for w in ["chambre", "lit", "suite"]):
        return (
            "23 chambres face plage 🌊 : T1 (25.000 F), T2 (30.000 F), T3 (35.000 F), "
            "T4 (40.000 F). Toutes avec clim, wifi gratuit. Dites 'pré-réserver' pour commencer !"
        )
    if any(w in msg for w in ["pré-réserver", "prereserver", "reserver", "réserver", "reserver"]):
        return (
            "Avec plaisir ! 🎉 Pour votre pré-réservation, donnez-moi :\n"
            "1️⃣ Votre nom complet\n"
            "2️⃣ Les dates (arrivée et départ)\n"
            "3️⃣ Le type de chambre : T1 (25.000F), T2 (30.000F), T3 (35.000F) ou T4 (40.000F)\n\n"
            "Ex : 'Je suis Jean Kouassi, du 20 au 25 décembre, chambre T2'"
        )
    if any(w in msg for w in ["contact", "adresse", "téléphone", "telephone", "whatsapp", "numéro"]):
        return (
            "Vous pouvez nous joindre au 01 42 30 84 84 ou sur @hotelpopaix 📞 "
            "Nous sommes face plage/lagune Koyiri à Fresco, Côte d'Ivoire."
        )
    if any(w in msg for w in ["paiement", "payer", "wave", "orange", "mtn", "espèces"]):
        return (
            "Paiement en espèces, Wave, Orange Money ou MTN Money 💳 "
            "Facile et sécurisé. Dites 'pré-réserver' pour lancer la résa."
        )
    if any(w in msg for w in ["resto", "restaurant", "pizza", "manger", "menu"]):
        return (
            "Restaurant ANWUKWA 🍕 : Sorbets 2.000 F, Margherita 4.000 F + boisson, "
            "Royale 5.000 F + boisson. Cuisine africaine, caribéenne et française halal."
        )
    return (
        "Bienvenue à l'Hôtel Pôpaix 🌴 23 chambres face plage à Fresco. "
        "Réouverture le 15 décembre 2026 avec piscine ! Les pré-réservations sont ouvertes. "
        "Demandez-moi les prix, les chambres ou écrivez 'pré-réserver'."
    )


def ask_ai(user_message: str, history: list[tuple[str, str]] | None = None) -> str:
    provider = os.getenv("AI_PROVIDER", "mistral").lower()
    history = history or []
    context = build_context(history)

    try:
        if provider == "mistral":
            return ask_mistral(context, history)
        elif provider == "claude":
            return ask_claude(context, history)
        elif provider == "openai":
            return ask_openai(context, history)
        else:
            return fallback_reply(user_message)
    except Exception as e:
        print(f"[ERROR] AI provider '{provider}' failed: {e}")
        return fallback_reply(user_message)