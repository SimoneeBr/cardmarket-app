import { request, type FullConfig } from "@playwright/test";
import { mkdirSync } from "node:fs";

export const ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@example.com",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-password-2026",
  name: "E2E Admin",
};

/** Creates the first administrator (first-run) if needed and stores a logged-in session. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL as string;
  const ctx = await request.newContext({ baseURL });
  const status = await (await ctx.get("/api/setup/status")).json();
  if (status.needs_admin) {
    const res = await ctx.post("/api/setup/admin", { data: ADMIN });
    if (!res.ok()) throw new Error(`setup failed: ${res.status()} ${await res.text()}`);
  } else {
    const res = await ctx.post("/api/auth/login", { data: { email: ADMIN.email, password: ADMIN.password } });
    if (!res.ok()) throw new Error(`login failed: ${res.status()} ${await res.text()}`);
  }
  // Wait until the mock agent completed at least one sync.
  const deadline = Date.now() + 120_000;
  for (;;) {
    const orders = await (await ctx.get("/api/orders?limit=1")).json();
    if (orders.total > 0) break;
    if (Date.now() > deadline) throw new Error("mock agent did not sync any order in time");
    await new Promise((r) => setTimeout(r, 2000));
  }
  mkdirSync(".auth", { recursive: true });
  await ctx.storageState({ path: ".auth/admin.json" });
  await ctx.dispose();
}
