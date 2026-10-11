import type { AskEvent } from "./types";

// fetch 응답 본문을 SSE 이벤트로 읽는다 (EventSource는 POST를 못 보내서 직접 파싱)
export async function* readSse(res: Response): AsyncGenerator<AskEvent> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let cut: number;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) yield JSON.parse(data) as AskEvent;
    }
  }
}
