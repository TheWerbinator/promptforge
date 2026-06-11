import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("create a prompt, see it, then delete it", async ({ page }) => {
  await page.goto("/prompts");
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
  await expect(page.getByText("Seed Prompt")).toBeVisible();

  await page.getByRole("link", { name: "New prompt" }).click();
  await expect(page).toHaveURL(/\/prompts\/new/);
  await page.getByLabel("Name").fill("E2E Prompt");
  await page.getByRole("button", { name: "Create prompt" }).click();

  // Lands on the detail page for the new prompt.
  await expect(page).toHaveURL(/\/prompts\/[0-9a-f-]{36}/);
  await expect(page.getByRole("heading", { name: "E2E Prompt" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Version history" })).toBeVisible();

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/prompts$/);
});
