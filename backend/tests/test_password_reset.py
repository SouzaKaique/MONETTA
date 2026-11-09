"""Recuperação de senha por link enviado ao e-mail."""
import re
from datetime import timedelta

from app.extensions import db
from app.models import PasswordReset, User
from app.models.common import utcnow

from .conftest import register

NEW = "nova-senha-segura-1"


def outbox(app):
    return app.extensions.setdefault("mail_outbox", [])


def ask(client, email="ana@example.com"):
    return client.post("/api/auth/password/forgot", json={"email": email})


def token_from(app):
    match = re.search(r"/redefinir-senha#(\S+)", outbox(app)[-1]["body"])
    return match.group(1)


def login(client, password):
    return client.post("/api/auth/login", json={"email": "ana@example.com", "password": password})


def test_link_redefine_a_senha_e_derruba_as_sessoes(app, client, make_client):
    register(client)
    res = ask(make_client())
    assert res.status_code == 200
    assert outbox(app)[-1]["to"] == "ana@example.com"
    assert "http://localhost:4200/redefinir-senha#" in outbox(app)[-1]["body"]

    res = make_client().post("/api/auth/password/reset", json={"token": token_from(app), "password": NEW})
    assert res.status_code == 200
    # A sessão antiga cai: quem estava com o acesso indevido perde.
    assert client.get("/api/auth/me").status_code == 401
    assert login(make_client(), "senha-de-teste-1").status_code == 401
    assert login(make_client(), NEW).status_code == 200
    assert db.session.scalar(db.select(User)).email_verified is True


def test_mesma_resposta_para_email_inexistente(app, client):
    register(client)
    known, unknown = ask(client), ask(client, "ninguem@example.com")
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json
    assert len(outbox(app)) == 1


def test_link_e_de_uso_unico(app, client):
    register(client)
    ask(client)
    token = token_from(app)
    assert client.post("/api/auth/password/reset", json={"token": token, "password": NEW}).status_code == 200
    again = client.post("/api/auth/password/reset", json={"token": token, "password": "outra-senha-123"})
    assert again.status_code == 400
    assert login(client, NEW).status_code == 200


def test_novo_pedido_invalida_o_link_anterior(app, client):
    register(client)
    ask(client)
    first = token_from(app)
    ask(client)
    assert client.post("/api/auth/password/reset", json={"token": first, "password": NEW}).status_code == 400
    assert client.post("/api/auth/password/reset",
                       json={"token": token_from(app), "password": NEW}).status_code == 200


def test_link_expira(app, client):
    register(client)
    ask(client)
    db.session.execute(db.update(PasswordReset).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.session.commit()
    res = client.post("/api/auth/password/reset", json={"token": token_from(app), "password": NEW})
    assert res.status_code == 400


def test_banco_guarda_so_o_hash(app, client):
    register(client)
    ask(client)
    stored = db.session.scalar(db.select(PasswordReset))
    assert stored.token_hash != token_from(app) and len(stored.token_hash) == 64


def test_senha_curta_e_recusada(app, client):
    register(client)
    ask(client)
    res = client.post("/api/auth/password/reset", json={"token": token_from(app), "password": "curta"})
    assert res.status_code == 422
    assert login(client, "senha-de-teste-1").status_code == 200


def test_desbloqueia_conta_travada(app, client, make_client):
    register(client)
    for _ in range(5):
        login(make_client(), "senha-errada-123")
    assert login(make_client(), "senha-de-teste-1").status_code == 429
    ask(client)
    client.post("/api/auth/password/reset", json={"token": token_from(app), "password": NEW})
    assert login(make_client(), NEW).status_code == 200


def test_conta_so_com_google_pode_criar_senha(app, client):
    from app.services.accounts import create_user
    create_user(email="ana@example.com", account_name="Ana", email_verified=True)
    db.session.commit()
    ask(client)
    client.post("/api/auth/password/reset", json={"token": token_from(app), "password": NEW})
    assert login(client, NEW).status_code == 200


def test_limita_pedidos_por_email(app, client):
    register(client)
    for _ in range(5):
        ask(client)
    assert len(outbox(app)) == 3
