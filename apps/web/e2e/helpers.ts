import { expect, type Page } from "@playwright/test";

/**
 * Sign in by calling the real BFF signup route — it sets the sealed session
 * cookie in the browser context, so subsequent `page.goto`s are authenticated.
 * Faster and less brittle than driving the signup form in every spec.
 */
export async function signIn(page: Page): Promise<void> {
  const res = await page.request.post("/api/auth/signup", {
    data: { email: "e2e@example.com", password: "supersecret1" },
  });
  expect(res.ok()).toBeTruthy();
}
