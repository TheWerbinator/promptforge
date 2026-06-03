# promptforge-api

FastAPI backend for PromptForge — auth, multi-tenancy, prompts + versioning, runs,
the eval engine, a Postgres-backed job queue, demo mode, and public share links.

**Live:** https://promptforge-api.fly.dev/docs

## Endpoints

| Group | Routes |
|---|---|
| Auth | `/auth/{signup,login,me,refresh,logout,api-keys}` — JWT access + rotating refresh cookies, API keys |
| Demo | `/demo/{login,quota}` — instant read-only session, per-IP free-run quota |
| Prompts | `/prompts` CRUD + `/prompts/{id}/versions` (append-only) + `/versions/{id}` |
| Runs | `/versions/{id}/run` + `/runs/{id}` — single execution, cost-tracked |
| Evals | `/eval-suites` (+ cases, run) · `/eval-batches/{id}` · `/eval-batches/{id}/stream` (SSE) |
| Shares | `/shares` (+ revoke) · `/public/share/{token}` (no auth) |

Interactive OpenAPI docs at `/docs`.

## Quick start (local)

```sh
# From repo root: Postgres + this app + worker
docker compose -f infra/compose.yml up --wait

# Or from this directory, with uv
uv sync --all-extras
uv run uvicorn promptforge_api.main:app --reload --port 8000
python -m promptforge_api.seed   # optional: seed the demo workspace
```

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict promptforge_api
uv run pytest --cov                              # full suite (needs Docker)
uv run pytest -m "not integration and not e2e"   # unit only (no Docker)
```

CI runs the same checks across Python 3.11 + 3.12, then deploys to Fly on green
pushes to `main`. See [../../docs/DEPLOY.md](../../docs/DEPLOY.md).

## Docs

- **[../../docs/GUIDE.md](../../docs/GUIDE.md)** — what it does, the workflow, what you provide.
- **[../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)** — system shape.
- **[../../docs/DECISIONS.md](../../docs/DECISIONS.md)** — the "why" behind every choice.
