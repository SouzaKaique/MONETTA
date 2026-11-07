"""
Wishlist e metas de economia.

Guardar dinheiro não é despesa nem movimenta conta: o valor continua no banco e apenas
deixa de contar como disponível enquanto a meta estiver aberta.
"""
from datetime import date
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .cards import CardPurchase
from .common import IdMixin, Money, TimestampMixin
from .finance import Category, Transaction


class WishlistItem(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "wishlist_items"
    __table_args__ = (
        sa.CheckConstraint("price > 0", name="price_positive"),
        sa.CheckConstraint("priority BETWEEN 1 AND 3", name="priority_valid"),
        sa.CheckConstraint(
            "status IN ('desired', 'planning', 'saving', 'bought', 'given_up')", name="status_valid"
        ),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("categories.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(sa.String(120))
    image_url: Mapped[str | None] = mapped_column(sa.String(500))
    store_url: Mapped[str | None] = mapped_column(sa.String(500))
    price: Mapped[Money]
    priority: Mapped[int] = mapped_column(default=2)  # 1 alta, 2 média, 3 baixa
    status: Mapped[str] = mapped_column(sa.String(10), default="desired")
    added_on: Mapped[date]
    notes: Mapped[str | None] = mapped_column(sa.Text)
    bought_on: Mapped[date | None]
    # Despesa criada ao comprar; fica no histórico mesmo se o item for excluído.
    transaction_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("transactions.id", ondelete="SET NULL"))
    card_purchase_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("card_purchases.id", ondelete="SET NULL"))

    category: Mapped[Category | None] = relationship()
    goal: Mapped["SavingsGoal"] = relationship(
        back_populates="item", cascade="all, delete-orphan", uselist=False
    )
    image: Mapped["WishlistImage | None"] = relationship(cascade="all, delete-orphan", uselist=False)
    transaction: Mapped[Transaction | None] = relationship()
    card_purchase: Mapped[CardPurchase | None] = relationship()


class SavingsGoal(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "savings_goals"
    __table_args__ = (sa.CheckConstraint("target_amount > 0", name="target_positive"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("wishlist_items.id", ondelete="CASCADE"), unique=True
    )
    target_amount: Mapped[Money]
    monthly_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    target_date: Mapped[date | None]

    item: Mapped[WishlistItem] = relationship(back_populates="goal")
    contributions: Mapped[list["GoalContribution"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan",
        order_by="GoalContribution.contributed_on.desc(), GoalContribution.created_at.desc()",
    )


class GoalContribution(IdMixin, TimestampMixin, db.Model):
    """Valor guardado (positivo) ou retirado (negativo) de uma meta."""

    __tablename__ = "goal_contributions"
    __table_args__ = (
        sa.CheckConstraint("amount <> 0", name="amount_not_zero"),
        sa.UniqueConstraint("user_id", "idempotency_key"),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[UUID] = mapped_column(sa.ForeignKey("savings_goals.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Money]
    contributed_on: Mapped[date]
    notes: Mapped[str | None] = mapped_column(sa.Text)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(64))

    goal: Mapped[SavingsGoal] = relationship(back_populates="contributions")


class WishlistImage(db.Model):
    """Imagem enviada pelo usuário, em tabela própria para não pesar nas listagens."""

    __tablename__ = "wishlist_images"

    item_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("wishlist_items.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(sa.String(20))
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
