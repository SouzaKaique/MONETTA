"""Identidade: usuários, sessões e logins sociais."""
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .common import IdMixin, TimestampMixin, utcnow


class User(IdMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(254), unique=True)  # sempre minúsculo
    # True só quando um provedor (Google/Apple) confirmou o e-mail.
    email_verified: Mapped[bool] = mapped_column(default=False)
    account_name: Mapped[str] = mapped_column(sa.String(80))
    avatar_url: Mapped[str | None] = mapped_column(sa.String(500))
    # Nulo em contas criadas só com Google/Apple.
    password_hash: Mapped[str | None] = mapped_column(sa.String(255))
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped["AppSettings"] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserIdentity(IdMixin, db.Model):
    """Vínculo entre um usuário e sua conta em um provedor externo."""

    __tablename__ = "user_identities"
    __table_args__ = (sa.UniqueConstraint("provider", "subject"),)

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(sa.String(20))  # google | apple
    subject: Mapped[str] = mapped_column(sa.String(255))  # "sub" estável do provedor
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="identities")


class UserSession(IdMixin, db.Model):
    """Sessão revogável: o cookie guarda o token, o banco guarda apenas o hash."""

    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class OAuthState(db.Model):
    """Tentativa de login social em andamento; de uso único e curta duração."""

    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(sa.String(64))  # amarra ao navegador de origem
    provider: Mapped[str] = mapped_column(sa.String(20))
    nonce: Mapped[str] = mapped_column(sa.String(64))
    code_verifier: Mapped[str] = mapped_column(sa.String(128))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
