"""Contas, categorias, movimentações e recorrências."""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .common import IdMixin, Money, TimestampMixin


class AppSettings(TimestampMixin, db.Model):
    __tablename__ = "app_settings"

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(sa.String(10), default="system")  # system | light | dark
    timezone: Mapped[str] = mapped_column(sa.String(50), default="America/Sao_Paulo")
    safety_minimum: Mapped[Money] = mapped_column(default=Decimal("0.00"))
    debt_strategy: Mapped[str] = mapped_column(sa.String(12), default="snowball", server_default="snowball")
    # Valor que o usuário pretende guardar por mês; não é despesa.
    planned_reserve: Mapped[Money] = mapped_column(default=Decimal("0.00"), server_default="0")
    alert_prefs: Mapped[dict | None] = mapped_column(sa.JSON)

    user: Mapped["User"] = relationship(back_populates="settings")  # noqa: F821


class Account(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(80))
    type: Mapped[str] = mapped_column(sa.String(20), default="checking")  # checking | savings | cash
    opening_balance: Mapped[Money] = mapped_column(default=Decimal("0.00"))
    opening_date: Mapped[date]
    # Saldo informado pelo usuário a partir do banco; nunca entra nos cálculos.
    real_balance: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    real_balance_on: Mapped[date | None]
    active: Mapped[bool] = mapped_column(default=True)


class Category(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "categories"
    __table_args__ = (sa.UniqueConstraint("user_id", "kind", "name"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(60))
    kind: Mapped[str] = mapped_column(sa.String(10))  # income | expense
    icon: Mapped[str] = mapped_column(sa.String(40), default="tag")
    is_default: Mapped[bool] = mapped_column(default=False)
    is_essential: Mapped[bool] = mapped_column(default=False, server_default=sa.false())


class Recurrence(IdMixin, TimestampMixin, db.Model):
    """Regra que gera lançamentos pendentes: salário, aluguel, assinaturas."""

    __tablename__ = "recurrences"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('income', 'expense')", name="kind_valid"),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'biweekly', 'monthly', 'yearly')", name="frequency_valid"
        ),
        sa.CheckConstraint("day_of_month BETWEEN 1 AND 31", name="day_valid"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("accounts.id", ondelete="SET NULL"))
    category_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("categories.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(sa.String(10))
    name: Mapped[str] = mapped_column(sa.String(160))
    is_salary: Mapped[bool] = mapped_column(default=False)
    payment_method: Mapped[str | None] = mapped_column(sa.String(20))
    frequency: Mapped[str] = mapped_column(sa.String(10), default="monthly")
    day_of_month: Mapped[int] = mapped_column(default=1)  # usado apenas na frequência mensal
    start_date: Mapped[date]
    # Início efetivo da geração; avança ao reativar, para não criar meses da pausa.
    generate_from: Mapped[date]
    end_date: Mapped[date | None]
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)

    amounts: Mapped[list["RecurrenceAmount"]] = relationship(
        back_populates="recurrence", cascade="all, delete-orphan",
        order_by="RecurrenceAmount.effective_from",
    )
    skips: Mapped[list["RecurrenceSkip"]] = relationship(cascade="all, delete-orphan")
    category: Mapped[Category | None] = relationship()


class RecurrenceAmount(IdMixin, db.Model):
    """Histórico de valores: um reajuste vale a partir de um mês, nunca para trás."""

    __tablename__ = "recurrence_amounts"
    __table_args__ = (
        sa.UniqueConstraint("recurrence_id", "effective_from"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
    )

    recurrence_id: Mapped[UUID] = mapped_column(sa.ForeignKey("recurrences.id", ondelete="CASCADE"))
    amount: Mapped[Money]
    effective_from: Mapped[date]  # sempre o dia 1 do mês

    recurrence: Mapped[Recurrence] = relationship(back_populates="amounts")


class RecurrenceSkip(IdMixin, db.Model):
    """Ocorrência apagada pelo usuário: não pode ser gerada de novo."""

    __tablename__ = "recurrence_skips"
    __table_args__ = (sa.UniqueConstraint("recurrence_id", "occurrence_date"),)

    recurrence_id: Mapped[UUID] = mapped_column(sa.ForeignKey("recurrences.id", ondelete="CASCADE"))
    occurrence_date: Mapped[date]


class Transaction(IdMixin, TimestampMixin, db.Model):
    """
    Movimentação de receita ou despesa.

    competence_date: mês a que pertence (visão por competência).
    paid_on: dia em que o dinheiro entrou ou saiu (fluxo de caixa).
    Só afeta saldo quando status = 'confirmed'.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint("kind IN ('income', 'expense')", name="kind_valid"),
        sa.CheckConstraint("status IN ('pending', 'confirmed')", name="status_valid"),
        sa.CheckConstraint("status = 'pending' OR paid_on IS NOT NULL", name="confirmed_has_paid_on"),
        sa.CheckConstraint("status = 'pending' OR account_id IS NOT NULL", name="confirmed_has_account"),
        sa.UniqueConstraint("user_id", "idempotency_key"),
        sa.UniqueConstraint("recurrence_id", "occurrence_date"),  # impede duplicar ocorrência
        sa.Index("ix_transactions_user_competence", "user_id", "competence_date"),
        sa.Index("ix_transactions_user_paid_on", "user_id", "paid_on"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("accounts.id", ondelete="RESTRICT"))
    category_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("categories.id", ondelete="RESTRICT"))
    recurrence_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("recurrences.id", ondelete="SET NULL"))
    occurrence_date: Mapped[date | None]
    kind: Mapped[str] = mapped_column(sa.String(10))
    status: Mapped[str] = mapped_column(sa.String(10), default="pending")
    is_salary: Mapped[bool] = mapped_column(default=False)
    is_fixed: Mapped[bool] = mapped_column(default=False)  # continua fixa se a regra for apagada
    # True quando o usuário editou esta ocorrência; um reajuste não a sobrescreve.
    amount_overridden: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str] = mapped_column(sa.String(160))
    amount: Mapped[Money]
    competence_date: Mapped[date]
    paid_on: Mapped[date | None]
    payment_method: Mapped[str | None] = mapped_column(sa.String(20))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64))  # evita lançamento duplicado

    category: Mapped[Category | None] = relationship()
    account: Mapped[Account | None] = relationship()


class Transfer(IdMixin, TimestampMixin, db.Model):
    """Movimento entre contas próprias: muda saldos, nunca receita ou despesa."""

    __tablename__ = "transfers"
    __table_args__ = (
        sa.CheckConstraint("amount > 0", name="amount_positive"),
        sa.CheckConstraint("from_account_id <> to_account_id", name="different_accounts"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_account_id: Mapped[UUID] = mapped_column(sa.ForeignKey("accounts.id", ondelete="RESTRICT"))
    to_account_id: Mapped[UUID] = mapped_column(sa.ForeignKey("accounts.id", ondelete="RESTRICT"))
    amount: Mapped[Money]
    date: Mapped[date]
    notes: Mapped[str | None] = mapped_column(sa.Text)

    from_account: Mapped[Account] = relationship(foreign_keys=[from_account_id])
    to_account: Mapped[Account] = relationship(foreign_keys=[to_account_id])
