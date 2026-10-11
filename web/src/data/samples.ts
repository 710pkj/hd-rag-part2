// 에이전트 백엔드를 붙이기 전, 화면 시연에 쓰는 샘플 답변.
// 문장은 정답 페이지 원문(pkl page_content)과 Part 1 판 비교표(kr_edition_diff.csv)에서 확인한 내용만 쓴다.
// keywords는 과제 PDF 테스트 데이터 표의 "키워드(참고)" 열이다.
import type { Sentence } from "@/lib/types";

export type Sample = { keywords: string; diff?: string; sentences: Sentence[] };

const ok = (text: string, ...cites: string[]): Sentence => ({ text, cites, status: "supported" });
const infer = (text: string, note: string): Sentence => ({ text, cites: [], status: "inferred", note });

export const SAMPLES: Record<string, Sample> = {
  t01: {
    keywords: "",
    sentences: [
      ok("KR 2026 가이드의 Cyber Resilience 계열 노테이션은 Cyber Resilience, Cyber Resilience+, Cyber Resilience(CSMS), Cyber Resilience(CSMS)+, CSMS입니다.", "KR2026:233"),
      ok("선박 및 시스템의 사이버 복원력 지침(Guidance for Cyber Resilience of Ships and Systems)의 요건을 만족하는 선박에 부여됩니다.", "KR2026:233"),
      ok("같은 페이지의 CS0~CS3과 CS READY는 해양 사이버 보안 시스템 지침에 따른 별도 노테이션입니다.", "KR2026:233"),
    ],
  },
  t02: {
    keywords: "ESA_iSG",
    diff: "Ch 3 신설: ESA-iSG, ESA1-iSG, ESA2-iSG (2026 234쪽)",
    sentences: [
      ok("추진축과 일렬로 결합된 축발전기(in-line type Shaft Generator, iSG)에는 ESA-iSG 노테이션(ESA1-iSG, ESA2-iSG 포함)이 부여됩니다.", "KR2026:234"),
      ok("지침 Pt 5, Annex 5-12-2의 iSG 요건과, 해당하는 경우 Annex 5-12-1의 강화 축계 정렬(ESA) 요건을 만족해야 합니다.", "KR2026:234"),
      ok("판 비교표 기준으로 이 노테이션은 2026년 판에서 신설되었습니다.", "tool:edition-diff"),
    ],
  },
  t03: {
    keywords: "SolarPV",
    sentences: [
      ok("선박 태양광 시스템 지침(Guidance for Photovoltaic Systems Onboard Ships)에 따른 태양광 발전 시스템을 갖춘 선박에는 SolarPV 노테이션이 부여됩니다.", "KR2026:238"),
    ],
  },
  t04: {
    keywords: "Yes",
    sentences: [
      ok("네, WHIP+를 취득한 것으로 볼 수 있습니다.", "KR2026:223"),
      ok("2026년 가이드는 2025년 7월 이전에 부여된 WHIP 노테이션을 SeaTrust(WHIP+)와 동등한 것으로 간주한다고 명시합니다.", "KR2026:223"),
      infer("2024년에 취득했다면 이 조건에 해당합니다.", "인용 문장의 날짜 조건(2025년 7월 이전)과 질문의 연도를 비교한 추론"),
    ],
  },
  t05: {
    keywords: "LNG는 yes, LPG는 No",
    diff: "Ch 3 신설: LPG Ready D, LPG Ready I (2026 229쪽) → 2022년 판에는 없음",
    sentences: [
      ok("2022년 판에는 LNG 연료 준비 선박 지침에 따른 LNG Ready 노테이션(LNG Ready D(A), LNG Ready D, LNG Ready I 등)이 규정되어 있습니다.", "KR2022:224"),
      ok("LPG Ready 노테이션(LPG Ready D, LPG Ready I)은 2026년 판에서 신설되어 2022년 판에는 없습니다.", "tool:edition-diff"),
      infer("따라서 2022년 기준으로는 LNG Ready만 적용되고 LPG Ready는 적용되지 않습니다.", "위 두 문장을 합친 결론"),
    ],
  },
  t06: {
    keywords: "Autonomous, remote-con",
    sentences: [
      ok("AUTONOMOUS는 상시 설치된 자율 기능을 갖춘 선박·유닛에, REMOTE-CON은 상시 설치된 원격 제어 기능을 갖춘 선박에 부여됩니다.", "ABS2025:26"),
      ok("AUTONOMOUS는 기능 범주와 운용 감독 수준(operations supervision level)을 함께 표기하지만, REMOTE-CON은 기능 범주만 표기합니다.", "ABS2025:26"),
      ok("기능 범주는 항해(NAV)부터 자율 플랫폼(APF)까지의 목록에서 고릅니다.", "ABS2025:26"),
    ],
  },
  t07: {
    keywords: "R 시리즈 (R1, R+ 등)",
    sentences: [
      ok("엔진 고장 시 추진·조종 능력 유지와 관련된 노테이션은 R 계열(R1, R1+ 등)입니다.", "ABS2025:116"),
      ok("R1은 추진기관은 여러 대이지만 추진기와 조타장치는 하나인 선박의 이중화 배치를 나타냅니다.", "ABS2025:116"),
      ok("+ 표시는 단일 고장이 나도 추진력을 유지하거나 즉시 복구할 수 있다는 뜻입니다.", "ABS2025:116"),
      ok("나머지 R 계열 노테이션은 117~119쪽에 이어집니다.", "ABS2025:117", "ABS2025:118", "ABS2025:119"),
    ],
  },
  t08: {
    keywords: "Cable Layer, CTV",
    diff: "Offshore Support Vessel 신설: Cable Layer, CTV (2026 176·177쪽)",
    sentences: [
      ok("2026년 판의 해양지원선(Offshore Support Vessel) 노테이션에는 Cable Layer와 CTV가 있습니다.", "KR2026:176"),
      ok("Cable Layer는 해저 케이블 부설·유지보수용, CTV(Crew Transfer Vessel)는 인원 수송용 선박에 부여됩니다.", "KR2026:176"),
      ok("각각 OSV 지침 10장과 11장을 따릅니다.", "KR2026:177"),
      ok("판 비교표에 따르면 두 항목은 2022년 판에 없고 2026년 판에서 신설되었습니다.", "tool:edition-diff"),
    ],
  },
  t09: {
    keywords: "OPEN-TOP",
    diff: "Container Ship 신설: OPEN-TOP(CC)(Hold Nos.), OPEN-TOP(Hold Nos.) · 명칭 변경: LS(CL, RS, HHS or HHT) → LS(HHS or HHT)",
    sentences: [
      ok("Yes. The 2026 edition adds two container-ship notations, OPEN-TOP(CC)(Hold Nos. a, b, ...) and OPEN-TOP(Hold Nos. a, b, ...).", "KR2026:100", "tool:edition-diff"),
      ok("They apply to ships not required to have hatch covers fitted on one or more cargo holds during the voyage; (CC) is dropped for ships carrying only non-combustible cargo.", "KR2026:100"),
      ok("The LS notation was also renamed from LS(CL, RS, HHS or HHT) to LS(HHS or HHT).", "tool:edition-diff"),
    ],
  },
  t10: {
    keywords: "KR: UMA / ABS: AMS, ACCU",
    sentences: [
      ok("KR 2026은 주기적 무인 기관실 운용 시스템에 UMA를, 자동화 설비 등급에 UMA1·UMA2·UMA3을, 주추진·주요 보기의 집중 감시 제어에 CMA를 부여합니다.", "KR2026:236"),
      ok("ABS 2025는 상시 유인 집중 제어실에서 기관을 제어·감시하는 선박에 ACC를 부여합니다.", "ABS2025:15"),
      ok("ACCU(Automatic Centralized Control Unmanned)는 선교와 집중 제어 위치에서 기관실을 제어·감시하는 선박에 부여됩니다.", "ABS2025:16"),
      infer("따라서 무인 기관실 개념은 KR의 UMA와 ABS의 ACCU가 서로 대응합니다.", "두 문서의 정의를 비교한 해석으로, 이를 직접 말하는 페이지는 없음"),
    ],
  },
};

export const QTYPE_LABELS: Record<string, string> = {
  definition: "설명",
  which: "무엇",
  yesno: "예/아니오",
  compare: "비교",
  compare_year: "판 비교",
  english: "영어 질문",
  compare_society: "선급 비교",
};
