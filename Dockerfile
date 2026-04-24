# SelfFarm-Lite — image Docker multi-arch (amd64, arm64 pour Raspberry Pi 4)
# Usage :
#   docker build -t selffarm-lite:latest .
#   docker run --rm -it -v $(pwd)/data:/data selffarm-lite self-dnja --version
#
FROM python:3.12-slim AS base

LABEL org.opencontainers.image.title="SelfFarm-Lite"
LABEL org.opencontainers.image.description="Modules agricoles AGPL pour JA français"
LABEL org.opencontainers.image.source="https://github.com/Pierroons/selffarm-lite"
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Dépendances système pour WeasyPrint (fontes + libs image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libjpeg62-turbo \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps en une couche
COPY pyproject.toml VERSION README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir pydantic pyyaml jinja2 weasyprint

# Copie le code applicatif
COPY modules/ ./modules/
COPY examples/ ./examples/

ENV PYTHONPATH=/app/modules
ENV PYTHONUNBUFFERED=1

# Par défaut la commande self-dnja (override avec `docker run ... self-aid ...`)
ENTRYPOINT ["python3", "-m"]
CMD ["self_dnja.cli", "--help"]
