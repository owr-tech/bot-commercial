import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./popaix.db")

# Render fournit postgresql://... (sans driver) → ajouter psycopg2
if DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {
        "sslmode": "require"
    },
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, nullable=False)  # whatsapp | telegram
    user_id = Column(String, nullable=False, index=True)  # phone ou tg chat id
    user_message = Column(Text, nullable=False)
    bot_reply = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Prebooking(Base):
    __tablename__ = "prebookings"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    check_in = Column(String, nullable=True)
    check_out = Column(String, nullable=True)
    room_type = Column(String, nullable=True)  # T1-T4
    phone = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | confirmed | paid | awaiting_payment
    notes = Column(Text, nullable=True)
    amount_due = Column(Integer, nullable=True)  # FCFA
    amount_paid = Column(Integer, nullable=True, default=0)  # FCFA
    payment_ref = Column(String, nullable=True)  # invoice_token PayDunya
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SessionState(Base):
    __tablename__ = "session_states"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    state = Column(String, nullable=True)  # prebooking flow step
    data = Column(Text, nullable=True)  # JSON
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def _ensure_payment_columns():
    """Migration légère : ajoute les colonnes paiement si la table prebookings existe déjà."""
    try:
        from sqlalchemy import inspect, text

        cols = {c["name"] for c in inspect(engine).get_columns("prebookings")}
        missing = [
            c
            for c in ["amount_due", "amount_paid", "payment_ref", "paid_at"]
            if c not in cols
        ]
        ddl = {
            "amount_due": "INTEGER",
            "amount_paid": "INTEGER",
            "payment_ref": "VARCHAR",
            "paid_at": "DATETIME",
        }
        for name in missing:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE prebookings ADD COLUMN {name} {ddl[name]}"))
    except Exception as e:
        print(f"[DB][WARN] migration paiement ignorée: {e}")


_ensure_payment_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_conversation(channel: str, user_id: str, user_message: str, bot_reply: str):
    db = SessionLocal()
    try:
        db.add(
            Conversation(
                channel=channel,
                user_id=user_id,
                user_message=user_message,
                bot_reply=bot_reply,
            )
        )
        db.commit()
    finally:
        db.close()


def save_prebooking(
    channel: str,
    user_id: str,
    name: Optional[str] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    room_type: Optional[str] = None,
    phone: Optional[str] = None,
    notes: Optional[str] = None,
    amount_due: Optional[int] = None,
    amount_paid: int = 0,
) -> Prebooking:
    db = SessionLocal()
    try:
        book = Prebooking(
            channel=channel,
            user_id=user_id,
            name=name,
            check_in=check_in,
            check_out=check_out,
            room_type=room_type,
            phone=phone,
            notes=notes,
            amount_due=amount_due,
            amount_paid=amount_paid,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book
    finally:
        db.close()


def get_prebooking(prebooking_id: int) -> Optional[Prebooking]:
    db = SessionLocal()
    try:
        return db.query(Prebooking).filter(Prebooking.id == prebooking_id).first()
    finally:
        db.close()


def update_prebooking_payment(prebooking_id: int, payment_ref: str, status: Optional[str] = None):
    """Attache la référence PayDunya à la pré-réservation (et optionnellement le statut)."""
    db = SessionLocal()
    try:
        row = db.query(Prebooking).filter(Prebooking.id == prebooking_id).first()
        if row:
            row.payment_ref = payment_ref
            if status:
                row.status = status
            db.commit()
    finally:
        db.close()


def mark_prebooking_paid(prebooking_id: int, amount_paid: int):
    db = SessionLocal()
    try:
        row = db.query(Prebooking).filter(Prebooking.id == prebooking_id).first()
        if row:
            row.status = "paid"
            row.amount_paid = amount_paid or row.amount_due
            row.paid_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def get_session_state(channel: str, user_id: str) -> Optional[SessionState]:
    db = SessionLocal()
    try:
        return (
            db.query(SessionState)
            .filter(
                SessionState.channel == channel,
                SessionState.user_id == user_id,
            )
            .first()
        )
    finally:
        db.close()


def set_session_state(channel: str, user_id: str, state: str, data: dict):
    db = SessionLocal()
    try:
        row = (
            db.query(SessionState)
            .filter(
                SessionState.channel == channel,
                SessionState.user_id == user_id,
            )
            .first()
        )
        import json

        if row:
            row.state = state
            row.data = json.dumps(data, ensure_ascii=False)
        else:
            db.add(
                SessionState(
                    channel=channel,
                    user_id=user_id,
                    state=state,
                    data=json.dumps(data, ensure_ascii=False),
                )
            )
        db.commit()
    finally:
        db.close()


def clear_session_state(channel: str, user_id: str):
    db = SessionLocal()
    try:
        row = (
            db.query(SessionState)
            .filter(
                SessionState.channel == channel,
                SessionState.user_id == user_id,
            )
            .first()
        )
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def get_recent_history(channel: str, user_id: str, limit: int = 10) -> list[Conversation]:
    db = SessionLocal()
    try:
        return (
            db.query(Conversation)
            .filter(
                Conversation.channel == channel,
                Conversation.user_id == user_id,
            )
            .order_by(Conversation.id.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def get_all_prebookings(limit: int = 100) -> list[Prebooking]:
    db = SessionLocal()
    try:
        return (
            db.query(Prebooking)
            .order_by(Prebooking.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def get_stats() -> dict:
    db = SessionLocal()
    try:
        conversations = db.query(Conversation).count()
        prebookings = db.query(Prebooking).count()
        confirmed = db.query(Prebooking).filter(Prebooking.status == "confirmed").count()
        paid = db.query(Prebooking).filter(Prebooking.status == "paid").count()
        awaiting_payment = db.query(Prebooking).filter(Prebooking.status == "awaiting_payment").count()
        pending = db.query(Prebooking).filter(Prebooking.status == "pending").count()
        cancelled = db.query(Prebooking).filter(Prebooking.status == "cancelled").count()
        whatsapp_convs = db.query(Conversation).filter(Conversation.channel == "whatsapp").count()
        telegram_convs = db.query(Conversation).filter(Conversation.channel == "telegram").count()
        return {
            "conversations": conversations,
            "whatsapp_conversations": whatsapp_convs,
            "telegram_conversations": telegram_convs,
            "prebookings": prebookings,
            "confirmed": confirmed,
            "paid": paid,
            "awaiting_payment": awaiting_payment,
            "pending": pending,
            "cancelled": cancelled,
        }
    finally:
        db.close()


def update_prebooking_status(prebooking_id: int, status: str):
    db = SessionLocal()
    try:
        row = db.query(Prebooking).filter(Prebooking.id == prebooking_id).first()
        if row:
            row.status = status
            db.commit()
    finally:
        db.close()