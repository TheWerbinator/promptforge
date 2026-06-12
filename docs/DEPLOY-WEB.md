# Deploy runbook — apps/web (Vercel)

The Next.js frontend deploys to **Vercel** via its native GitHub integration:
push to `main` → Vercel builds and promotes to Production; pull requests get
Preview deployments. There is no GitHub Actions deploy job for web (CI only runs
lint + typecheck + build + the Playwright E2E suite).

Production URL: **https://thewerbinator-promptforge.vercel.app** *(confirm in Vercel →
Settings → Domains; use the domain actually assigned to Production).*

## One-time Vercel project setup

This is a **polyglot monorepo** — the Next app is in `apps/web`, not the repo
root. The single most important setting:

- **Settings → General → Root Directory = `apps/web`.** The Next app lives in a
  subdirectory; without this Vercel builds from the repo root and finds no app.
- **Settings → Build and Deployment → Framework Preset = `Next.js`.** Do **not**
  assume this auto-detects — for this project it imported as **"Other"**, which
  produced a *green* build that served Vercel's platform `NOT_FOUND` on every
  route (the build ran but Next.js routing/functions were never wired up).
  Setting it to Next.js fixed it. Leave **Output Directory** empty (Next manages
  it — an override like `out`/`.next` breaks serving), build/install at defaults.
- Node version: 24 (matches CI); Vercel's default LTS is fine.

## Environment variables (Settings → Environment Variables)

Set all three for **Production** (and **Preview** if you want preview deploys to
function):

| Variable | Example | Notes |
|---|---|---|
| `WEB_SESSION_SECRET` | `openssl rand -base64 32` | **Server-only** (no `NEXT_PUBLIC_`). Seals the JWE session + BYOK cookies. Read at runtime, so changing it doesn't need a rebuild — but it logs everyone out and orphans BYOK cookies. Keep it stable. |
| `NEXT_PUBLIC_API_URL` | `https://promptforge-api.fly.dev` | apps/api origin. |
| `NEXT_PUBLIC_RAGENT_URL` | `https://promptforge-ragent.fly.dev` | apps/ragent origin (chat + corpora). |

- `NEXT_PUBLIC_*` are **inlined at build time** — set them *before* the build;
  changing one requires a redeploy. `WEB_SESSION_SECRET` is runtime-only.
- **Do NOT set `NEXT_PUBLIC_API_MOCKING`.** That flag is E2E-only; if it's
  `enabled`, the server boots the in-process MSW mock and every API call hits
  fake data.
- No CORS config is needed on the backends: the browser only talks to the Vercel
  origin (the BFF); all upstream calls are server-to-server.

## Deploy

Push to `main` (or merge a PR). Vercel builds from `apps/web`, runs `next build`,
and promotes to Production on success. Watch the build log in the Vercel
dashboard; a green deployment is aliased to the production domain automatically.

## Smoke (after a deploy)

The backends auto-stop when idle, so the first call may cold-start (~45 s). Run
against the production URL:

```sh
BASE=https://thewerbinator-promptforge.vercel.app

# 1. Landing renders (static, no API call)
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/"                 # 200

# 2. Demo login through the BFF → live api, sets the sealed session cookie
curl -s -i -X POST "$BASE/api/auth/demo" | grep -E "HTTP/|set-cookie: pf_session"

# 3. Authenticated data through the BFF proxy (use the cookie jar in a browser
#    or a scripted client): GET /api/pf/api/v1/prompts → the 3 seeded prompts;
#    GET /api/pf-ragent/api/v1/corpora → the 3 seeded corpora.

# 4. Demo is read-only: POST /api/pf/api/v1/prompts → 403.

# 5. Public share route renders: /share/<bad-token> → the branded
#    "no longer available" page (HTML, not a platform 404).
```

In a browser: open `/`, click **Try the demo** → lands on `/dashboard` with the
seeded workspace; open **Chat**, pick a corpus, ask a question → a streamed,
cited answer. (Chat/demo runs use the hosted key's free quota, then prompt for
BYOK.)

## Troubleshooting

- **Green build but every route returns `x-vercel-error: NOT_FOUND`** (plain-text
  "The page could not be found", *not* our branded 404): **Framework Preset is
  "Other" instead of Next.js** (this actually happened on first deploy). Vercel
  ran `next build` but never set up Next routing/functions, so it serves the
  output as an empty static site. Fix in Settings → Build and Deployment →
  Framework Preset → **Next.js**, then redeploy. Confirm via the build log line
  `Detected Next.js version: …` — if it's absent, the preset is wrong. (Note:
  this is *not* an API problem — the landing is static and makes no API calls,
  so a down backend can't 404 it.) A related-but-different symptom is the
  *production domain* 404ing while the deployment's own **Visit** URL serves —
  that's a domain/alias issue (Settings → Domains), not the build.
- **Build fails with `Cannot find module '@/lib/...'`** for files that exist and
  build locally: they were caught by the root Python `.gitignore` and never
  pushed (the `lib/` / `build/` / `dist/` rules). The root `.gitignore` already
  negates `!apps/web/lib/`; if it recurs on a new dir, add the matching negation
  and confirm with `git status` that the source is tracked.
- **Auth works but data calls fail in prod**: a `NEXT_PUBLIC_*` URL is wrong or
  was changed without a rebuild (they're inlined at build time → redeploy).
- **Everyone got logged out after a deploy**: `WEB_SESSION_SECRET` changed.
