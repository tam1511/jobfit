import { bandFor, BAND_COLOR } from "./scoreThreshold";

type Props = {
  category: string;
  score: number;
  weight: number;
  evidence: string;
};

export function CategoryBar({ category, score, weight, evidence }: Props) {
  const clamped = Math.max(0, Math.min(100, score));
  const color = BAND_COLOR[bandFor(clamped)];

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-ink">{category}</span>
        <span className="text-xs text-muted">
          <span className="font-semibold text-ink">{clamped}</span>
          <span className="mx-1">/</span>
          <span>100</span>
          <span className="ml-2">weight {weight}%</span>
        </span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
        aria-label={category}
      >
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${clamped}%`, backgroundColor: color }}
        />
      </div>
      {evidence && <p className="text-xs text-muted">{evidence}</p>}
    </div>
  );
}
