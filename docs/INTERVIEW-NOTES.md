# INTERVIEW-NOTES

> Defendable answers for every architectural choice in PromptForge. Read this before any AI Engineer interview. Each block is a 2-3 sentence quote you can use directly.

---

## Why FastAPI over Django?

Async-first matches LLM call patterns (concurrent evals on 50+ cases). Pydantic-native — same schemas as OpenAI/Anthropic SDKs use, no translation. Industry default for AI infra in 2026: LangServe, LiteLLM, BentoML, vLLM all ship FastAPI examples. Django's killer feature is the admin and forms — neither relevant to an API-first AI app.

## Why JWT HS256 over RS256?

Single-service deployment — no key-distribution problem. HS256 is faster and simpler. RS256 would matter if multiple services needed to verify tokens issued elsewhere; not the case here. Documented; would migrate if architecture demands.

## Why argon2 over bcrypt?

OWASP 2024 recommendation. argon2id provides memory-hardness against GPU attacks that bcrypt doesn't. The `argon2-cffi` library is the standard Python binding.

## Why Postgres + pgvector instead of a separate vector DB?

One database simpler than two. Our scale ceiling is ~10k chunks demo, ~100k personal corpora — pgvector ANN indexes (ivfflat/hnsw) handle that well below the point where Pinecone/Qdrant become necessary. If the platform grew past ~1M chunks I'd evaluate moving the vector tier; until then, fewer moving parts wins.

## Why Postgres SKIP LOCKED queue instead of Redis/RQ?

Same one-DB principle. SKIP LOCKED is the production-shape pattern for moderate throughput (used by GraphileWorker, river queue, et al.). For higher throughput I'd consider Redis+RQ for FIFO simplicity. The SQLite-embedded version I considered would add a second storage system without benefit on Fly.

## Why TenantRepository pattern instead of row-level security?

RLS in Postgres is elegant but couples enforcement to the DB role. With async SQLAlchemy + connection pooling, switching session roles per request adds friction and surprises. Repository pattern keeps enforcement in code where it's testable and visible. The tenancy test class enforces the contract.

## Why litellm instead of provider SDKs directly?

Multi-provider with one client. Cost tracking, retries, function-calling normalization out of the box. Switching from gpt-4o-mini to claude-haiku-4-5 is a string change, not a refactor. Used widely in AI infra (LangServe, hosted gateways).

## Why refresh tokens despite portfolio scope?

OWASP best practice for session management. Demonstrates rotation + chain revocation thinking — when a rotated refresh token is replayed, the entire chain is revoked. This is the senior signal: most portfolios skip refresh entirely, then can't answer "how do you handle session compromise?"

## Why Postgres LISTEN/NOTIFY for SSE fanout?

One-DB principle. Multiple worker processes publish; api processes subscribe. NOTIFY payload caps at 8KB → only send small status events, full data fetched via subsequent GET. Documented limit; would migrate to Redis pub/sub if subscriber count >1k or payload needs exceeded 8KB.

## Why custom queue module instead of Celery / Dramatiq / RQ?

Celery is overkill for ~hundreds of eval jobs and brings broker requirement. Dramatiq and RQ require Redis. We have one Postgres; SKIP LOCKED + a 200-line module is honest and removes a hosting dependency. If we needed scheduling, priorities, or 10k+ jobs/s I'd swap to dramatiq/RQ.

## Why SSE instead of WebSockets for eval streaming?

One-way server→client is sufficient (clients only receive eval-completion events). SSE works over plain HTTP, traverses proxies cleanly, browser support is universal, no separate handshake. WebSockets would be overkill and add reconnection complexity.

## Why hybrid retrieval (vector + BM25) instead of pure vector?

Pure dense retrieval underperforms on lexical-heavy queries — proper nouns, exact function names, code snippets, error messages. BM25 covers that gap. RRF fusion needs no normalization between dense and sparse scores. This combo is the production-shape RAG pattern (used by Vespa, Weaviate hybrid, Elasticsearch ELSER).

## Why RRF instead of weighted score fusion?

RRF (k=60) is robust to score-scale differences between retrievers — no need to calibrate BM25 vs cosine similarity. Performs comparably to or better than linear combination in benchmarks (Cormack et al.).

## Why pgvector ivfflat over hnsw?

ivfflat with 100 lists is sufficient at our scale and rebuilds faster. hnsw is better for higher recall at scale but adds build/insert cost we don't need. Documented switch criterion: when corpus exceeds 100k chunks.

## Why per-corpus embedding model?

Demonstrates flexibility without coupling indices. Variable-dim pgvector exists but separate columns are cleaner for index management. If we added a third model, we'd extract to a `chunk_embeddings` table with `(chunk_id, model, vector)` rows.

## Why ReAct loop over a more sophisticated planner?

ReAct is the most-supported function-calling pattern in LiteLLM / OpenAI / Anthropic SDKs. It's transparent (every step is a tool call you can log/replay), and circuit breakers + max-iter caps make it safe. Planners (Plan-and-Execute, ReWOO, tree search) are higher-ceiling but lower-floor — easy to overfit a benchmark and fragile in production.

## Why fetch system prompt from apps/api at runtime?

Demonstrates the platform integration story: prompts are managed in the platform, agent consumes them. Editing the prompt in PromptForge UI changes ragent behavior on next request — a real product feature, not a demo gimmick. Cached 60s to bound api load.

## Why shared HS256 secret between api and ragent?

Two services under same control + same deploy unit = HS256 shared secret is fine. The alternative — opaque tokens validated via api round-trip — adds latency on every request. If a third service joined or services were operated by different teams, RS256 + JWKS at apps/api would be the move.

## Why Next.js 15 App Router over Pages Router?

RSC + Server Actions remove a ton of client-state ceremony. Data fetches happen on the server, types stay shared with server code, mutations don't need separate API routes. Prior Pages Router experience; App Router took ~1 week to internalize and now is the better pick for new builds.

## Why no TanStack Query?

RSC + Server Actions handle server state for the patterns I have: read-on-render, mutate-via-action, refresh-on-action. TanStack Query is the right answer if I had client-side optimistic updates across many entities, heavy cache invalidation logic, or paginated infinite scroll. I don't here. Less surface area = fewer bugs.

## Why Zustand over Context + useReducer?

Zustand is ~1KB and avoids the Context-rerender-everything problem. The two stores I have (dashboard filter, UI shell) are accessed from many components; Context would require splitting providers to avoid cascade rerenders, which is itself ceremony. Zustand's selector pattern handles this for free.

## Why httpOnly cookie for refresh, in-memory for access?

Best balance per OWASP recommendations. Refresh cookie httpOnly = not readable by JS = XSS can't steal it. Access in memory = lost on page reload (intentional; refresh restores it) = no persistent XSS attack surface for the long-lived credential. The 15-min access TTL bounds damage if access token is stolen via in-page XSS.

## Why openapi-typescript over orval / Kiota?

Generates types only, not runtime code. Smaller bundle. My fetch wrapper is ~80 lines of code I can read and explain — vs adopting orval's hooks API which would hide auth + refresh logic behind abstraction. Right-size tool for the contract.

## Why monorepo over separate api/web/ragent repos?

One CI, one issue tracker, one PR can change both contract and consumer. The repo is small enough (3 apps) that the monorepo penalty (slower CI, harder partial clones) doesn't bite. If the platform grew teams, splitting would make sense.

## Why uv?

Astral's uv replaces pip + pip-tools + virtualenv in one fast Rust binary. Industry adoption accelerated through 2025. Lock file format is straightforward, resolution is fast enough to feel free in CI. Poetry works but is slower and brings opinions I don't need.

## Why path-filtered CI workflows?

A web-only change shouldn't run api tests and vice versa. CI minutes saved + faster PR feedback. Standard monorepo hygiene; matches turborepo/nx patterns even though we don't use them.

## Why dark mode default with no toggle?

Demo UX: looks better in screenshots and on hiring teams' likely-dark IDEs. Toggle is a feature I'd add if real users requested. Senior signal is "make decisions; defer features without users to ask."
