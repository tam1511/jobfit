export const DISCLAIMER_TEXT =
  "JobFit only helps rephrase experience you actually have. It never invents credentials, and no score guarantees an interview or job offer.";

export function Disclaimer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-4 text-xs text-muted">
        <span className="font-medium text-ink">Note.</span> {DISCLAIMER_TEXT}
      </div>
    </footer>
  );
}

export function DisclaimerBanner() {
  return (
    <p className="rounded-lg bg-slate-50 p-3 text-xs text-muted ring-1 ring-slate-200">
      <span className="font-medium text-ink">Fair use.</span> {DISCLAIMER_TEXT}
    </p>
  );
}
