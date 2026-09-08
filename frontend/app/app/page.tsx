"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { listUploads, type UploadSummary } from "../lib/api";
import { AppShell } from "../components/AppShell";
import { applicationHref, groupByApplication, type ApplicationGroup } from "../lib/applications";
import { bandFor, BAND_COLOR } from "../components/scoreThreshold";

export default function DashboardPage() {
  const [uploads, setUploads] = useState<UploadSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listUploads()
      .then(setUploads)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load history."));
  }, []);

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Applications</h1>
          <p className="text-sm text-muted">
            Every company and role you have scored a CV against.
          </p>
        </div>
        <Link
          href="/app/new"
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
        >
          Score a new CV
        </Link>
      </div>

      {error && (
        <p role="alert" className="mb-4 text-sm text-weak">
          {error}
        </p>
      )}

      {uploads === null ? (
        <p className="text-sm text-muted">Loading...</p>
      ) : uploads.length === 0 ? (
        <EmptyState />
      ) : (
        <ApplicationGrid groups={groupByApplication(uploads)} />
      )}
    </AppShell>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
      <h2 className="text-lg font-medium text-ink">No applications yet</h2>
      <p className="mt-2 text-sm text-muted">
        Score your first CV against a job description to start tracking history.
      </p>
      <Link
        href="/app/new"
        className="mt-6 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
      >
        Score a new CV
      </Link>
    </div>
  );
}

function ApplicationGrid({ groups }: { groups: ApplicationGroup[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {groups.map((group) => (
        <ApplicationCard key={`${group.company}\u0000${group.role_title}`} group={group} />
      ))}
    </div>
  );
}

function ApplicationCard({ group }: { group: ApplicationGroup }) {
  const bandColor = BAND_COLOR[bandFor(group.latestScore)];
  return (
    <Link
      href={applicationHref(group.company, group.role_title)}
      className="block rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted">{group.company}</p>
          <h3 className="mt-1 truncate text-base font-semibold text-ink">{group.role_title}</h3>
        </div>
        <div
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
          style={{ backgroundColor: bandColor }}
          aria-label={`Latest score ${group.latestScore}`}
        >
          {group.latestScore}
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-muted">
        <span>
          {group.versions.length} version{group.versions.length === 1 ? "" : "s"}
        </span>
        <span>Best score {group.bestScore}</span>
      </div>
    </Link>
  );
}
