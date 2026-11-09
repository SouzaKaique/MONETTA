"""
Login social com Google e Apple (OpenID Connect, fluxo authorization code).

O backend troca o código por um id_token e valida assinatura, emissor, audiência,
validade e nonce antes de aceitar qualquer dado do provedor.
"""
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
import requests
from flask import current_app

from ..extensions import db
from ..models import User, UserIdentity
from .accounts import create_user, registration_open


class OAuthError(Exception):
    """`code` vira o parâmetro ?erro= exibido na tela de login."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuers: tuple[str, ...]
    algorithms: tuple[str, ...]


GOOGLE = Provider(
    "google",
    "https://accounts.google.com/o/oauth2/v2/auth",
    "https://oauth2.googleapis.com/token",
    "https://www.googleapis.com/oauth2/v3/certs",
    ("https://accounts.google.com", "accounts.google.com"),
    ("RS256",),
)
APPLE = Provider(
    "apple",
    "https://appleid.apple.com/auth/authorize",
    "https://appleid.apple.com/auth/token",
    "https://appleid.apple.com/auth/keys",
    ("https://appleid.apple.com",),
    ("RS256", "ES256"),
)
PROVIDERS = {"google": GOOGLE, "apple": APPLE}


def is_enabled(name: str) -> bool:
    c = current_app.config
    if name == "google":
        return bool(c["GOOGLE_CLIENT_ID"] and c["GOOGLE_CLIENT_SECRET"])
    if name == "apple":
        return bool(c["APPLE_CLIENT_ID"] and c["APPLE_TEAM_ID"]
                    and c["APPLE_KEY_ID"] and c["APPLE_PRIVATE_KEY_PATH"])
    return False


def client_id(provider: Provider) -> str:
    return current_app.config[f"{provider.name.upper()}_CLIENT_ID"]


def redirect_base() -> str:
    c = current_app.config
    return c["OAUTH_REDIRECT_BASE"] or c["PUBLIC_URL"]


def redirect_uri(provider: Provider) -> str:
    return f"{redirect_base()}/api/auth/{provider.name}/callback"


def authorization_url(provider: Provider, state: str, nonce: str, verifier: str) -> str:
    params = {
        "client_id": client_id(provider),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "state": state,
        "nonce": nonce,
    }
    if provider is GOOGLE:
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        params |= {
            "scope": "openid email profile",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    else:
        # A Apple exige form_post quando nome/e-mail são solicitados.
        params |= {"scope": "name email", "response_mode": "form_post"}
    return f"{provider.authorize_url}?{urlencode(params)}"


def apple_client_secret() -> str:
    """A Apple usa um JWT assinado com a chave .p8 no lugar de um segredo fixo."""
    c = current_app.config
    with open(c["APPLE_PRIVATE_KEY_PATH"], encoding="utf8") as f:
        key = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": c["APPLE_TEAM_ID"], "iat": now, "exp": now + 300,
         "aud": "https://appleid.apple.com", "sub": c["APPLE_CLIENT_ID"]},
        key, algorithm="ES256", headers={"kid": c["APPLE_KEY_ID"]},
    )


def exchange_code(provider: Provider, code: str, verifier: str) -> str:
    """Troca o código de autorização pelo id_token."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
        "client_id": client_id(provider),
    }
    if provider is GOOGLE:
        data |= {"client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
                 "code_verifier": verifier}
    else:
        data["client_secret"] = apple_client_secret()
    try:
        response = requests.post(provider.token_url, data=data, timeout=10)
        response.raise_for_status()
        return response.json()["id_token"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        current_app.logger.warning("Falha na troca de código com %s: %s",
                                   provider.name, type(exc).__name__)
        raise OAuthError("provedor") from exc


def signing_key(provider: Provider, token: str):
    return jwt.PyJWKClient(provider.jwks_url).get_signing_key_from_jwt(token).key


def verify_id_token(provider: Provider, token: str, nonce: str) -> dict:
    try:
        claims = jwt.decode(
            token, signing_key(provider, token), algorithms=list(provider.algorithms),
            audience=client_id(provider), issuer=list(provider.issuers),
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except (jwt.PyJWTError, requests.RequestException) as exc:
        raise OAuthError("token_invalido") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("token_invalido")
    return claims


def resolve_user(provider: Provider, claims: dict, name_hint: str | None = None) -> User:
    """Encontra ou cria o usuário correspondente à identidade validada."""
    identity = db.session.scalar(
        db.select(UserIdentity).filter_by(provider=provider.name, subject=claims["sub"])
    )
    if identity is not None:
        return identity.user

    email = (claims.get("email") or "").strip().lower()
    # A Apple envia email_verified como string.
    verified = str(claims.get("email_verified", "")).lower() == "true"
    if not email or not verified:
        raise OAuthError("email_nao_verificado")

    user = db.session.scalar(db.select(User).filter_by(email=email))
    if user is None:
        if not registration_open():
            raise OAuthError("cadastro_fechado")
        name = name_hint or claims.get("name") or email.split("@")[0]
        picture = claims.get("picture") if str(claims.get("picture", "")).startswith("https://") else None
        user = create_user(email=email, account_name=name[:80], email_verified=True,
                           avatar_url=picture)
    elif not user.email_verified:
        # Cadastro por senha não prova a posse do e-mail. Vincular aqui permitiria
        # que alguém criasse uma conta com o e-mail alheio e mantivesse o acesso.
        raise OAuthError("conta_existente")

    user.identities.append(UserIdentity(provider=provider.name, subject=claims["sub"]))
    return user


def link_identity(provider: Provider, claims: dict, user: User) -> None:
    """Vincula o provedor à conta de quem já está logado, mesmo com outro e-mail."""
    identity = db.session.scalar(
        db.select(UserIdentity).filter_by(provider=provider.name, subject=claims["sub"])
    )
    if identity is not None:
        if identity.user_id != user.id:
            raise OAuthError("ja_vinculado")
        return
    if any(i.provider == provider.name for i in user.identities):
        raise OAuthError("ja_vinculado")
    user.identities.append(UserIdentity(provider=provider.name, subject=claims["sub"]))
    email = (claims.get("email") or "").strip().lower()
    if email == user.email and str(claims.get("email_verified", "")).lower() == "true":
        user.email_verified = True
