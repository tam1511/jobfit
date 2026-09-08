"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { AuthError, fetchJd, uploadCv, type UploadResult } from "../../lib/api";
import { AppShell } from "../../components/AppShell";
import { DisclaimerBanner } from "../../components/Disclaimer";
import { ScorePanel } from "../../components/ScorePanel";
import { applicationHref } from "../../lib/applications";

export default function NewScorePage() {
  const router = useRouter();
  const [company, setCompany] = useState("");
  const [roleTitle, setRoleTitle] = useState("");
  const [jdUrl, setJdUrl] = useState("");
  const [jdText, setJdText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function handleFetchJd() {
    setError(null);
    if (!jdUrl.trim()) return setError("Paste a link to fetch.");
    setFetching(true);
    try {
      const fetched = await fetchJd(jdUrl.trim());
      setJdText(fetched.jd_text);
    } catch (err) {
      if (err instanceof AuthError) {
        router.replace("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Could not fetch that link.");
    } finally {
      setFetching(false);
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!company.trim()) return setError("Enter the company name.");
    if (!roleTitle.trim()) return setError("Enter the role title.");
    if (!file) return setError("Choose a CV to upload.");
    if (!jdText.trim()) return setError("Paste the job description or fetch it from a link.");

    setSubmitting(true);
    try {
      const uploaded = await uploadCv(
        company.trim(),
        roleTitle.trim(),
        jdText.trim(),
        file,
        jdUrl.trim() || null,
      );
      setResult(uploaded);
    } catch (err) {
      if (err instanceof AuthError) {
        router.replace("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-ink">Score a new CV</h1>
        <p className="text-sm text-muted">
          Tell us where you are applying, upload your CV, and paste the job description.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200"
      >
        <DisclaimerBanner />

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block">
            <span className="text-sm font-medium text-ink">Company</span>
            <input
              type="text"
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              placeholder="Acme Inc"
              className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-ink">Role title</span>
            <input
              type="text"
              value={roleTitle}
              onChange={(event) => setRoleTitle(event.target.value)}
              placeholder="Senior Backend Engineer"
              className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
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

          <div className="block">
            <span className="text-sm font-medium text-ink">Job description</span>
            <div className="mt-2 flex gap-2">
              <input
                type="url"
                value={jdUrl}
                onChange={(event) => setJdUrl(event.target.value)}
                placeholder="Paste the job posting link (optional)"
                className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
              <button
                type="button"
                onClick={handleFetchJd}
                disabled={fetching || !jdUrl.trim()}
                className="whitespace-nowrap rounded-lg border border-primary px-3 py-2 text-sm font-medium text-primary transition hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {fetching ? "Fetching..." : "Fetch JD"}
              </button>
            </div>
            <textarea
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              rows={8}
              placeholder="Paste the JD here, or fetch it from the link above..."
              className="mt-2 block w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>
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
        <div className="mt-8 space-y-4">
          <ScorePanel score={result.score} extractedText={result.extracted_text} />
          <div className="flex justify-end">
            <a
              href={applicationHref(result.company, result.role_title)}
              className="text-sm font-medium text-primary hover:underline"
            >
              View all versions for {result.company} - {result.role_title} &rarr;
            </a>
          </div>
        </div>
      )}
    </AppShell>
  );
}
