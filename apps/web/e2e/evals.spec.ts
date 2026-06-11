import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("create a suite, add a case, run it, and watch the batch stream", async ({ page }) => {
  await page.goto("/evals/new");
  await page.getByLabel("Name").fill("E2E Suite");
  await page.getByRole("button", { name: "Create suite" }).click();
  await expect(page).toHaveURL(/\/evals\/[0-9a-f-]{36}/);

  // Add a case.
  await page.getByPlaceholder("variable").fill("topic");
  await page.getByPlaceholder("value").fill("otters");
  await page.getByLabel("Expected value").fill("otter");
  await page.getByRole("button", { name: "Add case" }).click();
  await expect(page.getByRole("heading", { name: "Cases (1)" })).toBeVisible();

  // Run against the seeded prompt's latest version.
  await page.getByLabel("Prompt (latest version)").selectOption({ label: "Seed Prompt" });
  await page.getByRole("button", { name: "Run batch" }).click();

  // Batch page: SSE streams a result then `done`; the page refetches final results.
  await expect(page).toHaveURL(/\/evals\/batches\/[0-9a-f-]{36}/);
  await expect(page.getByText("pass rate")).toBeVisible();
  await expect(page.getByText("Output contains the expected value.")).toBeVisible();
});
