# PromptForge Architecture

> System overview. For the reasoning behind every choice, see [INTERVIEW-NOTES.md](INTERVIEW-NOTES.md). For the full development plan, see [../../PLAN.md](../../PLAN.md).

## System diagram

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

### apps/api (FastAPI backend)

Multi-tenant API powering prompt management, eval orchestration, and the job queue. Two processes share a single Docker image: `api` (uvicorn) and `worker` (queue consumer).

Stack: FastAPI · SQLAlchemy 2.x async · Alembic · Postgres 16 + pgvector · Pydantic v2 · python-jose (JWT HS256) · argon2-cffi · litellm · uv · ruff · mypy strict · pytest · testcontainers-postgres.

Internal modules (training-repo DNA):
- `core/prompts.py` — typed prompt templates
- `core/async_utils.py` — retry/backoff/bounded gather
- `core/queue.py` — Postgres `SKIP LOCKED` queue + `LISTEN/NOTIFY` SSE fanout

### apps/ragent (RAG + agent service)

Four corpora (`promptforge-docs`, `fastapi-docs`, `arxiv-ml-abstracts`, user-uploaded). Per-corpus embedding model (OpenAI 1536d or local bge 384d). Hybrid retrieval (vector + BM25 + RRF). Optional cross-encoder rerank. ReAct loop w/ 3 tools (`search_docs`, `fetch_passage`, `cite_sources`). Streams chat via SSE. Fetches system prompt from apps/api at runtime — real platform integration.

### apps/web (Next.js frontend)

Next.js 15 App Router · React 19 · TypeScript strict · Tailwind · shadcn/ui · Zustand (small UI stores) · openapi-typescript (API types codegen) · eventsource-parser (SSE) · monaco-editor (prompt body) · Vitest · Playwright · pnpm.

Routes: marketing landing, auth, prompts CRUD, eval suites + batches, dashboard (KPI tiles + paginated table), ragent chat, settings, public share.

## Data model

| Entity | Purpose |
|---|---|
| `User`, `Org`, `Membership` | Multi-tenant auth |
| `ApiKey`, `RefreshToken` | Machine + session credentials |
| `Prompt`, `PromptVersion`, `Run` | Prompt management + iteration |
| `EvalSuite`, `EvalCase`, `EvalBatch`, `EvalResult` | Eval orchestration + results |
| `ShareToken` | Public read-only links |
| `Job` | Queue (SKIP LOCKED) |
| `Corpus`, `Document`, `Chunk` | ragent vector store (chunks have `embedding_1536` + `embedding_384` nullable columns) |
| `Conversation`, `Message` | Chat history |

All carry `org_id`. Repository base class enforces tenancy.

## Auth flow

```
Signup → JWT access (15 min) + refresh cookie (30 days, httpOnly, SameSite=Lax)
                                  ↓
                          Refresh rotated on every refresh call
                                  ↓
                          Reuse of rotated refresh → revoke entire chain
```

Demo mode runs side-by-side: `POST /demo/login` issues a read-only JWT for the seeded `Demo Corp` org. BYOK header lets demo users run LLM calls with their own key.

## Local development

```sh
docker compose -f infra/compose.yml up --wait
```

See [DEMO.md](DEMO.md) once it lands.
