import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("ask the agent and get a streamed, cited answer", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Chat" })).toBeVisible();

  const input = page.getByPlaceholder("Ask about this corpus…");
  await expect(input).toBeEnabled(); // corpus auto-selected once corpora load
  await input.fill("How are prompts versioned?");
  await page.getByRole("button", { name: "Send" }).click();

  // The user message, then the streamed assistant answer + its citation.
  await expect(page.getByText("How are prompts versioned?")).toBeVisible();
  await expect(page.getByText(/append-only so every run is reproducible/)).toBeVisible();
  await expect(page.getByText("Sources")).toBeVisible();
  await expect(page.getByText("Prompts are append-only versioned.")).toBeVisible();
});
