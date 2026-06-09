# PromptForge

**Multi-tenant LLM prompt-management and evaluation platform** — versioned prompts, batch evals with four judge types, live result streaming, and a RAG-agent sample app that consumes the platform's own prompts at runtime.

[![api](https://github.com/TheWerbinator/promptforge/actions/workflows/api.yml/badge.svg)](https://github.com/TheWerbinator/promptforge/actions/workflows/api.yml)
[![ragent](https://github.com/TheWerbinator/promptforge/actions/workflows/ragent.yml/badge.svg)](https://github.com/TheWerbinator/promptforge/actions/workflows/ragent.yml)
&nbsp;Python 3.11–3.12 · FastAPI · Postgres 17 + pgvector · mypy --strict · 300+ tests · ~85% coverage

**New here?** [docs/GUIDE.md](docs/GUIDE.md) explains what PromptForge does, the workflow, and what you provide to get value out of it.

---

## Try it without signing up

The API is live, with a seeded demo workspace:

- **API + interactive docs:** https://promptforge-api.fly.dev/docs
- **A shared prompt (public link, no auth):** https://promptforge-api.fly.dev/api/v1/public/share/demo-prompt-support-reply
- **A shared eval report (public link, no auth):** https://promptforge-api.fly.dev/api/v1/public/share/demo-eval-support-quality
- **Instant demo session:** `POST https://promptforge-api.fly.dev/api/v1/demo/login` → a read-only token for the demo org, plus a few free real LLM runs before you bring your own key.

> These return JSON today (the API is the finished piece). The Next.js web UI that
> renders them is in progress — see **Status** below.

## What this demonstrates

Production-shape backend engineering for AI infrastructure, with every choice
made deliberately and written down:

- **Multi-tenancy that's enforced, not hoped for** — a generic `TenantRepository[T]` scopes every query by `org_id`; cross-org access returns `404` (never `403` — existence isn't leaked). Each resource has its own tenancy contract test.
- **Real session security** — argon2id passwords, HS256 JWT access tokens, httpOnly refresh cookies with **rotation + chain-revocation replay defense**, and API keys (argon2-hashed, prefix-indexed).
- **An eval engine** — suites/cases/batches with four judges (exact, contains, regex, and an LLM-as-judge with a rubric), fanned out onto a Postgres job queue and **streamed to the client over SSE** as each case finishes.
- **One database, fewer moving parts** — the job queue is `SELECT … FOR UPDATE SKIP LOCKED`; pub/sub for the live stream is `LISTEN/NOTIFY`; vectors are pgvector. No Redis, no separate broker, no separate vector DB — each documented with the scale at which I'd change it.
- **A demo mode designed like a product** — instant read-only access to seeded data, a per-IP free-run quota on the hosted key (then BYOK), rate-limited login, and revocable public share links.
- **Operability** — structured JSON logs with a request id on every line and the `X-Request-ID` response header, idempotent demo seeding wired into the deploy release step, zero-downtime migrations, and CI that gates lint + `mypy --strict` + the full test suite + coverage before it deploys.
- **A RAG agent that consumes the platform** (`apps/ragent`) — hybrid retrieval (pgvector + BM25 + RRF), a ReAct loop with citations and safety rails, and its system prompt **fetched live from the API** so a managed prompt drives the agent. Shares the platform's Postgres + `SKIP LOCKED` queue; demo turns are bounded by per-IP **and global** daily caps. See [apps/ragent/README.md](apps/ragent/README.md).

The reasoning behind each of these (and ~35 more decisions, with the alternatives
I rejected and when I'd revisit) lives in **[docs/DECISIONS.md](docs/DECISIONS.md)** — it's the most useful file in the repo.

## Architecture

```
 Next.js (web)  ──REST + SSE──▶  FastAPI (api)  ──enqueue──▶  Postgres queue  ──▶  worker
                                      │  litellm                (SKIP LOCKED          │
                                      ▼                          + LISTEN/NOTIFY)     ▼
                              OpenAI / Anthropic            Postgres 17 + pgvector ◀──┘
                                                                  ▲
   RAG-agent (ragent) ──fetches its system prompt from the api at runtime──┘
```

Full diagram and component breakdown: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**. Deploy runbook: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## Tech stack

| Area | Choice |
|---|---|
| API | FastAPI · SQLAlchemy 2 async · Pydantic v2 · Alembic |
| Data | Postgres 17 + pgvector (Neon) |
| Auth | python-jose (JWT HS256) · argon2-cffi · httpOnly refresh cookies |
| LLM | litellm (multi-provider, cost + retry normalization) |
| Async infra | Postgres `SKIP LOCKED` queue · `LISTEN/NOTIFY` → SSE · slowapi rate limiting |
| Observability | structlog (JSON in prod) · request-id middleware |
| Tooling | uv · ruff · mypy --strict · pytest + testcontainers |
| Deploy | Fly.io (api + worker) · GitHub Actions CI/CD |

## Repo layout

```
apps/
├── api/      FastAPI backend — auth, prompts, versions, runs, evals, queue, demo, shares
├── web/      Next.js 16 frontend — App Router, BFF auth, dark by default    (in progress)
└── ragent/   RAG-agent service — hybrid retrieval, ReAct loop, SSE chat     (feature-complete)
docs/         ARCHITECTURE · DECISIONS · DEPLOY · DEPLOY-RAGENT
infra/        docker compose for the full local stack
```

## Local development

```sh
docker compose -f infra/compose.yml up --wait   # Postgres + api + worker
```

Or just the API, with [uv](https://docs.astral.sh/uv/):

```sh
cd apps/api
uv sync --all-extras
uv run uvicorn promptforge_api.main:app --reload --port 8000   # docs at /docs
python -m promptforge_api.seed                                 # optional: demo data
```

Quality bar (matches CI):

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict promptforge_api
uv run pytest --cov          # full suite needs Docker (testcontainers Postgres)
```

## Status

- **apps/api** — feature-complete and deployed. Auth, multi-tenancy, prompts + versioning, runs, the eval engine + SSE, demo mode, public shares, seed, CI/CD.
- **apps/ragent** — feature-complete (hybrid retrieval, ReAct agent + citations, SSE chat, live system-prompt fetch, async ingestion, demo cost caps). CI runs the full suite; `fly deploy` + prod smoke pending.
- **apps/web** — Next.js 16 frontend, in progress (auth, prompts, evals + live SSE, dashboard done; ragent chat UI next).

## License

MIT — see [LICENSE](LICENSE).
