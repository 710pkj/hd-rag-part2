// 답변 피드백(👍👎 · 사유)을 백엔드 /feedback으로 넘긴다. 백엔드가 꺼져 있으면 저장하지 못했다고 알린다
const BACKEND = process.env.AGENT_BACKEND_URL ?? "http://127.0.0.1:8000";

export async function POST(request: Request) {
  try {
    const res = await fetch(`${BACKEND}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) throw new Error(String(res.status));
    return Response.json(await res.json());
  } catch {
    return Response.json({ ok: false, error: "백엔드에 연결하지 못함" });
  }
}
