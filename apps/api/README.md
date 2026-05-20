# promptforge-api

FastAPI backend for PromptForge.

## Quick start (local)

```sh
# From repo root, brings up Postgres + this app + worker
docker compose -f infra/compose.yml up --wait

# Or from this directory, with uv
uv sync --all-extras
uv run uvicorn promptforge_api.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Development

```sh
uv run ruff check .
uv run ruff format .
uv run mypy --strict promptforge_api
uv run pytest --cov
```

## Architecture

See [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) and [../../PLAN.md](../../../PLAN.md) for the full plan.
