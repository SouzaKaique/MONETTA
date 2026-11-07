"""Comandos de administração do servidor."""
import click
from flask import Flask

from .extensions import db
from .models import User
from .services.security import hash_password, revoke_all_sessions

MIN_PASSWORD = 10


def register_commands(app: Flask) -> None:
    @app.cli.command("reset-password")
    @click.argument("email")
    @click.password_option("--password", prompt="Nova senha", confirmation_prompt="Repita a senha")
    def reset_password(email: str, password: str) -> None:
        """Define uma nova senha e encerra todas as sessões da conta."""
        user = db.session.scalar(db.select(User).filter_by(email=email.strip().lower()))
        if user is None:
            raise click.ClickException("Conta não encontrada.")
        if len(password) < MIN_PASSWORD:
            raise click.ClickException(f"Use pelo menos {MIN_PASSWORD} caracteres.")
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        revoke_all_sessions(user)
        db.session.commit()
        click.echo("Senha alterada. Todas as sessões foram encerradas.")
