"""Login com Google e Apple, e vínculo desses provedores a uma conta existente."""
import json
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from flask import Blueprint, abort, current_app, g, jsonify, make_response, redirect, request

from ..extensions import db
from ..models import OAuthState, User
from ..models.common import utcnow
from ..services import oauth
from ..services.security import cookie_is_secure, session_from_request, sha256, start_session
from .common import error, login_required, user_payload

bp = Blueprint("social", __name__, url_prefix="/api/auth")

BROWSER_COOKIE = "monetta_oauth"
STATE_MINUTES = 10


def _provider(name: str) -> oauth.Provider:
    if name not in oauth.PROVIDERS or not oauth.is_enabled(name):
        abort(404)
    return oauth.PROVIDERS[name]


def _back(path: str):
    response = redirect(f"{current_app.config['PUBLIC_URL']}{path}", code=303)
    response.delete_cookie(BROWSER_COOKIE, path="/api/auth")
    return response


def _apple_name() -> str | None:
    """A Apple envia o nome uma única vez, no primeiro login, fora do id_token."""
    try:
        name = json.loads(request.form.get("user", "{}")).get("name", {})
        return " ".join(p for p in (name.get("firstName"), name.get("lastName")) if p) or None
    except (ValueError, AttributeError):
        return None


def _begin(provider: oauth.Provider, response, link_user_id: UUID | None = None) -> str:
    """Registra a tentativa e amarra ao navegador; devolve o endereço do provedor."""
    state, nonce, verifier, browser = (secrets.token_urlsafe(32) for _ in range(4))
    db.session.execute(db.delete(OAuthState).where(OAuthState.expires_at < utcnow()))
    db.session.add(OAuthState(
        state_hash=sha256(state), browser_hash=sha256(browser), provider=provider.name,
        nonce=nonce, code_verifier=verifier, link_user_id=link_user_id,
        expires_at=utcnow() + timedelta(minutes=STATE_MINUTES),
    ))
    db.session.commit()
    # O retorno da Apple é um POST de outro site: exige SameSite=None (e portanto HTTPS).
    cross_site = provider is oauth.APPLE and cookie_is_secure()
    response.set_cookie(
        BROWSER_COOKIE, browser, max_age=STATE_MINUTES * 60, httponly=True, path="/api/auth",
        secure=cookie_is_secure(), samesite="None" if cross_site else "Lax",
    )
    return oauth.authorization_url(provider, state, nonce, verifier)


@bp.get("/<name>/start")
def start(name: str):
    provider = _provider(name)
    response = make_response()
    response.status_code = 302
    response.headers["Location"] = _begin(provider, response)
    return response


@bp.post("/<name>/link")
@login_required
def link(name: str):
    """Para quem já está logado: o app abre o endereço devolvido."""
    provider = _provider(name)
    response = make_response()
    url = _begin(provider, response, link_user_id=g.user.id)
    response.set_data(json.dumps({"url": url}))
    response.mimetype = "application/json"
    return response


@bp.delete("/<name>/link")
@login_required
def unlink(name: str):
    if name not in oauth.PROVIDERS:
        abort(404)
    user = g.user
    identity = next((i for i in user.identities if i.provider == name), None)
    if identity is None:
        abort(404)
    others = [i for i in user.identities if i is not identity]
    if user.password_hash is None and not others:
        return error("Crie uma senha antes de desvincular: seria sua única forma de entrar.", 409)
    user.identities.remove(identity)
    db.session.commit()
    return jsonify(user_payload(user))


def _arrived_at_redirect_base() -> bool:
    """O retorno chegou ao endereço aceito pelo provedor, que não é o do app."""
    c = current_app.config
    base = c["OAUTH_REDIRECT_BASE"]
    if not base or base == c["PUBLIC_URL"]:
        return False
    return request.host == urlsplit(base).netloc


@bp.route("/<name>/callback", methods=["GET", "POST"])
def callback(name: str):
    provider = _provider(name)
    if request.method == "GET" and _arrived_at_redirect_base():
        # Os cookies deste navegador estão no endereço do app: repassa para lá.
        return redirect(f"{current_app.config['PUBLIC_URL']}{request.full_path}", code=302)

    params = request.form if request.method == "POST" else request.args
    state, code = params.get("state"), params.get("code")
    if not state:
        return _back("/login?erro=cancelado")

    pending = db.session.get(OAuthState, sha256(state))
    if pending is None:
        return _back("/login?erro=sessao_expirada")
    failure = "/perfil?erro={}" if pending.link_user_id else "/login?erro={}"
    browser = request.cookies.get(BROWSER_COOKIE, "")
    # O state é de uso único, mesmo quando a validação falha.
    db.session.delete(pending)
    db.session.commit()
    if not code:
        return _back(failure.format("cancelado"))
    if (pending.provider != provider.name or pending.expires_at <= utcnow()
            or not secrets.compare_digest(pending.browser_hash, sha256(browser))):
        return _back(failure.format("sessao_expirada"))

    session = None
    if pending.link_user_id:
        session = session_from_request(request)
        if session is None or session.user_id != pending.link_user_id:
            return _back(failure.format("sessao_expirada"))

    try:
        token = oauth.exchange_code(provider, code, pending.code_verifier)
        claims = oauth.verify_id_token(provider, token, pending.nonce)
        if session is not None:
            oauth.link_identity(provider, claims, db.session.get(User, session.user_id))
        else:
            user = oauth.resolve_user(
                provider, claims, _apple_name() if provider is oauth.APPLE else None
            )
    except oauth.OAuthError as exc:
        db.session.rollback()
        return _back(failure.format(exc.code))

    if session is not None:
        db.session.commit()
        return _back(f"/perfil?vinculado={provider.name}")

    # 303: transforma o POST da Apple em um GET comum para a aplicação.
    response = _back("/")
    start_session(user, request, response)
    db.session.commit()
    return response
