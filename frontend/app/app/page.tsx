"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { StaleSessionError, uploadCv, type UploadResult } from "../lib/api";
import { clearSession, readSession } from "../lib/session";
import { CategoryBar } from "../components/CategoryBar";
import { GapCard } from "../components/GapCard";
import { ScoreRing } from "../components/ScoreRing";

export default function AppPage() {
  const router = useRouter();
  const [userName, setUserName] = useState<string | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const session = readSession();
    if (!session) {
      router.replace("/");
      return;
    }
    setUserId(session.user_id);
    setUserName(session.name);
  }, [router]);

  function handleSignOut() {
    clearSession();
    router.replace("/");
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (userId === null) return;
    if (!file) {
      setError("Choose a CV to upload.");
      return;
    }
    if (!jdText.trim()) {
      setError("Paste the job description.");
      return;
    }
    setSubmitting(true);
    try {
      const uploaded = await uploadCv(userId, jdText.trim(), file);
      setResult(uploaded);
    } catch (err) {
      if (err instanceof StaleSessionError) {
        clearSession();
        router.replace("/?stale=1");
        return;
      }
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (userId === null) {
    return null;
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">JobFit</h1>
          <p className="text-sm text-muted">Signed in as {userName}</p>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="text-sm text-muted transition hover:text-ink"
        >
          Sign out
        </button>
      </header>

      <form
        onSubmit={handleSubmit}
        className="space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200"
      >
        <div>
          <h2 className="text-lg font-medium text-ink">
            Score your CV against a job description
          </h2>
          <p className="mt-1 text-sm text-muted">
            Upload your CV as a PDF, paste the job description you are
            applying for, and we will read them both.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-ink">CV (PDF)</span>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="mt-2 block w-full cursor-pointer rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-6 text-sm text-muted file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:opacity-90"
            />
            {file && (
              <p className="mt-2 text-xs text-muted">
                Selected: <span className="text-ink">{file.name}</span>
              </p>
            )}
          </label>

          <label className="block">
            <span className="text-sm font-medium text-ink">Job description</span>
            <textarea
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              rows={8}
              placeholder="Paste the JD here..."
              className="mt-2 block w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
        </div>

        {error && (
          <p role="alert" className="text-sm text-weak">
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-3">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Scoring your CV..." : "Score CV against JD"}
          </button>
        </div>
      </form>

      {result && (
        <section className="mt-8 space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
          <div>
            <h2 className="text-lg font-medium text-ink">Your fit score</h2>
            <p className="text-sm text-muted">
              Weighted overall score with a category breakdown from the rubric.
            </p>
          </div>

          <div className="flex flex-col items-center gap-8 md:flex-row md:items-start">
            <ScoreRing score={result.score.overall_score} />
            <div className="w-full flex-1 space-y-4">
              {result.score.breakdown.map((c) => (
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

          {(result.score.matched_keywords.length > 0 ||
            result.score.missing_keywords.length > 0) && (
            <div className="grid gap-6 md:grid-cols-2">
              <div>
                <h3 className="text-sm font-medium text-ink">Matched keywords</h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {result.score.matched_keywords.map((kw) => (
                    <li
                      key={kw}
                      className="rounded-full border border-strong px-2.5 py-1 text-xs font-medium text-strong"
                    >
                      {kw}
                    </li>
                  ))}
                  {result.score.matched_keywords.length === 0 && (
                    <li className="text-xs text-muted">None</li>
                  )}
                </ul>
              </div>
              <div>
                <h3 className="text-sm font-medium text-ink">Missing keywords</h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {result.score.missing_keywords.map((kw) => (
                    <li
                      key={kw}
                      className="rounded-full border border-weak px-2.5 py-1 text-xs font-medium text-weak"
                    >
                      {kw}
                    </li>
                  ))}
                  {result.score.missing_keywords.length === 0 && (
                    <li className="text-xs text-muted">None</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          <div>
            <h3 className="text-sm font-medium text-ink">Gaps to close</h3>
            {result.score.gaps.length === 0 ? (
              <p className="mt-2 text-sm text-muted">
                No gaps flagged against this JD.
              </p>
            ) : (
              <ul className="mt-3 space-y-3">
                {result.score.gaps.map((gap, idx) => (
                  <GapCard key={idx} gap={gap} />
                ))}
              </ul>
            )}
          </div>

          <details className="rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200">
            <summary className="cursor-pointer text-sm font-medium text-ink">
              Extracted CV text
            </summary>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap text-sm text-ink">
              {result.extracted_text}
            </pre>
          </details>
        </section>
      )}
    </main>
  );
}
