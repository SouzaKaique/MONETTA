"""Início e retorno do login com Google e Apple."""
import json
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, make_response, redirect, request

from ..extensions import db
from ..models import OAuthState
from ..models.common import utcnow
from ..services import oauth
from ..services.security import cookie_is_secure, sha256, start_session

bp = Blueprint("social", __name__, url_prefix="/api/auth")

BROWSER_COOKIE = "monetta_oauth"
STATE_MINUTES = 10


def _provider(name: str) -> oauth.Provider:
    if name not in oauth.PROVIDERS or not oauth.is_enabled(name):
        abort(404)
    return oauth.PROVIDERS[name]


def _login_error(code: str):
    response = redirect(f"{current_app.config['PUBLIC_URL']}/login?erro={code}")
    response.delete_cookie(BROWSER_COOKIE, path="/api/auth")
    return response


def _apple_name() -> str | None:
    """A Apple envia o nome uma única vez, no primeiro login, fora do id_token."""
    try:
        name = json.loads(request.form.get("user", "{}")).get("name", {})
        return " ".join(p for p in (name.get("firstName"), name.get("lastName")) if p) or None
    except (ValueError, AttributeError):
        return None


@bp.get("/<name>/start")
def start(name: str):
    provider = _provider(name)
    state, nonce, verifier, browser = (secrets.token_urlsafe(32) for _ in range(4))
    db.session.execute(db.delete(OAuthState).where(OAuthState.expires_at < utcnow()))
    db.session.add(OAuthState(
        state_hash=sha256(state), browser_hash=sha256(browser), provider=provider.name,
        nonce=nonce, code_verifier=verifier,
        expires_at=utcnow() + timedelta(minutes=STATE_MINUTES),
    ))
    db.session.commit()

    response = redirect(oauth.authorization_url(provider, state, nonce, verifier))
    # O retorno da Apple é um POST de outro site: exige SameSite=None (e portanto HTTPS).
    cross_site = provider is oauth.APPLE and cookie_is_secure()
    response.set_cookie(
        BROWSER_COOKIE, browser, max_age=STATE_MINUTES * 60, httponly=True, path="/api/auth",
        secure=cookie_is_secure(), samesite="None" if cross_site else "Lax",
    )
    return response


@bp.route("/<name>/callback", methods=["GET", "POST"])
def callback(name: str):
    provider = _provider(name)
    params = request.form if request.method == "POST" else request.args
    state, code = params.get("state"), params.get("code")
    if not state or not code:
        return _login_error("cancelado")

    pending = db.session.get(OAuthState, sha256(state))
    browser = request.cookies.get(BROWSER_COOKIE, "")
    if pending is None:
        return _login_error("sessao_expirada")
    # O state é de uso único, mesmo quando a validação falha.
    db.session.delete(pending)
    db.session.commit()
    if (pending.provider != provider.name or pending.expires_at <= utcnow()
            or not secrets.compare_digest(pending.browser_hash, sha256(browser))):
        return _login_error("sessao_expirada")

    try:
        token = oauth.exchange_code(provider, code, pending.code_verifier)
        claims = oauth.verify_id_token(provider, token, pending.nonce)
        user = oauth.resolve_user(
            provider, claims, _apple_name() if provider is oauth.APPLE else None
        )
    except oauth.OAuthError as exc:
        db.session.rollback()
        return _login_error(exc.code)

    # 303: transforma o POST da Apple em um GET comum para a aplicação.
    response = make_response(redirect(f"{current_app.config['PUBLIC_URL']}/", code=303))
    response.delete_cookie(BROWSER_COOKIE, path="/api/auth")
    start_session(user, request, response)
    db.session.commit()
    return response
