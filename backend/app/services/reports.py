"""Relatórios por mês, trimestre ou ano, somando cada valor uma única vez."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import AppSettings, Debt, DebtPayment
from . import dashboard, wishlist
from .balances import ZERO
from .periods import month_bounds, shift_month

EVOLUTION_MONTHS = 6
RELEVANT_CHANGE_PCT = 5


def period_months(period: str, year: int, month: int) -> list[tuple[int, int]]:
    if period == "year":
        return [(year, m) for m in range(1, 13)]
    if period == "quarter":
        first = (month - 1) // 3 * 3 + 1
        return [(year, m) for m in range(first, first + 3)]
    return [(year, month)]


def _pct(part: Decimal, whole: Decimal) -> int | None:
    return round(part / whole * 100) if whole > 0 else None


def _totals(rows: list[dict]) -> dict:
    income = sum((r["income"] for r in rows), ZERO)
    expenses = sum((r["expenses"] for r in rows), ZERO)
    debts = sum((r["debt_paid"] for r in rows), ZERO)
    left = income - expenses - debts
    return {
        "income": income, "expenses": expenses, "cards": sum((r["cards"] for r in rows), ZERO),
        "debt_paid": debts, "saved": sum((r["saved"] for r in rows), ZERO), "result": left,
        "savings_pct": _pct(left, income),
    }


def _categories(user_id: UUID, start: date, end: date) -> list[dict]:
    return dashboard.by_category(user_id, start, end)


def _debt_payments(user_id: UUID, start: date, end: date) -> list[dict]:
    rows = db.session.execute(
        sa.select(DebtPayment, Debt.name).join(Debt)
        .where(DebtPayment.user_id == user_id, DebtPayment.paid_on.between(start, end))
        .order_by(DebtPayment.paid_on.desc()).limit(50)
    ).all()
    return [{"date": p.paid_on.isoformat(), "debt": name, "amount": p.amount} for p, name in rows]


def _wishlist(user_id: UUID) -> list[dict]:
    return [{
        "name": item.name, "saved": wishlist.saved_of(item), "target": item.goal.target_amount,
        "pct": min(100, round(wishlist.saved_of(item) / item.goal.target_amount * 100)),
    } for item in wishlist.user_items(user_id) if wishlist.is_open(item)]


def _insights(totals: dict, previous: dict, categories: list[dict]) -> list[str]:
    tips = []
    if categories:
        tips.append(f"Sua maior categoria de gastos foi {categories[0]['category'].lower()}.")
    base = previous["expenses"]
    if base > 0:
        change = round((totals["expenses"] - base) / base * 100)
        if abs(change) >= RELEVANT_CHANGE_PCT:
            word = "subiram" if change > 0 else "caíram"
            tips.append(f"Suas despesas {word} {abs(change)}% em relação ao período anterior.")
    if totals["savings_pct"] is not None:
        if totals["result"] < 0:
            tips.append("Saiu mais dinheiro do que entrou neste período.")
        else:
            tips.append(f"Sobraram {totals['savings_pct']}% do que você recebeu.")
    return tips


def report(user_id: UUID, settings: AppSettings, today: date, period: str, year: int, month: int) -> dict:
    months = period_months(period, year, month)
    start = month_bounds(*months[0])[0]
    end = month_bounds(*months[-1])[1]
    rows = [dashboard.month_row(user_id, y, m, today) for y, m in months]

    # Um único mês não forma tendência: os gráficos mostram os meses anteriores também.
    if len(rows) >= EVOLUTION_MONTHS:
        evolution = rows
    else:
        last_year, last_month = months[-1]
        evolution = [
            dashboard.month_row(user_id, *shift_month(last_year, last_month, offset), today)
            for offset in range(-(EVOLUTION_MONTHS - 1), 1)
        ]

    size = len(months)
    previous_months = [shift_month(months[0][0], months[0][1], -(size - i)) for i in range(size)]
    previous = _totals([dashboard.month_row(user_id, y, m, today) for y, m in previous_months])

    totals = _totals(rows)
    categories = _categories(user_id, start, end)
    return {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "totals": totals,
        "evolution": evolution,
        "categories": categories,
        "distribution": dashboard.income_distribution(user_id, settings, start, end, rows),
        "debt_payments": _debt_payments(user_id, start, end),
        "wishlist": _wishlist(user_id),
        "insights": _insights(totals, previous, categories),
    }
