// 선 아이콘 몇 개 (외부 아이콘 패키지 없이)
type P = { size?: number };
const base = (size = 16) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export const IconClip = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M21 11.5 12.5 20a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9" />
  </svg>
);
export const IconSend = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M5 12h13M13 6l6 6-6 6" />
  </svg>
);
export const IconStop = ({ size }: P) => (
  <svg {...base(size)}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </svg>
);
export const IconChevron = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);
export const IconNodes = ({ size }: P) => (
  <svg {...base(size)}>
    <circle cx="5" cy="6" r="2.2" />
    <circle cx="19" cy="6" r="2.2" />
    <circle cx="12" cy="18" r="2.2" />
    <path d="M7.2 6h9.6M6.2 8l4.6 8M17.8 8l-4.6 8" />
  </svg>
);
export const IconCheck = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="m5 12.5 4.2 4.2L19 7" />
  </svg>
);
export const IconExternal = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
  </svg>
);
export const IconExpand = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </svg>
);
export const IconClose = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const IconFile = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
    <path d="M14 3v4h4" />
  </svg>
);
export const IconPlus = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
