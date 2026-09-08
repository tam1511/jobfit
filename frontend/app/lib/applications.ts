import type { UploadSummary } from "./api";

export type ApplicationGroup = {
  company: string;
  role_title: string;
  versions: UploadSummary[];
  latest: UploadSummary;
  bestScore: number;
  latestScore: number;
};

export function groupByApplication(uploads: UploadSummary[]): ApplicationGroup[] {
  const byKey = new Map<string, UploadSummary[]>();
  for (const upload of uploads) {
    const key = `${upload.company}\u0000${upload.role_title}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.push(upload);
    } else {
      byKey.set(key, [upload]);
    }
  }
  const groups: ApplicationGroup[] = [];
  for (const versions of byKey.values()) {
    versions.sort((a, b) => b.created_at.localeCompare(a.created_at));
    const latest = versions[0];
    const bestScore = versions.reduce((max, v) => Math.max(max, v.overall_score), 0);
    groups.push({
      company: latest.company,
      role_title: latest.role_title,
      versions,
      latest,
      bestScore,
      latestScore: latest.overall_score,
    });
  }
  groups.sort((a, b) => b.latest.created_at.localeCompare(a.latest.created_at));
  return groups;
}

export function applicationHref(company: string, role_title: string): string {
  const params = new URLSearchParams({ company, role: role_title });
  return `/app/applications?${params.toString()}`;
}
