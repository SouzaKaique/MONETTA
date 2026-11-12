"""
Backup e restauração dos dados de um usuário.

O arquivo é tratado como não confiável: só colunas conhecidas são aceitas, todos os
identificadores são gerados de novo e uma referência só vale se apontar para um registro
do próprio arquivo. Assim, ele nunca alcança dados de outro usuário.
"""
import base64
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

import sqlalchemy as sa

from ..extensions import db
from ..models import (
    Account, AppSettings, CardPurchase, Category, CreditCard, Debt, DebtPayment, GoalContribution,
    Installment, Invoice, InvoicePayment, Recurrence, RecurrenceAmount, RecurrenceSkip,
    RecoveryPlan, SavingsGoal, Transaction, Transfer, Budget, WishlistImage, WishlistItem,
)
from ..models.common import utcnow

VERSION = 1
# Ordem das dependências: cada tabela só aponta para as anteriores.
MODELS = [
    Account, Category, CreditCard, Recurrence, RecurrenceAmount, RecurrenceSkip, Transaction,
    Transfer, Invoice, CardPurchase, Installment, InvoicePayment, Debt, DebtPayment, Budget,
    RecoveryPlan, WishlistItem, SavingsGoal, GoalContribution, WishlistImage,
]
# Tabelas sem user_id, ligadas ao dono pela tabela pai.
PARENTS = {
    RecurrenceAmount: (RecurrenceAmount.recurrence_id, Recurrence),
    RecurrenceSkip: (RecurrenceSkip.recurrence_id, Recurrence),
    WishlistImage: (WishlistImage.item_id, WishlistItem),
}
SETTINGS_FIELDS = ("theme", "timezone", "safety_minimum", "debt_strategy", "planned_reserve", "alert_prefs")
USER_DATA = (Account, Transaction, CreditCard, Debt, WishlistItem)


class BackupError(Exception):
    pass


def _serialize(value):
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    return value


def _rows(model, user_id: UUID) -> list[dict]:
    table = model.__table__
    if model in PARENTS:
        column, parent = PARENTS[model]
        query = sa.select(table).where(
            column.in_(sa.select(parent.id).where(parent.user_id == user_id))
        )
    else:
        query = sa.select(table).where(table.c.user_id == user_id)
    return [
        {key: _serialize(value) for key, value in row._mapping.items() if key != "user_id"}
        for row in db.session.execute(query)
    ]


def export_user(user_id: UUID, settings: AppSettings) -> dict:
    return {
        "app": "monetta",
        "version": VERSION,
        "created_at": utcnow().isoformat(),
        "settings": {f: _serialize(getattr(settings, f)) for f in SETTINGS_FIELDS},
        "tables": {m.__tablename__: _rows(m, user_id) for m in MODELS},
    }


def _convert(column: sa.Column, value):
    """Converte pelo tipo declarado na coluna; valor estranho vira erro, não dado."""
    if value is None:
        return None
    kind = column.type
    try:
        if isinstance(kind, sa.Uuid):
            return UUID(str(value))
        if isinstance(kind, sa.DateTime):
            return datetime.fromisoformat(value)
        if isinstance(kind, sa.Date):
            return date.fromisoformat(value)
        if isinstance(kind, sa.Numeric):
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError
            return number
        if isinstance(kind, sa.Boolean):
            if not isinstance(value, bool):
                raise ValueError
            return value
        if isinstance(kind, sa.Integer):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError
            return value
        if isinstance(kind, sa.LargeBinary):
            return base64.b64decode(value, validate=True)
        if isinstance(kind, sa.String):
            if not isinstance(value, str):
                raise ValueError
            return value
    except (ValueError, TypeError, InvalidOperation, AttributeError) as exc:
        raise BackupError(f"Valor inválido em {column.name}.") from exc
    return value


def _insert_table(model, rows: list, ids: dict, user_id: UUID) -> None:
    table = model.__table__
    known = {c.name for c in table.columns}
    for row in rows:
        if not isinstance(row, dict) or set(row) - known or "user_id" in row:
            raise BackupError("O arquivo tem campos desconhecidos.")
        values = {}
        for name, raw in row.items():
            column = table.c[name]
            value = _convert(column, raw)
            if value is not None and column.foreign_keys:
                if str(value) not in ids:
                    raise BackupError("O arquivo aponta para um registro inexistente.")
                value = ids[str(value)]
            values[name] = value
        if "id" in known:
            old = row.get("id")
            if not old:
                raise BackupError("Registro sem identificador.")
            new = uuid4()
            ids[str(old)] = new
            values["id"] = new
        if "user_id" in known:
            values["user_id"] = user_id
        if model is RecoveryPlan:
            values["priority_debt_ids"] = [
                str(ids[str(i)]) for i in (values.get("priority_debt_ids") or []) if str(i) in ids
            ]
        db.session.execute(sa.insert(table).values(**values))


def restore_user(user_id: UUID, settings: AppSettings, payload: dict) -> dict:
    """Só restaura em conta vazia: um backup nunca sobrescreve dados existentes."""
    if not isinstance(payload, dict) or payload.get("app") != "monetta":
        raise BackupError("Este não é um backup do MONETTA.")
    if payload.get("version") != VERSION:
        raise BackupError("Versão de backup não suportada.")
    tables = payload.get("tables")
    if not isinstance(tables, dict) or set(tables) - {m.__tablename__ for m in MODELS}:
        raise BackupError("O arquivo tem tabelas desconhecidas.")
    for model in USER_DATA:
        if db.session.scalar(sa.select(sa.exists().where(model.user_id == user_id))):
            raise BackupError("A restauração só funciona em uma conta sem dados.")

    db.session.execute(sa.delete(Category).where(Category.user_id == user_id))
    ids: dict[str, UUID] = {}
    counts = {}
    for model in MODELS:
        rows = tables.get(model.__tablename__, [])
        if not isinstance(rows, list):
            raise BackupError("Formato de tabela inválido.")
        _insert_table(model, rows, ids, user_id)
        counts[model.__tablename__] = len(rows)

    saved = payload.get("settings") or {}
    if not isinstance(saved, dict) or set(saved) - set(SETTINGS_FIELDS):
        raise BackupError("Configurações inválidas.")
    table = AppSettings.__table__
    for field, value in saved.items():
        setattr(settings, field, _convert(table.c[field], value))
    return counts
