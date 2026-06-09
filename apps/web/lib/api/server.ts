import "server-only";

import { clearSession, readSession, writeSession, type Session } from "../session";
import { API_URL } from "./config";
import type { components } from "./schema";

/**
 * Server-side API client for the BFF. Browser code never calls the API directly;
 * route handlers use these helpers, which attach the access token from the sealed
 * session and transparently refresh it on a 401.
 */

type AuthSuccess = components["schemas"]["AuthSuccessResponse"];
type DemoLogin = components["schemas"]["DemoLoginResponse"];

/** The subset of auth/demo responses we need to build a Session. */
interface AuthLike {
  access_token: string;
  user: { id: string; email: string; display_name: string | null };
  org: { id: string; slug: string };
  role: string;
}

const REFRESH_COOKIE = "pf_refresh"; // must match apps/api REFRESH_COOKIE

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
}

function setCookieHeaders(headers: Headers): string[] {
  // getSetCookie() exists on the runtime (undici) Headers but isn't in the DOM lib types.
  const h = headers as unknown as { getSetCookie?: () => string[] };
  return h.getSetCookie?.() ?? [];
}

function extractRefreshCookie(headers: Headers): string | null {
  for (const cookie of setCookieHeaders(headers)) {
    const match = new RegExp(`^${REFRESH_COOKIE}=([^;]+)`).exec(cookie);
    if (match) return decodeURIComponent(match[1]);
  }
  return null;
}

function sessionFrom(body: AuthLike, refreshToken: string): Session {
  return {
    accessToken: body.access_token,
    refreshToken,
    userId: body.user.id,
    email: body.user.email,
    displayName: body.user.display_name ?? null,
    orgId: body.org.id,
    orgSlug: body.org.slug,
    role: body.role,
  };
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return res.statusText || "request failed";
  }
}

/** Log in or sign up against the API. Returns a Session the caller seals into a cookie. */
export async function authenticate(
  path: "/api/v1/auth/login" | "/api/v1/auth/signup",
  payload: Record<string, unknown>,
): Promise<ApiResult<Session>> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!res.ok) return { ok: false, status: res.status, data: null, error: await errorDetail(res) };

  const body = (await res.json()) as AuthSuccess;
  const refreshToken = extractRefreshCookie(res.headers);
  if (!refreshToken) {
    return { ok: false, status: 502, data: null, error: "API did not return a refresh token" };
  }
  return { ok: true, status: res.status, data: sessionFrom(body, refreshToken), error: null };
}

/** Start a demo session (read-only, no signup). The API seeds the demo org. */
export async function authenticateDemo(): Promise<ApiResult<Session>> {
  const res = await fetch(`${API_URL}/api/v1/demo/login`, { method: "POST", cache: "no-store" });
  if (!res.ok) return { ok: false, status: res.status, data: null, error: await errorDetail(res) };

  const body = (await res.json()) as DemoLogin;
  const refreshToken = extractRefreshCookie(res.headers);
  if (!refreshToken) {
    return { ok: false, status: 502, data: null, error: "API did not return a refresh token" };
  }
  return { ok: true, status: res.status, data: sessionFrom(body, refreshToken), error: null };
}

async function refresh(session: Session): Promise<Session | null> {
  const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { cookie: `${REFRESH_COOKIE}=${session.refreshToken}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  const body = (await res.json()) as { access_token: string };
  const rotated = extractRefreshCookie(res.headers) ?? session.refreshToken;
  return { ...session, accessToken: body.access_token, refreshToken: rotated };
}

/** Best-effort API logout (revokes the refresh-token chain). */
export async function apiLogout(session: Session): Promise<void> {
  try {
    await fetch(`${API_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: { cookie: `${REFRESH_COOKIE}=${session.refreshToken}` },
      cache: "no-store",
    });
  } catch {
    // best-effort; the local session cookie is cleared regardless
  }
}

/**
 * Authenticated API call, for use inside ROUTE HANDLERS (where cookies are
 * writable). Attaches the access token; on 401, refreshes once, persists the
 * rotated session, and retries.
 *
 * Not safe during Server Component render — refresh needs a writable-cookie
 * context. Later data-fetching phases proxy through handlers or refresh in
 * middleware.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  base: string = API_URL,
): Promise<ApiResult<T>> {
  const session = await readSession();
  if (!session) return { ok: false, status: 401, data: null, error: "not authenticated" };

  const send = (accessToken: string): Promise<Response> => {
    const headers = new Headers(init.headers);
    headers.set("authorization", `Bearer ${accessToken}`);
    if (init.body) headers.set("content-type", "application/json");
    return fetch(`${base}${path}`, { ...init, headers, cache: "no-store" });
  };

  let res = await send(session.accessToken);
  if (res.status === 401) {
    const refreshed = await refresh(session);
    if (!refreshed) {
      await clearSession();
      return { ok: false, status: 401, data: null, error: "session expired" };
    }
    await writeSession(refreshed);
    res = await send(refreshed.accessToken);
  }

  if (!res.ok) return { ok: false, status: res.status, data: null, error: await errorDetail(res) };
  const data = res.status === 204 ? null : ((await res.json()) as T);
  return { ok: true, status: res.status, data, error: null };
}

/**
 * Open an upstream SSE (or any streaming) response with the session's access
 * token, refreshing once on a 401. Returns the raw upstream Response so a route
 * handler can pipe `.body` straight to the browser. Use from a route handler.
 */
export async function apiStream(
  path: string,
  opts: { base?: string; method?: string; body?: string } = {},
): Promise<Response> {
  const base = opts.base ?? API_URL;
  const session = await readSession();
  if (!session) return new Response("not authenticated", { status: 401 });

  const open = (accessToken: string): Promise<Response> => {
    const headers: Record<string, string> = {
      authorization: `Bearer ${accessToken}`,
      accept: "text/event-stream",
    };
    if (opts.body) headers["content-type"] = "application/json";
    return fetch(`${base}${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body,
      cache: "no-store",
    });
  };

  let res = await open(session.accessToken);
  if (res.status === 401) {
    const refreshed = await refresh(session);
    if (!refreshed) {
      await clearSession();
      return new Response("session expired", { status: 401 });
    }
    await writeSession(refreshed);
    res = await open(refreshed.accessToken);
  }
  return res;
}
