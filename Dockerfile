# SelfFarm-Lite — image Docker multi-arch (linux/amd64 + linux/arm64)
#
# Build local :
#   docker build -t selffarm-lite:latest .
#
# Run webapp (par défaut) :
#   docker run --rm -p 8001:8001 -v selffarm-data:/app/data ghcr.io/pierroons/selffarm-lite:latest
#   → http://localhost:8001
#
# Run CLI ponctuel (override entrypoint) :
#   docker run --rm -v $(pwd)/data:/app/data --entrypoint python ghcr.io/pierroons/selffarm-lite:latest -m self_dnja.cli --help
#
# Volumes persistés :
#   /app/data       → SQLite compta + cache aides (à mapper sur un volume nommé)
#
# AGPL-3.0-or-later — my-self.fr

# ============================================================================
# STAGE 1 — Builder : compile les wheels Python dans un venv isolé
# ============================================================================
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango1.0-dev \
        libcairo2-dev \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml VERSION README.md ./
COPY modules/ ./modules/

RUN pip install --upgrade pip wheel setuptools && \
    pip install \
        "fastapi>=0.110,<1.0" \
        "starlette>=0.40,<1.0" \
        "uvicorn[standard]>=0.27" \
        "pydantic>=2.6" \
        "pyyaml>=6.0" \
        "jinja2>=3.1" \
        "weasyprint>=62.0" \
        "sqlalchemy>=2.0" \
        "python-dateutil>=2.9" \
        "python-multipart>=0.0.9" \
        "pdfplumber>=0.11" \
        "reportlab>=4.0" \
        "drafthorse>=2.3"

RUN pip install --no-deps .

# ============================================================================
# STAGE 2 — Runtime : image légère sans toolchain de build
# ============================================================================
FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="SelfFarm-Lite" \
      org.opencontainers.image.description="Étage applicatif agricole MySelf — DNJA, Factur-X, compta hub, parcelles IGN" \
      org.opencontainers.image.source="https://github.com/Pierroons/selffarm-lite" \
      org.opencontainers.image.url="https://selffarm.my-self.fr" \
      org.opencontainers.image.documentation="https://github.com/Pierroons/selffarm-lite/blob/main/README.md" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.vendor="MySelf"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    SELFFARM_HOST=0.0.0.0 \
    SELFFARM_PORT=8001 \
    SELFFARM_ENV=prod \
    SELFFARM_COMPTA_DB=/app/data/compta.db \
    SELFFARM_AIDES_CACHE=/app/data/aides

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libjpeg62-turbo \
        shared-mime-info \
        fonts-dejavu \
        fonts-liberation \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 selffarm && \
    useradd --system --uid 1001 --gid selffarm --home /app --shell /bin/bash selffarm

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=selffarm:selffarm modules/ ./modules/
COPY --chown=selffarm:selffarm webapp/ ./webapp/
COPY --chown=selffarm:selffarm examples/ ./examples/
COPY --chown=selffarm:selffarm VERSION README.md LICENSE ./

RUN mkdir -p /app/data /app/data/aides && \
    chown -R selffarm:selffarm /app/data

VOLUME ["/app/data"]

USER selffarm

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${SELFFARM_PORT}/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["sh", "-c", "uvicorn webapp.main:app --host ${SELFFARM_HOST} --port ${SELFFARM_PORT} --proxy-headers --forwarded-allow-ips='*'"]
