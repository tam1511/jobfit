"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { me } from "./lib/api";
import { DisclaimerBanner } from "./components/Disclaimer";

export default function LandingPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    me()
      .then(() => router.replace("/app"))
      .catch(() => setChecking(false));
  }, [router]);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted">Loading...</p>
      </div>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2">
            <span
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-sm font-semibold text-white"
              style={{ backgroundColor: "var(--color-primary)" }}
            >
              J
            </span>
            <span className="text-lg font-semibold text-ink">JobFit</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <Link href="/login" className="text-muted transition hover:text-ink">
              Sign in
            </Link>
            <Link
              href="/register"
              className="rounded-md bg-primary px-3 py-1.5 font-medium text-white transition hover:opacity-90"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      <section className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center px-6 py-16 text-center">
        <h1 className="text-4xl font-semibold text-ink md:text-5xl">
          Score your CV against any job description.
        </h1>
        <p className="mt-4 max-w-xl text-base text-muted">
          Upload your CV and paste a job description. JobFit reads both, scores the fit
          with a five-category rubric, and shows you the gaps you can close before you apply.
        </p>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <Link
            href="/register"
            className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white shadow-sm transition hover:opacity-90"
          >
            Create free account
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-ink transition hover:bg-slate-100"
          >
            I already have an account
          </Link>
        </div>
        <div className="mt-10 w-full max-w-lg">
          <DisclaimerBanner />
        </div>
      </section>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-4 text-xs text-muted">
          &copy; JobFit. A preview build.
        </div>
      </footer>
    </main>
  );
}
