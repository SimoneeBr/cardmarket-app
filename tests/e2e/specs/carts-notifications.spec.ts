import { expect, test } from "@playwright/test";

test("carts: list, filter and detail", async ({ page }) => {
  await page.goto("/carts");
  const list = page.getByTestId("carts-list");
  await expect(list.getByRole("link").first()).toBeVisible();
  await page.getByRole("tab", { name: "Da pagare" }).click();
  await expect(list.getByText("Da pagare").first()).toBeVisible();
  await list.getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: /Carrello/ })).toBeVisible();
  await expect(page.getByText("Acquirente")).toBeVisible();
});

test("notifications: new marketplace activity produces notifications", async ({ page, request }) => {
  const sim = await request.post("/api/admin/simulate", {
    data: { scenario: "new_activity" },
    headers: { "x-csrf-token": await csrf(page) },
  });
  expect(sim.ok()).toBeTruthy();
  await expect
    .poll(async () => (await (await request.get("/api/notifications/unread-count")).json()).unread, { timeout: 60_000 })
    .toBeGreaterThan(0);
  await page.goto("/notifications");
  await expect(page.getByTestId("notifications-list").locator("li").first()).toBeVisible();
  await page.getByRole("button", { name: "Segna tutte come lette" }).click();
  await expect(page.getByText("0 non lette")).toBeVisible();
});

async function csrf(page: import("@playwright/test").Page): Promise<string> {
  await page.goto("/");
  const cookie = (await page.context().cookies()).find((c) => c.name === "cmc_csrf");
  return cookie?.value ?? "";
}
