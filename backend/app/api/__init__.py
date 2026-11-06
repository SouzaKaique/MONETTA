from flask import Flask

from . import accounts, auth, cards, dashboard, profile, recurrences, social, transactions


def register_blueprints(app: Flask) -> None:
    for module in (auth, social, profile, dashboard, accounts, transactions, recurrences, cards):
        app.register_blueprint(module.bp)
