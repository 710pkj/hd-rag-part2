// part1.json(scripts/prepare.mjs가 생성)에 타입을 붙여 내보낸다
import raw from "./part1.json";
import type { DocMeta, RunMeta, TestQuestion } from "@/lib/types";

type Part1 = { source: string; docs: Record<string, DocMeta>; runs: RunMeta[]; questions: TestQuestion[] };

export const PART1 = raw as unknown as Part1;
