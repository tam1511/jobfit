const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export type SessionUser = {
  user_id: number;
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
  extracted_text: string;
  jd_text: string;
  score: ScoreResult;
};

export async function login(name: string): Promise<SessionUser> {
  const response = await fetch(apiUrl("/api/session"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    throw new Error(await extractError(response, "Login failed."));
  }
  return response.json();
}

export class StaleSessionError extends Error {
  constructor(message = "Your session is no longer valid.") {
    super(message);
    this.name = "StaleSessionError";
  }
}

export async function uploadCv(
  userId: number,
  jdText: string,
  file: File
): Promise<UploadResult> {
  const form = new FormData();
  form.set("user_id", String(userId));
  form.set("jd_text", jdText);
  form.set("cv", file);
  const response = await fetch(apiUrl("/api/uploads"), {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const detail = await extractError(response, "Upload failed.");
    if (response.status === 422 && detail === "Unknown user.") {
      throw new StaleSessionError();
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchScore(uploadId: number): Promise<ScoreResult> {
  const response = await fetch(apiUrl(`/api/uploads/${uploadId}/score`));
  if (!response.ok) {
    throw new Error(await extractError(response, "Could not load score."));
  }
  return response.json();
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
