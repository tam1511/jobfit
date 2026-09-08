"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { logout, me, type SessionUser } from "../lib/api";
import { Disclaimer } from "./Disclaimer";

type Props = {
  children: React.ReactNode;
};

export function AppShell({ children }: Props) {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let mounted = true;
    me()
      .then((u) => {
        if (mounted) {
          setUser(u);
          setChecking(false);
        }
      })
      .catch(() => {
        if (mounted) router.replace("/login");
      });
    return () => {
      mounted = false;
    };
  }, [router]);

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // best-effort; the cookie is going regardless
    }
    router.replace("/login");
  }

  if (checking || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <Link href="/app" className="flex items-center gap-2">
            <span
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-sm font-semibold text-white"
              style={{ backgroundColor: "var(--color-primary)" }}
            >
              J
            </span>
            <span className="text-lg font-semibold text-ink">JobFit</span>
          </Link>
          <nav className="hidden gap-6 text-sm font-medium text-muted md:flex">
            <Link href="/app" className="transition hover:text-ink">
              Applications
            </Link>
            <Link href="/app/new" className="transition hover:text-ink">
              New score
            </Link>
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-muted sm:inline">{user.name}</span>
            <button
              type="button"
              onClick={handleSignOut}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-muted transition hover:bg-slate-100 hover:text-ink"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
      <Disclaimer />
    </div>
  );
}
