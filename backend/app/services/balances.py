"""Saldos calculados a partir de movimentações confirmadas e transferências."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from ..extensions import db
from ..models import Account, InvoicePayment, Transaction, Transfer

ZERO = Decimal("0.00")


def _sum(query) -> Decimal:
    return db.session.scalar(query) or ZERO


def account_balance(account: Account, day: date) -> Decimal:
    """
    Saldo no fim de `day`. Movimentos anteriores à abertura ficam de fora:
    o saldo de abertura já os contém.
    """
    if account.opening_date > day:
        return ZERO
    moved = sa.select(sa.func.sum(Transaction.amount)).where(
        Transaction.account_id == account.id,
        Transaction.status == "confirmed",
        Transaction.paid_on.between(account.opening_date, day),
    )
    transfer = sa.select(sa.func.sum(Transfer.amount)).where(
        Transfer.date.between(account.opening_date, day)
    )
    # Pagamento de fatura tira dinheiro da conta, mas a despesa já foi contada nas parcelas.
    invoice_payments = sa.select(sa.func.sum(InvoicePayment.amount)).where(
        InvoicePayment.account_id == account.id,
        InvoicePayment.paid_on.between(account.opening_date, day),
    )
    return (
        account.opening_balance
        + _sum(moved.where(Transaction.kind == "income"))
        - _sum(moved.where(Transaction.kind == "expense"))
        + _sum(transfer.where(Transfer.to_account_id == account.id))
        - _sum(transfer.where(Transfer.from_account_id == account.id))
        - _sum(invoice_payments)
    )


def total_balance(user_id: UUID, day: date) -> Decimal:
    accounts = db.session.scalars(
        sa.select(Account).where(Account.user_id == user_id, Account.active)
    ).all()
    return sum((account_balance(a, day) for a in accounts), ZERO)
