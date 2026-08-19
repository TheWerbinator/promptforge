# PromptForge — Consolidated Plan


## 0. Constraints

**Constraints (locked):**
- Python on the backend (FastAPI). No Node or Java in new backend code.
- No PyPI publishing — library-shaped code stays as internal modules.
- Every architectural choice must be explainable in 2-3 lines.
- Hosting: Fly.io (backends/DB) + Vercel (frontend).
- One GitHub repo, three apps inside.

---

## 1. Unified Architecture

Single repo: `promptforge`. Three apps in a monorepo. Multi-tenant + demo mode. Each app deployed independently.

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

**Demo + multi-tenant flow runs simultaneously.** Visitors hit "Try demo" for instant read-only access to seeded `Demo Corp`; signup creates own org w/ full isolation.

---

## 2. Repo Layout (target end state)

```
promptforge/
├── apps/
│   ├── api/                      # FastAPI backend
│   ├── web/                      # Next.js frontend
│   └── ragent/                   # RAG + agent FastAPI service
├── docs/
│   ├── ARCHITECTURE.md           # this doc (expanded)
│   ├── DECISIONS.md        # cheat sheet, every "Why" pre-written
│   └── DEMO.md                   # local-dev + demo-URL walkthrough
├── infra/
│   └── compose.yml               # local dev: postgres + api + worker + ragent + web
├── .github/workflows/
│   ├── api.yml
│   ├── ragent.yml
│   ├── web.yml
│   └── deploy.yml
├── .gitignore
├── README.md
└── LICENSE                       # MIT
```

---

## 3. Tech Stack Summary

### apps/api (FastAPI backend)

| Layer | Choice |
|---|---|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.x async + Alembic |
| DB | Postgres 16 + pgvector |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | python-jose (JWT HS256) + argon2-cffi + httpOnly refresh cookies |
| LLM client | litellm |
| Queue | Postgres `SELECT FOR UPDATE SKIP LOCKED` |
| Pub/sub | Postgres `LISTEN/NOTIFY` for SSE fanout |
| Pkg/build | uv + hatchling |
| Lint/type | ruff + mypy --strict |
| Tests | pytest + pytest-asyncio + httpx + testcontainers-postgres + hypothesis |
| Logs | structlog |

### apps/ragent (RAG + agent)

| Layer | Choice |
|---|---|
| Framework | FastAPI + SSE |
| Vector store | pgvector (shared Postgres) |
| BM25 | `rank-bm25` in-process |
| Embeddings (per-corpus) | OpenAI `text-embedding-3-small` (1536d) OR local `bge-small-en-v1.5` (384d) |
| Reranker (optional) | `bge-reranker-base` via sentence-transformers, config-flagged |
| LLM tool-use | litellm function-calling |
| Parsers | `markdown-it-py`, `pypdf`, `selectolax` |

### apps/web (Next.js frontend)

| Layer | Choice |
|---|---|
| Framework | Next.js 16 App Router + React 19 (was planned as 15; ecosystem moved by build time) |
| Types | TypeScript strict + `openapi-typescript` codegen |
| Styling | Tailwind + shadcn/ui (dark default) |
| State | Server Components + Server Actions + Zustand (small UI stores) |
| Forms | react-hook-form + Zod |
| SSE | `eventsource-parser` over fetch streams |
| Editor | `monaco-editor` (lazy-loaded) |
| Tests | Vitest + Playwright |
| Pkg | npm (was pnpm; single JS app — no JS monorepo — so pnpm's workspace edge doesn't apply) |

### Deploy

| App | Target |
|---|---|
| apps/api | Fly.io (2 processes: api + worker), Fly Postgres |
| apps/ragent | Fly.io (2 processes: web + ingest-worker), shared Postgres |
| apps/web | Vercel (Next.js native) |
| Local dev | `docker compose up` brings full stack |

---

## 4. apps/api — Deep Plan Summary

### Scope (MVP)
- Email/password signup → org auto-created → JWT access (15min) + refresh cookie (30d) w/ rotation + chain-revocation replay defense
- API keys (one-time view, argon2 hashed)
- Demo mode (`POST /demo/login`, read-only role, BYOK header for LLM)
- Prompts CRUD + immutable versions w/ typed variables
- Single runs w/ cost tracking
- Eval suites w/ 4 judge types (exact, contains, regex, llm_judge); batch runs queued + SSE-streamed
- Public share tokens

### Data model
`User`, `Org`, `Membership`, `ApiKey`, `RefreshToken`, `Prompt`, `PromptVersion`, `Run`, `EvalSuite`, `EvalCase`, `EvalBatch`, `EvalResult`, `ShareToken`, `Job` (queue). All carry `org_id`. Repository base class enforces tenancy; cross-org access returns 404.

### Internal modules
- `core/config.py` — pydantic-settings (no separate envguard)
- `core/security.py` — JWT, argon2, API key hashing, refresh rotation
- `core/db.py` — async SQLAlchemy session
- `core/deps.py` — FastAPI dependencies (`get_principal`, `require_role`, `get_repo`)
- `core/prompts.py` — typed prompt templates w/ applicative validation + composition
- `core/async_utils.py` — retry, rate_limited, gather_bounded
- `core/queue.py` — Postgres `SKIP LOCKED` queue + `LISTEN/NOTIFY`

### Phases (~11d focused work)
1. Bootstrap (0.5d) — repo init, pyproject, hello world, Dockerfile, CI skeleton, /health
2. DB + Alembic (0.5d)
3. Auth + refresh tokens (1.5d)
4. Multi-tenancy + repo base (0.5d)
5. Prompts + versions (1d)
6. core/prompts.py (0.5d)
7. core/async_utils.py (0.5d)
8. core/queue.py + LISTEN/NOTIFY + worker (1.5d)
9. services/llm.py (0.5d)
10. Runs (0.5d)
11. Eval engine (judges, batches, SSE) (1.5d)
12. Eval e2e (0.5d)
13. Demo mode (0.5d)
14. Public share (0.25d)
15. Seed (0.5d)
16. Deploy + smoke (0.5d)
17. README + DECISIONS (0.5d)

### Acceptance criteria
- All endpoints live, OpenAPI at `/docs`, `/health` 200
- Signup → JWT, refresh works, demo mode read-only enforced
- Eval batch e2e: queue → worker → SSE events → completion
- CI green: ruff + ruff format + mypy --strict + alembic + pytest w/ ≥85% project / ≥90% core / ≥80% repositories coverage
- Cross-org 404s tested per resource
- DECISIONS complete

---

## 5. apps/ragent — Deep Plan Summary

### Scope (MVP)
- 4 corpora: `promptforge-docs` (self-referential), `fastapi-docs`, `arxiv-ml-abstracts` subset (3 seeded) + `user-uploaded` (per-org)
- Per-corpus embedding model: OpenAI `text-embedding-3-small` (1536d) OR local `bge-small-en-v1.5` (384d)
- Hybrid retrieval: pgvector cosine + BM25 + RRF fusion
- Optional cross-encoder reranker (config-flagged)
- ReAct agent loop, max 6 iterations, 3 tools: `search_docs`, `fetch_passage`, `cite_sources`
- Streaming chat via SSE w/ inline citations + tool-call chips
- User PDF/MD upload (5MB/file, 50MB/corpus caps)
- System prompt fetched live from apps/api by id (cached 60s)

### Data additions
`Corpus`, `Document`, `Chunk` (w/ `embedding_1536` + `embedding_384` nullable columns + ivfflat partial indexes), `Conversation`, `Message`. Migrations owned by `apps/api/alembic/` (single migration history).

### Phases (~8.75d focused work)
1. Bootstrap (0.5d)
2. DB models (0.5d)
3. Ingest pipeline (1.5d)
4. Ingest worker (0.5d)
5. Hybrid retrieval (1d)
6. Optional rerank (0.5d)
7. Agent tools (0.5d)
8. Agent loop (1d)
9. Chat SSE (0.5d)
10. Corpora API + upload (0.5d + 0.25d caps)
11. Seed scripts (1d)
12. Per-corpus embedding routing (0.5d)
13. Deploy + smoke (0.5d)
14. README + DECISIONS (0.5d)

### Acceptance criteria
- All 4 corpora work for demo user; user upload tested
- Agent answers cite chunks; click → drawer w/ source
- System prompt fetched from apps/api (live update demonstrable)
- CI green w/ coverage ≥80%
- Cross-org tenancy tests pass for corpora + conversations

---

## 6. apps/web — Deep Plan Summary

### Scope (MVP)
- Marketing landing w/ "Try demo" CTA (no signup wall)
- Auth (signup, login, logout) w/ refresh-token rotation
- Prompts: list / create / detail / patch / delete; versions: list / create / detail w/ Monaco editor
- Single run runner: pick version + fill variables + pick model
- Eval suites: create / list / cases editor; batch detail w/ SSE live progress
- Dashboard: 4 KPI tiles + paginated runs table w/ multi-column filter/sort
- ragent chat page: corpus picker, SSE streaming, citation popovers, tool-call chips, upload dropzone
- Settings: profile, API keys CRUD, BYOK input
- Public share `/share/[token]`

### Routes
See full route tree in `docs/ARCHITECTURE.md`. App Router conventions; (app)/* gated by middleware.

### State management
- Server Components for data fetching
- Server Actions for mutations
- Zustand for dashboard filter + UI shell (~2 small stores)
- React context for access token (in-memory)
- No TanStack Query (defendable: RSC handles server state for our patterns)

### Phases (~12d focused work)
1. Bootstrap (0.5d)
2. Auth shell (1d)
3. Layout + sidebar (0.5d)
4. Landing + Try Demo (0.5d)
5. API client + types codegen + SSE client (0.5d)
6. Prompts pages (1.5d)
7. Evals pages (1.5d)
8. Dashboard (1d)
9. ragent chat (1.5d)
10. ragent upload (0.5d)
11. Settings + API keys (0.5d)
12. Public share (0.25d)
13. Playwright E2E suite — 6 specs (1.5d)
14. Visual polish (0.5d)
15. Deploy + smoke (0.5d)
16. README + DECISIONS (0.5d)

### Acceptance criteria
- Lighthouse perf ≥85 on landing
- All routes implemented + responsive ≥768px
- "Try demo" instant access, no signup wall
- Auth refresh silent + replay-defended
- ragent chat streams + citations work
- Dashboard filter URL-synced
- 6 Playwright specs green
- CI green: lint + typecheck + unit + build + OpenAPI contract drift check

---

## 7. Effort & Sequencing

### Total focused work
- apps/api: ~11d
- apps/ragent: ~8.75d
- apps/web: ~12d
- Integration + polish (root README, demo seed validation, end-to-end smoke): ~2-3d
- **Total: ~34-35d**

### Implementation order
1. apps/api (foundation; ragent depends on it for prompt source; web depends on it for everything)
2. apps/ragent (depends on api running; can stub during early dev)
3. apps/web (consumes both stable backends)

Within each app, follow the phase list in that app's section. Land MVPs progressively — api live before ragent finishes; ragent live before web polish completes.

---

## 8. Risks & Mitigations (consolidated)

| Risk | Mitigation |
|---|---|
| Scope (~34d real time) | Phase deployments; land MVPs of each app progressively |
| LLM cost on demo | BYOK mode for demo user; rate-limit `/demo/login`; cap per-IP run count |
| Cross-org leaks | TenantRepository base class + dedicated tenancy test per resource |
| Worker / queue scaling | Postgres SKIP LOCKED holds to ~hundreds of jobs/s; Redis+RQ documented as next step |
| SSE through Fly/Vercel proxies | `Cache-Control: no-cache`, `X-Accel-Buffering: no`, chunked transfer; tested in deploy smoke |
| Agent runaway/cost | Max iters cap, circuit breaker on repeated tool+args, BYOK + per-IP rate limit |
| Auth refresh race | Single-flight refresh promise in interceptor; concurrent 401s await same refresh |
| OpenAPI/web contract drift | CI check compares committed `apps/web/openapi.json` snapshot against fresh generation from apps/api |
| testcontainers flakiness | Session-scoped container; pinned `postgres:16-alpine`; truncate between tests |
| Framework choices drifting past what's explainable | DECISIONS written alongside the code; stick to well-trodden App Router patterns |

---

## 9. DECISIONS.md — Decisions Index

Living document at `docs/DECISIONS.md` in the repo. Every "Why" recorded for posterity. Categories:

- **Why FastAPI over Django** — async-first, Pydantic-native, AI infra default
- **Why JWT HS256 over RS256** — single-service deployment
- **Why argon2 over bcrypt** — OWASP 2024 memory-hardness recommendation
- **Why Postgres + pgvector instead of separate vector DB** — one DB; ANN sufficient at our scale
- **Why Postgres SKIP LOCKED queue** — one DB; production-shape; SQLite considered, rejected
- **Why TenantRepository over RLS** — testable, visible in code, pool-friendly
- **Why litellm** — multi-provider; cost+retry+function-call normalization
- **Why refresh tokens MVP** — OWASP best practice; rotation + chain revocation answers session compromise
- **Why PG LISTEN/NOTIFY for SSE** — one DB; multi-process fanout w/o Redis
- **Why ReAct loop** — transparent, well-supported, safe w/ caps + circuit breaker
- **Why hybrid retrieval (vector + BM25 + RRF)** — covers lexical gap; RRF needs no calibration
- **Why pgvector ivfflat over hnsw** — sufficient at scale; faster build/insert
- **Why per-corpus embedding model** — flexibility w/o coupled indices; documented scale-out
- **Why fetch system prompt from apps/api at runtime** — real platform integration story
- **Why shared HS256 secret between api and ragent** — two services, same control; RS256 if teams diverge
- **Why Next.js App Router** — prior experience; RSC reduces client-state surface
- **Why no TanStack Query** — RSC + Server Actions sufficient for our patterns
- **Why Zustand** — tiny, explicit, right-size for 2-3 UI stores
- **Why httpOnly refresh cookie + in-memory access** — OWASP recommended balance
- **Why openapi-typescript over orval/Kiota** — types only, smaller bundle, auditable client
- **Why monorepo over split repos** — small enough; one CI; one PR can change contract + consumer
- **Why uv** — modern Python tooling; replacing poetry/pip-tools
- **Why dark mode default no toggle** — screenshots; toggle is feature without users to ask

---

## 10. What's Locked vs. Open

### Locked
- Single GitHub repo `promptforge`, three apps in a monorepo
- Three apps: api (FastAPI), web (Next.js 15), ragent (FastAPI + RAG agent)
- Multi-tenant + demo mode side-by-side
- Refresh-token rotation; PG LISTEN/NOTIFY SSE; per-corpus embeddings; 5MB/50MB upload caps
- All 4 corpora (3 seeded + user-uploadable)
- Fly.io + Vercel deploys

### Open (deferred)
- Custom domain choice (Vercel free domain fine MVP)
- Webhooks, audit log, password reset (post-MVP roadmap in README)

---

## 11. Build Order

1. **apps/api Phase 1** — repo init, pyproject, FastAPI hello world, Dockerfile, fly.toml, CI skeleton, /health.
2. **apps/api Phase 2** — DB + Alembic + first migration + testcontainers fixture.
3. Continue the apps/api phase list sequentially, then apps/ragent, then apps/web.

---

## 12. References

- This plan is the design blueprint. `DECISIONS.md` records why each choice was made; `ARCHITECTURE.md` describes what was actually built.
