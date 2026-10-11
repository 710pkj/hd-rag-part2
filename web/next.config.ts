import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 로컬 시연 화면에 Next.js 개발 표시(왼쪽 아래 N)가 겹치지 않게 끈다. 오류 표시는 그대로 나온다
  devIndicators: false,
};

export default nextConfig;
