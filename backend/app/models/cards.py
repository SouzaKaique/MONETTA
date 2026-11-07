"""
Cartões de crédito.

Uma compra é despesa uma única vez, pelas parcelas. O pagamento da fatura (InvoicePayment)
liquida uma obrigação: tira dinheiro da conta, mas nunca conta como despesa.
"""
from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .common import IdMixin, Money, TimestampMixin
from .finance import Account, Category

DAY_RANGE = "BETWEEN 1 AND 31"


class CreditCard(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "credit_cards"
    __table_args__ = (
        sa.CheckConstraint("credit_limit >= 0", name="limit_not_negative"),
        sa.CheckConstraint(f"closing_day {DAY_RANGE}", name="closing_day_valid"),
        sa.CheckConstraint(f"due_day {DAY_RANGE}", name="due_day_valid"),
        sa.CheckConstraint("closing_day <> due_day", name="days_differ"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    institution: Mapped[str | None] = mapped_column(sa.String(80))
    credit_limit: Mapped[Money]
    closing_day: Mapped[int]
    due_day: Mapped[int]
    color: Mapped[str] = mapped_column(sa.String(20), default="forest")
    active: Mapped[bool] = mapped_column(default=True)


class Invoice(IdMixin, TimestampMixin, db.Model):
    """
    Fatura identificada pelo mês de vencimento. Datas ficam gravadas para que mudar
    o dia de fechamento do cartão não reescreva faturas passadas.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        sa.UniqueConstraint("card_id", "reference_month"),
        sa.Index("ix_invoices_user_due", "user_id", "due_date"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    card_id: Mapped[UUID] = mapped_column(sa.ForeignKey("credit_cards.id", ondelete="CASCADE"), index=True)
    reference_month: Mapped[date]  # dia 1 do mês de vencimento
    closing_date: Mapped[date]
    due_date: Mapped[date]

    card: Mapped[CreditCard] = relationship()
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="invoice", order_by="Installment.number"
    )
    payments: Mapped[list["InvoicePayment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoicePayment.paid_on"
    )


class CardPurchase(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "card_purchases"
    __table_args__ = (
        sa.CheckConstraint("total_amount > 0", name="amount_positive"),
        sa.CheckConstraint("installment_count BETWEEN 1 AND 48", name="installments_valid"),
        sa.UniqueConstraint("user_id", "idempotency_key"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[UUID] = mapped_column(sa.ForeignKey("credit_cards.id", ondelete="RESTRICT"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("categories.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(sa.String(160))
    total_amount: Mapped[Money]
    purchase_date: Mapped[date]
    installment_count: Mapped[int] = mapped_column(default=1)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64))

    card: Mapped[CreditCard] = relationship()
    category: Mapped[Category | None] = relationship()
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan", order_by="Installment.number"
    )


class Installment(IdMixin, db.Model):
    """
    Parcela de uma compra. Sem fatura significa que foi paga antes de a compra ser
    registrada aqui: existe no histórico da compra, mas fora de despesas e limite.
    """

    __tablename__ = "installments"
    __table_args__ = (
        sa.UniqueConstraint("purchase_id", "number"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purchase_id: Mapped[UUID] = mapped_column(sa.ForeignKey("card_purchases.id", ondelete="CASCADE"))
    invoice_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    number: Mapped[int]
    amount: Mapped[Money]

    purchase: Mapped[CardPurchase] = relationship(back_populates="installments")
    invoice: Mapped[Invoice | None] = relationship(back_populates="installments")


class InvoicePayment(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "invoice_payments"
    __table_args__ = (
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.UniqueConstraint("user_id", "idempotency_key"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[UUID] = mapped_column(sa.ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[UUID] = mapped_column(sa.ForeignKey("accounts.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Money]
    paid_on: Mapped[date]
    notes: Mapped[str | None] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64))

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    account: Mapped[Account] = relationship()
