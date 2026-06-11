import { expect, test } from "@playwright/test";

// Public, unauthenticated — no signIn.

test("public prompt share renders read-only", async ({ page }) => {
  await page.goto("/share/prompt-demo");
  await expect(page.getByText("Shared prompt")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Support Reply Drafter" })).toBeVisible();
  await expect(page.getByText("read-only")).toBeVisible();
});

test("public eval-report share renders the results", async ({ page }) => {
  await page.goto("/share/eval-demo");
  await expect(page.getByText("Shared eval report")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Support Reply Quality" })).toBeVisible();
  await expect(page.getByText("Pass rate")).toBeVisible();
});

test("a bad token shows the unavailable state", async ({ page }) => {
  await page.goto("/share/does-not-exist");
  await expect(page.getByText("This share link is no longer available")).toBeVisible();
});
