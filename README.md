# PromptForge

**Multi-tenant LLM prompt-management and evaluation platform** — versioned prompts, batch evals with four judge types, live result streaming, and a RAG-agent sample app that consumes the platform's own prompts at runtime.

[![api](https://github.com/TheWerbinator/promptforge/actions/workflows/api.yml/badge.svg)](https://github.com/TheWerbinator/promptforge/actions/workflows/api.yml)
[![ragent](https://github.com/TheWerbinator/promptforge/actions/workflows/ragent.yml/badge.svg)](https://github.com/TheWerbinator/promptforge/actions/workflows/ragent.yml)
[![web](https://github.com/TheWerbinator/promptforge/actions/workflows/web.yml/badge.svg)](https://github.com/TheWerbinator/promptforge/actions/workflows/web.yml)
&nbsp;Python 3.11–3.12 · FastAPI · Next.js 16 · Postgres 17 + pgvector · mypy --strict · 300+ tests · ~85% coverage

**New here?** [docs/GUIDE.md](docs/GUIDE.md) explains what PromptForge does, the workflow, and what you provide to get value out of it.

---

## Try it without signing up

Everything's live, with a seeded demo workspace:

- **Web app — start here:** https://thewerbinator-promptforge.vercel.app → click **Try the demo** for instant read-only access (prompts, eval reports, and the RAG-agent chat), no signup.
- **API + interactive docs:** https://promptforge-api.fly.dev/docs
- **A shared prompt (public link, no auth):** https://promptforge-api.fly.dev/api/v1/public/share/demo-prompt-support-reply
- **A shared eval report (public link, no auth):** https://promptforge-api.fly.dev/api/v1/public/share/demo-eval-support-quality

> The backends auto-stop when idle, so the first request after a while may
> cold-start (~45 s) before the demo is responsive.

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
- **A frontend with a real BFF** (`apps/web`) — the browser only talks to the Next origin; route handlers proxy to *both* backends and the session is a **JWE-sealed httpOnly cookie**, so no API token ever reaches the browser. Eval batches and agent chat stream as real SSE through the proxy; the public share pages are static server components. Tested end-to-end with **Playwright + in-process MSW** — the real BFF runs against a faked upstream, no live backend. See [apps/web/README.md](apps/web/README.md).

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
├── web/      Next.js 16 frontend — App Router, BFF auth, SSE, dark by default  (deployed)
└── ragent/   RAG-agent service — hybrid retrieval, ReAct loop, SSE chat        (deployed)
docs/         ARCHITECTURE · DECISIONS · DEPLOY · DEPLOY-RAGENT · DEPLOY-WEB
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
- **apps/ragent** — feature-complete and deployed (hybrid retrieval, ReAct agent + citations, SSE chat, live system-prompt fetch, async ingestion, demo cost caps).
- **apps/web** — feature-complete and deployed on Vercel. BFF auth (JWE session), prompts + versioning, the eval engine with live SSE, RAG-agent chat, corpora + upload, settings (API keys + BYOK), public share pages, and a Playwright + MSW E2E suite.

## License

MIT — see [LICENSE](LICENSE).
