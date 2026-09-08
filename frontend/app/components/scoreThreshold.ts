export type Band = "strong" | "partial" | "weak";

export function bandFor(score: number): Band {
  if (score >= 75) return "strong";
  if (score >= 50) return "partial";
  return "weak";
}

export const BAND_COLOR: Record<Band, string> = {
  strong: "var(--color-strong)",
  partial: "var(--color-partial)",
  weak: "var(--color-weak)",
};

export const BAND_LABEL: Record<Band, string> = {
  strong: "Strong",
  partial: "Partial",
  weak: "Weak",
};
