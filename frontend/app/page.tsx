"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { login } from "./lib/api";
import { readSession, writeSession } from "./lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (readSession()) {
      router.replace("/app");
    }
  }, [router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter your name to continue.");
      return;
    }
    setSubmitting(true);
    try {
      const user = await login(trimmed);
      writeSession(user);
      router.push("/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md space-y-6 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-slate-200"
      >
        <div>
          <h1 className="text-2xl font-semibold text-ink">JobFit</h1>
          <p className="mt-1 text-sm text-muted">
            Score your CV against a job description in seconds.
          </p>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-ink">Your name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Mai Nguyen"
            autoFocus
            className="mt-2 block w-full rounded-lg border border-slate-300 px-3 py-2 text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-weak">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-primary px-4 py-2 font-medium text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Signing in..." : "Continue"}
        </button>

        <p className="text-xs text-muted">
          No password needed for this preview build.
        </p>
      </form>
    </main>
  );
}
