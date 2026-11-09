"""Envio de e-mails do sistema (hoje, só o link de redefinição de senha)."""
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app


def send(to: str, subject: str, body: str) -> None:
    """Envia sem bloquear a resposta: o tempo de envio não revela se a conta existe."""
    c = current_app.config
    backend = c["MAIL_BACKEND"]
    if backend == "memory":
        current_app.extensions.setdefault("mail_outbox", []).append(
            {"to": to, "subject": subject, "body": body}
        )
        return
    if backend == "console":
        print(f"\n[MONETTA] E-mail para {to}: {subject}\n{body}\n", flush=True)
        return

    message = EmailMessage()
    message["From"] = c["SMTP_FROM"] or c["SMTP_USER"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    settings = (c["SMTP_HOST"], c["SMTP_PORT"], c["SMTP_USER"], c["SMTP_PASSWORD"])
    logger = current_app.logger
    threading.Thread(target=_deliver, args=(message, settings, logger), daemon=True).start()


def _deliver(message: EmailMessage, settings: tuple, logger) -> None:
    host, port, user, password = settings
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            if user:
                server.login(user, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Falha ao enviar e-mail: %s", type(exc).__name__)
