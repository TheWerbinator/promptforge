import "server-only";

import { cookies } from "next/headers";

import { seal, unseal } from "./seal";

/**
 * BYOK (bring-your-own-key) provider key. A user can run the agent (and prompt
 * runs) on their own OpenAI/Anthropic key instead of the hosted demo key. The
 * key is a real secret, so it's kept in its own sealed, httpOnly cookie on the
 * web origin — never in localStorage and never readable by browser JS. The BFF
 * reads it server-side and forwards it as `X-Provider-Key`; it's a separate
 * cookie from the session so it has an independent lifetime and isn't touched by
 * token rotation.
 */

const COOKIE = "pf_byok";
const HEADER = "X-Provider-Key";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30d

interface ByokPayload {
  providerKey: string;
}

export async function readProviderKey(): Promise<string | null> {
  const raw = (await cookies()).get(COOKIE)?.value;
  const payload = await unseal<ByokPayload>(raw);
  return payload?.providerKey ?? null;
}

export async function writeProviderKey(providerKey: string): Promise<void> {
  (await cookies()).set(COOKIE, await seal({ providerKey }), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE_SECONDS,
  });
}

export async function clearProviderKey(): Promise<void> {
  (await cookies()).delete(COOKIE);
}

/** `{ "X-Provider-Key": key }` when a key is set, else `{}`. For proxy routes. */
export async function providerKeyHeader(): Promise<Record<string, string>> {
  const key = await readProviderKey();
  return key ? { [HEADER]: key } : {};
}

/** A non-secret preview so the UI can confirm which key is stored. */
export function maskKey(key: string): string {
  const tail = key.slice(-4);
  return key.length <= 8 ? `…${tail}` : `${key.slice(0, 3)}…${tail}`;
}
