"""Gastos por categoria e limites do orçamento mensal."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import Budget, CardPurchase, Category, Installment, Invoice, Transaction
from .balances import ZERO
from .periods import month_bounds, shift_month

MIN_INCREASE_BASE = Decimal("50.00")  # abaixo disso, variação percentual não diz nada
INCREASE_PCT = 20


def spent_by_category(user_id: UUID, start: date, end: date) -> dict[UUID | None, Decimal]:
    """Despesas por competência: lançamentos mais parcelas de cartão, cada compra uma vez."""
    totals: dict[UUID | None, Decimal] = {}
    rows = db.session.execute(
        sa.select(Transaction.category_id, sa.func.sum(Transaction.amount))
        .where(Transaction.user_id == user_id, Transaction.kind == "expense",
               Transaction.competence_date.between(start, end))
        .group_by(Transaction.category_id)
    ).all()
    cards = db.session.execute(
        sa.select(CardPurchase.category_id, sa.func.sum(Installment.own_amount()))
        .select_from(Installment)
        .join(Invoice, Installment.invoice_id == Invoice.id)
        .join(CardPurchase, Installment.purchase_id == CardPurchase.id)
        .where(Installment.user_id == user_id, Invoice.due_date.between(start, end))
        .group_by(CardPurchase.category_id)
    ).all()
    for category_id, total in [*rows, *cards]:
        totals[category_id] = totals.get(category_id, ZERO) + total
    return totals


def expense_categories(user_id: UUID) -> list[Category]:
    return list(db.session.scalars(
        sa.select(Category).where(Category.user_id == user_id, Category.kind == "expense")
        .order_by(Category.name)
    ))


def limits_for(user_id: UUID, month_start: date) -> dict[UUID, Decimal]:
    """Último limite definido até o mês; zero significa sem limite."""
    rows = db.session.scalars(
        sa.select(Budget).where(Budget.user_id == user_id, Budget.month <= month_start)
        .order_by(Budget.month)
    ).all()
    limits = {row.category_id: row.amount for row in rows}
    return {category: amount for category, amount in limits.items() if amount > 0}


def status(user_id: UUID, year: int, month: int) -> list[dict]:
    start, end = month_bounds(year, month)
    spent = spent_by_category(user_id, start, end)
    limits = limits_for(user_id, start)
    rows = []
    for category in expense_categories(user_id):
        limit = limits.get(category.id)
        total = spent.get(category.id, ZERO)
        if limit is None and total == 0:
            continue
        rows.append({
            "category_id": str(category.id), "name": category.name, "icon": category.icon,
            "is_essential": category.is_essential, "limit": limit, "spent": total,
            "remaining": None if limit is None else limit - total,
            "pct": None if limit is None else round(total / limit * 100),
        })
    if spent.get(None):
        rows.append({
            "category_id": None, "name": "Sem categoria", "icon": "tag", "is_essential": False,
            "limit": None, "spent": spent[None], "remaining": None, "pct": None,
        })
    return sorted(rows, key=lambda r: r["spent"], reverse=True)


def essential_split(user_id: UUID, start: date, end: date) -> tuple[Decimal, Decimal]:
    """Lançamentos do mês, sem cartão, separados em essenciais e não essenciais."""
    rows = db.session.execute(
        sa.select(Category.is_essential, sa.func.sum(Transaction.amount))
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == user_id, Transaction.kind == "expense",
               Transaction.competence_date.between(start, end))
        .group_by(Category.is_essential)
    ).all()
    essential = sum((total for flag, total in rows if flag), ZERO)
    other = sum((total for flag, total in rows if not flag), ZERO)
    return essential, other


def non_essential_spent(user_id: UUID, start: date, end: date) -> Decimal:
    """Inclui compras no cartão: é o que o Modo Recuperação tenta reduzir."""
    essential = {c.id for c in expense_categories(user_id) if c.is_essential}
    return sum(
        (total for category, total in spent_by_category(user_id, start, end).items()
         if category not in essential),
        ZERO,
    )


def top_non_essential(user_id: UUID, start: date, end: date) -> str | None:
    names = {c.id: c.name for c in expense_categories(user_id) if not c.is_essential}
    spent = spent_by_category(user_id, start, end)
    ranked = sorted(
        ((total, names[c]) for c, total in spent.items() if c in names), reverse=True
    )
    return ranked[0][1] if ranked else None


def budget_alerts(user_id: UUID, year: int, month: int, threshold: int) -> list[dict]:
    alerts = []
    tag = f"{year:04d}-{month:02d}"
    for row in status(user_id, year, month):
        if row["pct"] is None or row["pct"] < threshold:
            continue
        # A faixa na chave faz o aviso repetir só ao cruzar 100%.
        band = "over" if row["pct"] >= 100 else "near"
        alerts.append({
            "kind": "budget",
            "key": f"budget:{row['category_id']}:{tag}:{band}",
            "level": "critical" if band == "over" else "warning",
            "message": f"Você utilizou {row['pct']}% do orçamento de {row['name'].lower()}.",
            "link": "/planejamento",
        })
    return alerts


def spending_increases(user_id: UUID, year: int, month: int) -> list[dict]:
    start, end = month_bounds(year, month)
    previous = month_bounds(*shift_month(year, month, -1))
    names = {c.id: c.name for c in expense_categories(user_id)}
    current = spent_by_category(user_id, start, end)
    before = spent_by_category(user_id, *previous)
    alerts = []
    for category, total in current.items():
        base = before.get(category, ZERO)
        if category is None or base < MIN_INCREASE_BASE:
            continue
        growth = round((total - base) / base * 100)
        if growth >= INCREASE_PCT:
            alerts.append({
                "kind": "insight",
                "key": f"increase:{category}:{year:04d}-{month:02d}",
                "level": "warning",
                "message": f"Seus gastos com {names[category].lower()} aumentaram {growth}%.",
                "link": "/planejamento",
            })
    return alerts
