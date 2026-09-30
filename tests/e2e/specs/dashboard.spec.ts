import { expect, test } from "@playwright/test";

test("dashboard shows actionable counters and connection state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("connection-banner")).toHaveAttribute("data-status", "CONNECTED");
  await expect(page.getByTestId("connection-banner")).toContainText("Ultima sincronizzazione");
  for (const id of ["stat-new", "stat-to-ship", "stat-unread", "stat-unpaid"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  await expect(page.getByTestId("carts-summary")).toContainText("da pagare");
  // Counters link to the matching filtered list.
  await page.getByTestId("stat-to-ship").click();
  await expect(page).toHaveURL(/\/orders\?filter=to_ship/);
  await expect(page.getByRole("tab", { name: "Da spedire" })).toHaveAttribute("aria-selected", "true");
});
