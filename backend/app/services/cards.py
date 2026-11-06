"""Faturas, parcelas e indicadores de cartão."""
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ..extensions import db
from ..models import (
    CardPurchase, Category, CreditCard, Installment, Invoice, InvoicePayment,
)
from .balances import ZERO
from .periods import clamp_day, month_bounds, shift_month

HIGH_USAGE_PCT = 80
DUE_SOON_DAYS = 3
SPENDING_MONTHS = 6


def split_installments(total: Decimal, count: int) -> list[Decimal]:
    """Divide sem perder centavos: a diferença do arredondamento fica na primeira parcela."""
    base = (total / count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [total - base * (count - 1)] + [base] * (count - 1)


def invoice_month_for(card: CreditCard, day: date) -> date:
    """
    Mês de vencimento da fatura que recebe uma compra. Compra feita até o dia do
    fechamento entra na fatura que está fechando; depois dele, na seguinte.
    """
    closing = clamp_day(day.year, day.month, card.closing_day)
    year, month = (day.year, day.month) if day <= closing else shift_month(day.year, day.month, 1)
    if card.due_day < card.closing_day:
        year, month = shift_month(year, month, 1)
    return date(year, month, 1)


def invoice_dates(card: CreditCard, reference: date) -> tuple[date, date]:
    """Fechamento e vencimento da fatura de um mês de vencimento."""
    due = clamp_day(reference.year, reference.month, card.due_day)
    year, month = reference.year, reference.month
    if card.due_day < card.closing_day:
        year, month = shift_month(year, month, -1)
    return clamp_day(year, month, card.closing_day), due


def get_invoice(card: CreditCard, reference: date) -> Invoice:
    """Busca ou cria; a constraint protege contra criação simultânea."""
    closing, due = invoice_dates(card, reference)
    db.session.execute(
        insert(Invoice).values(
            id=db.func.gen_random_uuid(), user_id=card.user_id, card_id=card.id,
            reference_month=reference, closing_date=closing, due_date=due,
            created_at=db.func.now(), updated_at=db.func.now(),
        ).on_conflict_do_nothing(index_elements=["card_id", "reference_month"])
    )
    return db.session.scalar(
        sa.select(Invoice).filter_by(card_id=card.id, reference_month=reference)
    )


def create_installments(purchase: CardPurchase, first_month: date, already_paid: int) -> None:
    amounts = split_installments(purchase.total_amount, purchase.installment_count)
    year, month = first_month.year, first_month.month
    for index, amount in enumerate(amounts):
        invoice = None
        if index >= already_paid:
            y, m = shift_month(year, month, index)
            invoice = get_invoice(purchase.card, date(y, m, 1))
        purchase.installments.append(Installment(
            user_id=purchase.user_id, number=index + 1, amount=amount,
            invoice_id=invoice.id if invoice else None,
        ))


def remove_empty_invoices(card_id: UUID) -> None:
    """Fatura sem parcelas nem pagamentos não tem por que continuar existindo."""
    db.session.execute(sa.delete(Invoice).where(
        Invoice.card_id == card_id,
        ~sa.exists().where(Installment.invoice_id == Invoice.id),
        ~sa.exists().where(InvoicePayment.invoice_id == Invoice.id),
    ))


def invoice_total(invoice: Invoice) -> Decimal:
    return sum((i.amount for i in invoice.installments), ZERO)


def invoice_paid(invoice: Invoice) -> Decimal:
    return sum((p.amount for p in invoice.payments), ZERO)


def invoice_status(invoice: Invoice, today: date) -> str:
    total, paid = invoice_total(invoice), invoice_paid(invoice)
    if total > 0 and paid >= total:
        return "paid"
    if today > invoice.due_date:
        return "overdue"
    if paid > 0:
        return "partial"
    if today > invoice.closing_date:
        return "closed"
    # A primeira fatura ainda não fechada é a atual; as demais são futuras.
    previous_month_closing = _previous_closing(invoice)
    return "open" if today > previous_month_closing else "future"


def _previous_closing(invoice: Invoice) -> date:
    year, month = shift_month(invoice.reference_month.year, invoice.reference_month.month, -1)
    return invoice_dates(invoice.card, date(year, month, 1))[0]


def _sum(query) -> Decimal:
    return db.session.scalar(query) or ZERO


def used_limit(card: CreditCard) -> Decimal:
    """Parcelas ainda não pagas, inclusive futuras: é o que ocupa o limite."""
    charged = _sum(
        sa.select(sa.func.sum(Installment.amount)).join(Invoice)
        .where(Invoice.card_id == card.id)
    )
    paid = _sum(
        sa.select(sa.func.sum(InvoicePayment.amount)).join(Invoice)
        .where(Invoice.card_id == card.id)
    )
    return charged - paid


def card_invoices(card: CreditCard) -> list[Invoice]:
    return list(db.session.scalars(
        sa.select(Invoice).where(Invoice.card_id == card.id).order_by(Invoice.reference_month)
    ))


def card_summary(card: CreditCard, today: date) -> dict:
    used = used_limit(card)
    invoices = card_invoices(card)
    unpaid = [i for i in invoices if invoice_status(i, today) != "paid"]
    future = [i for i in invoices if invoice_status(i, today) == "future"]
    # Pelo ciclo, não pela situação: a fatura atual continua sendo a atual depois de paga.
    current = next((i for i in invoices if i.closing_date >= today), None)
    upcoming = unpaid[0] if unpaid else None
    return {
        "used": used,
        "available": card.credit_limit - used,
        "usage_pct": round(used / card.credit_limit * 100) if card.credit_limit > 0 else None,
        "current_invoice": invoice_total(current) if current else ZERO,
        "future_invoices": sum((invoice_total(i) for i in future), ZERO),
        "remaining_installments": sum(len(i.installments) for i in future),
        "next_due_date": upcoming.due_date.isoformat() if upcoming else None,
        "next_due_amount": invoice_total(upcoming) - invoice_paid(upcoming) if upcoming else ZERO,
    }


def spending_by_month(card: CreditCard, today: date) -> list[dict]:
    rows = []
    for offset in range(-(SPENDING_MONTHS - 1), 1):
        year, month = shift_month(today.year, today.month, offset)
        start, end = month_bounds(year, month)
        total = _sum(
            sa.select(sa.func.sum(Installment.amount)).join(Invoice)
            .where(Invoice.card_id == card.id, Invoice.due_date.between(start, end))
        )
        rows.append({"month": f"{year:04d}-{month:02d}", "total": total})
    return rows


# Consultas usadas pelo dashboard. Competência da parcela = vencimento da sua fatura.

def installments_total(user_id: UUID, start: date, end: date) -> Decimal:
    return _sum(
        sa.select(sa.func.sum(Installment.amount)).join(Invoice)
        .where(Installment.user_id == user_id, Invoice.due_date.between(start, end))
    )


def invoices_due_until(user_id: UUID, day: date) -> Decimal:
    """Quanto falta pagar das faturas que vencem até o dia, incluindo atrasadas."""
    charged = _sum(
        sa.select(sa.func.sum(Installment.amount)).join(Invoice)
        .where(Installment.user_id == user_id, Invoice.due_date <= day)
    )
    paid = _sum(
        sa.select(sa.func.sum(InvoicePayment.amount)).join(Invoice)
        .where(InvoicePayment.user_id == user_id, Invoice.due_date <= day)
    )
    return charged - paid


def invoices_due_between(user_id: UUID, start: date, end: date) -> Decimal:
    return invoices_due_until(user_id, end) - invoices_due_until(user_id, start - timedelta(days=1))


def installments_by_category(user_id: UUID, start: date, end: date) -> dict[str | None, Decimal]:
    rows = db.session.execute(
        sa.select(Category.name, sa.func.sum(Installment.amount))
        .select_from(Installment)
        .join(Invoice, Installment.invoice_id == Invoice.id)
        .join(CardPurchase, Installment.purchase_id == CardPurchase.id)
        .outerjoin(Category, CardPurchase.category_id == Category.id)
        .where(Installment.user_id == user_id, Invoice.due_date.between(start, end))
        .group_by(Category.name)
    ).all()
    return {name: total for name, total in rows}


def card_alerts(user_id: UUID, today: date) -> list[dict]:
    alerts = []
    cards = db.session.scalars(
        sa.select(CreditCard).where(CreditCard.user_id == user_id, CreditCard.active)
    ).all()
    for card in cards:
        summary = card_summary(card, today)
        if summary["usage_pct"] is not None and summary["usage_pct"] >= HIGH_USAGE_PCT:
            alerts.append({
                "level": "warning",
                "message": f"{card.name}: {summary['usage_pct']}% do limite utilizado.",
            })
        for invoice in card_invoices(card):
            status = invoice_status(invoice, today)
            if status == "overdue":
                alerts.append({"level": "critical", "message": f"Fatura do {card.name} em atraso."})
            elif status != "paid" and invoice_total(invoice) > 0:
                days = (invoice.due_date - today).days
                if 0 <= days <= DUE_SOON_DAYS:
                    when = "hoje" if days == 0 else f"em {days} dia(s)"
                    alerts.append({"level": "warning", "message": f"Fatura do {card.name} vence {when}."})
    return alerts
