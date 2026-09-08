import type { UploadDetail } from "../lib/api";
import { formatDate } from "../lib/date";
import { CategoryBar } from "./CategoryBar";
import { ScoreRing } from "./ScoreRing";

type Props = {
  a: UploadDetail;
  b: UploadDetail;
};

export function ComparisonPanel({ a, b }: Props) {
  return (
    <section className="rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
      <div className="mb-6">
        <h2 className="text-lg font-medium text-ink">Compare versions</h2>
        <p className="text-sm text-muted">
          Side-by-side score breakdown for two CV versions of this application.
        </p>
      </div>
      <div className="grid gap-8 md:grid-cols-2">
        {[a, b].map((detail, idx) => (
          <div key={detail.upload_id} className="space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted">
                {idx === 0 ? "Version A" : "Version B"}
              </p>
              <p className="text-sm font-medium text-ink">{detail.filename}</p>
              <p className="text-xs text-muted">{formatDate(detail.created_at)}</p>
            </div>
            <div className="flex justify-center">
              <ScoreRing score={detail.score.overall_score} size={128} stroke={12} />
            </div>
            <div className="space-y-3">
              {detail.score.breakdown.map((c) => (
                <CategoryBar
                  key={c.category}
                  category={c.category}
                  score={c.score}
                  weight={c.weight}
                  evidence=""
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
