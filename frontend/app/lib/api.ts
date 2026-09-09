const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export type SessionUser = {
  user_id: number;
  email: string;
  name: string;
};

export type ScoreCategory = {
  category: string;
  score: number;
  weight: number;
  evidence: string;
};

export type ScoreGap = {
  severity: "high" | "medium" | "low";
  evidence: string;
  suggestion: string;
};

export type ScoreResult = {
  overall_score: number;
  breakdown: ScoreCategory[];
  gaps: ScoreGap[];
  matched_keywords: string[];
  missing_keywords: string[];
};

export type UploadResult = {
  upload_id: number;
  filename: string;
  company: string;
  role_title: string;
  extracted_text: string;
  jd_text: string;
  jd_url: string | null;
  score: ScoreResult;
};

export type FetchedJd = {
  jd_text: string;
  final_url: string;
  used_browser: boolean;
};

export type UploadSummary = {
  upload_id: number;
  filename: string;
  company: string;
  role_title: string;
  created_at: string;
  overall_score: number;
};

export type UploadDetail = {
  upload_id: number;
  filename: string;
  company: string;
  role_title: string;
  extracted_text: string;
  jd_text: string;
  jd_url: string | null;
  created_at: string;
  score: ScoreResult;
};

export class AuthError extends Error {
  constructor(message = "Not authenticated.") {
    super(message);
    this.name = "AuthError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...init,
  });
  if (response.status === 401) {
    throw new AuthError();
  }
  if (!response.ok) {
    throw new Error(await extractError(response, "Request failed."));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function register(
  email: string,
  password: string,
  name: string,
): Promise<SessionUser> {
  return request<SessionUser>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
}

export async function login(email: string, password: string): Promise<SessionUser> {
  return request<SessionUser>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  await request<void>("/api/auth/logout", { method: "POST" });
}

export async function me(): Promise<SessionUser> {
  return request<SessionUser>("/api/auth/me");
}

export async function uploadCv(
  company: string,
  roleTitle: string,
  jdText: string,
  file: File,
  jdUrl?: string | null,
): Promise<UploadResult> {
  const form = new FormData();
  form.set("company", company);
  form.set("role_title", roleTitle);
  form.set("jd_text", jdText);
  form.set("cv", file);
  if (jdUrl) form.set("jd_url", jdUrl);
  return request<UploadResult>("/api/uploads", { method: "POST", body: form });
}

export async function fetchJd(url: string): Promise<FetchedJd> {
  return request<FetchedJd>("/api/jd/fetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export async function listUploads(filter?: {
  company?: string;
  role_title?: string;
}): Promise<UploadSummary[]> {
  const params = new URLSearchParams();
  if (filter?.company) params.set("company", filter.company);
  if (filter?.role_title) params.set("role_title", filter.role_title);
  const suffix = params.toString();
  return request<UploadSummary[]>(`/api/uploads${suffix ? `?${suffix}` : ""}`);
}

export async function getUpload(uploadId: number): Promise<UploadDetail> {
  return request<UploadDetail>(`/api/uploads/${uploadId}`);
}

export async function deleteUpload(uploadId: number): Promise<void> {
  await request<void>(`/api/uploads/${uploadId}`, { method: "DELETE" });
}

export type OptimiseMessage = {
  role: "user" | "assistant";
  content: string;
};

export type OptimiseRewrite = {
  gap_index: number;
  action: "rewrite" | "add" | "skip" | "unavailable";
  original_bullet: string | null;
  rewritten_bullet: string | null;
  reason: string | null;
};

export type OptimiseSession = {
  session_id: number;
  upload_id: number;
  status: "active" | "done";
  current_gap_index: number;
  gaps: ScoreGap[];
  transcript: OptimiseMessage[];
  rewrites: OptimiseRewrite[];
};

export async function startOptimise(uploadId: number): Promise<OptimiseSession> {
  return request<OptimiseSession>("/api/optimise/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId }),
  });
}

export async function sendOptimiseMessage(
  sessionId: number,
  content: string,
): Promise<OptimiseSession> {
  return request<OptimiseSession>(`/api/optimise/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function skipOptimiseGap(sessionId: number): Promise<OptimiseSession> {
  return request<OptimiseSession>(`/api/optimise/${sessionId}/skip`, {
    method: "POST",
  });
}

export async function downloadRewrittenCv(uploadId: number): Promise<void> {
  const response = await fetch(apiUrl(`/api/uploads/${uploadId}/rewritten.pdf`), {
    credentials: "include",
  });
  if (response.status === 401) throw new AuthError();
  if (!response.ok) throw new Error(await extractError(response, "Download failed."));

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filenameFromContentDisposition(response.headers.get("content-disposition"));
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Firefox may cancel the download if the object URL is revoked in the
  // same tick as click(); defer just long enough for the browser to bind
  // the blob to the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function filenameFromContentDisposition(header: string | null): string {
  if (!header) return "cv.pdf";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8) return decodeURIComponent(utf8[1]);
  const ascii = /filename="([^"]+)"/i.exec(header);
  return ascii ? ascii[1] : "cv.pdf";
}

async function extractError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg ?? "").join(", ");
  } catch {
    // fall through
  }
  return fallback;
}
