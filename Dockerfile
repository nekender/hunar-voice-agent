# --- build the browser UI
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- API + static UI in one small image
FROM python:3.13-slim
# State lives in Postgres (DATABASE_URL); DATA_DIR is only scratch space, so it can be ephemeral.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/tmp/app-data
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /web/dist frontend/dist
RUN useradd --uid 1000 app
USER app
WORKDIR /app/backend
EXPOSE 8080
# Hosts that inject $PORT (Render) are honoured; 8080 otherwise.
# One worker on purpose: live sessions and the per-session locks are in-process (see README limitations).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
