import { expect, test } from "@playwright/test";

test("orders: filter, search, open detail", async ({ page }) => {
  await page.goto("/orders");
  const list = page.getByTestId("orders-list");
  await expect(list.getByRole("link").first()).toBeVisible();
  const allCount = await list.getByRole("link").count();
  expect(allCount).toBeGreaterThanOrEqual(20);

  await page.getByRole("tab", { name: "Spediti" }).click();
  await expect(page).toHaveURL(/filter=shipped/);
  await expect(list.getByText("Spedito").first()).toBeVisible();

  await page.getByRole("tab", { name: "Tutti" }).click();
  const firstRow = list.getByRole("link").first();
  const orderNumber = (await firstRow.textContent())?.match(/#(\d+)/)?.[1];
  expect(orderNumber).toBeTruthy();
  await page.getByPlaceholder(/Cerca acquirente/).fill(orderNumber!);
  await expect(list.getByRole("link")).toHaveCount(1);
  await list.getByRole("link").first().click();

  await expect(page.getByRole("heading", { name: `Ordine #${orderNumber}` })).toBeVisible();
  await expect(page.getByTestId("order-items").locator("li").first()).toBeVisible();
  await expect(page.getByText("Pagamento")).toBeVisible();
});

test("orders: mark as shipped goes through the verified action queue", async ({ page }) => {
  await page.goto("/orders?filter=to_ship");
  const list = page.getByTestId("orders-list");
  await list.getByRole("link").first().click();
  await page.getByLabel("Numero di tracking").fill("RR123456789IT");
  await page.getByRole("button", { name: /Conferma spedizione/ }).click();
  // Pending until the agent executed AND verified it on (mock) Cardmarket.
  await expect(page.getByText("Spedito", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("RR123456789IT")).toBeVisible();
});
