/**
 * Next.js instrumentation hook. Used ONLY to start the in-process MSW mock for
 * the hermetic E2E suite — gated on a test-only env flag and the node runtime,
 * with a dynamic import so the mock (and `msw`) never loads in a normal build or
 * at runtime in production.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_PUBLIC_API_MOCKING === "enabled" && process.env.NEXT_RUNTIME === "nodejs") {
    const { server } = await import("./e2e/mocks/node");
    server.listen({ onUnhandledRequest: "bypass" });
  }
}
