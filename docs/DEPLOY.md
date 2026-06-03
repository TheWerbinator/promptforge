# DEPLOY — apps/api on Fly.io + Neon

> Phase 16 production runbook. Gets `apps/api` (api + worker) live on Fly.io with
> Neon Postgres, demo data seeded, structured logging on, and a full smoke that
> covers auth, demo mode, eval streaming, and public share links. **Jake runs all
> of these commands** — this doc is the checklist.

The app is already provisioned (Phase 10.5). Day-to-day you just `git push` to `main`; CI runs and the `deploy` job in `.github/workflows/api.yml` ships it. The sections below are the one-time setup + the manual deploy/smoke path.

## Topology

- **Fly app** `promptforge-api`, region `ord`, two processes (`api` + `worker`) from one image.
- **Database** Neon Postgres 17 + pgvector, **direct (session-mode)** endpoint. *Not* Fly Postgres — see INTERVIEW-NOTES "Why Neon over Fly Managed Postgres or Supabase". The DSN normalizer in `core/config.py` rewrites any provider DSN to `postgresql+asyncpg://`.
- **Release step** runs migrations then the idempotent demo seed (see `fly.toml [deploy]`).

## One-time setup

### 1. Secrets

```sh
fly secrets set --app promptforge-api \
  PF_DATABASE_URL="postgresql://<user>:<pwd>@<neon-direct-host>/<db>?sslmode=require" \
  PF_JWT_SECRET="$(openssl rand -hex 32)" \
  PF_COOKIE_SECURE=true \
  PF_CORS_ORIGINS='["https://promptforge.vercel.app"]'
```

Use Neon's **direct** connection string (not the `-pooler` host): asyncpg's
prepared-statement cache breaks against PgBouncer transaction mode. The normalizer
handles the `postgresql://` scheme and `sslmode`→`ssl` rewrite.

**Hosted demo key (required for the free-run demo to work).** Demo visitors get a
few real runs on this key before BYOK; without it, every demo run 402s immediately.

```sh
fly secrets set --app promptforge-api PF_OPENAI_API_KEY="sk-..."
# and/or PF_ANTHROPIC_API_KEY="sk-ant-..."
```

Optional demo tuning (defaults shown): `PF_DEMO_FREE_RUNS=5`, `PF_DEMO_RATE_LIMIT=5/minute`, `PF_DEMO_EMAIL=demo@promptforge.dev`.

### 2. CI/CD deploy token

The `deploy` job needs `FLY_API_TOKEN` as a **GitHub Actions repo secret**:

```sh
fly tokens create deploy -x 999999h --app promptforge-api
# copy the output, then in GitHub: Settings → Secrets and variables → Actions →
# New repository secret → name FLY_API_TOKEN, paste value.
```

## Deploy

Normal path: merge to `main`; CI lints + types + tests, then the `deploy` job runs `flyctl deploy`. Manual deploy from `apps/api/`:

```sh
fly deploy
```

The release machine runs `alembic upgrade head && python -m promptforge_api.seed` before traffic shifts. Migration or seed failure aborts the release; old machines keep serving (zero-downtime invariant). The seed is idempotent — re-running it on every deploy is intended.

### Worker

The `worker` process consumes eval-batch jobs. The seeded demo eval batch is pre-computed (no worker needed to view it), and demo accounts can't launch batches, so the worker can sit at 0 to save cost until a real signed-up user runs evals:

```sh
fly scale count worker=1   # enable eval-batch processing
fly scale count worker=0   # idle / cost-saving
```

Scale tracks **deploy** state, not commit state — only bring the worker up after a successful deploy, and down when there's no eval traffic.

## Smoke test

```sh
APP="https://promptforge-api.fly.dev"

# 1. Liveness + version
curl -fsS $APP/health
# 2. OpenAPI + docs reachable (hiring teams open /docs)
curl -fsS -o /dev/null $APP/openapi.json && echo "openapi ok"
curl -fsS -o /dev/null $APP/docs && echo "docs ok"

# 3. Demo login works (the seed ran in the release step)
DEMO=$(curl -fsS -X POST $APP/api/v1/demo/login)
echo "$DEMO" | jq '{role, org: .org.slug, free_runs_remaining}'
DTOKEN=$(echo "$DEMO" | jq -r .access_token)

# 4. Demo session is read-only (expect 403)
curl -s -o /dev/null -w '%{http_code}\n' -X POST $APP/api/v1/prompts \
  -H "Authorization: Bearer $DTOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"x","body":"y","variables":[]}'   # expect 403

# 5. Seeded public share links resolve (no auth)
curl -fsS $APP/api/v1/public/share/demo-prompt-support-reply | jq '.prompt.name'
curl -fsS $APP/api/v1/public/share/demo-eval-support-quality | jq '.eval_batch | {status, pass_rate}'

# 6. A free demo run on the hosted key (no BYOK) — proves PF_OPENAI_API_KEY is set
VID=$(curl -fsS $APP/api/v1/public/share/demo-prompt-support-reply | jq -r '.prompt.latest_version.version')
# (browse /docs to grab a real version id, or sign up and run; the share view
#  exposes the body but not the version id by design.)

# 7. Every response carried a request id
curl -fsS -D - -o /dev/null $APP/health | grep -i x-request-id
```

Green smoke = auth, demo mode, read-only enforcement, public shares, and the seed/release pipeline all work in prod. For the live SSE path, sign up, create a suite + case, `POST /eval-suites/{id}/run`, and `curl -N` the `/eval-batches/{id}/stream` endpoint with the worker scaled to 1 — you should see `event: open`, `event: result`, `event: done`.

## Observability

Structured logs (structlog) are JSON in prod, console when `PF_LOG_LEVEL=DEBUG`.
Each line carries `request_id`; the same id is on the `X-Request-ID` response
header. View: `fly logs --app promptforge-api`.

OpenTelemetry tracing is deliberately not wired (see INTERVIEW-NOTES). The single
enable point is the lifespan in `main.py`, gated on `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Roll back

```sh
fly releases --app promptforge-api
fly deploy --app promptforge-api --image registry.fly.io/promptforge-api:deployment-<previous-id>
```
