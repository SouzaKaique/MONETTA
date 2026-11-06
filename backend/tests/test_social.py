"""Login social com tokens reais assinados por uma chave local no lugar do provedor."""
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.extensions import db
from app.models import User, UserIdentity
from app.services import oauth

from .conftest import register

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def id_token(nonce, sub="g-1", email="ana@example.com", verified=True, aud="google-test-client",
             iss="https://accounts.google.com", key=KEY, exp_delta=600, **extra):
    now = int(time.time())
    return jwt.encode({
        "sub": sub, "email": email, "email_verified": verified, "aud": aud, "iss": iss,
        "nonce": nonce, "iat": now, "exp": now + exp_delta, **extra,
    }, key, algorithm="RS256")


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    """Substitui só a rede; a validação do token roda de verdade."""
    monkeypatch.setattr(oauth, "signing_key", lambda provider, token: KEY.public_key())
    holder = {}
    monkeypatch.setattr(oauth, "exchange_code", lambda p, code, verifier: holder["token"](verifier))
    return holder


def begin(client):
    res = client.get("/api/auth/google/start")
    assert res.status_code == 302
    query = parse_qs(urlparse(res.headers["Location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    return query["state"][0], query["nonce"][0]


def finish(client, state):
    return client.get(f"/api/auth/google/callback?code=abc&state={state}")


def test_primeiro_login_cria_conta_com_nome_do_google(client, fake_provider):
    state, nonce = begin(client)
    fake_provider["token"] = lambda v: id_token(nonce, name="Ana Google")
    res = finish(client, state)
    assert res.status_code == 303 and res.headers["Location"] == "http://localhost:4200/"
    me = client.get("/api/auth/me").json
    assert me["account_name"] == "Ana Google"
    assert me["providers"] == ["google"] and me["has_password"] is False


def test_segundo_login_reusa_a_mesma_conta(client, make_client, fake_provider):
    for c in (client, make_client()):
        state, nonce = begin(c)
        fake_provider["token"] = lambda v, n=nonce: id_token(n)
        finish(c, state)
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 1
    assert db.session.scalar(db.select(db.func.count()).select_from(UserIdentity)) == 1


@pytest.mark.parametrize("claims", [
    {"aud": "outro-app"},
    {"iss": "https://evil.example"},
    {"key": OTHER_KEY},
    {"exp_delta": -600},
])
def test_rejeita_token_adulterado(client, fake_provider, claims):
    state, nonce = begin(client)
    fake_provider["token"] = lambda v: id_token(nonce, **claims)
    res = finish(client, state)
    assert "erro=token_invalido" in res.headers["Location"]
    assert client.get("/api/auth/me").status_code == 401


def test_rejeita_nonce_de_outra_tentativa(client, fake_provider):
    state, _ = begin(client)
    fake_provider["token"] = lambda v: id_token("nonce-errado")
    assert "erro=token_invalido" in finish(client, state).headers["Location"]


def test_state_e_de_uso_unico_e_preso_ao_navegador(client, make_client, fake_provider):
    state, nonce = begin(client)
    fake_provider["token"] = lambda v: id_token(nonce)
    assert "erro=sessao_expirada" in finish(make_client(), state).headers["Location"]
    assert "erro=sessao_expirada" in finish(client, state).headers["Location"]


def test_nao_vincula_a_conta_de_senha_sem_email_confirmado(client, make_client, fake_provider):
    """Quem cadastrou o e-mail alheio com senha não pode herdar a conta da vítima."""
    register(make_client())
    state, nonce = begin(client)
    fake_provider["token"] = lambda v: id_token(nonce)
    assert "erro=conta_existente" in finish(client, state).headers["Location"]
    assert db.session.scalar(db.select(db.func.count()).select_from(UserIdentity)) == 0


def test_rejeita_email_nao_verificado(client, fake_provider):
    state, nonce = begin(client)
    fake_provider["token"] = lambda v: id_token(nonce, verified=False)
    assert "erro=email_nao_verificado" in finish(client, state).headers["Location"]


def test_apple_sem_credenciais_fica_desligado(client):
    assert client.get("/api/auth/providers").json == {"google": True, "apple": False}
    assert client.get("/api/auth/apple/start").status_code == 404
