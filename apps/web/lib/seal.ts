import "server-only";

import { EncryptJWT, jwtDecrypt } from "jose";

/**
 * JWE seal/unseal used for any server-only secret we keep in a cookie (the auth
 * session, the BYOK provider key). The value is opaque ciphertext, not a usable
 * token if it ever leaks, and it's tamper-evident. Key is derived from a single
 * server secret so there's one thing to rotate.
 */

async function key(): Promise<Uint8Array> {
  const secret = process.env.WEB_SESSION_SECRET;
  if (!secret) throw new Error("WEB_SESSION_SECRET is not set");
  // Hash to a fixed 32-byte key so any-length secret works (and it's edge-safe).
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  return new Uint8Array(digest);
}

export async function seal(payload: Record<string, unknown>): Promise<string> {
  return new EncryptJWT(payload)
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuedAt()
    .encrypt(await key());
}

/** Decrypt a sealed value, or null if it's missing/tampered/unreadable. */
export async function unseal<T>(raw: string | undefined): Promise<T | null> {
  if (!raw) return null;
  try {
    const { payload } = await jwtDecrypt(raw, await key());
    return payload as unknown as T;
  } catch {
    return null;
  }
}
