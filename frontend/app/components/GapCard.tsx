import type { ScoreGap } from "../lib/api";

const SEVERITY_COLOR: Record<ScoreGap["severity"], string> = {
  high: "var(--color-weak)",
  medium: "var(--color-partial)",
  low: "var(--color-strong)",
};

type Props = {
  gap: ScoreGap;
};

export function GapCard({ gap }: Props) {
  const color = SEVERITY_COLOR[gap.severity];
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center gap-2">
        <span
          className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium text-white"
          style={{ backgroundColor: color }}
        >
          {gap.severity}
        </span>
      </div>
      <p className="text-sm text-ink">{gap.evidence}</p>
      <p className="mt-2 text-sm text-muted">
        <span className="font-medium text-ink">Suggestion: </span>
        {gap.suggestion}
      </p>
    </li>
  );
}
