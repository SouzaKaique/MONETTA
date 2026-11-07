"""Regras que só importam com o sistema publicado."""
from app import create_app
from app.config import Config, TestConfig, production_problems
from app.extensions import db
from app.models import User
from app.services import oauth

from .conftest import HEADERS, register

STRONG = "a" * 64


def config(**values):
    base = {
        "PUBLIC_URL": "https://monetta.example.com",
        "SECRET_KEY": STRONG,
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://u:p@db/monetta",
    }
    return type("Production", (Config,), base | values)


# Validação da configuração

def test_configuracao_correta_nao_tem_problemas():
    assert production_problems(config()) == []


def test_exige_https():
    assert any("https://" in p for p in production_problems(config(PUBLIC_URL="http://monetta.example.com")))


def test_recusa_endereco_local():
    assert any("endereço público" in p for p in production_problems(config(PUBLIC_URL="https://localhost")))
    assert production_problems(config(PUBLIC_URL="https://localhost"), allow_local=True) == []


def test_exige_segredo_forte_e_sem_valor_de_exemplo():
    assert any("SECRET_KEY" in p for p in production_problems(config(SECRET_KEY="curto")))
    assert any("SECRET_KEY" in p for p in production_problems(config(SECRET_KEY="troque-" + "x" * 60)))


def test_exige_banco():
    assert any("DATABASE_URL" in p for p in production_problems(config(SQLALCHEMY_DATABASE_URI="")))


# Cadastro fechado

class ClosedConfig(TestConfig):
    REGISTRATION_OPEN = False


def closed_client(app):
    closed = create_app(ClosedConfig)
    return closed.test_client()


def test_primeira_conta_passa_e_as_demais_nao(app):
    web = closed_client(app)
    first = {"account_name": "Ana", "email": "ana@example.com", "password": "senha-de-teste-1"}
    assert web.get("/api/auth/providers").json["registration"] is True
    assert web.post("/api/auth/register", json=first, headers=HEADERS).status_code == 201

    other = closed_client(app)
    assert other.get("/api/auth/providers").json["registration"] is False
    second = first | {"email": "bia@example.com"}
    res = other.post("/api/auth/register", json=second, headers=HEADERS)
    assert res.status_code == 403 and "fechado" in res.json["error"]


def test_cadastro_fechado_ainda_permite_login(app):
    web = closed_client(app)
    body = {"account_name": "Ana", "email": "ana@example.com", "password": "senha-de-teste-1"}
    web.post("/api/auth/register", json=body, headers=HEADERS)
    res = closed_client(app).post("/api/auth/login", headers=HEADERS, json={
        "email": body["email"], "password": body["password"],
    })
    assert res.status_code == 200


def test_login_social_nao_cria_conta_com_cadastro_fechado(app):
    closed = create_app(ClosedConfig)
    with closed.app_context():
        from app.services.accounts import create_user
        create_user(email="ana@example.com", account_name="Ana", email_verified=True)
        db.session.commit()
        claims = {"sub": "g-2", "email": "bia@example.com", "email_verified": True}
        try:
            oauth.resolve_user(oauth.GOOGLE, claims)
            raised = False
        except oauth.OAuthError as exc:
            raised = exc.code == "cadastro_fechado"
        db.session.rollback()
        assert raised
        # Quem já tem conta continua entrando pelo provedor.
        same = {"sub": "g-1", "email": "ana@example.com", "email_verified": True}
        assert oauth.resolve_user(oauth.GOOGLE, same).email == "ana@example.com"


def test_com_cadastro_aberto_nada_muda(client):
    assert client.get("/api/auth/providers").json["registration"] is True
    assert register(client).status_code == 201


# Redefinição de senha pelo servidor

def test_comando_redefine_senha_e_encerra_sessoes(app, client):
    register(client)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["reset-password", "ANA@example.com"], input="nova-senha-forte\nnova-senha-forte\n")
    assert result.exit_code == 0, result.output
    assert client.get("/api/auth/me").status_code == 401
    res = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "nova-senha-forte"})
    assert res.status_code == 200


def test_comando_destrava_conta_bloqueada(app, client):
    register(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "ana@example.com", "password": "errada-123"})
    assert db.session.scalar(db.select(User)).locked_until is not None
    app.test_cli_runner().invoke(args=["reset-password", "ana@example.com"], input="nova-senha-forte\nnova-senha-forte\n")
    db.session.expire_all()
    assert db.session.scalar(db.select(User)).locked_until is None


def test_comando_recusa_conta_inexistente_e_senha_curta(app, client):
    register(client)
    runner = app.test_cli_runner()
    assert runner.invoke(args=["reset-password", "x@example.com"], input="nova-senha-forte\nnova-senha-forte\n").exit_code != 0
    assert runner.invoke(args=["reset-password", "ana@example.com"], input="curta\ncurta\n").exit_code != 0


# Arquivos do aplicativo

class FrontendConfig(TestConfig):
    SERVE_FRONTEND = True


def test_arquivos_com_hash_ficam_em_cache_e_os_demais_nao(app, tmp_path, monkeypatch):
    import app as package
    for name in ("index.html", "ngsw.json", "ngsw-worker.js", "main-36EZRQPT.js"):
        (tmp_path / name).write_text("x", encoding="utf8")
    monkeypatch.setattr(package, "FRONTEND_DIR", tmp_path)
    web = create_app(FrontendConfig).test_client()
    assert "immutable" in web.get("/main-36EZRQPT.js").headers["Cache-Control"]
    for path in ("/", "/planejamento", "/ngsw.json", "/ngsw-worker.js"):
        assert "immutable" not in web.get(path).headers["Cache-Control"]
        assert "no-cache" in web.get(path).headers["Cache-Control"]
