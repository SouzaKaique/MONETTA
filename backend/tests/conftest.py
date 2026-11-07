import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db

HEADERS = {"X-Monetta-Client": "web"}


class Client:
    """Cliente de teste que envia o header exigido pela API."""

    def __init__(self, app):
        self.raw = app.test_client()

    def get(self, *a, **k):
        return self.raw.get(*a, **k)

    def post(self, *a, **k):
        return self.raw.post(*a, headers=HEADERS, **k)

    def put(self, *a, **k):
        return self.raw.put(*a, headers=HEADERS, **k)

    def patch(self, *a, **k):
        return self.raw.patch(*a, headers=HEADERS, **k)


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return Client(app)


@pytest.fixture()
def make_client(app):
    return lambda: Client(app)


def register(client, email="ana@example.com", password="senha-de-teste-1", name="Ana"):
    return client.post("/api/auth/register", json={
        "account_name": name, "email": email, "password": password,
    })
