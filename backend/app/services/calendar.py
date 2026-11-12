"""Calendário: todos os eventos do mês, calculados a partir dos módulos."""
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Debt, DebtPayment, Invoice, Transaction
from . import cards, debts, recovery, wishlist
from .periods import month_bounds


def _transaction_type(tx: Transaction) -> str:
    if tx.kind == "income":
        return "salary" if tx.is_salary else "income"
    return "recurring" if tx.is_fixed else "bill"


def _transactions(user_id: UUID, start: date, end: date) -> list[dict]:
    rows = db.session.scalars(
        sa.select(Transaction).options(joinedload(Transaction.category))
        .where(Transaction.user_id == user_id, Transaction.competence_date.between(start, end))
    ).all()
    return [{
        "id": f"tx:{t.id}", "type": _transaction_type(t), "date": t.competence_date.isoformat(),
        "title": t.description, "amount": t.amount,
        "status": "done" if t.status == "confirmed" else "pending",
        "transaction_id": str(t.id), "link": "/receitas" if t.kind == "income" else "/despesas",
    } for t in rows]


def _invoices(user_id: UUID, start: date, end: date, today: date) -> list[dict]:
    rows = db.session.scalars(
        sa.select(Invoice).options(joinedload(Invoice.card)).where(
            Invoice.user_id == user_id,
            sa.or_(Invoice.closing_date.between(start, end), Invoice.due_date.between(start, end)),
        )
    ).unique().all()
    events = []
    for invoice in rows:
        total = cards.invoice_total(invoice)
        done = cards.invoice_status(invoice, today) == "paid"
        link = f"/cartoes/{invoice.card_id}"
        if start <= invoice.closing_date <= end:
            events.append({
                "id": f"closing:{invoice.id}", "type": "invoice_closing",
                "date": invoice.closing_date.isoformat(), "title": f"Fechamento {invoice.card.name}",
                "amount": total, "status": "done" if today >= invoice.closing_date else "pending",
                "link": link,
            })
        if start <= invoice.due_date <= end:
            events.append({
                "id": f"due:{invoice.id}", "type": "invoice_due",
                "date": invoice.due_date.isoformat(), "title": f"Vencimento {invoice.card.name}",
                "amount": total - cards.invoice_paid(invoice) if not done else total,
                "status": "done" if done else "pending", "link": link,
            })
    return events


def _debts(user_id: UUID, start: date, end: date) -> list[dict]:
    events = [{
        "id": f"payment:{p.id}", "type": "debt", "date": p.paid_on.isoformat(),
        "title": f"Pagamento {name}", "amount": p.amount, "status": "done", "link": "/dividas",
    } for p, name in db.session.execute(
        sa.select(DebtPayment, Debt.name).join(Debt).where(
            DebtPayment.user_id == user_id, DebtPayment.paid_on.between(start, end),
        )
    ).all()]
    for debt in debts.user_debts(user_id):
        balance = debts.balance_of(debt)
        if debt.due_date and start <= debt.due_date <= end and balance > 0:
            events.append({
                "id": f"debt-due:{debt.id}", "type": "debt", "date": debt.due_date.isoformat(),
                "title": f"Vencimento {debt.name}", "amount": balance, "status": "pending",
                "link": "/dividas",
            })
    return events


def _goals(user_id: UUID, start: date, end: date) -> list[dict]:
    events = [{
        "id": f"goal:{item.goal.id}", "type": "goal", "date": item.goal.target_date.isoformat(),
        "title": f"Meta: {item.name}", "amount": item.goal.target_amount,
        "status": "done" if item.status == "bought" else "pending", "link": "/wishlist",
    } for item in wishlist.user_items(user_id)
        if item.goal.target_date and start <= item.goal.target_date <= end
        and item.status != "given_up"]
    plan = recovery.plan_for(user_id)
    if plan and plan.active and plan.target_date and start <= plan.target_date <= end:
        events.append({
            "id": f"goal:{plan.id}", "type": "goal", "date": plan.target_date.isoformat(),
            "title": "Meta do Modo Recuperação", "amount": None, "status": "pending",
            "link": "/recuperacao",
        })
    return events


def month_events(user_id: UUID, year: int, month: int, today: date) -> list[dict]:
    start, end = month_bounds(year, month)
    events = (
        _transactions(user_id, start, end) + _invoices(user_id, start, end, today)
        + _debts(user_id, start, end) + _goals(user_id, start, end)
    )
    return sorted(events, key=lambda e: (e["date"], e["title"]))
