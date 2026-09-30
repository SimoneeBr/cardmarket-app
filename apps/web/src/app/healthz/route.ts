/**
 * Container healthcheck: healthy only if this Next.js server renders dynamic
 * responses AND can reach the API it proxies to (a running process alone is
 * not considered healthy). Blocked from the Internet by the reverse proxy.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  const base = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(`${base}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return Response.json({ status: "degraded", api: res.status }, { status: 503 });
    return Response.json({ status: "ok", api: "ok" });
  } catch {
    return Response.json({ status: "degraded", api: "unreachable" }, { status: 503 });
  }
}
