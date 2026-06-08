# PromptForge Architecture

> System overview. Reasoning for every choice lives in [DECISIONS.md](DECISIONS.md). Current implementation progress lives in [PROGRESS.md](PROGRESS.md). Master plan in [../../PLAN.md](../../PLAN.md).

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

**Stack:** FastAPI · SQLAlchemy 2.x async · Alembic (async-mode using asyncpg, no sync driver) · Postgres 17 + pgvector (Neon managed) · Pydantic v2 · python-jose (JWT HS256) · argon2-cffi · litellm · slowapi (rate limiting) · sse-starlette · uv · ruff · mypy strict · pytest · testcontainers-postgres.

**Internal modules (training-repo DNA):**
- `core/config.py` — pydantic-settings
- `core/security.py` — JWT, argon2, API key hashing, refresh rotation w/ chain-revocation replay defense
- `core/db.py` — lazy async engine, session factory, `get_session` dependency
- `core/deps.py` — `Principal`, `get_principal`, `require_role`, `get_repo(Model)` factory
- `core/prompts.py` — typed `PromptTemplate` w/ applicative `render()` and content-stable `fingerprint()`  (applicative-practice DNA)
- `core/async_utils.py` — `retry` decorator, `TokenBucket` w/ injectable clock, `rate_limited`, `gather_bounded` (promises-practice DNA)
- `core/queue.py` — *pending phase 8* — Postgres `SKIP LOCKED` queue + `LISTEN/NOTIFY` SSE fanout (sqlite-practice DNA reframed)
- `repositories/base.py` — `TenantRepository[T]` generic; mandatory `org_id` scope; optional composed-after `where` kwarg; cross-org returns None (404, not 403)

**Routes (current):** `/api/v1/auth/{signup,login,me,refresh,logout,api-keys}` · `/api/v1/demo/{login,quota}` · `/api/v1/prompts` CRUD + `/prompts/{id}/versions` + `/versions/{id}` · `/api/v1/versions/{id}/run` + `/runs/{id}` · `/api/v1/eval-suites` (+ cases, run) + `/eval-batches/{id}` + `/eval-batches/{id}/stream` (SSE) · `/api/v1/shares` (+ `/{id}`) + `/api/v1/public/share/{token}` (no auth) · `/health`. OpenAPI at `/docs`.

**Routes (pending):** none for apps/api MVP — remaining work is seed (15), deploy/observability (16), README polish (17).

### apps/ragent — RAG + agent service *(in active development — 12/14)*

Four corpora (3 seeded + user-uploadable). Per-corpus embedding model (OpenAI `text-embedding-3-small` 1536d or local `bge-small-en-v1.5` 384d). Hybrid retrieval (pgvector cosine + BM25 + RRF). Optional cross-encoder rerank. ReAct loop w/ 3 tools (`search_docs`, `fetch_passage`, `cite_sources`). Streams chat via SSE. Fetches system prompt from apps/api at runtime — real platform integration.

**Stack:** FastAPI · SQLAlchemy 2.x async (shared DB, schema migrated by apps/api) · pgvector · litellm (embeddings + generation) · tiktoken (chunk sizing) · markdown-it-py + pypdf + selectolax (parsing) · structlog · uv · ruff · mypy strict · pytest + testcontainers (pgvector image). Shares the `PF_` config + HS256 secret with apps/api.

**Modules so far:** `core/{config,logging,db}.py` (mirror api's) + `core/queue.py` (trimmed SKIP-LOCKED client over apps/api's shared `jobs` table; raw SQL, no ORM Job model). `models/` — Corpus/Document/Chunk/Conversation/Message (ragent owns these; apps/api migrates them). `services/` — the ingest pipeline: `parsing.extract_text` (per content type), `chunking.chunk_text` (token-window + overlap), `embeddings.embed_texts` (per-corpus routing: OpenAI via litellm 1536-d, or local bge-small 384-d via sentence-transformers in the opt-in `local-embeddings` extra — `is_query` adds bge's query instruction; transient OpenAI errors → `RetriableEmbeddingError`), `ingest.ingest_document` (parse→chunk→embed→persist orchestrator, idempotent, durable READY/FAILED, re-raises transient for requeue), `retrieval.hybrid_search` (pgvector cosine + in-process BM25 → RRF fusion, returns ranked `RetrievedChunk`s), `rerank.rerank` (optional cross-encoder reorder; off by default, passthrough otherwise — the `sentence-transformers`/torch backend is in the opt-in `rerank` extra, not in CI or the default image). `agent/tools.py` — the 3 ReAct tools (`search_docs`/`fetch_passage`/`cite_sources`) as litellm function schemas + corpus/org-scoped handlers + an `execute_tool` dispatcher; handlers return error dicts, not raises, so the loop can self-correct. `agent/loop.py` — `run_agent`, the ReAct loop (litellm function-calling → execute_tool → loop) with a max-iteration cap + a circuit breaker on repeated tool+args that forces a tool-less final answer; an async generator of `tool_call`/`tool_result`/`answer` events. `services/system_prompt.py` — resolves the agent's prompt from the shared DB by natural key (`services/platform.py`: demo org by slug + the prompt by name; apps/api owns + seeds the prompt) then fetches its body from apps/api over HTTP, authenticated by a service JWT minted from the shared HS256 secret, TTL-cached, with a default-prompt fallback. `seed.py` + `seed_data.py` — seed the 3 demo corpora (`promptforge-docs` self-referential, `fastapi-docs`, `arxiv-ml-abstracts`) into Demo Corp by running real `ingest_document` (idempotent; `python -m promptforge_ragent.seed`). `core/security.py` + `core/deps.py` — decode the shared-HS256 access token apps/api issues → `Principal` (validate-only, no token issuance). `api/v1/chat.py` — `POST /api/v1/chat`, the streaming chat endpoint: auth → resolve corpus (org-scoped) → load/create conversation + history → persist user message → `run_agent` streamed over SSE (`conversation`/`tool_call`/`tool_result`/`answer`/`done`) → persist assistant message (citations + tool trail); BYOK via `X-Provider-Key`; the SSE generator owns its own DB session. `api/v1/corpora.py` — `GET/POST /corpora` + `POST/GET /corpora/{id}/documents`: list/create corpora and upload documents; reads open to any principal, writes (create + upload) writer-gated; upload persists `Document(raw_content)` + `enqueue_ingest` on the shared queue (worker ingests async), with 5 MB/file + 50 MB/corpus caps. `workers/ingest_worker.py` — second Fly process, claims `kind="ingest_document"`, drives `ingest_document` from `documents.raw_content`, marks FAILED only on the final retry. Retrieval/agent/chat are Phases 5–9.

**Queue:** ragent shares apps/api's `jobs` table (migration 0004) rather than standing up its own — `kind="ingest_document"` for ingest, `kind="eval_case"` for api's eval worker, one table, two consumers filtered by kind. Requeue backoff is computed with the DB clock (`now() + make_interval`) so it's correct under host/container clock drift.

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
| `Job` | Postgres queue (SKIP LOCKED) | ✓ phase 8 |
| `Run` | Single LLM execution record | ✓ phase 10 |
| `EvalSuite`, `EvalCase`, `EvalBatch`, `EvalResult` | Eval orchestration | ✓ phase 11 |
| `DemoUsage` | Per-IP daily free-run counter (HMAC'd IP) — abuse/cost control | ✓ phase 13 |
| `ShareToken` | Public read-only links (polymorphic: prompt or eval_batch; HMAC'd token) | ✓ phase 14 |
| `Corpus`, `Document`, `Chunk` | ragent vector store (`embedding_1536` + `embedding_384` nullable cols + partial ivfflat indexes) | ✓ ragent phase 2 (migration `0009`) |
| `Conversation`, `Message` | Chat history (citations + tool_calls JSONB) | ✓ ragent phase 2 |

The five ragent entities are **defined in `apps/ragent/promptforge_ragent/models/`** (ragent's domain) but their table DDL lives in apps/api's migration history — apps/api is the single migrator for the shared DB. apps/api's `alembic/env.py` has an `include_object` guard so autogenerate ignores tables outside its own metadata. Because migration `0009` creates the `vector` extension, the testcontainers + compose Postgres image is `pgvector/pgvector:pg17` (Neon prod ships pgvector). Migration `0010` adds `documents.raw_content` (BYTEA) — the source bytes the detached ingest worker reads. ragent also reuses apps/api's `jobs` table (no new queue table) for ingest jobs.

Most carry `org_id` and go through `TenantRepository`. Exceptions are infrastructure tables: `Job` (internal queue) and `DemoUsage` (cross-org abuse control) deliberately sit outside tenancy. Routes use the `get_repo(Model)` dependency factory; direct `session.execute` in routes is a code smell.

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

Demo mode (phase 13): `POST /demo/login` issues a read-only JWT for the seeded `Demo Corp` org (no signup; rate-limited via slowapi). Demo is read-only everywhere except the single-run route — visitors get a small free hosted-key quota (`demo_free_runs`/IP/day, counted in `demo_usage` keyed by HMAC'd IP), then a 402 asks them to BYOK via the `X-Provider-Key` header. `GET /demo/quota` reports remaining free runs. Read-only enforced by the `require_writer` (owner/member) dependency on every mutating route.

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

Fly's `[deploy] release_command = "sh -c 'alembic upgrade head && python -m promptforge_api.seed'"` runs migrations then the idempotent demo seed on a temp machine before traffic shifts; failure aborts the deploy with old machines still serving.

**Observability:** structlog (`core/logging.py`) — JSON in prod, console at `PF_LOG_LEVEL=DEBUG`. A raw-ASGI `RequestContextMiddleware` binds a `request_id` to the log contextvars and echoes it on `X-Request-ID` (raw ASGI, not BaseHTTPMiddleware, so it doesn't buffer the SSE stream). OpenTelemetry is deferred behind a documented gated enable-point in the `main.py` lifespan.

The DSN normalizer in [`promptforge_api/core/config.py`](../apps/api/promptforge_api/core/config.py) (`Settings.async_database_url`) accepts any provider's DSN shape — bare `postgresql://`, old-style `postgres://`, with or without `sslmode` query param — and rewrites it to `postgresql+asyncpg://` with `ssl=` for asyncpg compatibility.

## Local development

```sh
docker compose -f infra/compose.yml up --wait
```

Brings up Postgres 17 + a one-shot `api-migrate` (runs `alembic upgrade head`) + the api service. See `infra/compose.yml`. Production deploy runbook: [`DEPLOY.md`](DEPLOY.md).

Populate the demo workspace with `python -m promptforge_api.seed` (idempotent — `promptforge_api/seed.py`). This is what makes `POST /demo/login` land on real content; Phase 16 runs it as part of the Fly release step.
