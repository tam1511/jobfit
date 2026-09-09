import type { OptimiseRewrite } from "../lib/api";

type Props = {
  rewrite: OptimiseRewrite;
  gapEvidence: string;
};

const ACTION_LABEL: Record<OptimiseRewrite["action"], string> = {
  rewrite: "Rewrote a bullet",
  add: "Added a new bullet",
  skip: "Skipped",
  unavailable: "No rewrite produced",
};

const ACTION_BORDER: Record<OptimiseRewrite["action"], string> = {
  rewrite: "border-primary",
  add: "border-strong",
  skip: "border-slate-300",
  unavailable: "border-partial/60",
};

const ACTION_PILL: Partial<Record<OptimiseRewrite["action"], { text: string; className: string }>> = {
  skip: {
    text: "No relevant experience",
    className: "bg-slate-100 text-muted",
  },
  unavailable: {
    text: "System couldn't rewrite",
    className: "bg-partial/15 text-partial",
  },
};

const isNonRewrite = (action: OptimiseRewrite["action"]) =>
  action === "skip" || action === "unavailable";

export function BulletDiff({ rewrite, gapEvidence }: Props) {
  const border = ACTION_BORDER[rewrite.action];
  const pill = ACTION_PILL[rewrite.action];

  return (
    <article className={`rounded-lg border ${border} bg-white p-4`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-wide text-muted">
          {ACTION_LABEL[rewrite.action]}
        </p>
        {pill && (
          <span className={`rounded-full px-2 py-0.5 text-xs ${pill.className}`}>
            {pill.text}
          </span>
        )}
      </div>

      <p className="mb-3 text-xs text-muted">
        <span className="font-medium text-ink">Gap: </span>
        {gapEvidence}
      </p>

      {isNonRewrite(rewrite.action) ? (
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

    </article>
  );
}
