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

---

# Phase 5 — Prompts + versions CRUD

## Why append-only versions instead of mutating a single body?

Every Run row points at a specific PromptVersion, so the exact bytes that produced any historical output stay reproducible forever. Mutating in place would make eval comparisons across "v1 of the summarizer" vs "v2" meaningless because v1 would no longer exist. Append-only is also the auditing story: who changed what, when. The unique(prompt_id, version) constraint enforces sequential integers per prompt.

## Why visibility filtering at the route layer, not in the repository?

TenantRepository's invariant is `org_id` scope only. Visibility is a per-resource concept that doesn't generalize — adding it to the base class would couple the repo to every model's visibility column. Routes layer it on via the `where` kwarg I added to `list()`. Same enforcement pattern, but visible at the call site where it's defensible.

## Why 404 on PRIVATE prompts the user doesn't own, not 403?

Same reason as cross-org access: 403 leaks existence ("there is a thing here, you just can't see it"). 404 says nothing about whether the prompt exists. Consistent leak-protection across all tenancy + visibility paths.

## Why `next_version_number` is max+1 in Python, not a sequence?

Simplicity. The unique(prompt_id, version) constraint catches the rare race; on conflict we 409 and the client retries. A per-prompt Postgres sequence would be cleaner but adds DDL complexity for a write pattern that's already low-frequency (humans editing prompts, not machines). TODO tagged (`phase-5+`) to collapse compute + insert into one statement when it matters.

## Why `where` kwarg on TenantRepository.list/count instead of subclassing?

I considered PromptRepository extending the base, but it would have been ~20 lines of glue around what's really just "compose another filter after the org scope." The `where` kwarg is applied AFTER the mandatory org_id filter, so callers can narrow but can't widen tenant scope. Documented in the docstring.

# Phase 6 — `core/prompts.py` typed templates

## Why applicative (collect-all) validation instead of fail-fast?

Fail-fast UX is hostile: user submits a form with 3 mistakes, gets told about #1, fixes it, submits again, gets told about #2, etc. Three round-trips. Applicative validation returns all 3 in one response. Pattern is canonical in functional-programming literature (Validation applicative vs Either monad). The module docstring calls this out explicitly because it's the literal lesson from the applicative-practice training repo.

## Why reject undeclared body variables at construction time?

A `{{name}}` in the body that has no declared spec means render() will fail unpredictably at the worst moment (when an LLM call is about to happen). Catching it at template construction means errors land where the user is editing, not where the platform is executing. The construction-time check makes invalid templates unrepresentable beyond that line.

## Why bool excluded from int/float type checks?

`isinstance(True, int)` is True in Python — bool is a subclass of int. Without an explicit exclusion, `n=True` would pass a `type="int"` check, and render would substitute "True" into the body. That's almost never what the user meant. Honest type validation rejects it.

## Why fingerprint with sorted variable list?

Two templates differing only in declaration order should be identical for caching purposes. Sorting by name before hashing makes the fingerprint a true content hash, not a representation hash. Uses canonical JSON (sort_keys=True, no whitespace) for the same reason.

# Phase 7 — `core/async_utils.py`

## Why retry / rate-limit / gather as internal modules, not tenacity + aiolimiter?

Three reasons. (1) Combined size is ~100 lines — adopting two deps for that surface area is the wrong trade. (2) This module is the async-orchestration showcase of the repo per the training-repo absorption story; importing tenacity hides the muscle. (3) Pinning + tracking two more deps' CVEs is real maintenance cost for portfolio scope. I'd adopt tenacity the moment retry policies grew into per-exception strategies or stop conditions.

## Why equal jitter instead of full jitter or no jitter?

Equal jitter (`delay/2 + random.uniform(0, delay/2)`) guarantees a nonzero minimum wait while still spreading the herd. Full jitter (`random.uniform(0, delay)`) can collapse to zero, which makes thundering-herd worse on the first retry. No jitter synchronizes failures across callers (every retry happens at the same instant). The AWS architecture blog post on backoff covers this well; equal jitter is their middle-ground recommendation.

## Why TokenBucket takes injectable clock/sleep?

So the pacing logic is unit-testable with a fake clock that advances by `sleep(d)` calls — no real wall-clock waits in tests. The injection points are kwargs with sensible defaults (`time.monotonic`, `asyncio.sleep`), so production callers don't see the seam. This is the test-doubles pattern from the integration-tests book, applied to async primitives.

## Why one bucket per decorated function, shared globally?

The rate-limit semantic we want is "≤10 LLM requests per second across the whole process," not "≤10 per call site." One bucket bound at decoration time gives that. If two distinct LLM call sites needed different limits, each would have its own decorator with its own bucket — also correct.

## Why cancel pending tasks on first error in `gather_bounded(on_error="raise")`?

If the caller is going to see an exception, they're aborting; leaving sibling tasks running burns LLM tokens (and money) for results the caller will discard. Cancellation is best-effort — tasks already in `await fn(...)` may finish their in-flight call before the cancel takes effect, but no new work starts. This matches the `asyncio.TaskGroup` semantics in Python 3.11 without forcing callers to deal with `ExceptionGroup`.

# Phase 8 — `core/queue.py` + worker

## Why Postgres `SKIP LOCKED` instead of Redis + RQ / Celery / SQS?

One-DB principle. We already have Postgres; adding Redis adds a service to provision, monitor, secure, and back up — for moderate throughput (eval batches at hundreds of jobs/s tops), `SELECT ... FOR UPDATE SKIP LOCKED` is the production-shape primitive used by GraphileWorker, river queue, Hatchet, Inngest. If this ever needed 10k+ jobs/s I'd migrate to Redis-backed RQ, but the SKIP LOCKED setup is correct at our scale and removes a dependency.

## Why BIGSERIAL for the jobs primary key instead of UUID?

The jobs table is an internal queue, not an externally-shared identifier. BIGSERIAL gives monotonic ordering for cheap FIFO-ish pulls and a smaller index. UUIDs would add randomness with zero benefit here. Every other table in the schema is UUID-primary because IDs leak in URLs and we want unguessability; jobs are never in URLs.

## Why the partial index `WHERE status = 'queued'`?

The claim query walks `kind + run_after` on rows whose status is queued. A full index on `(kind, run_after)` would also index done and failed rows, which accumulate forever (until the phase-13 reaper). The partial index keeps the working set tiny — done/failed rows don't bloat what the planner has to scan.

## Why the `ClaimedJob` async-context-manager pattern?

It's the only safe way to ensure ack/fail always runs even when the handler raises mid-work. The alternative — call `claim()`, then handler, then `await ack()` in caller code — guarantees we'll forget the ack in some error path. The context manager makes it impossible to leave a job stuck in `running` indefinitely (well, until the future reaper-of-stuck-running-jobs runs; that's phase-13).

## Why a CTE for the claim query?

`UPDATE ... WHERE id IN (subquery FOR UPDATE SKIP LOCKED ...)` doesn't apply SKIP LOCKED to the UPDATE itself — Postgres acquires its own write lock on the chosen rows. The CTE form `WITH picked AS (SELECT ... FOR UPDATE SKIP LOCKED) UPDATE jobs WHERE id IN (SELECT id FROM picked)` is the canonical recipe to get atomic select-and-mark with the right locking semantics. Two concurrent claims never see the same row.

## Why NOTIFY payloads capped + small?

Postgres caps NOTIFY payloads at 8KB by default. Putting the full job/result row in there would couple the queue to the result schema and break if anything grows. The pattern here is "notify with a tiny status event (which row changed, what status), then the subscriber SELECTs full data if it cares." That's how SSE eval-progress will work in phase 11 — small status events fan out, web fetches full row on demand.

## Why exponential backoff capped at 60s on requeue?

Failed jobs that retry forever at zero delay would hot-loop the queue. Pure exponential without a cap could grow to hours, which is wrong for transient errors. `min(60, 2**attempts)` gives: 2s → 4s → 8s → 16s → 32s → 60s. Bounded reasonable waits, no thundering herd, no week-long retries.

## Why the worker is a skeleton instead of fully wired?

Phase 8's scope is the queue primitive + a worker that can boot, attach to the DB, and consume. Actual handler logic for `kind="eval_case"` requires the eval engine (phase 11) — wiring it now would couple this phase to work that hasn't happened. The TODO and the registered-handler pattern make the seam obvious for phase 11 to fill in.
