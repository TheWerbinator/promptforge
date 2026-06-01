# DEPLOY — apps/api on Fly.io

> Phase 10.5 deploy-smoke runbook. Goal: get `apps/api` + Postgres live on Fly.io and verify `/health`, `/docs`, `/api/v1/auth/signup`, `/api/v1/auth/login`, and one `POST /api/v1/versions/{id}/run` work end-to-end in production. This is a milestone, not a real deploy — we'll do the polished deploy (with seed + ragent + web) in phase 16.

## Prerequisites

- Fly CLI installed (`flyctl`)
- Logged in: `fly auth login`
- Docker Desktop running locally (for `fly deploy` image build)

## One-time setup

### 1. Launch the app (no deploy yet)

From `apps/api/`:

```sh
fly launch --no-deploy --copy-config --name promptforge-api --region ord
```

The `fly.toml` already on disk has the processes, services, health check, and `release_command = "alembic upgrade head"` ready. Decline the prompt to overwrite it.

### 2. Provision Postgres

```sh
fly postgres create --name promptforge-db --region ord --vm-size shared-cpu-1x --volume-size 1
fly postgres attach --app promptforge-api promptforge-db
```

`attach` sets `DATABASE_URL` as a secret on the api app. Our config expects `PF_DATABASE_URL`, so rename:

```sh
fly secrets set --app promptforge-api PF_DATABASE_URL="$(fly secrets list --app promptforge-api -j | jq -r '.[] | select(.Name==\"DATABASE_URL\") | .Value')"
```

Or set it manually using the DSN from `fly postgres connect`. The DSN must use the `postgresql+asyncpg://` scheme — replace the `postgres://` prefix Fly returns.

### 3. Required secrets

```sh
fly secrets set --app promptforge-api \
  PF_JWT_SECRET="$(openssl rand -hex 32)" \
  PF_COOKIE_SECURE=true \
  PF_CORS_ORIGINS='["https://promptforge.vercel.app"]'   # placeholder until web ships

# Optional — only needed when not using BYOK on every request:
fly secrets set --app promptforge-api \
  PF_OPENAI_API_KEY="sk-..." \
  PF_ANTHROPIC_API_KEY="sk-ant-..."
```

## Deploy

From `apps/api/`:

```sh
fly deploy
```

The release_command runs `alembic upgrade head` on a temporary machine before traffic shifts. If migrations fail, the deploy aborts and old machines keep serving (zero-downtime invariant).

## Smoke test

Once `fly deploy` reports success:

```sh
APP="https://promptforge-api.fly.dev"

# 1. Liveness
curl -fsS $APP/health
# Expect: {"status":"ok","version":"0.1.0"}

# 2. OpenAPI is reachable
curl -fsS -o /dev/null $APP/openapi.json && echo "openapi ok"

# 3. Signup
SIGNUP=$(curl -fsS -X POST $APP/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@promptforge.dev","password":"Smoke12345!","display_name":"Smoke"}')
TOKEN=$(echo $SIGNUP | jq -r .access_token)
echo "token len: ${#TOKEN}"

# 4. /me
curl -fsS $APP/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .user.email

# 5. Create a prompt
PROMPT=$(curl -fsS -X POST $APP/api/v1/prompts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"smoke","body":"Say hi to {{name}}","variables":[{"name":"name","type":"str"}]}')
VID=$(echo $PROMPT | jq -r .latest_version.id)
echo "version id: $VID"

# 6. Run it (BYOK — supply your own key on this call so it does not depend on
#    PF_OPENAI_API_KEY being set on the server).
curl -fsS -X POST "$APP/api/v1/versions/$VID/run" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Provider-Key: $OPENAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"openai/gpt-4o-mini","inputs":{"name":"Jake"}}' | jq '{output, latency_ms, error}'
```

If all six steps return cleanly, the smoke is green. Take a screenshot of the `/docs` page for the README, then move to phase 11.

## What we proved

- Docker image builds + boots on Fly
- Alembic release-command actually runs migrations against Fly Postgres
- asyncpg DSN scheme works end-to-end
- JWT auth round-trips through HTTPS (cookie_secure=true won't leak)
- TenantRepository + visibility + template rendering + LLM call work in prod
- /docs is publicly reachable (good for hiring teams)

## What we did NOT prove (intentional — later phases)

- Worker process consuming the queue (phase 11 wires it)
- SSE through Fly's proxy (phase 12)
- Demo mode + `/demo/login` (phase 13)
- Seed data (phase 15)
- ragent + web (separate apps, separate deploys)

## Roll back

```sh
fly releases --app promptforge-api
fly deploy --app promptforge-api --image registry.fly.io/promptforge-api:deployment-<previous-id>
```
