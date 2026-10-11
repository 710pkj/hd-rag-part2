import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "선급 기술검토 에이전트",
  description: "선급 노테이션 문서 RAG 에이전트 시연 (DT인력양성과정 Part 2)",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
