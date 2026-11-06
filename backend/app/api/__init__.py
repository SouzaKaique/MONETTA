from flask import Flask

from . import auth, dashboard, profile, social


def register_blueprints(app: Flask) -> None:
    for module in (auth, social, profile, dashboard):
        app.register_blueprint(module.bp)
