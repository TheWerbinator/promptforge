import { expect, test } from "@playwright/test";

test("landing renders and Try Demo drops into the dashboard", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "PromptForge", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "Try the demo" }).click();

  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  // Demo session: the topbar shows the read-only role.
  await expect(page.getByText("demo", { exact: true })).toBeVisible();
});
