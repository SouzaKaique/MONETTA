"""Validação e serialização compartilhadas pelas rotas financeiras."""
from uuid import UUID

import sqlalchemy as sa
from flask import abort, g
from marshmallow import ValidationError, fields, validate
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Account, Category, Recurrence, Transaction, Transfer
from ..services.balances import account_balance
from ..services.periods import today_for
from ..services.recurrences import amount_for, occurrences

PAYMENT_METHODS = ["pix", "debit", "cash", "boleto", "transfer", "other"]


def MoneyField(**kwargs):
    """Valor positivo com duas casas; fields.Decimal rejeita NaN e infinito."""
    return fields.Decimal(
        places=2, validate=validate.Range(min=0.01, max=999_999_999.99), **kwargs
    )


def PaymentField(**kwargs):
    return fields.String(validate=validate.OneOf(PAYMENT_METHODS), allow_none=True, **kwargs)


def owned(model, record_id: UUID):
    """Busca um registro do usuário atual; de outro usuário é 404, nunca 403."""
    record = db.session.get(model, record_id)
    if record is None or record.user_id != g.user.id:
        abort(404)
    return record


def check_account(account_id: UUID | None, field: str = "account_id") -> None:
    if account_id is None:
        return
    account = db.session.get(Account, account_id)
    if account is None or account.user_id != g.user.id:
        raise ValidationError({field: ["Conta não encontrada."]})


def check_category(category_id: UUID | None, kind: str) -> None:
    if category_id is None:
        return
    category = db.session.get(Category, category_id)
    if category is None or category.user_id != g.user.id or category.kind != kind:
        raise ValidationError({"category_id": ["Categoria inválida."]})


def today():
    return today_for(g.user.settings)


def find_by_key(model, key: str | None):
    """Registro já criado com esta Idempotency-Key, se houver."""
    if not key:
        return None
    return db.session.scalar(sa.select(model).filter_by(user_id=g.user.id, idempotency_key=key))


def save_once(model, key: str | None):
    """
    Grava a transação. Se dois envios iguais chegarem juntos, a constraint barra o
    segundo: aí a resposta é o registro do primeiro, não um erro. Retorna esse registro.
    """
    try:
        db.session.commit()
        return None
    except IntegrityError:
        db.session.rollback()
        existing = find_by_key(model, key)
        if existing is None:
            raise
        return existing


def category_payload(category: Category) -> dict:
    return {
        "id": str(category.id), "name": category.name, "kind": category.kind,
        "icon": category.icon, "is_default": category.is_default,
        "is_essential": category.is_essential,
    }


def account_payload(account: Account) -> dict:
    balance = account_balance(account, today())
    real = account.real_balance
    return {
        "id": str(account.id), "name": account.name, "type": account.type,
        "opening_balance": account.opening_balance,
        "opening_date": account.opening_date.isoformat(),
        "balance": balance,
        "real_balance": real,
        "real_balance_on": account.real_balance_on.isoformat() if account.real_balance_on else None,
        "difference": None if real is None else real - balance,
        "active": account.active,
    }


def transaction_payload(tx: Transaction) -> dict:
    return {
        "id": str(tx.id), "kind": tx.kind, "status": tx.status, "description": tx.description,
        "amount": tx.amount, "competence_date": tx.competence_date.isoformat(),
        "paid_on": tx.paid_on.isoformat() if tx.paid_on else None,
        "account_id": str(tx.account_id) if tx.account_id else None,
        "account_name": tx.account.name if tx.account else None,
        "category_id": str(tx.category_id) if tx.category_id else None,
        "category_name": tx.category.name if tx.category else None,
        "payment_method": tx.payment_method, "notes": tx.notes,
        "is_salary": tx.is_salary, "is_fixed": tx.is_fixed,
        "recurrence_id": str(tx.recurrence_id) if tx.recurrence_id else None,
    }


def recurrence_payload(rec: Recurrence) -> dict:
    now = today()
    upcoming = next(
        (d for d in occurrences(rec, now.replace(year=now.year + 2, day=1)) if d >= now), None
    ) if rec.active else None
    return {
        "id": str(rec.id), "kind": rec.kind, "name": rec.name, "is_salary": rec.is_salary,
        "amount": amount_for(rec, now), "frequency": rec.frequency,
        "day_of_month": rec.day_of_month, "start_date": rec.start_date.isoformat(),
        "end_date": rec.end_date.isoformat() if rec.end_date else None,
        "active": rec.active, "next_date": upcoming.isoformat() if upcoming else None,
        "category_id": str(rec.category_id) if rec.category_id else None,
        "category_name": rec.category.name if rec.category else None,
        "account_id": str(rec.account_id) if rec.account_id else None,
        "card_id": str(rec.card_id) if rec.card_id else None,
        "card_name": rec.card.name if rec.card else None,
        "payment_method": rec.payment_method, "notes": rec.notes,
        "amount_history": [
            {"amount": a.amount, "effective_from": a.effective_from.isoformat()}
            for a in rec.amounts
        ],
    }


def transfer_payload(transfer: Transfer) -> dict:
    return {
        "id": str(transfer.id), "amount": transfer.amount, "date": transfer.date.isoformat(),
        "from_account": transfer.from_account.name, "to_account": transfer.to_account.name,
        "notes": transfer.notes,
    }
