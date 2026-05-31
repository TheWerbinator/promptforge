# PROGRESS

> Single source of truth for "where we are." Updated at the end of every phase per [feedback-phase-wrap]. If you're a fresh chat picking this up, read the **Bootstrap** section at the bottom first.

**Current position:** apps/api Phase 8 done (`core/queue.py` + Job model + migration + eval_worker skeleton + queue integration tests). Strategic check 2026-05-29 confirmed direction; quality bar set to "senior engineer takes seriously"; Phase 10.5 deploy-smoke inserted. Next: Phase 9 (`services/llm.py` — litellm wrapper w/ retry + rate_limit).

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

## apps/api — pending

- [ ] **Phase 9 — `services/llm.py`.** litellm wrapper with `retry` + `rate_limited` applied, cost computation, mocked tests.
- [ ] **Phase 10 — Runs.** `POST /versions/{id}/run`, Run model + endpoint, services + repo + tests.
- [ ] **Phase 10.5 — DEPLOY SMOKE.** Push api + Postgres to Fly. Verify `/health` + `/auth/signup` + `/docs` + one `/run` work in production. Half-day; de-risks the deploy infra before 6 more phases depend on it. *(Added 2026-05-29 per `feedback-phase-strategy`.)*
- [ ] **Phase 11 — Eval engine.** EvalSuite/EvalCase/EvalBatch/EvalResult, 4 judge types (exact/contains/regex/llm_judge), batch runner, SSE stream.
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
