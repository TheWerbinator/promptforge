/** Identity the UI needs. Safe to import from client components (no server-only
 *  code, no tokens). The full Session (with tokens) lives in lib/session.ts. */
export interface SessionProfile {
  userId: string;
  email: string;
  displayName: string | null;
  orgId: string;
  orgSlug: string;
  role: string;
}
