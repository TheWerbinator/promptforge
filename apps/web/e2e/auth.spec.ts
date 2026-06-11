import { expect, test } from "@playwright/test";

test("protected route redirects to login when unauthenticated", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
});

test("signup signs in, logout clears the session", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("supersecret1");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page).toHaveURL(/\/dashboard/);
  // Topbar reflects the signed-in identity returned by the BFF.
  await expect(page.getByText("e2e@example.com")).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);

  // Session cookie is gone: hitting a protected route bounces to login again.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});
