# promptforge-ragent

RAG + **ReAct agent** service for PromptForge. Answers questions over document
corpora with **hybrid retrieval** and inline **citations**, and consumes its own
system prompt from the platform's API at runtime — so editing the prompt in
PromptForge changes the agent's behavior, no redeploy.

**Live:** https://promptforge-ragent.fly.dev *(deploy + smoke pending — see
[../../docs/DEPLOY-RAGENT.md](../../docs/DEPLOY-RAGENT.md))*

## What this demonstrates

Production-shape RAG/agent engineering on top of the same platform DB as apps/api,
every choice written down in [../../docs/DECISIONS.md](../../docs/DECISIONS.md):

- **Hybrid retrieval, not just vectors** — pgvector cosine (dense) **+** BM25
  (sparse, in-process) fused with **Reciprocal Rank Fusion**. RRF combines on rank
  alone, so there's nothing to calibrate between cosine and BM25 scales; a test
  pins the payoff — a keyword-matching passage that's semantically *far* from the
  query still surfaces, which pure dense retrieval can't do.
- **A ReAct agent with safety rails** — litellm function-calling over three tools
  (`search_docs` / `fetch_passage` / `cite_sources`), bounded by a max-iteration
  cap **and** a circuit breaker on repeated identical tool calls; when either
  fires it forces a clean final answer instead of looping. Answers are grounded:
  the model declares its sources and they become the message's citations.
- **Real platform integration** — the agent fetches its system prompt *live from
  apps/api* (discovered from the shared DB by name, body fetched over HTTP with a
  service JWT minted from the shared secret), with a built-in fallback so a managed
  prompt can never take the agent down.
- **One database, shared cleanly** — ragent **owns its domain models** (corpora,
  documents, chunks, conversations, messages) but apps/api **owns the single
  migration history**; ingestion runs async on apps/api's `SELECT … FOR UPDATE
  SKIP LOCKED` queue (one table, two consumers filtered by `kind`).
- **A demo designed for cost** — free hosted-key agent turns then BYOK, bounded by
  a per-IP **and a global** daily cap. The global cap is the real backstop against
  IP/VPN rotation (reliable VPN detection is a paid arms race; a global ceiling
  makes rotation pointless).
- **Right-sized heavy deps** — per-corpus embedding routing (OpenAI 1536-d *or*
  local bge-small 384-d) and an optional cross-encoder reranker live behind
  **opt-in extras**, off by default, so the demo image never carries torch.

## Endpoints

| Route | What |
|---|---|
| `POST /api/v1/chat` | One agent turn, **streamed over SSE** (tool-call chips → answer → citations); BYOK via `X-Provider-Key` |
| `GET/POST /api/v1/corpora` | List / create corpora (writes writer-gated) |
| `POST/GET /api/v1/corpora/{id}/documents` | Upload a document (→ async ingest) / list with ingest status |
| `GET /health` | Liveness |

## Architecture

```
 client ──REST + SSE──▶  ragent (FastAPI)
                            │  ├─ hybrid_search: pgvector cosine + BM25 → RRF
                            │  ├─ ReAct loop (litellm tools) → cited answer
                            │  └─ system prompt fetched live from apps/api
                            ▼
            Postgres 17 + pgvector (shared with apps/api)
                            ▲   └─ ingest jobs on the shared SKIP LOCKED queue
            ingest-worker ──┘      (parse → chunk → embed → persist)
```

Full breakdown: [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md).

## Tech stack

| Area | Choice |
|---|---|
| Service | FastAPI · SSE (`sse-starlette`) · SQLAlchemy 2 async |
| Retrieval | pgvector (dense) · `rank-bm25` (sparse) · RRF fusion |
| Agent | litellm function-calling (ReAct) · 3 tools + circuit breaker |
| Embeddings | OpenAI `text-embedding-3-small` (1536-d) · local `bge-small-en-v1.5` (384-d, opt-in) |
| Parsing | `markdown-it-py` · `pypdf` · `selectolax` · tiktoken chunking |
| Infra | shared Postgres `SKIP LOCKED` queue · structlog · uv · ruff · mypy --strict |
| Deploy | Fly.io (web + ingest-worker) · GitHub Actions CI/CD |

## Quick start (local)

Needs the shared Postgres (apps/api seeds Demo Corp + the agent's system prompt):

```sh
uv sync --extra dev
cp .env.example .env   # PF_DATABASE_URL + PF_JWT_SECRET must match apps/api
uv run uvicorn promptforge_ragent.main:app --reload --port 8001
python -m promptforge_ragent.seed   # one-time: seed the 3 demo corpora (real ingest)
```

## Development

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict promptforge_ragent
uv run pytest -m "not integration and not e2e"   # unit only (no Docker)
uv run pytest                                     # full suite (testcontainers pgvector)
```

The heavy local models are opt-in extras (`uv sync --extra rerank` /
`--extra local-embeddings`); CI and the default image install neither.

## Docs

- **[../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)** — system shape.
- **[../../docs/DECISIONS.md](../../docs/DECISIONS.md)** — the "why" behind every choice.
- **[../../docs/DEPLOY-RAGENT.md](../../docs/DEPLOY-RAGENT.md)** — deploy + smoke runbook.
