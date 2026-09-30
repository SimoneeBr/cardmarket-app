import { expect, test } from "@playwright/test";

test("chat: open a conversation, use a template and send a verified message", async ({ page }) => {
  await page.goto("/chat");
  const list = page.getByTestId("conversations-list");
  await expect(list.getByRole("link").first()).toBeVisible();
  await list.getByRole("link").first().click();
  await expect(page.getByTestId("messages").getByTestId("message").first()).toBeVisible();

  await page.getByTestId("templates").getByRole("button", { name: /Grazie/ }).click();
  const box = page.getByRole("textbox", { name: "Messaggio" });
  await expect(box).not.toHaveValue("");

  const text = `Messaggio E2E ${Date.now()}`;
  await box.fill(text);
  await page.getByRole("button", { name: "Invia" }).click();
  const bubble = page.getByTestId("message").filter({ hasText: text });
  await expect(bubble).toBeVisible();
  // SENT only after the agent verified the message on (mock) Cardmarket.
  await expect(bubble).toHaveAttribute("data-status", "SENT", { timeout: 60_000 });
});

test("chat: an unverifiable send is shown as UNKNOWN, never as sent", async ({ page }) => {
  await page.goto("/chat");
  await page.getByTestId("conversations-list").getByRole("link").nth(1).click();
  const text = `Verifica impossibile ${Date.now()} [mock:unverified]`;
  await page.getByRole("textbox", { name: "Messaggio" }).fill(text);
  await page.getByRole("button", { name: "Invia" }).click();
  const bubble = page.getByTestId("message").filter({ hasText: text });
  await expect(bubble).toHaveAttribute("data-status", "UNKNOWN", { timeout: 60_000 });
  await expect(bubble).toContainText("Esito da verificare");
});
