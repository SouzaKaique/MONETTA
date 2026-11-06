from app.extensions import db
from app.models import Category, User, UserSession

from .conftest import register


def test_register_cria_conta_sessao_e_categorias(client):
    res = register(client, email="Ana@Example.com")
    assert res.status_code == 201
    assert res.json["email"] == "ana@example.com"
    assert res.json["account_name"] == "Ana"
    assert "password" not in str(res.json).replace("has_password", "")

    assert client.get("/api/auth/me").status_code == 200
    user = db.session.scalar(db.select(User))
    assert user.password_hash.startswith("$argon2")
    total = db.session.scalar(db.select(db.func.count()).select_from(Category))
    assert total == 16


def test_token_de_sessao_nao_fica_no_banco_em_texto(client):
    res = register(client)
    cookie = res.headers["Set-Cookie"]
    token = cookie.split("monetta_session=")[1].split(";")[0]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert db.session.scalar(db.select(UserSession)).token_hash != token


def test_email_duplicado_e_senha_curta(client, make_client):
    register(client)
    assert register(make_client()).status_code == 409
    assert register(make_client(), email="b@example.com", password="curta").status_code == 422


def test_login_e_logout_revoga_sessao(client, make_client):
    register(client)
    other = make_client()
    res = other.post("/api/auth/login", json={"email": "ana@example.com", "password": "senha-de-teste-1"})
    assert res.status_code == 200
    assert other.post("/api/auth/logout").status_code == 204
    assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200  # a outra sessão continua


def test_login_invalido_nao_revela_se_email_existe(client, make_client):
    register(client)
    wrong = make_client().post("/api/auth/login", json={"email": "ana@example.com", "password": "errada-123"})
    unknown = make_client().post("/api/auth/login", json={"email": "x@example.com", "password": "errada-123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json == unknown.json


def test_bloqueia_depois_de_cinco_erros(client, make_client):
    register(client)
    other = make_client()
    body = {"email": "ana@example.com", "password": "errada-123"}
    for _ in range(5):
        assert other.post("/api/auth/login", json=body).status_code == 401
    correct = {"email": "ana@example.com", "password": "senha-de-teste-1"}
    assert other.post("/api/auth/login", json=correct).status_code == 429


def test_rotas_exigem_login_e_header(client):
    assert client.get("/api/dashboard").status_code == 401
    assert client.raw.post("/api/auth/login", json={}).status_code == 403


def test_perfil_atualiza_nome_e_tema(client):
    register(client)
    res = client.patch("/api/profile", json={"account_name": "Ana Souza", "theme": "dark"})
    assert res.json["account_name"] == "Ana Souza"
    assert res.json["theme"] == "dark"
    assert client.patch("/api/profile", json={"theme": "azul"}).status_code == 422


def test_troca_de_senha_exige_atual_e_derruba_outras_sessoes(client, make_client):
    register(client)
    other = make_client()
    other.post("/api/auth/login", json={"email": "ana@example.com", "password": "senha-de-teste-1"})

    bad = client.post("/api/profile/password", json={"current_password": "x", "new_password": "nova-senha-123"})
    assert bad.status_code == 403
    ok = client.post("/api/profile/password", json={
        "current_password": "senha-de-teste-1", "new_password": "nova-senha-123",
    })
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
