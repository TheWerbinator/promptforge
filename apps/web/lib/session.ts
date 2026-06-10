import "server-only";

import { cookies } from "next/headers";

import { seal, unseal } from "./seal";
import type { SessionProfile } from "./types";

export type { SessionProfile };

/**
 * BFF session. The browser never sees the API tokens — they live here, in an
 * encrypted (JWE) httpOnly cookie on the WEB origin. `profile` is the small bit
 * of identity the UI needs; the tokens are used only by server-side code calling
 * the API. Sealing means the cookie value is opaque ciphertext, not a usable
 * bearer token if it ever leaks.
 */

const COOKIE = "pf_session";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30d, matches the API refresh TTL

export interface Session extends SessionProfile {
  accessToken: string;
  refreshToken: string;
}

export async function sealSession(session: Session): Promise<string> {
  return seal({ ...session });
}

export async function readSession(): Promise<Session | null> {
  const raw = (await cookies()).get(COOKIE)?.value;
  return unseal<Session>(raw); // tampered / expired key / malformed → null (logged out)
}

export async function writeSession(session: Session): Promise<void> {
  (await cookies()).set(COOKIE, await sealSession(session), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE_SECONDS,
  });
}

export async function clearSession(): Promise<void> {
  (await cookies()).delete(COOKIE);
}

export function toProfile(session: Session): SessionProfile {
  return {
    userId: session.userId,
    email: session.email,
    displayName: session.displayName,
    orgId: session.orgId,
    orgSlug: session.orgSlug,
    role: session.role,
  };
}

export const SESSION_COOKIE = COOKIE;
