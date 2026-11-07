"""Orçamento por categoria, Modo Recuperação e notificações."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .common import IdMixin, Money, TimestampMixin, utcnow
from .finance import Category


class Budget(IdMixin, TimestampMixin, db.Model):
    """Limite de uma categoria a partir de um mês; meses anteriores mantêm o limite antigo."""

    __tablename__ = "budgets"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "category_id", "month"),
        sa.CheckConstraint("amount >= 0", name="amount_not_negative"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[UUID] = mapped_column(sa.ForeignKey("categories.id", ondelete="CASCADE"))
    month: Mapped[date]  # dia 1 do mês em que o limite começa
    amount: Mapped[Money]  # zero remove o limite a partir deste mês

    category: Mapped[Category] = relationship()


class RecoveryPlan(IdMixin, TimestampMixin, db.Model):
    """Configuração do Modo Recuperação. Ao desativar, o registro e o histórico permanecem."""

    __tablename__ = "recovery_plans"

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    monthly_amount: Mapped[Money]
    strategy: Mapped[str] = mapped_column(sa.String(12), default="snowball")
    priority_debt_ids: Mapped[list] = mapped_column(sa.JSON, default=list)
    non_essential_limit: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    reserve_minimum: Mapped[Money] = mapped_column(default=Decimal("0.00"))
    spending_goal_pct: Mapped[int | None]  # redução desejada nos gastos não essenciais
    target_date: Mapped[date | None]
    initial_debt: Mapped[Money]  # total devido na primeira ativação
    started_on: Mapped[date]
    ended_on: Mapped[date | None]


class Notification(IdMixin, db.Model):
    """Cada aviso tem uma chave: a mesma situação nunca notifica duas vezes."""

    __tablename__ = "notifications"
    __table_args__ = (sa.UniqueConstraint("user_id", "key"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(sa.String(120))
    kind: Mapped[str] = mapped_column(sa.String(20))
    level: Mapped[str] = mapped_column(sa.String(10))
    message: Mapped[str] = mapped_column(sa.String(240))
    link: Mapped[str | None] = mapped_column(sa.String(120))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
