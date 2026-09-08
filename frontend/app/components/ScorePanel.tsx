import type { ScoreResult } from "../lib/api";
import { CategoryBar } from "./CategoryBar";
import { GapCard } from "./GapCard";
import { ScoreRing } from "./ScoreRing";

type Props = {
  score: ScoreResult;
  extractedText?: string;
};

export function ScorePanel({ score, extractedText }: Props) {
  return (
    <section className="space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
      <div>
        <h2 className="text-lg font-medium text-ink">Your fit score</h2>
        <p className="text-sm text-muted">
          Weighted overall score with a category breakdown from the rubric.
        </p>
      </div>

      <div className="flex flex-col items-center gap-8 md:flex-row md:items-start">
        <ScoreRing score={score.overall_score} />
        <div className="w-full flex-1 space-y-4">
          {score.breakdown.map((c) => (
            <CategoryBar
              key={c.category}
              category={c.category}
              score={c.score}
              weight={c.weight}
              evidence={c.evidence}
            />
          ))}
        </div>
      </div>

      {(score.matched_keywords.length > 0 || score.missing_keywords.length > 0) && (
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium text-ink">Matched keywords</h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {score.matched_keywords.map((kw) => (
                <li
                  key={kw}
                  className="rounded-full border border-strong px-2.5 py-1 text-xs font-medium text-strong"
                >
                  {kw}
                </li>
              ))}
              {score.matched_keywords.length === 0 && (
                <li className="text-xs text-muted">None</li>
              )}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-medium text-ink">Missing keywords</h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {score.missing_keywords.map((kw) => (
                <li
                  key={kw}
                  className="rounded-full border border-weak px-2.5 py-1 text-xs font-medium text-weak"
                >
                  {kw}
                </li>
              ))}
              {score.missing_keywords.length === 0 && (
                <li className="text-xs text-muted">None</li>
              )}
            </ul>
          </div>
        </div>
      )}

      <div>
        <h3 className="text-sm font-medium text-ink">Gaps to close</h3>
        {score.gaps.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No gaps flagged against this JD.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {score.gaps.map((gap, idx) => (
              <GapCard key={idx} gap={gap} />
            ))}
          </ul>
        )}
      </div>

      {extractedText && (
        <details className="rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200">
          <summary className="cursor-pointer text-sm font-medium text-ink">
            Extracted CV text
          </summary>
          <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap text-sm text-ink">
            {extractedText}
          </pre>
        </details>
      )}
    </section>
  );
}
