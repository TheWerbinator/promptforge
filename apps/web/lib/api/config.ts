/** Base URL of the PromptForge API. Used by the server-side BFF client and the
 *  landing page. NEXT_PUBLIC_ so it's available in both server and client code;
 *  the URL is not a secret. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Base URL of the ragent service (separate Fly app, shares the HS256 token, so
 *  the BFF attaches the same session access token). */
export const RAGENT_URL = process.env.NEXT_PUBLIC_RAGENT_URL ?? "http://localhost:8001";
