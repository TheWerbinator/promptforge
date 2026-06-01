# PromptForge Architecture

> System overview. Reasoning for every choice lives in [INTERVIEW-NOTES.md](INTERVIEW-NOTES.md). Current implementation progress lives in [PROGRESS.md](PROGRESS.md). Master plan in [../../PLAN.md](../../PLAN.md).

## System diagram (target end state)

```
              ┌────────────────────────────────────────────────────┐
              │  promptforge.vercel.app  (apps/web)                │
              │  Next.js 15 + shadcn/ui + Tailwind                 │
              └─────────────────┬──────────────────────────────────┘
                                │ REST + SSE
                                │ Bearer JWT or API key
              ┌─────────────────▼──────────────────────────────────┐
              │  promptforge-api.fly.dev  (apps/api)               │
              │  FastAPI + SQLAlchemy async + Pydantic v2          │
              │  Auth, prompts, versions, runs, evals, queue       │
              └───┬──────────────────────────────────────────┬─────┘
                  │ enqueues eval jobs                      │ LLM calls
                  ▼                                          ▼
            ┌──────────┐                            ┌─────────────────────┐
            │ worker   │                            │ OpenAI / Anthropic  │
            │ process  │ ◄── Postgres queue ────    │ via litellm         │
            └──────────┘    (SKIP LOCKED + NOTIFY)  └─────────────────────┘
                  │
                  ▼
            ┌─────────────────────────────────────────────────┐
            │  Postgres 16 + pgvector (Fly Postgres)          │
            │  orgs, users, prompts, evals, jobs, corpora,    │
            │  documents, chunks (1536d + 384d embeddings)    │
            └─────────────────────────────────────────────────┘
                                ▲
                                │ shared schema
              ┌─────────────────┴──────────────────────────────────┐
              │  promptforge-ragent.fly.dev  (apps/ragent)         │
              │  RAG-agent: 4 corpora, hybrid retrieval, ReAct     │
              │  loop, SSE chat. Fetches system prompt LIVE from   │
              │  apps/api — real platform integration.             │
              └────────────────────────────────────────────────────┘
```

## Apps

### apps/api — FastAPI backend (in active development)

Two processes share a single Docker image: `api` (uvicorn) and `worker` (queue consumer). Multi-tenant API powering prompt management, version-aware execution, eval orchestration, and the job queue.

**Stack:** FastAPI · SQLAlchemy 2.x async · Alembic (async-mode using asyncpg, no sync driver) · Postgres 17 + pgvector (Neon managed) · Pydantic v2 · python-jose (JWT HS256) · argon2-cffi · litellm · uv · ruff · mypy strict · pytest · testcontainers-postgres.

**Internal modules (training-repo DNA):**
- `core/config.py` — pydantic-settings
- `core/security.py` — JWT, argon2, API key hashing, refresh rotation w/ chain-revocation replay defense
- `core/db.py` — lazy async engine, session factory, `get_session` dependency
- `core/deps.py` — `Principal`, `get_principal`, `require_role`, `get_repo(Model)` factory
- `core/prompts.py` — typed `PromptTemplate` w/ applicative `render()` and content-stable `fingerprint()`  (applicative-practice DNA)
- `core/async_utils.py` — `retry` decorator, `TokenBucket` w/ injectable clock, `rate_limited`, `gather_bounded` (promises-practice DNA)
- `core/queue.py` — *pending phase 8* — Postgres `SKIP LOCKED` queue + `LISTEN/NOTIFY` SSE fanout (sqlite-practice DNA reframed)
- `repositories/base.py` — `TenantRepository[T]` generic; mandatory `org_id` scope; optional composed-after `where` kwarg; cross-org returns None (404, not 403)

**Routes (current):** `/api/v1/auth/{signup,login,me,refresh,logout,api-keys}` · `/api/v1/prompts` CRUD + `/prompts/{id}/versions` + `/versions/{id}` · `/health`. OpenAPI at `/docs`.

**Routes (pending):** `/runs`, `/eval-suites`, `/eval-batches`, `/demo/login`, `/public/share/{token}`.

### apps/ragent — RAG + agent service *(not started)*

Four corpora (3 seeded + user-uploadable). Per-corpus embedding model (OpenAI `text-embedding-3-small` 1536d or local `bge-small-en-v1.5` 384d). Hybrid retrieval (pgvector cosine + BM25 + RRF). Optional cross-encoder rerank. ReAct loop w/ 3 tools (`search_docs`, `fetch_passage`, `cite_sources`). Streams chat via SSE. Fetches system prompt from apps/api at runtime — real platform integration.

### apps/web — Next.js frontend *(not started)*

Next.js 15 App Router · React 19 · TypeScript strict · Tailwind · shadcn/ui · Zustand (small UI stores) · openapi-typescript (API types codegen) · eventsource-parser (SSE) · monaco-editor (prompt body) · Vitest · Playwright · pnpm.

## Data model (current)

| Entity | Purpose | Shipped |
|---|---|---|
| `User` | Authentication subject | ✓ phase 2 |
| `Org`, `Membership`, `OrgRole` enum | Multi-tenant boundary | ✓ phase 2 |
| `ApiKey` | Machine credential (argon2-hashed, prefix lookup) | ✓ phase 3 |
| `RefreshToken` | Single-use rotated session w/ chain-revocation replay defense | ✓ phase 3 |
| `Prompt` | Per-org named prompt w/ tags + visibility | ✓ phase 5 |
| `PromptVersion` | Append-only versioned body + variables jsonb | ✓ phase 5 |
| `Job` | Postgres queue (SKIP LOCKED) | pending phase 8 |
| `Run` | Single LLM execution record | pending phase 10 |
| `EvalSuite`, `EvalCase`, `EvalBatch`, `EvalResult` | Eval orchestration | pending phase 11 |
| `ShareToken` | Public read-only links | pending phase 14 |
| `Corpus`, `Document`, `Chunk` | ragent vector store (`embedding_1536` + `embedding_384` nullable cols) | pending |
| `Conversation`, `Message` | Chat history | pending |

All carry `org_id` and go through `TenantRepository`. Routes use the `get_repo(Model)` dependency factory; direct `session.execute` in routes is a code smell.

## Auth flow

```
Signup ─► JWT access (15 min) + refresh cookie (30 days, httpOnly, SameSite=Lax)
                                  │
                                  ▼
                          Refresh rotated on every refresh call
                                  │
                                  ▼
                          Reuse of rotated refresh ─► revoke entire chain
```

Demo mode (pending phase 13): `POST /demo/login` issues a read-only JWT for the seeded `Demo Corp` org. BYOK header lets demo users run LLM calls with their own key.

## Test architecture

- **Unit** — pure logic, no DB. Mocked LLM/time. ~71 tests (phase 7).
- **Integration** — testcontainers Postgres (session-scoped), per-test transactional rollback via `db_session` fixture. Migrations applied once per session.
- **E2E** — full ASGI app + testcontainers Postgres + per-test truncate. Bound to the app via FastAPI `app.dependency_overrides[get_session]` rather than mutating the module-global engine (avoids cross-test flake on engine dispose races).
- **Tenancy** — shared `tests/tenancy/_helpers.make_two_orgs` produces two signed-in users in distinct orgs. Each protected resource gets its own `test_*_tenancy.py` contract.

## Hosting

| Component | Where |
|---|---|
| `apps/api` (api + worker processes) | Fly.io, region `ord`, shared-cpu-1x / 512MB each |
| Postgres 17 + pgvector | Neon managed (AWS us-east-1), connected via direct (session-mode) endpoint |
| Future: `apps/ragent` | Fly.io, same region |
| Future: `apps/web` | Vercel |

Fly's `[deploy] release_command = "alembic upgrade head"` runs migrations on a temp machine before traffic shifts; failed migrations abort the deploy with old machines still serving.

The DSN normalizer in [`promptforge_api/core/config.py`](../apps/api/promptforge_api/core/config.py) (`Settings.async_database_url`) accepts any provider's DSN shape — bare `postgresql://`, old-style `postgres://`, with or without `sslmode` query param — and rewrites it to `postgresql+asyncpg://` with `ssl=` for asyncpg compatibility.

## Local development

```sh
docker compose -f infra/compose.yml up --wait
```

Brings up Postgres 17 + a one-shot `api-migrate` (runs `alembic upgrade head`) + the api service. See `infra/compose.yml`. Production deploy runbook: [`DEPLOY.md`](DEPLOY.md).
