"use client";

import { useEffect, useRef, useState } from "react";

import {
  AuthError,
  downloadRewrittenCv,
  sendOptimiseMessage,
  skipOptimiseGap,
  startOptimise,
  type OptimiseSession,
  type ScoreGap,
} from "../lib/api";
import { BulletDiff } from "./BulletDiff";

type Props = {
  uploadId: number;
  open: boolean;
  onClose: () => void;
  onAuthError: () => void;
};

export function OptimiseDrawer({ uploadId, open, onClose, onAuthError }: Props) {
  const [session, setSession] = useState<OptimiseSession | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || session) return;
    let mounted = true;
    setStarting(true);
    setError(null);
    startOptimise(uploadId)
      .then((s) => {
        if (mounted) setSession(s);
      })
      .catch((err) => {
        if (!mounted) return;
        if (err instanceof AuthError) return onAuthError();
        setError(err instanceof Error ? err.message : "Could not start Optimise.");
      })
      .finally(() => {
        if (mounted) setStarting(false);
      });
    return () => {
      mounted = false;
    };
  }, [open, uploadId, session, onAuthError]);

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [session?.transcript.length, session?.rewrites.length]);

  if (!open) return null;

  const currentGap: ScoreGap | undefined = session?.gaps[session.current_gap_index];
  const done = session?.status === "done";
  const hasRewrites = Boolean(
    session?.rewrites.some((rw) => rw.action === "rewrite"),
  );

  async function handleSend(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || busy || !input.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const next = await sendOptimiseMessage(session.session_id, input.trim());
      setSession(next);
      setInput("");
    } catch (err) {
      if (err instanceof AuthError) return onAuthError();
      setError(err instanceof Error ? err.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDownload() {
    if (!session || busy) return;
    setBusy(true);
    setError(null);
    try {
      await downloadRewrittenCv(uploadId);
    } catch (err) {
      if (err instanceof AuthError) return onAuthError();
      setError(err instanceof Error ? err.message : "Could not download.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSkip() {
    if (!session || busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await skipOptimiseGap(session.session_id);
      setSession(next);
    } catch (err) {
      if (err instanceof AuthError) return onAuthError();
      setError(err instanceof Error ? err.message : "Could not skip.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex" aria-modal="true" role="dialog">
      <button
        type="button"
        aria-label="Close Optimise"
        onClick={onClose}
        className="flex-1 bg-black/30"
      />
      <aside className="flex h-full w-full max-w-2xl flex-col bg-white shadow-xl">
        <header className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-medium text-ink">Optimise your CV</h2>
              <p className="text-sm text-muted">
                One gap at a time. I only use what you or your CV tell me.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {hasRewrites && (
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={busy}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Download PDF
                </button>
              )}
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-muted transition hover:bg-slate-100 hover:text-ink"
              >
                Close
              </button>
            </div>
          </div>
          {currentGap && !done && (
            <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-ink ring-1 ring-slate-200">
              <p className="font-medium text-muted uppercase tracking-wide">
                Current gap ({session!.current_gap_index + 1} of {session!.gaps.length}, {currentGap.severity})
              </p>
              <p className="mt-1">{currentGap.evidence}</p>
            </div>
          )}
          {done && (
            <p className="mt-3 rounded-lg bg-strong/10 p-3 text-sm text-ink ring-1 ring-strong/30">
              All gaps covered. Review the rewrites below.
            </p>
          )}
        </header>

        <div ref={transcriptRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {starting && <p className="text-sm text-muted">Starting Optimise...</p>}
          {session?.transcript.length === 0 && !starting && (
            <p className="text-sm text-muted">
              Send a message about your experience with this gap to get started.
            </p>
          )}
          {session?.transcript.map((m, i) => (
            <div
              key={i}
              className={
                m.role === "user"
                  ? "ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary/10 px-3 py-2 text-sm text-ink"
                  : "mr-auto max-w-[85%] rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-sm text-ink"
              }
            >
              {m.content}
            </div>
          ))}

          {session && session.rewrites.length > 0 && (
            <div className="mt-6 space-y-3">
              <h3 className="text-sm font-medium text-ink">Rewrites so far</h3>
              {session.rewrites.map((rw, i) => (
                <BulletDiff
                  key={i}
                  rewrite={rw}
                  gapEvidence={session.gaps[rw.gap_index]?.evidence ?? ""}
                />
              ))}
            </div>
          )}
        </div>

        {error && (
          <p role="alert" className="border-t border-weak/40 bg-weak/5 px-6 py-2 text-sm text-weak">
            {error}
          </p>
        )}

        <form onSubmit={handleSend} className="border-t border-slate-200 px-6 py-4">
          <div className="flex items-start gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={2}
              disabled={busy || done || !session}
              placeholder={done ? "Session complete." : "Answer the question, or say you have no such experience..."}
              className="block w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm text-ink shadow-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-slate-50"
            />
            <div className="flex flex-col gap-2">
              <button
                type="submit"
                disabled={busy || done || !session || !input.trim()}
                className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy ? "..." : "Send"}
              </button>
              <button
                type="button"
                onClick={handleSkip}
                disabled={busy || done || !session}
                className="rounded-lg border border-slate-300 px-3 py-2 text-xs text-muted transition hover:bg-slate-100 hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
              >
                Skip gap
              </button>
            </div>
          </div>
        </form>
      </aside>
    </div>
  );
}
