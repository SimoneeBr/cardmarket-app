import { api, ApiError } from "./api";

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the CSRF token on mutations and not on reads", async () => {
    document.cookie = "cmc_csrf=tok123";
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.get("/me");
    await api.post("/notifications/read-all");
    const [, getInit] = fetchMock.mock.calls[0]!;
    const [postUrl, postInit] = fetchMock.mock.calls[1]!;
    expect((getInit.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(postUrl).toBe("/api/notifications/read-all");
    expect((postInit.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
  });

  it("builds query strings without empty values", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.get("/orders", { filter: "new", q: "", limit: 30 });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/orders?filter=new&limit=30");
  });

  it("raises ApiError with the server message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Permesso negato" }), { status: 403 })));
    await expect(api.get("/admin/users")).rejects.toEqual(new ApiError(403, "Permesso negato"));
  });

  it("maps network failures to status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(api.get("/me")).rejects.toMatchObject({ status: 0 });
  });
});
