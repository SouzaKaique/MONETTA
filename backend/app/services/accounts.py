"""Criação de usuários e dados iniciais de cada conta."""
from ..extensions import db
from ..models import AppSettings, Category, User

DEFAULT_EXPENSE_CATEGORIES = [
    ("Moradia", "house"), ("Alimentação", "basket"), ("Transporte", "car-front"),
    ("Saúde", "heart-pulse"), ("Lazer", "controller"), ("Compras", "bag"),
    ("Assinaturas", "arrow-repeat"), ("Educação", "book"), ("Serviços", "tools"),
    ("Outros", "three-dots"),
]
ESSENTIAL_CATEGORIES = {"Moradia", "Alimentação", "Transporte", "Saúde", "Serviços", "Educação"}
DEFAULT_INCOME_CATEGORIES = [
    ("Salário", "wallet2"), ("Freelance", "laptop"), ("Vendas", "shop"),
    ("Comissões", "percent"), ("Presentes", "gift"), ("Outras entradas", "plus-circle"),
]


def create_user(
    *, email: str, account_name: str, password_hash: str | None = None,
    email_verified: bool = False, avatar_url: str | None = None,
) -> User:
    user = User(
        email=email.strip().lower(), account_name=account_name.strip(),
        password_hash=password_hash, email_verified=email_verified, avatar_url=avatar_url,
    )
    user.settings = AppSettings()
    db.session.add(user)
    db.session.flush()
    db.session.add_all(
        [Category(user_id=user.id, kind="expense", name=n, icon=i, is_default=True,
                  is_essential=n in ESSENTIAL_CATEGORIES)
         for n, i in DEFAULT_EXPENSE_CATEGORIES]
        + [Category(user_id=user.id, kind="income", name=n, icon=i, is_default=True)
           for n, i in DEFAULT_INCOME_CATEGORIES]
    )
    return user
