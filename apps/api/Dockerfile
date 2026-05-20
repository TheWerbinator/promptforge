FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv pip install --system -r <(uv pip compile pyproject.toml --no-header) \
    || uv sync --frozen --no-dev || uv sync --no-dev

COPY promptforge_api ./promptforge_api

EXPOSE 8000

CMD ["uvicorn", "promptforge_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
