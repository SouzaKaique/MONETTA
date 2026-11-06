"""
Indicadores do dashboard. Todo cálculo financeiro fica aqui, nunca no frontend.

Fluxo de caixa usa `paid_on` e só considera status 'confirmed'.
Competência usa `competence_date` e considera confirmados e pendentes.
Indicadores de módulos ainda não construídos voltam como None: zero seria
uma afirmação falsa sobre a situação financeira do usuário.
"""
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from ..extensions import db
from ..models import Account, AppSettings, Category, Transaction

ZERO = Decimal("0.00")
HISTORY_MONTHS = 6


def today_for(settings: AppSettings) -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _total(query) -> Decimal:
    return db.session.scalar(query) or ZERO


def _sum_amount():
    return sa.select(sa.func.coalesce(sa.func.sum(Transaction.amount), 0))


def balance_on(user_id: UUID, day: date) -> Decimal:
    """Saldo calculado: abertura das contas + entradas e saídas confirmadas até o dia."""
    opening = _total(sa.select(sa.func.coalesce(sa.func.sum(Account.opening_balance), 0)).where(
        Account.user_id == user_id, Account.active, Account.opening_date <= day
    ))
    moved = _sum_amount().where(
        Transaction.user_id == user_id,
        Transaction.status == "confirmed",
        Transaction.paid_on <= day,
    )
    income = _total(moved.where(Transaction.kind == "income"))
    expense = _total(moved.where(Transaction.kind == "expense"))
    return opening + income - expense


def _month_total(user_id: UUID, start: date, end: date, *filters) -> Decimal:
    return _total(_sum_amount().where(
        Transaction.user_id == user_id,
        Transaction.competence_date.between(start, end),
        *filters,
    ))


def _history(user_id: UUID, year: int, month: int) -> list[dict]:
    rows = []
    for offset in range(-(HISTORY_MONTHS - 1), 1):
        y, m = shift_month(year, month, offset)
        start, end = month_bounds(y, m)
        rows.append({
            "month": f"{y:04d}-{m:02d}",
            "income": _month_total(user_id, start, end, Transaction.kind == "income",
                                   Transaction.status == "confirmed"),
            "expenses": _month_total(user_id, start, end, Transaction.kind == "expense"),
        })
    return rows


def _by_category(user_id: UUID, start: date, end: date) -> list[dict]:
    rows = db.session.execute(
        sa.select(Category.name, sa.func.sum(Transaction.amount).label("total"))
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == user_id, Transaction.kind == "expense",
               Transaction.competence_date.between(start, end))
        .group_by(Category.name)
        .order_by(sa.text("total DESC"))
    ).all()
    return [{"category": name or "Sem categoria", "total": total} for name, total in rows]


def _alerts(summary: dict, is_current: bool) -> list[dict]:
    alerts = []
    pct = summary["income_commitment_pct"]
    if pct is not None and pct >= 80:
        alerts.append({"level": "warning", "message": f"Você já comprometeu {pct}% da sua renda."})
    if is_current and summary["projected_balance"] < 0:
        alerts.append({"level": "critical", "message": "Seu saldo projetado está negativo."})
    return alerts


def build_dashboard(user_id: UUID, settings: AppSettings, year: int, month: int) -> dict:
    today = today_for(settings)
    start, end = month_bounds(year, month)
    is_current = start <= today <= end
    is_past = end < today

    is_income = Transaction.kind == "income"
    is_expense = Transaction.kind == "expense"
    confirmed = Transaction.status == "confirmed"
    pending = Transaction.status == "pending"

    salary_received = _month_total(user_id, start, end, is_income, confirmed, Transaction.is_salary)
    salary_expected = _month_total(user_id, start, end, is_income, pending, Transaction.is_salary)
    extra_income = _month_total(user_id, start, end, is_income, confirmed, ~Transaction.is_salary)
    expenses_paid = _month_total(user_id, start, end, is_expense, confirmed)
    expenses_pending = _month_total(user_id, start, end, is_expense, pending)
    expenses_total = expenses_paid + expenses_pending

    # Renda de referência: previsto entra aqui só para medir comprometimento, nunca no saldo.
    income_base = salary_received + salary_expected + extra_income
    commitment = round(expenses_total / income_base * 100) if income_base > 0 else None

    balance = balance_on(user_id, end if is_past else today) if start <= today else None

    summary: dict = {
        "balance": balance,
        "salary_received": salary_received,
        "salary_expected": salary_expected,
        "extra_income": extra_income,
        "expenses_total": expenses_total,
        "expenses_paid": expenses_paid,
        "expenses_pending": expenses_pending,
        "income_commitment_pct": commitment,
        "safety_minimum": settings.safety_minimum,
        # Só faz sentido no mês corrente e nunca conta receita futura.
        "available_to_spend": None,
        "projected_balance": None,
        # Dependem de módulos das próximas etapas.
        "open_invoices": None,
        "pending_debts": None,
        "saved_total": None,
    }
    if is_current:
        summary["projected_balance"] = balance - expenses_pending
        summary["available_to_spend"] = max(
            ZERO, balance - expenses_pending - settings.safety_minimum
        )

    has_accounts = db.session.scalar(
        sa.select(sa.exists().where(Account.user_id == user_id, Account.active))
    )
    has_transactions = db.session.scalar(
        sa.select(sa.exists().where(Transaction.user_id == user_id))
    )
    return {
        "month": f"{year:04d}-{month:02d}",
        "is_current_month": is_current,
        "has_data": bool(has_accounts or has_transactions),
        "summary": summary,
        "history": _history(user_id, year, month),
        "by_category": _by_category(user_id, start, end),
        "alerts": _alerts(summary, is_current),
    }
