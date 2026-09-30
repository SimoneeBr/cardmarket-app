import { expect, test } from "@playwright/test";

test("session expiry is detected, shown, notified and recovered by re-pairing", async ({ page }) => {
  await page.goto("/settings/connection");
  const status = page.getByTestId("connection-status");
  await expect(status).toHaveAttribute("data-status", "CONNECTED");

  await page.getByTestId("simulate-session-expired").click();
  await expect(status).toHaveAttribute("data-status", /AUTH_REQUIRED|SESSION_EXPIRED/, { timeout: 60_000 });

  await page.goto("/");
  await expect(page.getByTestId("connection-banner")).toHaveAttribute("data-status", /AUTH_REQUIRED|SESSION_EXPIRED/);
  await expect(page.getByRole("link", { name: "Riconnetti" })).toBeVisible();

  await page.getByRole("link", { name: "Riconnetti" }).click();
  await page.getByRole("button", { name: /Avvia collegamento/ }).click();
  await expect(status).toHaveAttribute("data-status", "CONNECTED", { timeout: 60_000 });

  await page.goto("/notifications");
  await expect(page.getByText("Cardmarket: autenticazione richiesta").first()).toBeVisible();
});

test("operations page shows the action queue and the audit log", async ({ page }) => {
  await page.goto("/settings/operations");
  await expect(page.getByTestId("action-row").first()).toBeVisible();
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByTestId("audit-list")).toContainText("LOGIN");
});
