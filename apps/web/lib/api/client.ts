"use client";

/**
 * Client-side API helpers. Call the BFF proxy, which attaches the session token
 * server-side — the browser never holds a token. `api` targets the platform API
 * (/api/pf), `ragent` targets the ragent service (/api/pf-ragent). Pass paths
 * without a leading slash, e.g. `api.get("api/v1/prompts")`.
 */

export interface ClientResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
}

function makeClient(prefix: string) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<ClientResult<T>> {
    const res = await fetch(`${prefix}/${path}`, {
      method,
      headers: body !== undefined ? { "content-type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (res.status === 204) return { ok: true, status: 204, data: null, error: null };

    const text = await res.text();
    const json: unknown = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = json as { error?: string; detail?: string } | null;
      return {
        ok: false,
        status: res.status,
        data: null,
        error: err?.error ?? err?.detail ?? res.statusText,
      };
    }
    return { ok: true, status: res.status, data: json as T, error: null };
  }

  return {
    get: <T>(path: string) => request<T>("GET", path),
    post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
    patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
    del: <T>(path: string) => request<T>("DELETE", path),
  };
}

export const api = makeClient("/api/pf");
export const ragent = makeClient("/api/pf-ragent");
