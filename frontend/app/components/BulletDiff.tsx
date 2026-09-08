import type { OptimiseRewrite } from "../lib/api";

type Props = {
  rewrite: OptimiseRewrite;
  gapEvidence: string;
};

const ACTION_LABEL: Record<OptimiseRewrite["action"], string> = {
  rewrite: "Rewrote a bullet",
  add: "Added a new bullet",
  skip: "Skipped",
};

const ACTION_BORDER: Record<OptimiseRewrite["action"], string> = {
  rewrite: "border-primary",
  add: "border-strong",
  skip: "border-slate-300",
};

export function BulletDiff({ rewrite, gapEvidence }: Props) {
  const border = ACTION_BORDER[rewrite.action];

  return (
    <article className={`rounded-lg border ${border} bg-white p-4`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-wide text-muted">
          {ACTION_LABEL[rewrite.action]}
        </p>
        {rewrite.action === "skip" && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-muted">
            Cannot fill without inventing
          </span>
        )}
      </div>

      <p className="mb-3 text-xs text-muted">
        <span className="font-medium text-ink">Gap: </span>
        {gapEvidence}
      </p>

      {rewrite.action === "skip" ? (
        <p className="text-sm text-muted">
          {rewrite.reason ?? "Skipped."}
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
              Original
            </p>
            <p className="whitespace-pre-wrap text-sm text-ink">
              {rewrite.original_bullet ?? (
                <span className="italic text-muted">(new bullet)</span>
              )}
            </p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
              Rewritten
            </p>
            <p className="whitespace-pre-wrap text-sm text-ink">
              {rewrite.rewritten_bullet}
            </p>
          </div>
        </div>
      )}

      {rewrite.sources.length > 0 && (
        <div className="mt-3 border-t border-slate-200 pt-3">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
            Sources
          </p>
          <ul className="flex flex-wrap gap-2">
            {rewrite.sources.map((s, i) => (
              <li
                key={i}
                className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-ink"
                title={`From ${s.origin === "cv" ? "the CV" : "the chat"}`}
              >
                <span className="mr-1 uppercase text-muted">{s.origin}:</span>
                {s.text.length > 60 ? `${s.text.slice(0, 60)}...` : s.text}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
