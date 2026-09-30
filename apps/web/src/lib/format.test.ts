import { formatAgo, formatMoney, formatRelative } from "./format";

describe("formatMoney", () => {
  it("formats euro amounts the Italian way", () => {
    expect(formatMoney("12345.5")).toMatch(/12\.345,50\s€/);
    expect(formatMoney(4.2)).toMatch(/4,20\s€/);
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("abc")).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-30T12:00:00Z");
  it("uses compact labels", () => {
    expect(formatRelative("2026-09-30T11:59:40Z", now)).toBe("ora");
    expect(formatRelative("2026-09-30T11:58:00Z", now)).toBe("2 min");
    expect(formatRelative("2026-09-30T09:00:00Z", now)).toBe("3 h");
    expect(formatRelative("2026-09-29T08:00:00Z", now)).toBe("ieri");
    expect(formatRelative(null, now)).toBe("");
  });
});

describe("formatAgo", () => {
  const now = new Date("2026-09-30T12:00:00Z");
  it("describes elapsed time", () => {
    expect(formatAgo("2026-09-30T11:59:30Z", now)).toBe("30 secondi fa");
    expect(formatAgo("2026-09-30T11:55:00Z", now)).toBe("5 minuti fa");
    expect(formatAgo(null, now)).toBe("mai");
  });
});
