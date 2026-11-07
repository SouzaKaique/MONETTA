"""
Indicadores do mês. Todo cálculo financeiro fica aqui, nunca no frontend.

Fluxo de caixa usa `paid_on` e só considera status 'confirmed'.
Competência usa `competence_date` e considera confirmados e pendentes.
Indicadores de módulos ainda não construídos voltam como None: zero seria
uma afirmação falsa sobre a situação financeira do usuário.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import Account, AppSettings, Category, Recurrence, Transaction
from . import alerts, cards, debts, recovery, spending, wishlist
from .balances import ZERO, total_balance
from .periods import month_bounds, shift_month, today_for
from .recurrences import generate, generation_horizon

HISTORY_MONTHS = 6


def _total(query) -> Decimal:
    return db.session.scalar(query) or ZERO


def _sum_amount():
    return sa.select(sa.func.coalesce(sa.func.sum(Transaction.amount), 0))


def _month_total(user_id: UUID, start: date, end: date, *filters) -> Decimal:
    return _total(_sum_amount().where(
        Transaction.user_id == user_id,
        Transaction.competence_date.between(start, end),
        *filters,
    ))


def pending_expenses_until(user_id: UUID, day: date) -> Decimal:
    """Tudo o que está em aberto até o dia, inclusive contas atrasadas de meses anteriores."""
    return _total(_sum_amount().where(
        Transaction.user_id == user_id, Transaction.kind == "expense",
        Transaction.status == "pending", Transaction.competence_date <= day,
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
            "expenses": _month_total(user_id, start, end, Transaction.kind == "expense")
            + cards.installments_total(user_id, start, end),
        })
    return rows


def _by_category(user_id: UUID, start: date, end: date) -> list[dict]:
    rows = db.session.execute(
        sa.select(Category.name, sa.func.sum(Transaction.amount))
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == user_id, Transaction.kind == "expense",
               Transaction.competence_date.between(start, end))
        .group_by(Category.name)
    ).all()
    totals = {name: total for name, total in rows}
    for name, total in cards.installments_by_category(user_id, start, end).items():
        totals[name] = totals.get(name, ZERO) + total
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [{"category": name or "Sem categoria", "total": total} for name, total in ordered]


def monthly_capacity(user_id: UUID, settings: AppSettings, today: date) -> Decimal | None:
    """
    Quanto sobra da renda prevista do mês depois das despesas, da reserva e do mínimo de
    segurança. Serve de teto para não sugerir pagamentos que comprometam contas essenciais.
    """
    summary = build_dashboard(user_id, settings, today.year, today.month)["summary"]
    if summary["income_expected"] <= 0:
        return None
    left = (
        summary["income_expected"] - summary["expenses_total"]
        - recovery.effective_safety(user_id, settings) - settings.planned_reserve
    )
    return max(ZERO, left)


def build_dashboard(
    user_id: UUID, settings: AppSettings, year: int, month: int, sync_alerts: bool = False,
) -> dict:
    today = today_for(settings)
    start, end = month_bounds(year, month)
    generate(user_id, generation_horizon(today, end))
    is_current = start <= today <= end
    is_past = end < today

    is_income = Transaction.kind == "income"
    is_expense = Transaction.kind == "expense"
    confirmed = Transaction.status == "confirmed"
    pending = Transaction.status == "pending"

    salary_received = _month_total(user_id, start, end, is_income, confirmed, Transaction.is_salary)
    salary_expected = _month_total(user_id, start, end, is_income, pending, Transaction.is_salary)
    extra_income = _month_total(user_id, start, end, is_income, confirmed, ~Transaction.is_salary)
    extra_expected = _month_total(user_id, start, end, is_income, pending, ~Transaction.is_salary)
    expenses_paid = _month_total(user_id, start, end, is_expense, confirmed)
    expenses_pending = _month_total(user_id, start, end, is_expense, pending)
    expenses_fixed = _month_total(user_id, start, end, is_expense, Transaction.is_fixed)
    # Compras no cartão entram aqui, pelas parcelas; pagar a fatura não soma de novo.
    card_commitment = cards.installments_total(user_id, start, end)
    expenses_total = expenses_paid + expenses_pending + card_commitment

    income_received = salary_received + extra_income
    # Previsto entra aqui só para medir comprometimento, nunca no saldo.
    income_expected = income_received + salary_expected + extra_expected
    # Dívidas ficam fora de despesas, mas comprometem a renda do mesmo jeito.
    debt_paid = debts.paid_between(user_id, start, end)
    debt_due = recovery.debt_due(user_id, start, end) if not is_past else ZERO
    committed = expenses_total + debt_paid + debt_due
    contributed = wishlist.contributed_between(user_id, start, end)
    commitment = round(committed / income_expected * 100) if income_expected > 0 else None

    balance = total_balance(user_id, end if is_past else today) if start <= today else None
    safety = recovery.effective_safety(user_id, settings)

    summary: dict = {
        "balance": balance,
        "income_expected": income_expected,
        "income_received": income_received,
        "salary_received": salary_received,
        "salary_expected": salary_expected,
        "extra_income": extra_income,
        "expenses_total": expenses_total,
        "expenses_paid": expenses_paid,
        "expenses_pending": expenses_pending,
        "expenses_fixed": expenses_fixed,
        "expenses_variable": expenses_total - expenses_fixed - card_commitment,
        "income_commitment_pct": commitment,
        # Dinheiro livre do mês por competência: não é saldo em conta.
        "free_money": income_expected - committed - contributed,
        "safety_minimum": safety,
        "overdue_expenses": ZERO,
        # Só faz sentido no mês corrente e nunca conta receita futura.
        "available_to_spend": None,
        "projected_balance": None,
        "card_commitment": card_commitment,
        "open_invoices": cards.invoices_due_between(user_id, start, end),
        "overdue_invoices": ZERO,
        "debt_payments": debt_paid,
        "debt_due": debt_due,
        "pending_debts": debts.total_balance(user_id),
        "reserves": contributed,
        "saved_total": wishlist.saved_total(user_id),
    }
    if is_current:
        # Obrigações do mês: lançamentos pendentes e o que falta das faturas, sem sobreposição.
        open_until_month_end = (
            pending_expenses_until(user_id, end)
            + cards.invoices_due_until(user_id, end)
            + debt_due
        )
        summary["overdue_expenses"] = pending_expenses_until(user_id, start - timedelta(days=1))
        summary["overdue_invoices"] = cards.invoices_due_until(user_id, start - timedelta(days=1))
        summary["projected_balance"] = balance - open_until_month_end
        # Com salário cadastrado, vale o mesmo número do simulador: nunca dois "disponíveis".
        until = spending.until_salary(user_id, settings, today)
        summary["available_to_spend"] = until["available"] if until["has_salary"] else max(
            ZERO,
            balance - open_until_month_end - safety - wishlist.saved_total(user_id)
            - max(ZERO, settings.planned_reserve - contributed),
        )

    has_accounts = db.session.scalar(
        sa.select(sa.exists().where(Account.user_id == user_id, Account.active))
    )
    has_salary = db.session.scalar(
        sa.select(sa.exists().where(Recurrence.user_id == user_id, Recurrence.is_salary))
    )
    has_transactions = db.session.scalar(
        sa.select(sa.exists().where(Transaction.user_id == user_id))
    )
    month_alerts = alerts.collect(user_id, settings, summary, today, year, month, is_current)
    if sync_alerts:
        alerts.sync(user_id, settings, month_alerts)
    return {
        "month": f"{year:04d}-{month:02d}",
        "is_current_month": is_current,
        "has_accounts": bool(has_accounts),
        "has_salary": bool(has_salary),
        "has_data": bool(has_accounts or has_transactions),
        "summary": summary,
        "history": _history(user_id, year, month),
        "by_category": _by_category(user_id, start, end),
        "recovery_active": recovery.active_plan(user_id) is not None,
        "alerts": month_alerts,
    }
