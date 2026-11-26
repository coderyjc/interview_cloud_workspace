# syntax=docker/dockerfile:1

# ---------- stage 1: build the React frontend ----------
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: runtime (node + python + claude code) ----------
FROM node:20-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates openssl \
 && rm -rf /var/lib/apt/lists/*

# The real Agent CLI. Runs headless as a non-root user (see below).
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY backend/requirements.txt ./
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /fe/dist ./static

# --dangerously-skip-permissions refuses to run as root, so run as the
# non-root `node` user (uid 1000) that already exists in node:20-slim.
RUN chmod +x /app/entrypoint.sh \
 && mkdir -p /data/workspaces /data/claude /data/home \
 && chown -R node:node /data /app

USER node
ENV PATH="/venv/bin:$PATH" \
    HOME=/data/home \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
