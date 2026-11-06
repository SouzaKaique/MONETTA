"""Senhas, tokens e sessões revogáveis."""
import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import Request, Response, current_app

from ..extensions import db
from ..models import User, UserSession
from ..models.common import utcnow

SESSION_COOKIE = "monetta_session"
_hasher = PasswordHasher()
# Mantém o tempo de resposta parecido quando o e-mail não existe.
_DUMMY_HASH = _hasher.hash("monetta-dummy")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_is_secure() -> bool:
    return current_app.config["PUBLIC_URL"].startswith("https://")


def start_session(user: User, request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    days = current_app.config["SESSION_DAYS"]
    db.session.add(UserSession(
        user_id=user.id,
        token_hash=sha256(token),
        user_agent=(request.user_agent.string or "")[:255],
        expires_at=utcnow() + timedelta(days=days),
    ))
    response.set_cookie(
        SESSION_COOKIE, token, max_age=days * 86400, httponly=True,
        secure=cookie_is_secure(), samesite="Lax", path="/",
    )


def session_from_request(request: Request) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    found = db.session.scalar(db.select(UserSession).filter_by(token_hash=sha256(token)))
    if found is None or found.revoked_at is not None or found.expires_at <= utcnow():
        return None
    return found


def revoke_all_sessions(user: User, keep: UserSession | None = None) -> None:
    query = db.update(UserSession).where(
        UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        query = query.where(UserSession.id != keep.id)
    db.session.execute(query.values(revoked_at=utcnow()))


def end_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
