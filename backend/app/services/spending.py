"""
"Quanto posso gastar até o próximo salário?"

Parte só do saldo confirmado. Receita futura nunca entra: o salário só marca o fim do período.
"""
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import AppSettings, CreditCard, Installment, Invoice, InvoicePayment, Transaction
from . import recovery
from .balances import ZERO, total_balance
from .periods import month_bounds

DAILY_ALERT_PCT = 80


def next_salary(user_id: UUID, today: date) -> Transaction | None:
    return db.session.scalar(
        sa.select(Transaction).where(
            Transaction.user_id == user_id, Transaction.is_salary,
            Transaction.status == "pending", Transaction.competence_date >= today,
        ).order_by(Transaction.competence_date).limit(1)
    )


def _pending_expenses(user_id: UUID, before: date) -> list[dict]:
    rows = db.session.scalars(
        sa.select(Transaction).where(
            Transaction.user_id == user_id, Transaction.kind == "expense",
            Transaction.status == "pending", Transaction.competence_date < before,
        ).order_by(Transaction.competence_date)
    ).all()
    return [
        {"kind": "fixed" if t.is_fixed else "expense", "label": t.description,
         "date": t.competence_date.isoformat(), "amount": t.amount}
        for t in rows
    ]


def _open_invoices(user_id: UUID, before: date) -> list[dict]:
    rows = db.session.execute(
        sa.select(Invoice, CreditCard.name).join(CreditCard).where(
            Invoice.user_id == user_id, Invoice.due_date < before,
        ).order_by(Invoice.due_date)
    ).all()
    items = []
    for invoice, card_name in rows:
        charged = db.session.scalar(
            sa.select(sa.func.sum(Installment.amount)).filter_by(invoice_id=invoice.id)
        ) or ZERO
        paid = db.session.scalar(
            sa.select(sa.func.sum(InvoicePayment.amount)).filter_by(invoice_id=invoice.id)
        ) or ZERO
        if charged > paid:
            items.append({"kind": "invoice", "label": f"Fatura {card_name}",
                          "date": invoice.due_date.isoformat(), "amount": charged - paid})
    return items


def spent_today(user_id: UUID, today: date) -> Decimal:
    return db.session.scalar(
        sa.select(sa.func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id, Transaction.kind == "expense",
            Transaction.status == "confirmed", Transaction.paid_on == today,
        )
    ) or ZERO


def until_salary(user_id: UUID, settings: AppSettings, today: date, spend: Decimal = ZERO) -> dict:
    salary = next_salary(user_id, today)
    if salary is None:
        return {"has_salary": False}

    salary_date = salary.competence_date
    days = max(1, (salary_date - today).days)
    balance = total_balance(user_id, today)

    commitments = _pending_expenses(user_id, salary_date) + _open_invoices(user_id, salary_date)
    start, end = month_bounds(today.year, today.month)
    due = recovery.debt_due(user_id, start, end)
    if due > 0:
        commitments.append({"kind": "debt", "label": "Pagamentos de dívidas", "date": None, "amount": due})
    if settings.planned_reserve > 0:
        commitments.append({"kind": "reserve", "label": "Reserva", "date": None, "amount": settings.planned_reserve})

    committed = sum((c["amount"] for c in commitments), ZERO)
    safety = recovery.effective_safety(user_id, settings)
    free = balance - committed - safety - spend
    available = max(ZERO, free)
    daily = (available / days).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return {
        "has_salary": True,
        "next_salary_date": salary_date.isoformat(),
        "days_left": days,
        "balance": balance,
        "committed": committed,
        "safety_minimum": safety,
        "commitments": commitments,
        "scenario_spend": spend,
        "available": available,
        # Quanto falta para cobrir tudo; zero quando as contas cabem no saldo.
        "shortfall": max(ZERO, -free),
        "daily_limit": daily,
        "weekly_limit": min(available, daily * 7),
        "spent_today": spent_today(user_id, today),
    }


def daily_alert(user_id: UUID, snapshot: dict, today: date) -> list[dict]:
    """Compara o gasto de hoje com o limite que valia antes dele."""
    if not snapshot.get("has_salary"):
        return []
    spent = snapshot["spent_today"]
    limit = (snapshot["available"] + spent) / snapshot["days_left"]
    if spent <= 0 or limit <= 0 or spent / limit * 100 < DAILY_ALERT_PCT:
        return []
    return [{
        "kind": "balance", "key": f"daily-limit:{today.isoformat()}", "level": "warning",
        "message": "Seu orçamento diário está próximo do limite.", "link": "/",
    }]


def future_commitments(user_id: UUID, after: date, months: int = 3) -> Decimal:
    """O que já está comprometido nos meses seguintes: pendências e parcelas."""
    until = after + timedelta(days=31 * months)
    pending = db.session.scalar(
        sa.select(sa.func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id, Transaction.kind == "expense",
            Transaction.status == "pending", Transaction.competence_date.between(
                after + timedelta(days=1), until),
        )
    ) or ZERO
    installments = db.session.scalar(
        sa.select(sa.func.sum(Installment.amount)).join(Invoice).where(
            Installment.user_id == user_id,
            Invoice.due_date.between(after + timedelta(days=1), until),
        )
    ) or ZERO
    return pending + installments
