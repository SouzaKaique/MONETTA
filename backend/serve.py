"""Modo de produção: API e aplicativo no mesmo endereço. Use atrás de um proxy com HTTPS."""
import os

from waitress import serve

os.environ["SERVE_FRONTEND"] = "1"

from app import create_app  # noqa: E402

if __name__ == "__main__":
    serve(create_app(), host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
