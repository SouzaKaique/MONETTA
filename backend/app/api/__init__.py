from flask import Flask

from . import (
    accounts, auth, cards, dashboard, debts, planning, profile, recurrences, social, transactions,
    wishlist,
)


def register_blueprints(app: Flask) -> None:
    for module in (
        auth, social, profile, dashboard, accounts, transactions, recurrences, cards, debts,
        planning, wishlist,
    ):
        app.register_blueprint(module.bp)
