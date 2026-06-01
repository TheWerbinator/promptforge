# PROGRESS

> Single source of truth for "where we are." Updated at the end of every phase per [feedback-phase-wrap]. If you're a fresh chat picking this up, read the **Bootstrap** section at the bottom first.

**Current position:** apps/api Phase 11 DONE — eval engine landed (suite + case CRUD, batch run, all 4 judges, queue-driven worker handler, SSE stream endpoint). **193 tests pass** end-to-end (3× consecutive, no flake after fixing global-engine leak in test fixture). Fly worker scaled back to 1 (`fly scale count worker=1`); ready for prod eval batches once Phase 11 commit lands and `fly deploy` runs. Next: Phase 12 (eval e2e against real Fly + screenshot dashboard) → Phase 13 (demo mode).

**Fresh-chat bootstrap:** if you're picking this up cold, read this file's Bootstrap section at the bottom first. Short version: 11 of 17 apps/api phases done; api + Postgres live on Fly+Neon; ~6 more apps/api phases (12-17) then apps/ragent + apps/web. INTERVIEW-NOTES.md has 30+ defendable "Why" entries — read before any architecture conversation.

**Last verified locally:** 2026-05-29 — 71 unit tests pass; ruff + format + mypy --strict clean across 26 source files. Integration/e2e (~70 tests) require Docker for testcontainers Postgres; not run today.

---

## apps/api — 7 / 17 phases done (~41%)

- [x] **Phase 1 — Bootstrap.** repo init, pyproject (uv + hatchling), FastAPI hello, `/health`, Dockerfile, fly.toml, CI skeleton.
- [x] **Phase 2 — DB + Alembic.** Async SQLAlchemy 2.x, naming convention, async-mode Alembic via asyncpg only (no separate sync driver). Models: User, Org, Membership, OrgRole. Migration `20260523_0001`.
- [x] **Phase 3 — Auth + refresh tokens.** argon2id passwords, HS256 JWT, HMAC-stored refresh tokens with rotation + chain-revocation replay defense, API keys (`pf_live_<prefix>_<secret>` with argon2 hash + prefix lookup). Migration `20260525_0002`.
- [x] **Phase 4 — TenantRepository + tenancy contract.** Generic `TenantRepository[T]`, `get_repo(Model)` dep factory, `tests/tenancy/_helpers.py`, ApiKey tenancy contract applied.
- [x] **Phase 5 — Prompts + versions CRUD.** Prompt + PromptVersion models (append-only versions), visibility enum (private/org/public), routes for list/create/get/patch/delete + version create/list/get-by-id, pagination + q/tag/visibility filters. Migration `20260525_0003`. `TenantRepository.list/count` gained a `where` kwarg.
- [x] **Phase 6 — `core/prompts.py` typed templates.** `PromptVariable`, `PromptTemplate`, applicative `render()` (collects every error before raising), `fingerprint()`, wired into create routes so invalid templates return 422.
- [x] **Phase 7 — `core/async_utils.py`.** `retry` decorator (exponential/linear/constant + equal jitter), `TokenBucket` with injectable clock/sleep for testability, `rate_limited` decorator, `gather_bounded` w/ overloaded raise/collect.
- [x] **Phase 8 — `core/queue.py` + worker.** Postgres `SELECT FOR UPDATE SKIP LOCKED` queue w/ CTE-based atomic claim, `LISTEN/NOTIFY` fanout (channel `jobs` for enqueue events, `batch_<uuid>` for SSE eval progress), Job model on BIGSERIAL w/ partial index on queued rows, `ClaimedJob` async-context-manager (ack on clean exit / requeue-with-backoff on raise / mark failed after max_attempts), `workers/eval_worker.py` skeleton process w/ graceful SIGINT/SIGTERM. Migration `20260529_0004`. 8 integration tests cover happy path, kind filter, run_after, ack, requeue, terminal fail, SKIP LOCKED no-double-claim concurrency, batch_progress aggregation.
- [x] **Phase 9 — `services/llm.py`.** litellm async wrapper (`call_llm`). Transient-only retry (APIConnectionError, Timeout, RateLimitError, APIError) — auth/bad-request propagate immediately. Global TokenBucket (10/s) for the hosted demo key; BYOK calls skip the limiter (user hits their own quota). Typed `LLMResponse` dataclass w/ text/tokens/cost/latency/raw. Cost via `litellm.completion_cost`; falls back to None if pricing unknown. 9 unit tests w/ fully mocked `litellm.acompletion`.
- [x] **Phase 10 — Runs.** `Run` model (org_id-scoped, version_id FK, output/tokens/cost/latency/error/provider_response, `Numeric(12, 6)` for cost precision), migration `0005`. `POST /api/v1/versions/{id}/run` → resolves version via parent prompt (tenancy), validates inputs via `PromptTemplate.render`, calls `services.llm.call_llm`, persists Run row (including on LLM failure — error column captures it). `GET /api/v1/runs/{id}` via TenantRepository. Demo users must supply `X-Provider-Key` (BYOK). 7 e2e tests w/ mocked LLM (happy path, invalid vars 422, LLM-failure-persists, cross-org POST 404, cross-org GET 404, auth required, unknown version 404). 3 integration tests on the Run model. **Also fixed phase-8 NOTIFY bug** — Postgres `NOTIFY` doesn't accept bound params; switched to `pg_notify()` function form.

## apps/api — pending

- [x] **Phase 10.5 — DEPLOY SMOKE.** *Done 2026-06-01.* Decisions locked: Neon free tier over Fly MPG ($38/mo floor) / unmanaged Fly Postgres (no support) / Supabase (PgBouncer footgun). Postgres 17 across testcontainers + compose + prod. `Settings.async_database_url()` normalizer handles bare `postgresql://`, `postgres://`, and `sslmode` → `ssl` rewriting so any provider DSN works (unit-tested w/ 5 DSN shapes). Dockerfile: added `README.md` to early COPY so hatchling validates during `uv sync`. Two Fly machines provisioned (`api` + `worker`); worker can scale to 0 via `fly scale count worker=0` until Phase 11 — effective demo cost under $0.50/mo. **Smoke validated end-to-end against `https://promptforge-api.fly.dev`:** /health, /openapi.json, /docs, signup, /me, prompt create, run (the run without BYOK proved the failed-run-persists-with-error design works in prod). *TODO: screenshot /docs for README header.*
- [x] **Phase 11 — Eval engine.** EvalSuite/EvalCase/EvalBatch/EvalResult models w/ unique(batch, version, case) for idempotent re-runs, migration `0006`. Four judges (`services/judge.py`): exact (whitespace-trimmed), contains (case_sensitive flag), regex (re.IGNORECASE/MULTILINE/DOTALL flags), llm_judge (separate LLM call w/ rubric, JSON-only response, threshold default 0.7, clamped to [0,1]). `services/eval_runner.py` orchestrates per-job execution: render template → call_llm (failed-run pattern preserved) → grade → upsert EvalResult via `ON CONFLICT` → atomic completed_jobs increment → pg_notify on batch channel. Routes (`api/v1/evals.py`): POST suite, POST cases, POST run (enqueues version × case jobs onto Postgres queue), GET batch detail, **GET /eval-batches/{id}/stream** SSE endpoint using asyncpg `add_listener` on the batch channel with heartbeat + done event. Worker handler wired (`kind=eval_case` → `run_eval_case`). 14 unit tests for judges (incl. LLM-judge mocked w/ threshold + clamp + non-JSON + call-failure paths), 4 e2e batch tests w/ in-process worker drain. Added `sse-starlette` dep. Also fixed test conftest leaking the module-global asyncpg engine across tests.
- [ ] **Phase 12 — Eval e2e.** Full flow test: create suite → run → SSE events → batch done.
- [ ] **Phase 13 — Demo mode.** `/demo/login`, role enforcement, BYOK header, slowapi rate-limit. Refresh-token reaper (see TODOs).
- [ ] **Phase 14 — Public share.** ShareToken model + `/public/share/{token}`.
- [ ] **Phase 15 — Seed.** `scripts/seed_demo.py` idempotent demo data.
- [ ] **Phase 16 — Deploy + smoke.** Fly deploy, fly postgres attach, secrets, OpenAPI accessible at deployed URL. Wire structlog + OTel (see TODOs).
- [ ] **Phase 17 — README + INTERVIEW-NOTES polish.** README header gets demo URL, screenshots, Loom link.

## apps/ragent — 0 / 14

Not started. Depends on apps/api having stable `/prompts/{id}/versions/{id}` GET so ragent can fetch its system prompt live. Plan in `PLAN.md` §6 / `apps/ragent` deep plan.

## apps/web — 0 / 16

Not started. Depends on apps/api OpenAPI being stable. Plan in `PLAN.md` §7 / `apps/web` deep plan.

## Integration + polish — 0 / 3

Root README polish, demo seed validation, end-to-end smoke. After all three apps deploy.

---

## Open TODOs in code

Grep `TODO(phase-` to refresh:

| File | Line | Tag | What |
|---|---|---|---|
| `apps/api/promptforge_api/main.py` | 16 | phase-16 | Wire structlog + OpenTelemetry in `lifespan`. |
| `apps/api/promptforge_api/models/api_key.py` | 3 | phase-5+ | Add `scopes` jsonb column for least-privilege keys. |
| `apps/api/promptforge_api/models/refresh_token.py` | 3 | phase-13 | Add `user_agent` + `ip_address` for forensics + "sign out everywhere." |
| `apps/api/promptforge_api/api/v1/auth.py` | 227 | phase-13 | Periodic reaper for expired refresh tokens. |
| `apps/api/promptforge_api/api/v1/auth.py` | 341 | phase-5+ | Per-key scopes enforcement. |
| `apps/api/promptforge_api/api/v1/prompts.py` | 240 | phase-5+ | Collapse `next_version_number` + insert into one statement (kill race window). |
| `apps/api/tests/e2e/test_prompts_flow.py` | 133 | phase-7+ | Real "private prompt hidden from same-org peer" test once member-invites land. |

## Code health snapshot

- **26 source files**, ~880 statements.
- **141 tests written** (71 unit + 6 integration models + 8 tenancy + ~56 e2e — last full run was on prior session, today only unit verified).
- **Coverage:** 81% project; `core/prompts.py` 100%; `core/security.py` 100%; `core/async_utils.py` brand-new, expected high.
- **CI workflow:** `.github/workflows/api.yml` — split into unit (3.11/3.12 matrix) + integration (testcontainers).

---

## Bootstrap (for a fresh chat picking this up)

Read in this order:

1. **`c:/Users/Shawn/Documents/GitHub/CLAUDE.md`** — project goal + working rules. Auto-loaded.
2. **`c:/Users/Shawn/.claude/projects/c--Users-Shawn-Documents-GitHub/memory/MEMORY.md`** — index of feedback + project memories. Auto-loaded. Pay attention to: `feedback-git-handling` (never run git), `feedback-no-pypi` (no published libs), `feedback-defensibility` (every choice must defend in interview), `feedback-ai-use-style` (avoid AI tells), `feedback-phase-wrap` (this doc + INTERVIEW-NOTES update at end of every phase), `feedback-phase-commits` (~10-15 line commit body).
3. **`c:/Users/Shawn/Documents/GitHub/PLAN.md`** — the master plan. Static, doesn't track progress — use this PROGRESS.md for state.
4. **This file (PROGRESS.md)** — current position + last decision + open TODOs.
5. **`promptforge/docs/ARCHITECTURE.md`** — system shape after most recent phase.
6. **`promptforge/docs/INTERVIEW-NOTES.md`** — defendable "Why" for every locked-in decision. Read before any architecture conversation.
7. **Verify locally:** `cd c:/Users/Shawn/Documents/GitHub/promptforge/apps/api && uv run pytest -m "not integration and not e2e" -q` — unit tests should be green without Docker. Integration/e2e need Docker Desktop running.

**Caveman mode** is active by default; respect it. Code/commits/docs ignore caveman mode (write normal English).

**Jake handles all git.** Never `git init`, `git add`, `git commit`, `git push`, `git status`, `git log`, `git diff`. Just write files; he commits.
