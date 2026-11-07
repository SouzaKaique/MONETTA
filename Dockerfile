# Etapa 1: compila o aplicativo Angular.
FROM node:24-slim AS web
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build

# Etapa 2: imagem final, só com o necessário para rodar.
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=wsgi.py
WORKDIR /app/backend

COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.lock

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/wsgi.py backend/serve.py ./
COPY deploy/start.sh ./start.sh
COPY --from=web /build/dist/frontend/browser /app/frontend/dist/frontend/browser

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin monetta
USER monetta

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:5000/api/health', timeout=4)"]

CMD ["sh", "start.sh"]
