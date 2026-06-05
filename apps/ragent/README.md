# promptforge-ragent

RAG + ReAct agent service for PromptForge. Hybrid retrieval (pgvector + BM25 +
RRF) over four corpora, a capped ReAct loop with citation tools, and SSE-streamed
chat — running on the **shared platform Postgres** and fetching its system prompt
**live from apps/api**.

> **Status:** bootstrap (Phase 1 of 14). Boots + `/health` only; retrieval, the
> agent loop, and chat land in later phases. See [../../docs/PROGRESS.md](../../docs/PROGRESS.md).

## Platform integration

- **Shared DB.** Same Postgres + pgvector as apps/api; the schema and Alembic
  migration history are owned by apps/api. ragent reads/writes the shared models,
  it never migrates.
- **Shared HS256 secret.** `PF_JWT_SECRET` is the same value as apps/api, so a
  platform-issued access token validates here directly — no round-trip to the API.
- **Live system prompt.** The agent fetches its system prompt from apps/api
  (`PF_API_BASE_URL`) at runtime, cached briefly. Editing the prompt in the
  PromptForge UI changes agent behavior on the next request.

## Quick start (local)

```sh
uv sync --all-extras
cp .env.example .env   # point PF_DATABASE_URL + PF_JWT_SECRET at the platform DB
uv run uvicorn promptforge_ragent.main:app --reload --port 8001
```

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict promptforge_ragent
uv run pytest -m "not integration and not e2e"   # unit only (no Docker)
uv run pytest --cov                              # full suite (needs Docker)
```

CI (`.github/workflows/ragent.yml`) runs the same checks across Python 3.11 + 3.12.

## Docs

- **[../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)** — system shape.
- **[../../docs/DECISIONS.md](../../docs/DECISIONS.md)** — the "why" behind every choice.
