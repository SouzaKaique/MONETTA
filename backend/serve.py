"""
Modo de produção: API e aplicativo no mesmo endereço, atrás de um proxy com HTTPS.

Com APP_ENV=production, recusa iniciar se a configuração for insegura.
TRUSTED_PROXY indica quem pode informar o IP real do visitante. Sem ele, cabeçalhos como
X-Forwarded-For são ignorados, porque qualquer um poderia falsificá-los.
"""
import logging
import os

from waitress import serve

os.environ["SERVE_FRONTEND"] = "1"

from app import create_app  # noqa: E402
from app.config import Config, production_problems  # noqa: E402

THREADS = 8


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("APP_ENV") == "production":
        problems = production_problems(Config, allow_local=os.environ.get("ALLOW_LOCAL") == "1")
        if problems:
            raise SystemExit("Configuração insegura:\n- " + "\n- ".join(problems))

    options = {
        "host": os.environ.get("HOST", "127.0.0.1"),
        "port": int(os.environ.get("PORT", "5000")),
        "threads": THREADS,
    }
    proxy = os.environ.get("TRUSTED_PROXY")
    if proxy:
        options |= {
            "trusted_proxy": proxy,
            "trusted_proxy_count": 1,
            "trusted_proxy_headers": "x-forwarded-for x-forwarded-proto",
        }
    serve(create_app(), **options)


if __name__ == "__main__":
    main()
