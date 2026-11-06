"""
Dívidas pessoais.

Pagar uma dívida liquida uma obrigação: reduz o saldo devedor e, se houver conta,
o dinheiro em conta, mas nunca conta como despesa.
"""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .common import IdMixin, Money, TimestampMixin
from .finance import Account


class Debt(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "debts"
    __table_args__ = (
        sa.CheckConstraint("original_amount > 0", name="original_positive"),
        sa.CheckConstraint("opening_balance >= 0", name="opening_not_negative"),
        sa.CheckConstraint("priority BETWEEN 1 AND 3", name="priority_valid"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    creditor: Mapped[str] = mapped_column(sa.String(120))
    original_amount: Mapped[Money]
    # Saldo quando a dívida foi cadastrada; pode ser menor que o original se já havia pagamentos.
    opening_balance: Mapped[Money]
    start_date: Mapped[date]
    due_date: Mapped[date | None]
    agreed_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    frequency: Mapped[str] = mapped_column(sa.String(10), default="none")  # none|weekly|biweekly|monthly
    interest_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3))  # % ao mês
    priority: Mapped[int] = mapped_column(default=2)  # 1 alta, 2 média, 3 baixa
    sort_order: Mapped[int] = mapped_column(default=0)  # ordem manual de quitação
    notes: Mapped[str | None] = mapped_column(sa.Text)

    payments: Mapped[list["DebtPayment"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan",
        order_by="DebtPayment.paid_on.desc(), DebtPayment.created_at.desc()",
    )


class DebtPayment(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "debt_payments"
    __table_args__ = (
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.UniqueConstraint("user_id", "idempotency_key"),
        sa.Index("ix_debt_payments_user_paid_on", "user_id", "paid_on"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    debt_id: Mapped[UUID] = mapped_column(sa.ForeignKey("debts.id", ondelete="CASCADE"), index=True)
    # Sem conta: pagamento antigo, que atualiza a dívida sem mexer no saldo de hoje.
    account_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Money]
    paid_on: Mapped[date]
    description: Mapped[str | None] = mapped_column(sa.String(160))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64))

    debt: Mapped[Debt] = relationship(back_populates="payments")
    account: Mapped[Account | None] = relationship()
