// 백엔드 상태 (상단 바 표시용). 꺼져 있으면 ok: false
const BACKEND = process.env.AGENT_BACKEND_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/health`, { cache: "no-store", signal: AbortSignal.timeout(1500) });
    if (!res.ok) throw new Error(String(res.status));
    return Response.json({ ok: true, ...(await res.json()) });
  } catch {
    return Response.json({ ok: false });
  }
}
