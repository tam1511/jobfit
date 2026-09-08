"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import {
  deleteUpload,
  getUpload,
  listUploads,
  type UploadDetail,
  type UploadSummary,
} from "../../lib/api";
import { AppShell } from "../../components/AppShell";
import { ComparisonPanel } from "../../components/ComparisonPanel";
import { ScorePanel } from "../../components/ScorePanel";
import { bandFor, BAND_COLOR } from "../../components/scoreThreshold";
import { formatDate } from "../../lib/date";

export default function ApplicationPage() {
  return (
    <Suspense fallback={<AppShell><p className="text-sm text-muted">Loading...</p></AppShell>}>
      <ApplicationInner />
    </Suspense>
  );
}

function ApplicationInner() {
  const searchParams = useSearchParams();
  const company = searchParams.get("company") ?? "";
  const role = searchParams.get("role") ?? "";

  const [versions, setVersions] = useState<UploadSummary[] | null>(null);
  const [detailA, setDetailA] = useState<UploadDetail | null>(null);
  const [detailB, setDetailB] = useState<UploadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!company || !role) {
      setError("Missing company or role.");
      return;
    }
    listUploads({ company, role_title: role })
      .then(async (rows) => {
        rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
        setVersions(rows);
        if (rows.length >= 1) {
          const a = await getUpload(rows[0].upload_id);
          setDetailA(a);
        }
        if (rows.length >= 2) {
          const b = await getUpload(rows[1].upload_id);
          setDetailB(b);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load application."));
  }, [company, role]);

  async function handleSelectForCompare(uploadId: number) {
    if (!detailA || uploadId === detailA.upload_id) return;
    try {
      const other = await getUpload(uploadId);
      setDetailB(other);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that version.");
    }
  }

  async function handleDelete(uploadId: number) {
    if (!confirm("Delete this version? This cannot be undone.")) return;
    try {
      await deleteUpload(uploadId);
      setVersions((prev) => prev?.filter((v) => v.upload_id !== uploadId) ?? null);
      if (detailA?.upload_id === uploadId) setDetailA(null);
      if (detailB?.upload_id === uploadId) setDetailB(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete that version.");
    }
  }

  return (
    <AppShell>
      <div className="mb-6">
        <Link href="/app" className="text-sm text-muted hover:text-ink">
          &larr; All applications
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-ink">{role || "Application"}</h1>
        <p className="text-sm text-muted">{company}</p>
      </div>

      {error && (
        <p role="alert" className="mb-4 text-sm text-weak">
          {error}
        </p>
      )}

      {versions === null ? (
        <p className="text-sm text-muted">Loading...</p>
      ) : versions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <h2 className="text-lg font-medium text-ink">No versions for this application</h2>
          <p className="mt-2 text-sm text-muted">
            It may have been deleted or never existed under this company and role.
          </p>
          <Link
            href="/app/new"
            className="mt-6 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
          >
            Score a new CV
          </Link>
        </div>
      ) : (
        <div className="space-y-6">
          <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <h2 className="mb-4 text-sm font-medium text-ink">Versions</h2>
            <ul className="divide-y divide-slate-100">
              {versions.map((v) => {
                const color = BAND_COLOR[bandFor(v.overall_score)];
                const isPrimary = detailA?.upload_id === v.upload_id;
                const isCompare = detailB?.upload_id === v.upload_id;
                return (
                  <li key={v.upload_id} className="flex items-center justify-between py-3">
                    <div className="flex items-center gap-3">
                      <div
                        className="flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold text-white"
                        style={{ backgroundColor: color }}
                      >
                        {v.overall_score}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-ink">{v.filename}</p>
                        <p className="text-xs text-muted">{formatDate(v.created_at, true)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      {isPrimary ? (
                        <span className="rounded-full bg-primary/10 px-2 py-1 font-medium text-primary">
                          Version A
                        </span>
                      ) : isCompare ? (
                        <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-ink">
                          Version B
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleSelectForCompare(v.upload_id)}
                          className="rounded-md border border-slate-200 px-2 py-1 text-muted transition hover:bg-slate-100 hover:text-ink"
                        >
                          Compare
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDelete(v.upload_id)}
                        className="text-muted transition hover:text-weak"
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>

          {detailA && detailB && <ComparisonPanel a={detailA} b={detailB} />}

          {detailA && !detailB && <ScorePanel score={detailA.score} />}
        </div>
      )}
    </AppShell>
  );
}
