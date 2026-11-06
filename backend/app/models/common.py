from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Dinheiro é sempre NUMERIC(14,2) / Decimal; nunca float.
Money = Annotated[Decimal, mapped_column(sa.Numeric(14, 2))]


class IdMixin:
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
