import { expect, test } from "@playwright/test";

import { ADMIN } from "../global-setup";

test.describe("login / logout", () => {
  // Own session: never touch the shared storage state used by the other specs.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("rejects wrong credentials and logs in with the right ones", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill("wrong-password-1");
    await page.getByRole("button", { name: "Accedi" }).click();
    await expect(page.getByText("Credenziali non valide")).toBeVisible();

    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Accedi" }).click();
    await expect(page.getByRole("heading", { name: "Cardmarket Companion" })).toBeVisible();
    await expect(page.getByTestId("stat-to-ship")).toBeVisible();
  });

  test("logout ends the session", async ({ page, context }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ADMIN.email);
    await page.getByLabel("Password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Accedi" }).click();
    await expect(page.getByTestId("stat-to-ship")).toBeVisible();
    await page.goto("/settings");
    await page.getByRole("button", { name: "Esci" }).click();
    await expect(page).toHaveURL(/\/login/);
    const res = await context.request.get("/api/me");
    expect(res.status()).toBe(401);
  });
});
