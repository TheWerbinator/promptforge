import "server-only";

import { EncryptJWT, jwtDecrypt } from "jose";
import { cookies } from "next/headers";

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

async function key(): Promise<Uint8Array> {
  const secret = process.env.WEB_SESSION_SECRET;
  if (!secret) throw new Error("WEB_SESSION_SECRET is not set");
  // Hash to a fixed 32-byte key so any-length secret works (and it's edge-safe).
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  return new Uint8Array(digest);
}

export async function sealSession(session: Session): Promise<string> {
  return new EncryptJWT({ ...session })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .encrypt(await key());
}

export async function readSession(): Promise<Session | null> {
  const raw = (await cookies()).get(COOKIE)?.value;
  if (!raw) return null;
  try {
    const { payload } = await jwtDecrypt(raw, await key());
    return payload as unknown as Session;
  } catch {
    return null; // tampered / expired key / malformed — treat as logged out
  }
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
