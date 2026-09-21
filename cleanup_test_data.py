"""Nettoyage des données de test : pré-réservations, sessions et conversations.

Usage (depuis popaix-bot/ — lit DATABASE_URL du .env, donc Neon prod si .env prod) :

    python cleanup_test_data.py --dry-run            # aperçu (par défaut)
    python cleanup_test_data.py --channel whatsapp --user 2250711223344
    python cleanup_test_data.py --ids 5,6,7
    python cleanup_test_data.py --phone 0709112233
    python cleanup_test_data.py --keep 1,2 --channel whatsapp --since 2026-09-21

Options :
  --dry-run        n'affiche que ce qui serait supprimé (défaut sans --apply)
  --apply          exécute réellement les suppressions
  --channel X      filtre whatsapp | telegram
  --user X         user_id exact (téléphone WhatsApp / chat id Telegram)
  --phone X        filtre les résas par numéro renseigné (partiel, chiffres seuls)
  --ids 1,2,3      IDs de pré-réservations à supprimer
  --since YYYY-MM-DD  ne garde que les résas créées à partir de cette date
  --keep 1,2       IDs à conserver même s'ils matchent les filtres
"""

import argparse
import sys
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

from database import Conversation, Prebooking, SessionLocal, SessionState  # noqa: E402


def _match_prebookings(q, args) -> list[Prebooking]:
    if args.channel:
        q = q.filter(Prebooking.channel == args.channel)
    if args.user:
        q = q.filter(Prebooking.user_id == args.user)
    if args.phone:
        digits = "".join(c for c in args.phone if c.isdigit())
        q = q.filter(Prebooking.phone.like(f"%{digits}%"))
    if args.since:
        since = datetime.combine(date.fromisoformat(args.since), datetime.min.time())
        q = q.filter(Prebooking.created_at >= since)
    if args.ids:
        raw = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]
        q = q.filter(Prebooking.id.in_(raw))
    keep = {int(x) for x in args.keep.split(",") if x.strip().isdigit()} if args.keep else set()
    out = [b for b in q.order_by(Prebooking.id).all() if b.id not in keep]
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="aperçu sans suppression (défaut)")
    p.add_argument("--apply", action="store_true", help="exécute réellement les suppressions")
    p.add_argument("--channel", choices=["whatsapp", "telegram"])
    p.add_argument("--user")
    p.add_argument("--phone")
    p.add_argument("--ids")
    p.add_argument("--since")
    p.add_argument("--keep", default="", help="IDs à conserver (ex: 1,2)")
    args = p.parse_args()

    db = SessionLocal()
    try:
        prebookings = _match_prebookings(db.query(Prebooking), args)
        users = {(b.channel, b.user_id) for b in prebookings}
        if args.user or args.channel:
            ch = args.channel or "whatsapp"
            users.add((args.channel or "whatsapp", args.user)) if args.user else None

        sessions = db.query(SessionState).filter(
            SessionState.user_id.in_([u for _, u in users]),
        )
        conversations = db.query(Conversation).filter(
            Conversation.user_id.in_([u for _, u in users]),
        )

        print(f"Cible : {len(prebookings)} pré-réservation(s), "
              f"{sessions.count()} session(s), {conversations.count()} conversation(s)\n")
        for b in prebookings:
            print(f"  #{b.id:<4} {b.channel:<9} {b.user_id or '':<14} {b.name or '':<20} "
                  f"{b.check_in or '':<7} → {b.check_out or '':<7} {b.room_type or '':<3} "
                  f"{b.status:<16} {b.amount_due or 0:,} F")

        if args.apply:
            if not prebookings and not sessions.count() and not conversations.count():
                print("\nRien à supprimer.")
                return 0
            n_prev = prebookings
            if n_prev:
                db.query(Prebooking).filter(
                    Prebooking.id.in_([b.id for b in n_prev])
                ).delete(synchronize_session=False)
            if sessions.count():
                sessions.delete(synchronize_session=False)
            if conversations.count():
                conversations.delete(synchronize_session=False)
            db.commit()
            print(f"\n✅ Suppression exécutée : {len(n_prev)} résa(s), "
                  f"{sessions.count()} session(s) restante(s), {conversations.count()} conversation(s) restante(s)")
        else:
            print("\n[DRY-RUN] aucune suppression. Relancez avec --apply pour exécuter.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())