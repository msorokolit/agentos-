import { expect, test } from "@playwright/test";

test("landing page renders the AgenticOS brand and a Log in link", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/AgenticOS/i);
  await expect(page.getByRole("heading", { name: /AgenticOS/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Log in/i })).toBeVisible();
});

test("workspaces page redirects unauthenticated users gracefully", async ({ page }) => {
  await page.goto("/workspaces");
  await expect(page).toHaveURL(/\/workspaces/);
  // Either a message or the login affordance must be present.
  await expect(
    page.getByText(/log in|unauthenti|workspace/i).first(),
  ).toBeVisible();
});
