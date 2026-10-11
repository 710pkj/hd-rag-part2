"use client";

// 근거 페이지 스택: A4 용지가 촘촘히 겹쳐 쌓인 모양.
// velog "React Card Stack" 글처럼 스크롤 위치(offset)를 카드 위치로 바꾸고, 휠 한 번에 한 장씩 스냅한다.
// 여기서는 스택 영역을 진짜 스크롤 상자로 만들었다:
//   - 한 장당 STEP px의 스크롤 길이를 두고, pos = scrollTop / STEP 으로 각 장의 위치를 매 프레임 계산한다.
//     스크롤이 움직이는 동안 앞 장이 위로 들려 나가고 뒤 장이 앞으로 나온다.
//   - 휠·키보드·순위 클릭은 직접 만든 애니메이션(ANIM_MS, ease-out)으로 다음 장까지 스크롤한다.
//     브라우저의 smooth 스크롤은 Windows "애니메이션 효과"가 꺼져 있으면 순간이동하므로 쓰지 않는다.
//   - 옆의 브라우저 스크롤바를 끌거나 터치로 밀면 기본 스크롤이 되고, 손을 떼면 scroll-snap이 가장 가까운 장에 맞춘다.
//   - 뒤 장일수록 위로 GAP만큼 비켜나고(종이 윗단이 보임), 조금 작아지고, 불투명도를 낮춰 "뒤에 있는 문서"로 보이게 한다.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Rels } from "@/lib/metrics";
import { parsePageId, type DocMeta } from "@/lib/types";
import { PdfPage } from "./PdfPage";

const STEP = 160; // 한 장 넘기는 스크롤 길이(px)
const GAP = 8; // 한 장 뒤로 갈 때마다 위로 비켜나는 거리(px)
const SHRINK = 0.016; // 한 장 뒤로 갈 때마다 줄어드는 비율
const MAX_BEHIND = 9; // 뒤에 보이는 최대 장 수
const ANIM_MS = 420; // 한 장 넘기는 애니메이션 시간
const WHEEL_STEP = 40; // 이만큼 휠 delta가 모이면 한 장 (트랙패드의 작은 delta를 모은다)
const WHEEL_GAP_MS = 260; // 한 장 넘긴 뒤 다음 장까지 최소 간격 (velog 글의 스냅 잠금, 트랙패드 관성 완화)
const RENDER_WIDTH = 1000; // PDF를 그리는 폭(px). 카드 폭의 약 2배

type Props = {
  ids: string[];
  rels: Rels | null;
  cited: Set<string>;
  index: number;
  onIndex: (i: number) => void;
  onOpen: (i: number) => void;
  docs: Record<string, DocMeta>;
};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const easeOut = (p: number) => 1 - Math.pow(1 - p, 3);

// d = 장 번호 − 스크롤 위치. 0이면 맨 앞, 양수면 뒤, 음수면 넘겨서 위로 빠져나가는 중
function sheetStyle(d: number, exitDistance: number) {
  if (d < 0) {
    // 종이처럼 불투명한 채로 들려 나가다가 마지막 40% 구간에서만 사라진다 (두 페이지 글자가 겹쳐 보이지 않게)
    const t = Math.min(1, -d);
    return {
      transform: `translateY(${-t * exitDistance}px) rotate(${-1.5 * t}deg)`,
      opacity: 1 - Math.max(0, (t - 0.6) / 0.4),
      zIndex: Math.round(1000 - d * 10),
    };
  }
  const k = Math.min(d, MAX_BEHIND);
  const opacity =
    d <= 1 ? 1 - 0.18 * d : d <= MAX_BEHIND ? Math.max(0.18, 0.82 - (d - 1) * 0.09) : Math.max(0, 0.18 * (MAX_BEHIND + 1 - d));
  return { transform: `translateY(${-k * GAP}px) scale(${1 - k * SHRINK})`, opacity, zIndex: Math.round(1000 - d * 10) };
}

export function PageStack({ ids, rels, cited, index, onIndex, onOpen, docs }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sheetRefs = useRef<(HTMLDivElement | null)[]>([]);
  const anim = useRef<{ raf: number; target: number } | null>(null);
  const reported = useRef(index); // 스크롤이 마지막으로 알린 장 (밖에서 바꾼 것과 구별)
  const [size, setSize] = useState({ w: 0, h: 0 });

  const behind = Math.min(MAX_BEHIND, Math.max(0, ids.length - 1));
  const peek = GAP * behind;
  const cardH = Math.max(0, Math.min(size.h - peek - 28, (size.w - 28) * Math.SQRT2));
  const cardW = cardH / Math.SQRT2;
  const top = peek + 14 + Math.max(0, (size.h - peek - 28 - cardH) / 2);
  const exitDistance = cardH + top + 24;

  // 스크롤 위치 → 각 장의 transform·opacity (React 렌더 없이 직접 적용)
  const layout = useCallback(
    (pos: number) => {
      sheetRefs.current.forEach((el, i) => {
        if (!el) return;
        const s = sheetStyle(i - pos, exitDistance);
        el.style.transform = s.transform;
        el.style.opacity = String(s.opacity);
        el.style.zIndex = String(s.zIndex);
        el.style.pointerEvents = i - pos < -0.5 ? "none" : "";
      });
    },
    [exitDistance],
  );

  // target 장까지 직접 애니메이션으로 스크롤한다. 도는 동안은 스냅을 꺼 둔다
  const animateTo = useCallback((target: number) => {
    const el = scrollRef.current;
    if (!el) return;
    if (anim.current) cancelAnimationFrame(anim.current.raf);
    const from = el.scrollTop;
    const to = target * STEP;
    if (Math.abs(to - from) < 1) {
      anim.current = null;
      el.style.scrollSnapType = "";
      return;
    }
    el.style.scrollSnapType = "none";
    const dur = Math.min(800, ANIM_MS + (Math.abs(to - from) / STEP - 1) * 45); // 멀리 갈수록 조금 길게
    const t0 = performance.now();
    const frame = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      el.scrollTop = from + (to - from) * easeOut(p);
      if (p < 1) anim.current = { raf: requestAnimationFrame(frame), target };
      else {
        anim.current = null;
        el.style.scrollSnapType = "";
      }
    };
    anim.current = { raf: requestAnimationFrame(frame), target };
  }, []);

  // 지금 향하는 장(애니메이션 중이면 그 목표)에서 dir만큼 이동
  const stepBy = useCallback(
    (dir: number) => {
      const el = scrollRef.current;
      if (!el || !ids.length) return;
      const base = anim.current ? anim.current.target : Math.round(el.scrollTop / STEP);
      const next = clamp(base + dir, 0, ids.length - 1);
      if (next !== base) animateTo(next);
    },
    [ids.length, animateTo],
  );

  const live = useRef({ count: ids.length, onIndex, layout, stepBy });
  useEffect(() => {
    live.current = { count: ids.length, onIndex, layout, stepBy };
  });

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 스크롤할 때마다 다음 프레임에 장 위치를 다시 계산하고, 가장 가까운 장을 현재 장으로 알린다
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const pos = el.scrollTop / STEP;
        const { count, onIndex: report, layout: lay } = live.current;
        lay(pos);
        const near = clamp(Math.round(pos), 0, Math.max(0, count - 1));
        if (count && near !== reported.current) {
          reported.current = near;
          report(near);
        }
      });
    };
    // 휠: 기본 스크롤을 막고 한 장씩 애니메이션 (React onWheel은 passive라 preventDefault가 안 됨)
    let acc = 0;
    let last = 0;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) return; // 확대·축소는 그대로
      e.preventDefault();
      const now = performance.now();
      if (now - last < WHEEL_GAP_MS) {
        acc = 0;
        return;
      }
      acc += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * el.clientHeight : e.deltaY;
      if (Math.abs(acc) < WHEEL_STEP) return;
      const dir = Math.sign(acc);
      acc = 0;
      last = now;
      live.current.stepBy(dir);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("wheel", onWheel);
      cancelAnimationFrame(raf);
    };
  }, []);

  // 렌더 뒤(크기·목록 변경 포함) 현재 스크롤 위치로 다시 배치
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) layout(el.scrollTop / STEP);
  });

  // 밖에서 장을 바꾸면(순위·인용 클릭) 그 장까지 애니메이션. 목록이 바뀌면(새 질문·실행 전환) 바로 이동
  const listKey = ids.join("|");
  const prevKey = useRef(listKey);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !size.h) return;
    const listChanged = prevKey.current !== listKey;
    prevKey.current = listKey;
    if (listChanged) {
      if (anim.current) cancelAnimationFrame(anim.current.raf);
      anim.current = null;
      el.style.scrollSnapType = "";
      el.scrollTop = index * STEP;
      reported.current = index;
      layout(index);
      return;
    }
    if (index === reported.current || index === anim.current?.target) return; // 스크롤이 알린 값이면 그대로
    reported.current = index;
    animateTo(index);
  }, [index, listKey, size.h, layout, animateTo]);

  return (
    <div
      ref={scrollRef}
      className="stack-scroll"
      tabIndex={0}
      role="listbox"
      aria-label="근거 페이지 스택. 스크롤이나 위아래 화살표로 넘기고 Enter로 크게 봅니다"
      aria-activedescendant={ids.length ? `sheet-${index}` : undefined}
      onKeyDown={(e) => {
        if (["ArrowDown", "PageDown", "j"].includes(e.key)) stepBy(1);
        else if (["ArrowUp", "PageUp", "k"].includes(e.key)) stepBy(-1);
        else if (e.key === "Home") animateTo(0);
        else if (e.key === "End") animateTo(Math.max(0, ids.length - 1));
        else if (e.key === "Enter" && ids.length) onOpen(index);
        else return;
        e.preventDefault();
      }}
    >
      {/* 화면에 붙어 있는 무대. 아래 스냅 칸들이 스크롤 길이를 만든다 */}
      <div className="stack-stage" style={{ height: size.h, marginBottom: -size.h }}>
        {ids.length === 0 && (
          <div className="stack-empty" style={{ width: cardW || undefined, height: cardH || undefined }}>
            <p>답변의 근거 페이지가 여기에 겹쳐 쌓입니다</p>
            <p className="muted">테스트 질문을 고르면 Part 1 검색 결과 top-10이 나옵니다</p>
          </div>
        )}
        {cardH > 0 &&
          ids.map((id, i) => {
            const p = parsePageId(id);
            const doc = p ? docs[p.doc] : null;
            const grade = rels?.[id] ?? 0;
            const front = i === index;
            return (
              <div
                key={`${id}-${i}`}
                ref={(el) => {
                  sheetRefs.current[i] = el;
                }}
                id={`sheet-${i}`}
                role="option"
                aria-selected={front}
                aria-label={`${i + 1}위 ${doc?.short ?? id} ${p?.page ?? ""}쪽`}
                className={`sheet${front ? " is-front" : ""}`}
                style={{ width: cardW, height: cardH, top, marginLeft: -cardW / 2 }}
                onClick={() => (front ? onOpen(i) : animateTo(i))}
              >
                {p && doc && <PdfPage url={doc.url} page={p.page} width={RENDER_WIDTH} alt={`${doc.label} ${p.page}쪽`} />}
                {front && (
                  <div className="sheet-tag" aria-hidden>
                    <span className="sheet-rank">#{i + 1}</span>
                    {grade > 0 && <span className="sheet-gt">정답</span>}
                    {cited.has(id) && <span className="sheet-cite">인용</span>}
                  </div>
                )}
              </div>
            );
          })}
      </div>
      {ids.length > 0 && size.h > 0 && (
        <div className="snap-track" aria-hidden>
          {ids.map((id, i) => (
            <div key={`${id}-${i}`} className="snap-cell" style={{ height: STEP }} />
          ))}
          <div style={{ height: Math.max(0, size.h - STEP) }} />
        </div>
      )}
    </div>
  );
}
