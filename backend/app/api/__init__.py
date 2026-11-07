from flask import Flask

from . import (
    accounts, auth, cards, dashboard, debts, integrations, planning, profile, recurrences, reports,
    social, transactions, wishlist,
)


def register_blueprints(app: Flask) -> None:
    for module in (
        auth, social, profile, dashboard, accounts, transactions, recurrences, cards, debts,
        planning, wishlist, reports, integrations,
    ):
        app.register_blueprint(module.bp)
