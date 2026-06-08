# DECISIONS

> Defendable answers for every architectural choice in PromptForge.

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

## Why does ragent own no migrations, and share the `PF_` env prefix with apps/api?

ragent and apps/api talk to the *same* Postgres, so the schema needs exactly one owner — apps/api owns the models and the Alembic history, ragent just reads/writes through the shared models. Two services migrating one database is how you get conflicting heads and a wedged deploy; making api the single migrator means ragent's deploy has no `release_command` and can never race a migration. The shared `PF_` env prefix is the same idea applied to config: `PF_DATABASE_URL` and `PF_JWT_SECRET` are literally the same secret values in both Fly apps, so there's one secret to rotate, not two that can drift. ragent adds only what's truly its own — `PF_API_BASE_URL` for the live system-prompt fetch.

## Why fetch system prompt from apps/api at runtime?

Demonstrates the platform integration story: prompts are managed in the platform, agent consumes them. Editing the prompt in PromptForge UI changes ragent behavior on next request — a real product feature, not a demo gimmick. Cached 60s to bound api load.

## Why shared HS256 secret between api and ragent?

Two services under same control + same deploy unit = HS256 shared secret is fine. The alternative — opaque tokens validated via api round-trip — adds latency on every request. If a third service joined or services were operated by different teams, RS256 + JWKS at apps/api would be the move.

## Why Next.js 16 App Router over Pages Router?

RSC + Server Actions remove a ton of client-state ceremony. Data fetches happen on the server, types stay shared with server code, mutations don't need separate API routes. Prior Pages Router experience; App Router took ~1 week to internalize and now is the better pick for new builds.

## Why no TanStack Query?

RSC + Server Actions handle server state for the patterns I have: read-on-render, mutate-via-action, refresh-on-action. TanStack Query is the right answer if I had client-side optimistic updates across many entities, heavy cache invalidation logic, or paginated infinite scroll. I don't here. Less surface area = fewer bugs.

## Why Zustand over Context + useReducer?

Zustand is ~1KB and avoids the Context-rerender-everything problem. The two stores I have (dashboard filter, UI shell) are accessed from many components; Context would require splitting providers to avoid cascade rerenders, which is itself ceremony. Zustand's selector pattern handles this for free.

## Why a BFF (Next route handlers) instead of the browser calling the API directly?

The web app and the API are on different origins (vercel.app vs fly.dev). The original plan was browser→API directly with an in-memory access token + httpOnly refresh cookie — but that refresh cookie is now a *third-party* cookie from the browser's perspective, and browsers are actively phasing those out, so it's fragile. The BFF (backend-for-frontend) fixes this: the browser only ever talks to the Next origin; Next route handlers proxy to the API. The session cookie is then *same-origin* to the web app, so no third-party-cookie problem, and — the bigger win — **no API token ever reaches the browser at all**. The cost is a little server-side plumbing (token relay + refresh in the handlers); worth it for the security posture and durability.

## Why seal the session cookie (JWE), and what's actually in it?

The cookie holds the API access token, the refresh token, and a small profile. httpOnly already keeps JS from reading it, but sealing it as a JWE (jose, AES-256-GCM, key derived from a server-only secret) means the cookie value is opaque ciphertext rather than a set of usable bearer tokens — so even if it leaked through some non-JS path it isn't directly replayable, and it's tamper-evident. The browser receives only the profile (id, email, org, role) in the JSON response, never the tokens.

## Why is refresh handled in route handlers (and why is that a known limitation)?

Next only lets you write cookies in a Server Action or Route Handler, not during a Server Component render. So `apiFetch` refreshes-on-401 and re-seals the rotated session only when called from a handler. That's fine for the auth shell (all API access goes through `/api/*` handlers). When later phases fetch data during RSC render, refresh will move to the proxy (middleware) or a generic proxy handler — the standard Next pattern. Calling the API's `/refresh` concurrently could trip the chain-revocation replay defense, so refresh needs single-flighting; documented as a follow-up for the data-heavy phases (serverless makes a shared lock non-trivial).

## Why gate routes in both the proxy and the (app) layout?

Defense in depth with different jobs. `proxy.ts` (Next 16's renamed middleware) does a cheap edge presence-check on the session cookie and redirects before any render — fast, good UX, but it only knows "a cookie exists," and matchers can drift out of sync with the route tree. The `(app)/layout.tsx` server guard reads + (implicitly) validates the session and is the authoritative gate covering every page in the group regardless of matcher config. Proxy for speed, layout for correctness.

## Why one generic data proxy (`/api/pf/[...path]`) instead of a route handler per endpoint?

With the BFF, every data call still has to go through the server (to attach the token + refresh). Writing a hand-rolled handler for each of ~20 API endpoints would be a wall of near-identical boilerplate. A single catch-all proxy forwards method + body + query to `/api/v1/*` with the session applied and relays the JSON + status — so the client just calls `api.get("api/v1/prompts")` and the API keeps enforcing tenancy/authz. It's restricted to the `/api/v1/` prefix so it can't be used to reach arbitrary hosts, and the dedicated auth routes (login/signup/demo/logout) stay separate because they do cookie-sealing the generic proxy shouldn't.

## Why consume SSE with fetch + a parser instead of the browser's EventSource?

`EventSource` can't set request headers, and in the BFF the stream is authenticated server-side — so the browser opens an unauthenticated connection to the proxy (`/api/pf-stream/...`), which attaches the token and pipes the upstream `text/event-stream` through. On the client, reading that stream with `fetch` + `eventsource-parser` (rather than `EventSource`) gives control over the request, clean abort via `AbortController`, and no reliance on EventSource's auto-reconnect (which would re-open a finished batch's channel). The proxy sets `X-Accel-Buffering: no` + `no-transform` so neither Vercel nor Fly buffers the stream.

## Why fetch data client-side through the proxy instead of in Server Components?

RSC data fetching would be the obvious choice, but the BFF can't refresh-and-re-seal the session cookie during a Server Component render (Next only allows cookie writes in a route handler or action). The interactive pages (prompts, evals) also need client state anyway — forms, the Monaco editor, live SSE, optimistic refresh after a mutation. So those pages are client components that fetch through the proxy (`api.get/post/...`), where the proxy handler owns auth + refresh. Static/marketing routes stay server-rendered. If a page needed RSC streaming for SEO or first-paint, I'd move its initial read to a server component and hydrate — not needed for an authed app behind a login.

## Why the Monaco editor, lazy-loaded?

Prompt bodies are edited text with `{{variables}}`; a real code editor (monospace, large-doc handling, a familiar editing surface) reads as a product, not a `<textarea>`. `@monaco-editor/react` lazy-loads Monaco only on the pages that mount it (create / version editor), so it never weighs down the landing or list pages. It's wrapped in one `CodeEditor` component so the rest of the app doesn't depend on Monaco's API directly.

## Why "live progress, then refetch full detail" on the eval batch page?

The SSE `result` events are intentionally tiny (case id, version id, pass/fail, score, completed/total) — the API keeps NOTIFY payloads small. That's perfect for a live progress bar and pass/fail ticks as cases finish, but it deliberately omits the judge reasoning. So the batch page renders the live events while streaming, and on the `done` event does one `GET /eval-batches/{id}` to pull the full result rows (with reasoning) for the final table. Small fan-out events for liveness, one authoritative fetch for detail — rather than fattening every event. The stream is opened inside the initial GET's callback (only if the batch isn't already terminal) and aborted on unmount.

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

# Phase 9 — `services/llm.py` (litellm wrapper)

## Why retry only on transient errors, not bare Exception?

`AuthenticationError` means the API key is wrong — retrying burns 3× the auth-fail cost for the same answer. `BadRequestError` (4xx invalid messages, content-policy violation) means the request is malformed — retrying gives the same error. The retry-on tuple is exactly the set that can succeed on a second try: `APIConnectionError`, `Timeout`, `RateLimitError`, `APIError` (provider 5xx). Anything else propagates immediately as `LLMCallError`. Saves money and surfaces real problems faster.

## Why a global TokenBucket for the default key but skip it for BYOK?

The bucket caps OUR hosted demo key at ≈10 req/s, which is appropriate for one shared key serving many demo visitors. A BYOK call is the user's own OpenAI/Anthropic key consuming the user's own quota — applying our bucket to it would slow down their personal usage for no reason and conflate two unrelated rate budgets. Skip is correct.

## Why `LLMResponse` as a frozen dataclass instead of returning the litellm object?

Three reasons. (1) The raw litellm `ModelResponse` shape can change across versions — pinning the route layer to the litellm type makes future upgrades a refactor instead of a non-event. (2) Frozen dataclass makes the contract explicit and auditable: text + tokens + cost + latency + raw. (3) Tests can construct an `LLMResponse` without going through litellm at all.

## Why `cost_usd: float | None` instead of `0.0` on failure?

`None` says "unknown." `0.0` would silently lie about cost on experimental/local models where pricing isn't in litellm's table. A future Run-cost-aggregation query would happily sum the lies. Surfacing `None` lets the dashboard render "—" instead of pretending zero, which is the honest UX.

## Why `_acompletion_with_retry` is a thin wrapper instead of decorating `call_llm` directly?

The retry decorator catches its allowed exceptions and retries; `call_llm` needs the parsing + LLMCallError translation to happen ONCE after retries exhaust. If the decorator wrapped `call_llm`, the parsing logic would re-execute on every retry and the error envelope would be wrong. Splitting them puts retry around just the network call.

## Why catch raw `Exception` after the retryable tuple?

Defense in depth. The retryable tuple covers known litellm exceptions; an unforeseen exception type (litellm upgrade, a third-party middleware, asyncpg connection thrash if the LLM call somehow used the DB) should still surface as a clean `LLMCallError` with the underlying type named, not propagate as an opaque traceback to the route handler.

# Phase 10 — Runs

## Why persist failed Runs instead of just returning the error to the caller?

Three reasons. (1) The Runs dashboard needs error rates — "why is my eval at 70% pass" is a real question that requires durable failure rows. (2) An LLM call that costs money and timed out should still be visible to the org so they can investigate, not silently vanish from the record. (3) A 4xx provider error (model down, bad request) is debugging info; throwing it away to keep the table "clean" loses signal. The route returns 201 with `error` populated and `output: null`; the row exists.

## Why `Numeric(12, 6)` for `cost_usd` instead of float?

Per-token costs are fractions of a cent — `text-embedding-3-small` is ~$0.00002 per call. Float drift on aggregation across thousands of runs would silently mis-bill. Numeric is exact. 12-digit precision with 6 after the decimal covers everything from $0.000001 to $999999.999999 USD, which spans every realistic per-run cost.

## Why `Run.org_id` denormalized from `version.prompt.org_id`?

So `TenantRepository[Run]` can scope by `org_id` directly without a 3-table join on every list/get. The denormalization is set once at insert time (after the route already resolves the version through the org-scoped prompt repo) and never updated — prompts don't move between orgs. Classic read-perf-vs-write-complexity tradeoff; in our access pattern, runs are read 100× more than written.

## Why demo accounts must BYOK to run prompts?

The hosted OpenAI/Anthropic key on the server pays per token. A read-only demo seeded for hiring teams running 10 evals against `gpt-4o` would rack up real cost. BYOK pushes that cost to the visitor: paste your own key, get a real run, no harm to us. The 403 with a clear `detail` string tells the demo UI exactly what header to add — no guesswork.

## Why `_provider_response` stored but not returned?

The raw litellm response can be large (tens of KB on long completions) and contains provider-specific fields nobody outside debugging needs. The `RunResponse` schema deliberately omits it; storing keeps it available for forensic queries (`SELECT provider_response FROM runs WHERE id = ?` from psql) without bloating every API payload.

## Why `pg_notify()` instead of the `NOTIFY` statement?

Postgres's `NOTIFY` is a utility command, not DML — it bypasses the prepared-statement layer, which means parameter binding (`:msg`) doesn't work. `pg_notify(channel text, payload text)` is the function form; it goes through normal parameter binding, plays nicely with SQLAlchemy's `text(...)` + parameters pattern, and protects against payload injection. Caught by integration tests; phase-8 had been shipping with broken enqueue NOTIFY.

# Phase 10.5 — Deploy infrastructure

## Why Postgres 17 instead of 16 or 18?

17 is the latest stable that's been out long enough (~21 months) for every extension I care about — pgvector, asyncpg, alembic — to ship tested wheels. 18 has been out ~9 months: mostly enough but introduces a small "first to hit a rough edge" risk I don't need on portfolio infra. 16 was where I started for habit reasons; the bump cost nothing and matches the latest-LTS rule I follow on every other dependency.

## Why Neon over Fly Managed Postgres or Supabase?

Managed Postgres without the $38/month Fly MPG floor. Neon's free tier (0.5 GB, 100 CU-hr/month) covers demo-scale data with room to spare. pgvector is enabled by default so ragent retrieval has no extension-install friction. **Database branching** is the differentiator: I can branch the prod database for migration testing without standing up a staging copy — that's a real engineering capability, not just a cost decision. Trade is +10–30 ms cross-cloud latency vs same-region Fly Postgres; acceptable because every request path is dominated by ≥500 ms LLM calls, so the DB hop is noise.

Fly's unmanaged Postgres (`fly postgres create`) is cheaper still but Fly explicitly tells you they don't support it — you own backups, point-in-time restore, upgrades, disk-full handling. For portfolio infra that's the wrong place to take on operational risk. Supabase would also work but uses transaction-mode PgBouncer on its default port, which breaks asyncpg's prepared-statement cache; Neon exposes a direct (session-mode) endpoint without that footgun.

## Why a DSN normalizer in `Settings` (not just "set the right env var")?

Provider DSNs (Neon, Fly Postgres, Heroku, Supabase) hand you bare `postgresql://` or even older `postgres://` schemes. SQLAlchemy parses those as psycopg2-default, which is the sync driver this app deliberately doesn't ship — first call into the DB fails with `ModuleNotFoundError: psycopg2`. Normalizing the scheme + `sslmode → ssl` (asyncpg's param name) in one place means any provider DSN works without manual editing per-deploy. Defensive against the most common DSN-from-cloud-provider footgun. Unit-tested against five real-world DSN shapes.

## Why two Fly machines (api + worker) instead of one process running both?

Separation of concerns + independent scaling. The api machine auto-stops to zero on idle (cheap demo cost). The worker runs continuously polling the queue; if it crashed under load, the api machine would still serve reads. Same Docker image, two `[processes]` entries in `fly.toml` — one image, two scale dials. Cost: ~$4.65/mo for both at shared-cpu-1x; the worker can be scaled to zero (`fly scale count worker=0`) until the eval engine lands in phase 11.

# Phase 11 — Eval engine

## Why four judge types and not just one?

Each judge optimizes for a different "what does correct look like" question:
- **exact**: deterministic ground-truth answers (math, codegen with a known right output)
- **contains**: substring matching for "the answer must mention X"
- **regex**: structured outputs (extract email, match a format)
- **llm_judge**: open-ended quality questions ("is this answer helpful, on-topic, factually correct")

A real eval suite mixes them. The judge field on EvalCase is nullable so a single suite can pick a default (e.g. contains) and individual cases can override (one regex case in a contains-heavy suite). Deterministic judges return score ∈ {0.0, 1.0}; llm_judge returns a clamped float so you can set passing thresholds.

## Why `unique(batch_id, version_id, case_id)` + ON CONFLICT instead of plain INSERT?

The queue retries failed jobs. If a worker crashes mid-write or the upsert ack races a NOTIFY, the same eval-case job can be re-run. A plain INSERT would duplicate the EvalResult row; the unique constraint + `ON CONFLICT DO UPDATE` makes re-running idempotent — the new result replaces the old. Same convergence guarantees, no manual dedup.

## Why does the eval runner catch errors instead of letting the queue retry?

A run that fails (LLM down, template invalid, judge LLM rejected) is a *durable* outcome — it's a real "this version failed this case" data point that belongs in the EvalResult row. Re-raising would have the queue requeue the job and we'd loop forever on a deterministic failure. Catching here and recording `passed=False` w/ reasoning converges: the batch completes, the dashboard shows error rate, and the human investigates.

The single case where we'd want a retry — transient provider error — is already handled inside `services/llm.py` via the retry decorator before the LLMCallError surfaces.

## Why does `_bump_progress` atomically increment in a single statement?

Two workers finishing two different jobs in the same batch could race a read-modify-write on `completed_jobs`. The SQL form `UPDATE eval_batches SET completed_jobs = completed_jobs + 1 RETURNING completed_jobs` is atomic at the row level. The RETURNING gives us the post-increment value, which we use to decide whether to flip status to done. No lock needed; the race is impossible.

## Why SSE via asyncpg `add_listener` instead of polling the batch row?

Polling would burn DB connections per active SSE client × poll interval. LISTEN/NOTIFY is push: the worker emits one `pg_notify` per result, every subscriber gets it via their own LISTEN. Single bidirectional cost per client. The SSE handler uses a raw asyncpg connection (SQLAlchemy doesn't expose LISTEN through its async API) and forwards each NOTIFY to the client. 30-second timeout emits a heartbeat so Fly's proxy doesn't drop the connection on long silences.

## Why does the SSE endpoint emit a "done" event and stop?

EventSource clients reconnect automatically on disconnect. If we just stopped sending events when the batch finished, the client would reconnect to a permanently-quiet channel — wasted resource. Emitting an explicit `event: done` lets the frontend close the EventSource cleanly, drop the connection, and stop listening. Server cleanup (UNLISTEN, raw connection close) runs in the `finally`.

## Why test the worker by importing `_run_one` instead of spawning the worker subprocess?

The worker subprocess does two things: signal handling + an infinite poll loop. Both are uninteresting to test — they're standard Unix process plumbing. The actual eval-case handling is in `run_eval_case`, and `_run_one` is the thin context-manager wrapper. Calling `_run_one(job)` from a test exercises the real production code path without the process-management overhead. The `_drain_queue` helper just claims jobs and feeds them to `_run_one`, which is exactly what the subprocess does in a loop.

## Why was the test conftest leaking the global engine?

The api routes use `get_session_factory()` directly for the queue enqueue (because the queue lives outside the request transaction). That returns the module-global lazy engine, not the per-test override. Across tests, the global engine accumulated asyncpg connections bound to event loops that pytest-asyncio had since closed. On teardown, asyncpg tried to gracefully close those connections via `asyncio.create_task`, which raised "Event loop is closed."

Fix: dispose the global engine at the end of each `api_client` fixture along with the per-test engine. The next test rebuilds the global lazily on first access. Stable across runs.

# Phase 12 — Eval e2e + SSE coverage

## Why does `pg_notify` have to fire inside the committing transaction?

`pg_notify` (and `NOTIFY`) is transactional: Postgres only delivers the notification when the transaction that issued it commits, and discards it on rollback. The eval runner was calling `_notify` *after* `session.commit()`, which started a fresh transaction that the session then closed without committing — so every SSE event was silently dropped. Phase 11's tests only polled the batch-detail endpoint, never subscribed to the live channel, so the bug shipped invisibly. The fix moves the NOTIFY before the commit, into the same transaction as the result upsert and progress bump. That's also more correct semantically: a subscriber is never woken to read data that isn't durable yet.

## Why extract the SSE event loop into a standalone generator instead of testing the HTTP endpoint?

httpx's `ASGITransport` buffers the entire response — it runs the ASGI app to completion before returning a `Response`. A live SSE stream never "completes" until the batch is done, and the batch can't finish until the worker runs, which the test can only trigger *after* the client call returns. That's a deadlock: you can't consume a still-streaming SSE response through the test client. Extracting the loop into `eval_event_stream(engine, batch_id)` lets the test drive the real generator against the real Postgres LISTEN/NOTIFY channel, advancing the batch one case at a time and asserting each `result` event arrives before the terminal `done`. The thin HTTP wrapper (route + `EventSourceResponse`) is covered separately with an already-done batch, where the generator returns promptly and ASGITransport's buffering is fine.

## Why a terminal short-circuit when a client subscribes to an already-finished batch?

Eval runs can finish in well under a second, so a client that subscribes a moment too late would attach to a channel that has already gone silent — and then sit there until the 30s heartbeat with no signal that the batch is done. On subscribe, after registering the LISTEN, the generator reads the batch status once; if it's already `done`/`failed` it emits `open` then `done` and closes. The LISTEN is registered *before* the status read, so if the batch is not yet terminal at that point, any concurrent completing NOTIFY is already queued and handled by the normal loop — no event can slip through the gap.

## Why register the LISTEN before producing any NOTIFY in the live test?

NOTIFY has no backlog for connections that subscribe later — a notification fired before a connection issues `LISTEN` is gone. The live test pulls the generator's first `open` event (which is yielded only after `add_listener` runs) before draining any jobs, guaranteeing the subscription is active. Without that ordering the test would be racy: the worker could finish and notify before the SSE connection subscribed, and the assertion would flake.

## Why a test that runs the real worker consume loop, not just the handler?

Calling the handler in-process (`_run_one(job)`) proves the eval logic but not that the worker's queue-claim/dispatch loop is wired correctly — wrong `kind` registration, a broken `consume()` poll, or a claim-query bug would all pass a handler-only test. One e2e test starts the actual `_consume_forever` loop against the real queue, enqueues jobs through the API, and asserts an SSE subscriber receives the live events the worker produces. That exercises queue → claim → handler → committed NOTIFY → SSE as one chain. True subprocess boot and SIGINT/SIGTERM handling are deliberately left to the Phase 16 deploy smoke — that's process plumbing, not application logic, and an in-process task can't faithfully test signal delivery anyway.

## Why delete `queue.notify_batch` instead of using it for the fix?

It was dead (nothing called it) and it wrapped the NOTIFY in its own `engine.begin()` transaction — separate from the transaction that commits the eval result. That's the exact non-atomicity that caused the original bug: the notify could commit while the result write rolled back, or vice versa, waking a subscriber to read data that isn't there. The correct fix keeps the NOTIFY inside the result's own transaction, so leaving `notify_batch` around as a tempting "batch notify helper" was a footgun. Removed it rather than document a trap.

# Phase 13 — Demo mode

## Why a free-run quota instead of "demo must always BYOK"?

The whole point of a demo is to convert a skimming visitor into someone who *gets* the product — and nobody pastes an API key before they've seen value. So demo browses all seeded content for free, and gets a few real runs on our hosted key (default 5) before we ask for a key. That's the conversion funnel: taste first, key second. The cost risk that BYOK originally guarded against is handled by capping the free runs, not by removing them.

## Why meter the free quota per client IP, not per demo session or globally?

A global pool fails the product goal — the first visitor of the day drains it and everyone after sees zero free runs. Per-session is trivially farmable: log in again, fresh quota, infinite hosted-key spend. Per-IP is the right unit because the real risk is *cost*, and IP is the thing an attacker can't cheaply multiply. NAT means some genuine visitors share a bucket — acceptable for a portfolio demo, and the limit's a config knob. The same forwarded-IP key function backs both this quota and the slowapi login limit.

## Why store a hash of the IP, not the raw address?

The counter only needs to tell visitors apart and rate them — it never needs to *read* an IP back. Storing `HMAC(ip)` (keyed on the JWT secret, via the existing `hmac_token`) gives exact per-visitor counting with no raw client IPs at rest. Cheap privacy-by-design: a DB dump leaks no addresses, and the column is a fixed 64-char digest.

## Why 402 Payment Required when the quota runs out, not 403?

403 means "you may never do this" — it's what demo gets on a real write (creating a prompt). Quota exhaustion is different: "you *can* do this, you've just used the free allotment — here's how to continue." 402 carries that meaning and lets the frontend branch cleanly: 402 → show the BYOK key prompt; 403 → show the sign-up CTA. Reusing 403 for both would collapse two distinct UX paths.

## Why a `require_writer` gate swapped onto each route, not one global middleware?

Read-only is the demo's defining constraint, so enforcement has to be impossible to forget. A global ASGI middleware can't see the principal — auth resolves inside the dependency tree — so it'd have to re-decode the token, duplicating auth and special-casing the unauthenticated routes (login, signup, demo-login). Instead `require_writer` is a dependency that *replaces* `get_principal` on mutating routes: one swap both authorizes and yields the principal, it's visible at each call site, and every write route has a matching tenancy/role test. The single-prompt-run route is the one deliberate exception — it owns the demo free-quota/BYOK logic itself.

## Why rate-limit `/demo/login` specifically?

It's the one unauthenticated endpoint that does real work on every call: a DB lookup plus a refresh-token row insert plus JWT signing. Without a limit it's a cheap amplification target — hammer it to bloat the refresh-tokens table and burn CPU. slowapi caps it per IP (default 5/min). The rest of the API sits behind auth, so the abuse surface is the login itself. Storage is in-process memory, which is correct for a single api machine; scaling the api horizontally would mean pointing slowapi at Redis so the counters are shared.

## Why is the refresh-token reaper in the worker, and why test the function not the loop?

The reaper is a periodic side task, and the worker is already the long-lived process that owns background work — putting it there avoids standing up a separate scheduler. Per the test-directness rule, the interval loop is process plumbing (sleep, cancel on shutdown) and isn't worth a brittle timing test; the *logic* — "delete tokens past the retention window, keep the rest" — is a plain function with an integration test against real Postgres. Revoked/replaced tokens are kept until they age out so the chain-revocation audit trail survives for the retention window, then they're just dead rows.

# Phase 14 — Public share tokens

## Why one polymorphic ShareToken instead of a share table per resource?

Sharing is the same mechanism regardless of what's shared: an opaque token, a target, optional expiry, revocation. Modeling it as `(resource_type, resource_id)` means one table, one creation path, one public endpoint that branches on type — adding a third shareable later (a single Run, say) is an enum value plus a projection function, not a new table + route + tests. The cost is no FK on `resource_id` (the target table varies), so the public endpoint resolves the row by type and 404s if it's gone — which is the behavior you want anyway when the underlying resource was deleted.

## Why hash the share token when the link is meant to be shared?

The token is low-secrecy by purpose — it lives in a URL someone forwards — but "stored hashed" still buys something: a database dump doesn't hand an attacker a set of live, working share URLs. Same pattern as refresh tokens: store `HMAC(token)`, look up by digest, return the plaintext exactly once at creation. Reuse isn't a problem the way it is for refresh tokens — a share link is meant to be hit repeatedly — so there's no rotation, just revoke + optional expiry.

## Why a separate minimal public projection instead of reusing the normal response models?

The authenticated responses carry workspace internals — `org_id`, `created_by`, `provider_response`, suite/case ids. A public link must expose the *artifact* and nothing about the workspace behind it, so the public schemas are a deliberately smaller, separate shape: a shared prompt is name + description + latest version body/vars; a shared eval batch is suite name + status + pass rate + per-case results. Reusing the internal models and hoping to strip fields later is how a refactor accidentally leaks `org_id` into a public endpoint. Separate types make the public surface explicit and reviewable.

## Why is the public endpoint the only unauthenticated read, and how is it kept safe?

Every other read goes through `get_principal` + `TenantRepository`; this one can't, because the whole point is access without an account. The safety comes from the token being the capability: 32 bytes of `secrets.token_urlsafe`, looked up by HMAC, with revocation and optional expiry checked before anything is loaded. Creating a share is still tenant-gated (you can only mint a link for a resource in your own org, writer role only — demo can't), so the unauthenticated surface is strictly "resolve a capability someone already chose to hand out."

# Phase 15 — Demo seed

## Why is the seed in-package (`promptforge_api/seed.py`) instead of a loose `scripts/` file?

A loose script sits outside the package, so it dodges mypy --strict, ruff, and coverage — exactly the seed that writes to every table is the one you don't want untyped and untested. Keeping `seed_demo(session)` in-package means it's type-checked against the real models, the logic is unit-testable (the test passes a session and asserts the dataset), and `main()` is a thin `python -m promptforge_api.seed` wrapper. The script/library split is the same one used for the worker.

## Why must the seed be idempotent rather than a one-shot insert?

It runs on every deploy (Phase 16 wires it into the release step), and a deploy can re-run or partially fail. A plain insert would either duplicate the demo data or crash on the unique constraints the second time. Every section is get-or-create keyed on a natural identifier — user by email, org by slug, prompts by (org, name), versions by number, the eval suite by (org, name), shares by token hash — so the second run is a no-op and the demo workspace stays exactly one clean copy.

## Why give the demo user an unusable password instead of a known one?

The demo account is meant to be entered only through `/demo/login`, which issues a read-only session without a password. Seeding a *known* password would create a second, uncontrolled way in — and since every visitor shares this account, a known password is effectively a public credential to a real (if read-only) org. Hashing a random throwaway secret means the row satisfies the not-null password constraint while `/auth/login` can never succeed for it.

## Why seed a failed run and a mixed-pass eval batch, not all-green data?

The demo's job is to show the product honestly, and the product's real value is in surfacing failures — the failed-run row exists precisely so the runs view shows error handling, and the 2-of-3 eval batch makes the pass-rate and the per-case "why it failed" reasoning meaningful instead of a meaningless 100%. All-green seed data would hide the exact features (error capture, eval scoring) that make the platform worth looking at.

## Why are the demo share tokens hard-coded constants?

The public share links need stable URLs so the README and demo walkthrough can point at "a live prompt" and "a live eval report" that don't change on each reseed. They're public-by-design capabilities (the whole point is to hand them out), so there's no secret to protect — but they're still stored hashed like any other share token, so the table has no special case. ruff's hardcoded-password lint flags them; they carry an inline `noqa` with the reason.

# Phase 16 — Deploy + observability

## Why is the request-context middleware raw ASGI instead of BaseHTTPMiddleware?

Starlette's `BaseHTTPMiddleware` reads the response body to hand you a `Response` object — it buffers. That's fine for JSON but fatal for the SSE eval stream: it would hold the whole stream until the batch finished, defeating the point. A raw ASGI middleware wraps `send` and touches only the `http.response.start` message (to grab the status and append `X-Request-ID`); the streaming body messages pass straight through untouched. So the same middleware that binds the request id and logs every request also coexists with SSE. It's added last so it's the outermost layer — the id is bound before anything else runs and is present even on error responses.

## Why structlog now but OpenTelemetry deferred?

Structured logs are non-negotiable for anything deployed: JSON lines with a bound `request_id` (echoed on `X-Request-ID`) make production debuggable for the cost of a small dependency already in the tree. Full OTel tracing is a different trade — it pulls in ~5 instrumentation packages that, on a zero-traffic demo, sit unused and add install weight and CVE surface. The senior move is to wire the cheap, high-value half and leave a clean, documented seam for the rest: a single enable-point in the lifespan, gated on `OTEL_EXPORTER_OTLP_ENDPOINT`. "I wired logs; tracing is one env var and a dependency group away" is a stronger answer than shipping an instrumentation stack the app never exercises.

## Why does the Fly release command run the seed on every deploy?

`release_command` runs on a temporary machine before traffic shifts, with the app's secrets and a migrated database — exactly the right place to guarantee the demo workspace exists. Because the seed is idempotent (get-or-create throughout), running it every deploy is safe and means a fresh environment is demo-ready with no manual step. It's chained after migrations with an explicit `sh -c 'alembic upgrade head && python -m promptforge_api.seed'` because Fly replaces `CMD` with the command and doesn't guarantee a shell — relying on bare `&&` would be undefined. If either step fails, the release aborts and the old machines keep serving.

## How was the flaky API-key 401 tracked down (and why was it ~12%)?

A test asserting "an API key can't mint another API key" (expects 403) intermittently got 401 instead — roughly 1 in 8 runs. The 401 was fast (1.6 ms, before the argon2 verify), which pointed at the prefix *lookup* finding no row, not a hash mismatch. Cause: the key prefix was generated with `secrets.token_urlsafe`, whose alphabet includes `_` — the same character used as the separator in `pf_live_<prefix>_<secret>`. The parser split on the first `_`, so any prefix that happened to contain one (≈12% of keys) parsed to the wrong value and missed the lookup. Two fixes: generate the prefix as hex (no ambiguous chars) and parse by fixed length instead of splitting (also backward-compatible). The regression test round-trips 200 generated keys so the probabilistic bug can't slip back in. Lesson: a flaky test is often a real bug wearing a probability — chase it, don't rerun it.

## Why does the demo's hosted key live in a server secret, and what breaks without it?

The free-taste demo runs execute against our key, so `PF_OPENAI_API_KEY` (or the Anthropic one) has to be a Fly secret on the api app. Without it, `services/llm.py` has no key for non-BYOK calls and every free demo run fails — the visitor hits the "add your own key" path immediately, which defeats the taste-first funnel. It's documented as a required secret in the deploy runbook for exactly that reason, separate from the BYOK path which never touches it.

# Phase 2 (ragent) — data model

## Where do ragent's models live, and who authors the migration?

These two are different responsibilities and I split them. *Domain ownership* — corpora, documents, chunks, conversations, messages are entirely ragent's data; apps/api never touches them — so the ORM models live in `apps/ragent`. *Migration execution* is an infra concern: one shared database needs exactly one migrator or you get conflicting Alembic heads, and apps/api is already that migrator, so the table DDL lives in apps/api's history. Putting the models in apps/api just so autogenerate could see them would make api "own" data it has nothing to do with — and would force ragent's Docker image to depend on the api package (dragging in litellm, slowapi, argon2) only to import table classes. Locality of the models plus a single migration history is the cleaner separation.

## Why is migration 0009 hand-authored, with the vector DDL as raw SQL?

Two reasons it isn't autogenerated. First, apps/api's Alembic can't see ragent's models (they're in a different package, not on api's `Base.metadata`), so there's nothing to diff against — autogenerate would propose dropping the tables, not creating them. Second, pgvector columns and *partial* ivfflat indexes don't autogenerate cleanly anyway; you hand-write them regardless. I went one step further and emit the `vector(1536)`/`vector(384)` columns and the `ivfflat ... vector_cosine_ops` indexes as raw `op.execute(...)` SQL rather than importing `pgvector` into apps/api — api never queries a vector, so it shouldn't carry the dependency just to run a migration. The rest of the DDL is normal `op.create_table`.

## Why the `include_object` guard in apps/api's Alembic env?

apps/api is now a co-migrator of a database that contains tables it doesn't model. Without a guard, the next `alembic revision --autogenerate` in api would diff the live DB against api's metadata, not find corpora/documents/chunks/conversations/messages there, and emit `DROP TABLE` for every one of them. `include_object` returns `False` for any table not in api's own metadata, so autogenerate simply ignores ragent's tables. It only affects diffing — applying migrations is untouched — which is exactly the scope you want for a shared-DB safety rail.

## Why denormalize `org_id` onto documents, chunks, and messages?

The same read-perf tradeoff apps/api makes on `Run.org_id`. A tenant-scoped query for "this org's chunks" shouldn't have to climb chunk → document → corpus to find the org on every retrieval; carrying `org_id` directly on the child lets the (future) tenant repository filter in one predicate. It's set once at insert (the parent's org never changes) and the cost is a denormalized column that can't drift because nothing moves a document between orgs. Retrieval reads these tables far more than ingest writes them, so the trade favors the read.

## Why two nullable embedding columns with *partial* ivfflat indexes, instead of one column?

A corpus pins exactly one embedding model, so a given chunk uses either the 1536-d (OpenAI) or the 384-d (bge) column and leaves the other NULL — separate typed columns keep each index's dimensionality fixed and clean (a single variable-dim column would complicate index management). The indexes are partial — `WHERE embedding_1536 IS NOT NULL` — so each ivfflat index only covers the rows that actually use that model, instead of wasting space and build time indexing a column that's NULL for every chunk belonging to the other-model corpora. If a third model ever joined, the clean move is a `chunk_embeddings(chunk_id, model, vector)` table rather than a third nullable column.

# Phase 3 (ragent) — ingest pipeline

## Why render markdown to HTML and flatten it, instead of embedding the raw markdown?

Raw markdown carries syntax that's noise to an embedding model — `## `, `**`, `[text](url)`, table pipes — and it varies by author. Rendering with markdown-it-py and flattening the HTML (the same selectolax/lexbor path raw HTML uses) gives the *content*: `## Overview` becomes "Overview", a link becomes its anchor text, a list becomes its items. One code path covers both markdown and HTML, and the embedding sees prose, not formatting. The flatten joins inline runs with a space (so `Hello <b>world</b>` stays "Hello world") and then collapses whitespace.

## Why fixed-size token windows for chunking, not sentence/semantic splitting?

The unit that matters for an embedding model is tokens (its context budget), so I chunk on tokens directly: encode once with tiktoken's `cl100k_base` (what text-embedding-3-small uses) and slide a fixed window with overlap. It's deterministic and trivially testable — `target=512, overlap=64` means step 448, and the test pins the exact windows. The known cost is mid-sentence cuts, which the 64-token overlap softens (a fact straddling a boundary is retrievable from both windows). Sentence/heading-aware recursive splitting is the higher-quality next step; I left the decision and the upgrade path as a comment so it's a conscious tradeoff, not an oversight.

## Why does embedding route on the corpus, and why is the local model just a seam right now?

The corpus pins the embedding model, so `embed_texts` dispatches on `corpus.embedding_model` — that's what keeps the 1536-d and 384-d columns coherent (a corpus's chunks all use one model, one column, one partial index). The OpenAI path goes through litellm, same client/cost story as apps/api. The local bge-small path raises a `TODO(phase-12)` instead of being half-built: wiring it means sentence-transformers + torch, which is a couple GB of dependencies and a real cold-start cost on a 512 MB Fly machine — not something to drag in before the corpus/seed flow that actually exercises it. Raising keeps the routing contract honest (no silent wrong-dimension vectors) until Phase 12 adds the backend deliberately.

## Why does ingest record a terminal status and *not* re-raise on failure?

Same reasoning as apps/api's eval-runner. A failed ingest — unparseable PDF, unsupported type — is a *durable fact* about that document, so `ingest_document` writes `status=FAILED` with the error and returns, rather than throwing. Re-raising would let the worker requeue the job and loop forever on a deterministic failure. The one exception is a *transient* provider error during embedding (rate limit, 5xx), which surfaces as `RetriableEmbeddingError` and *is* re-raised so the worker requeues it (Phase 4). Re-ingest is idempotent (it deletes prior chunks first), so a retry or an edited document converges to exactly one clean set of chunks.

# Phase 4 (ragent) — ingest worker

## Why does ragent reuse apps/api's `jobs` table instead of its own queue?

The platform already has one Postgres job queue (apps/api's `jobs` table, SKIP LOCKED, migration 0004), and the one-DB principle says don't add a second queue substrate for a second producer. ragent enqueues `kind="ingest_document"`; apps/api's eval worker only claims `kind="eval_case"`. Two consumers filtering one table by kind is exactly what the `kind` column is for, and it means no new table, no second migration owner, no Redis. ragent's queue *client* is its own (a trimmed copy of api's — enqueue/claim/ack/requeue, no batch-SSE fanout) because the table is shared but the code isn't importable across the two packages — the same ownership split as the models. It uses raw `text()` SQL, so ragent doesn't even need to model a `Job` table it doesn't migrate.

## Why store the source bytes in `documents.raw_content` (BYTEA in Postgres)?

The ingest worker is *detached* from whatever produced the document — an upload handler or the seed — so it can't be handed the bytes in-process; it has to read them back from the row. `raw_content` holds the original file bytes, and the worker parses → chunks → embeds from it. Keeping them after ingest means a re-ingest (re-chunk with new params, re-embed after a model change) needs no re-upload. At the demo's 5 MB/file cap, bytea in Postgres is the simplest correct choice — no object store to provision or secure. Object storage (S3/R2) with the row holding only a key is the documented path if file sizes or corpus volume grew.

## Why compute requeue backoff with the database clock, not the app clock?

The requeue sets `run_after` to "now + backoff" and the claim query filters `run_after <= now()` — if those two `now`s come from different clocks, backoff breaks. The first version computed `run_after` in Python (`datetime.now(UTC) + 2s`) while the claim compared against Postgres `now()`; under Docker Desktop / WSL2 the container clock can run *ahead* of the host, so a host-computed `run_after` was already in the container's past and the "backed-off" job was immediately re-claimable. Computing it DB-side (`now() + make_interval(secs => :n)`) uses one clock for both set and compare, so backoff is correct regardless of host/container skew. A test caught this — the kind of bug that hides until someone runs on a drifting clock.

## Why mark the document FAILED only on the worker's *last* attempt?

A transient embedding error should retry, so `ingest_document` re-raises it without recording a terminal status, and the `ClaimedJob` context manager turns that raise into a requeue-with-backoff. But if every attempt keeps failing transiently, the document would otherwise sit in INGESTING forever. So the worker checks `ClaimedJob.is_last_attempt`: on the final try it records a durable `FAILED` (with reason) and acks the job, instead of re-raising. Transient failures retry; exhausted retries become a visible terminal failure — no document left limbo. And `_run_one` swallows+logs after the context manager has already recorded ack/requeue, so a re-raised transient can't kill the consume loop.

# Phase 5 (ragent) — hybrid retrieval

## Why BM25 in-process (rank-bm25) instead of Postgres full-text search?

The sparse half could be Postgres `tsvector`/`ts_rank`, but BM25 is the better-understood lexical ranker and rank-bm25 keeps it transparent — I can see and tune the scoring instead of reasoning about Postgres FTS config (dictionaries, weights, `ts_rank` vs `ts_rank_cd`). It also keeps a `tsvector` column and its GIN index out of the schema. The cost is that the BM25 index is built per query from the corpus's chunk texts, which is fine at demo scale (hundreds–thousands of chunks); the documented optimization is a per-corpus cached index invalidated on ingest, or switching the sparse tier to Postgres FTS if corpora outgrow in-process memory.

## Why fuse on ranks (RRF) and keep only positive-scoring sparse hits?

RRF combines the dense and sparse lists using only each item's *rank position*, so there's nothing to normalize between a cosine distance (0–2) and a BM25 score (unbounded) — the reason RRF is robust to score-scale differences. Before fusing, the sparse list drops zero-score chunks: a BM25 score of 0 means the query shares no terms with the chunk, so including it would just pad the lexical list with non-matches and dilute the signal RRF is meant to capture. Dense always contributes its top-k by distance; sparse contributes only genuine lexical matches. An integration test pins the payoff: a chunk that's semantically far from the query embedding but shares keywords is lifted above a chunk that's exactly as far but shares none — which pure dense retrieval could never do.

## Why scope retrieval by both corpus_id and org_id?

The caller resolves the `Corpus` within the tenant, and chunks carry a denormalized `corpus_id`, so `corpus_id` alone is functionally sufficient. Adding `org_id` to the dense and sparse `WHERE` clauses is defense-in-depth: retrieval is the hot path the agent will call on every turn, and a belt-and-suspenders tenant filter there means a future bug that hands in a mis-scoped corpus still can't leak another org's chunks. Both columns are indexed, so it's free.

# Phase 6 (ragent) — optional cross-encoder rerank

## Why is the cross-encoder reranker off by default and behind an optional extra?

A cross-encoder (bge-reranker-base) genuinely improves ordering — it scores each (query, chunk) pair with full cross-attention instead of comparing pre-computed embeddings — but it pulls `sentence-transformers` + torch (a couple GB) and loads a model into memory. On a zero-traffic demo running shared-cpu-1x / 512 MB on Fly, that's a large, mostly-idle cost. So rerank ships as a *seam*: `PF_RERANK_ENABLED` defaults false (rerank is a passthrough that leaves the RRF order intact), and the dependency lives in an optional `rerank` extra that neither CI nor the default Docker image installs. Enabling it is a deliberate act — install the extra, flip the flag, size up the machine. Same judgment as deferring OpenTelemetry and the local bge embedding backend: wire the high-value-when-needed capability behind a clean, documented switch rather than carry the weight unconditionally. The interface is fully tested (passthrough, truncation, and — with the scorer mocked — the reorder logic) without ever importing torch.

## Why lazy-import + thread-offload the model when enabled?

The `from sentence_transformers import CrossEncoder` lives inside the scoring function, not at module top, so importing `rerank.py` (and running the whole test suite / the disabled path) never touches torch — only the first enabled call does, and the loaded model is cached in a module singleton after that. Inference is CPU-bound and synchronous, so `rerank` runs it via `asyncio.to_thread`; otherwise a multi-hundred-ms `predict()` would block the event loop and stall every other concurrent request the agent service is handling.

# Phase 7 (ragent) — agent tools

## Why these three tools (search / fetch / cite), split this way?

They map to the three distinct things a grounded-answer agent actually does, and keeping them separate keeps each ReAct step legible. `search_docs` returns *ranked snippets* — small, so the model can scan many candidates cheaply without blowing the context window. `fetch_passage` exists precisely because the snippets are truncated: when one looks promising, the model pulls its full text on demand instead of every result shipping its whole body. `cite_sources` is its own tool, not an inferred side effect of search, because grounding should be an explicit act — the model declares the chunk_ids its answer rests on, and that becomes the message's citations (the source drawer in the UI). Folding citation into search would cite everything retrieved, including passages the model looked at and discarded.

## Why do tool handlers return `{"error": ...}` dicts instead of raising?

In a ReAct loop the tool result is fed back to the model as the next observation, so an error is *information the model can act on* — "that chunk_id wasn't valid, search again" — not a failure that should abort the turn. A raised exception would unwind the loop and kill the whole response; an error dict lets the model self-correct on the next step, which is the entire point of the agent pattern. So every handler validates its arguments (the LLM routinely sends malformed args) and returns a structured error rather than throwing. The loop's own safety rails — max iterations, circuit breaker — are what bound a model that keeps erroring, not exceptions from the tools.

## Why are the tools corpus- and org-scoped at the handler, and why drop foreign ids silently?

The tools are the only surface the model can reach the database through, so tenant enforcement lives right there: every read filters `corpus_id` + `org_id`, and `fetch_passage`/`cite_sources` reject ids that resolve to another corpus. `cite_sources` *drops* out-of-corpus ids rather than erroring the whole call — a model that hallucinates one bad id among several good ones should still get a useful citation set, and silently excluding the bad one is safer than surfacing "this id exists elsewhere" (which would leak that another org has a chunk by that id). The requested order is preserved for the ids that are valid, so the citation list reflects the model's own ranking.

# Phase 8 (ragent) — agent loop + live system prompt

## Why a max-iteration cap *and* a duplicate-call circuit breaker?

They catch two different stuck states. The max-iteration cap bounds total cost and latency — a model that keeps finding "one more thing to check" can't run forever. The circuit breaker catches the more insidious failure: a model that calls the *same tool with the same arguments* over and over (it didn't like the result, but asks again identically). The cap alone would let it burn all six iterations on the identical call; the breaker trips after two repeats (tracked by a `name:sorted-args` signature) and short-circuits. Each duplicate is fed back as an error observation first, giving the model a chance to change course before the breaker fires. These are the safety rails that make ReAct production-safe — the transparency of the pattern is worthless if a bad turn can loop unbounded.

## Why force a tool-less completion when a rail fires, instead of returning the transcript?

When the cap or breaker trips, the loop has a pile of tool results but no answer the user can read. Returning that raw, or an empty string, is a bad experience. Instead it makes one final completion with the tools removed and a "answer now from what you have" instruction, so the user gets a coherent (if `truncated: True`) answer grounded in whatever was gathered. One extra call is a cheap price for never surfacing a dead-ended turn.

## Why is `run_agent` an async generator of events rather than a function returning an answer?

The chat route (Phase 9) needs to stream the agent's progress over SSE — tool-call chips as they happen, then the answer — so the loop yields small JSON events (`tool_call`, `tool_result`, `answer`) as it goes. A function that returned only the final answer would force Phase 9 to either lose the intermediate steps or re-derive them. Emitting events also keeps the loop the single source of truth for "what happened this turn," and makes it directly testable: collect the events and assert the sequence, no SSE plumbing needed. Citations declared via `cite_sources` are attached to the terminal `answer` event so the consumer gets answer + sources together.

## Why fetch the system prompt with a minted service JWT, cache it, and fall back to a default?

The live fetch is the platform-integration story — the agent's behavior is governed by a prompt managed in PromptForge — but it has to be both authenticated and robust. ragent authenticates by minting a short-lived access JWT with the *shared HS256 secret* for a configured service principal (the demo org/user), so apps/api validates it like any token with no extra round-trip — the same-secret, same-control rationale from the auth design. The result is TTL-cached so the agent isn't hitting apps/api on every message. And it falls back to a built-in `DEFAULT_SYSTEM_PROMPT` whenever the prompt isn't configured yet (the seed wires the id later) or the fetch fails — a managed-prompt feature must never be able to take the agent down, so a transient apps/api outage degrades to the default rather than erroring. Successful fetches (and the unconfigured default) are cached; a *failed* fetch is not, so the agent recovers on the next request once apps/api is back.

# Phase 9 (ragent) — chat SSE

## Why does the SSE generator own its DB session instead of taking the request one?

A FastAPI dependency-yielded session is torn down when the endpoint function returns — but a streaming endpoint *returns the `EventSourceResponse` immediately* and the generator body runs afterward, as the response streams. So a request-scoped session would already be closed by the time the agent's tools query through it. The generator opens its own session via `get_session_factory()` and holds it for the life of the turn — exactly the pattern apps/api's eval stream uses (a raw engine), for the same reason.

## Why persist the user message before the turn and the assistant message after?

The user message is committed up front so the turn is durable the moment it starts — if the agent errors or the stream drops mid-flight, the question isn't lost and the conversation stays consistent. History for the turn is loaded *before* that insert so the model sees prior turns but not a duplicate of the message it's currently answering. The assistant message is written after the loop finishes, carrying the answer plus its citations and the tool-call trail, so reloading the conversation reconstructs both the answer and how the agent reached it (the source drawer + tool chips) without re-running anything.

## Why only validate tokens in ragent (no issuance), and why is chat not behind a writer gate?

ragent never logs anyone in — it only *consumes* access tokens apps/api already issued, so `core/security.py` is decode-only: there's no password hashing, no refresh rotation, no session machinery to duplicate. And chat isn't gated to writer roles the way apps/api's mutations are: the whole point of the demo is that a read-only demo visitor can ask the agent questions over the seeded corpora. Chat does write `Conversation`/`Message` rows, but those are the caller's own transient turn history, not tenant content — so any authenticated principal, demo included, may chat.

## Why a BYOK header on chat, and what's still open?

Each chat turn spends real tokens on the hosted key, so `X-Provider-Key` lets a caller supply their own provider key (passed straight through to the loop) — the same BYOK posture as apps/api's run route. What's *not* built yet is the demo cost cap: apps/api meters free hosted-key runs per IP, and ragent chat should get the equivalent before the demo is public, or a determined visitor could run up the hosted-key bill. Tracked as a pre-deploy follow-up rather than built now, to keep this phase to the chat surface itself.

# Phase 10 (ragent) — corpora API + upload

## Why are corpus reads open to everyone but writes gated to writer roles?

The demo's value is browsing and chatting the seeded corpora, so listing corpora and their documents is open to any authenticated principal — demo included. Creating a corpus and uploading a document are different: each upload triggers an ingest that calls the embedding API on the hosted key, so an unmetered demo upload path is a direct way to run up cost (and fill storage). Gating those to writer roles (`owner`/`member`, excluding `demo`) is the same read-only-demo posture apps/api takes on its mutations — demo consumes, real signups produce. The caps below bound cost for the users who *can* upload.

## Why does upload return immediately with `pending` instead of ingesting inline?

Parsing a PDF, chunking, and embedding every chunk takes seconds to tens of seconds — far too long to hold an HTTP request open, and it would couple the upload's success to the embedding provider being up. So upload does the cheap, durable part synchronously (validate, store the bytes, write a `pending` Document) and hands the slow part to the ingest worker via the queue, returning the document id + status right away. The client polls `GET /corpora/{id}/documents` (or watches status) for progress. This is exactly why `documents.raw_content` and `enqueue_ingest` were built in Phase 4 — the upload endpoint is just their HTTP entry point. A failed ingest later surfaces as `status=failed` + `error` on the row, not as a failed upload.

## Why enforce both a per-file and a per-corpus byte cap?

They guard different things. The per-file cap (5 MB) stops a single huge upload from blowing out memory (the whole file is read into a bytea) and producing a runaway number of chunks/embeddings in one shot. The per-corpus cap (50 MB, checked as `sum(existing byte_size) + new`) bounds the *cumulative* cost and storage a single corpus can accrue across many small uploads — without it, the per-file limit alone lets someone upload 4.9 MB a thousand times. Both return 413 with a message naming the limit. At portfolio scale these are generous; they exist so the demo has a hard ceiling, and they're config knobs (`max_file_bytes`/`max_corpus_bytes`) for real deployments.

# Phase 11 (ragent) — seed

## Why does apps/api create the agent's system prompt while ragent only resolves it?

Two responsibilities, split by ownership again. apps/api owns prompts, so *creating* the "RAG Agent System Prompt" belongs in its seed (which already runs in the deploy release command and creates Demo Corp) — that keeps the "prompt managed in the platform" story honest. ragent only needs to *consume* it, and the awkward part is that apps/api seeds with random ids, so ragent can't be handed a fixed `version_id`/`org_id` in config (and the prod Demo Corp already has a random id — changing the seed to fixed ids would orphan it). So ragent *discovers* what to consume from the shared DB by natural key — the demo org by slug, the prompt by name — and then fetches the body over HTTP with a service JWT. This replaced the Phase-8 env-id wiring, which was fragile precisely because the ids are random. The result keeps the HTTP "consume via the API" integration story while making the discovery robust to reseeds: "find it by name in the shared store, fetch it through the API."

## Why does the seed run real ingestion instead of inserting pre-baked chunks?

The seeded corpora exist to make retrieval *demonstrably real* — the chat demo retrieves and cites actual passages — so the seed runs the same `ingest_document` path a user upload would (parse → chunk → embed), not a shortcut that inserts hand-written chunk rows with fake vectors. That means the demo's embeddings are produced by the real model and the seeded data exercises the exact pipeline being shown off. The cost is one embedding pass on each fresh database, which the bundled content is kept small (7 short docs) to bound; the seed is idempotent (ingest only when a document has zero chunks) so re-deploys don't re-embed. apps/api must be seeded first (it creates Demo Corp); if it isn't, the ragent seed no-ops with a message rather than failing.

## Why does ragent read apps/api's tables with raw SQL instead of modeling them?

The discovery queries touch orgs, memberships, prompts, and prompt_versions — all apps/api's domain. ragent could mirror those as ORM models, but that's four model definitions it would have to keep in lockstep with apps/api's schema, for read-only lookups it runs in two places. Raw `text()` queries against a tiny, stable subset of columns (a slug, a name, a version order) are the lighter, honest choice — the same reasoning as the queue client reading the shared `jobs` table by raw SQL. It's a one-directional read: ragent never writes these tables, so there's no integrity surface to own, just a discovery path. The tests stub those tables (the columns the queries read) so the cross-domain SQL is exercised against real Postgres without importing the api package.

# Phase 12 (ragent) — per-corpus embedding routing

## Why is the local bge embedding backend off by default, behind an extra?

Same trade as the cross-encoder reranker. The local bge-small model means no per-token API cost and data never leaving the box — genuinely useful — but it pulls sentence-transformers + torch (a couple GB) and loads a model into memory. The seeded corpora all use OpenAI, so the default deployment never needs it; making it the unconditional dependency would bloat every image for a path most deployments won't hit. So it lives in the optional `local-embeddings` extra and is lazy-loaded only when a corpus pinned to `bge_small_en_v1_5` is actually embedded (a singleton after first load, inference offloaded with `asyncio.to_thread` so it doesn't block the loop). A deployment that wants local embeddings installs the extra and sizes the machine for torch; everyone else carries nothing. The interface — routing, dimension validation, the query instruction — is fully tested with the model mocked, no torch in CI.

## Why does `embed_texts` take an `is_query` flag?

bge is an *asymmetric* retrieval model: per BAAI's guidance you prepend a short instruction ("Represent this sentence for searching relevant passages: ") to **queries** but not to the **passages** being searched, and skipping that on the query side measurably hurts recall. The same `embed_texts` embeds both — passages during ingest, the query during retrieval — so it needs to know which it's doing. `is_query` (default false, so ingest is correct without thinking about it) carries that; `hybrid_search` sets it true when embedding the query. The OpenAI path ignores the flag (text-embedding-3-small is symmetric), so the one parameter serves both backends without leaking bge-specific behavior into the OpenAI call. Column routing (1536 vs 384) was already settled in Phase 2/3 — this phase only had to make the bge branch produce real vectors and respect the instruction.
