// A handful of inline-style helpers — we'll swap to tailwind/shadcn in Phase 5.
import type { CSSProperties } from "react";

export const colors = {
  bg: "#0b0c0f",
  bg2: "#15171c",
  bg3: "#1f2229",
  fg: "#e7e9ee",
  muted: "#9aa0aa",
  accent: "#7c8cff",
  danger: "#ff5c70",
  ok: "#4ade80",
};

export const card: CSSProperties = {
  background: colors.bg2,
  border: `1px solid ${colors.bg3}`,
  borderRadius: 12,
  padding: "1.25rem 1.5rem",
};

export const button: CSSProperties = {
  background: colors.accent,
  color: "#0b0c0f",
  border: "none",
  borderRadius: 8,
  padding: "0.55rem 1rem",
  fontWeight: 600,
  cursor: "pointer",
};

export const buttonSecondary: CSSProperties = {
  ...button,
  background: "transparent",
  color: colors.fg,
  border: `1px solid ${colors.bg3}`,
};

export const input: CSSProperties = {
  background: colors.bg,
  border: `1px solid ${colors.bg3}`,
  color: colors.fg,
  borderRadius: 8,
  padding: "0.5rem 0.75rem",
  fontSize: 14,
  minWidth: 0,
};

export const tag: CSSProperties = {
  display: "inline-block",
  fontSize: 11,
  padding: "0.15rem 0.5rem",
  borderRadius: 999,
  background: colors.bg3,
  color: colors.muted,
  letterSpacing: 0.5,
  textTransform: "uppercase",
  fontWeight: 600,
};
