"""Tokens para lançamentos externos, como o app Atalhos do iPhone."""
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .common import IdMixin, utcnow


class ApiToken(IdMixin, db.Model):
    """O valor aparece só na criação; o banco guarda apenas o hash."""

    __tablename__ = "api_tokens"

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(sa.String(60))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    prefix: Mapped[str] = mapped_column(sa.String(12))  # ajuda a reconhecer o token na lista
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
