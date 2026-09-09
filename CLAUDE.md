# JobFit

## What this is

JobFit helps job seekers close the gap between the CV they have and the role they want. The user uploads a CV and gives us a job description — pasted in, or as a link we fetch ourselves.

We score it immediately. No questions first, no setup, no conversation: the CV goes in, the result comes back. That result is a weighted score, a per-category breakdown, and a set of gaps rendered inline on the user's own CV.

Only after that, and only if the user presses Optimise, does a conversation open. That conversation is scoped to the gaps we already
found — it asks about one specific missing detail at a time. It is not a general assistant and it does not interview the user from scratch.

There are no CV templates in this product. We read the document the user gives us and we work on that document.

The product never invents experience. It surfaces what is weak, asks the user to fill the blanks, and rephrases what is genuinely there. Everything in this codebase should respect that boundary.

Assets live in two places:
- `rubric.json` — scoring categories, weights and criteria (project root)
- `fixtures/` — CV and JD pairs with expected results, used to prove the
  rubric behaves consistently. Index inlined below.

@fixtures/index.json

Read `rubric.json` and the documents under `fixtures/` only when a task actually touches them. Do not pull them into context by default.

## How features get built

Each unit of work arrives as a GitHub Issue. For every one of them:

1. Read the issue through the GitHub tools — do not guess at scope
2. Run the full feature-dev workflow. All seven phases. No shortcuts, including the review and test phase
3. Cover the work with unit tests and integration tests, then fix everything those tests surface
4. Open a Pull Request through the GitHub tools when the work is done

If an issue is ambiguous, stop and ask before writing code. Vague tickets are intentional here.

## Conventions

Be simple. Work in small steps and confirm each one before moving on.
Do not over-engineer. Do not write defensively for problems that are not in front of us. Use the current version of every API.

Python lives in a standard venv with pip. Activate the project venv before running anything. `requirements.txt` is the only declaration of dependencies — nothing gets installed without landing there. Prefer short modules and clear docstrings over inline comments.

No emoji. Not in code, not in `print`, not in logs. Keep the README short.

When something breaks: prove the problem exists before touching it, find the root cause, test one hypothesis at a time, and reproduce it consistently. No workarounds for causes we do not understand yet.

## Working with the model

All scoring and rewriting know-how lives in the `cv-rubric` skill. That skill is the single source of truth for:

- the scoring rubric and its weights
- the structured output schema returned by a scoring call
- the rules that govern how CV content may be rewritten

The skill contains no code. It describes what a correct result looks like, not how to produce one. The how belongs here:

- Model calls go through OpenRouter. `OPENROUTER_API_KEY` lives in `.env` at the project root
- Scoring and rewriting are two separate calls with two separate schemas. Do not merge them into one
- Both use Structured Outputs, so the frontend can render the breakdown, the gap list and the keyword sets without parsing free text
- Scoring must be deterministic. The same CV and the same JD produce the same score, every time. `fixtures/` exists to prove that, and a change that breaks it is a broken change
- Anything that can be computed in code is computed in code. Do not ask the model for work that arithmetic or string matching already answers

Do not hand-roll a scoring prompt or a rewrite prompt. If the skill does not cover a case, extend the skill rather than working around it.

## Architecture

Ship the whole thing as a single Docker image. Resist the pull toward docker-compose and a container per service — this project does not need it.

- `backend/` — Python, FastAPI, dependencies pinned in `requirements.txt`, developed inside a standard venv
- `frontend/` — Next.js. Build it statically and let FastAPI serve it if that arrangement holds up
- SQLite, created inside the container. Early tickets may recreate it on every boot; once accounts land, the data has to survive restarts so users keep their application history

The app answers on http://localhost:8000

Scripts go in `scripts/`, one pair per platform:

scripts/start-mac.sh        scripts/stop-mac.sh
scripts/start-linux.sh      scripts/stop-linux.sh
scripts/start-windows.ps1   scripts/stop-windows.ps1

## Visual language

Score colour is meaning, not decoration. A user should read the result
before reading a single number.

| Token | Hex | Used for |
|---|---|---|
| Strong | `#16a34a` | score ≥ 75, matched keywords, rewritten bullets |
| Partial | `#ecad0a` | score 50–74, weak bullets worth improving |
| Weak | `#dc2626` | score < 50, requirements absent from the CV |
| Primary | `#209dd7` | actions, links, active states |
| Ink | `#032147` | headings and body emphasis |
| Muted | `#888888` | secondary text, helper copy |

Score breakdown renders as a ring for the overall figure and horizontal bars per category. Gaps render inline on the user's own CV using the three score colours above, not as a separate list.

## Status

### #2 — Rubric and fixtures (PR #6)

`rubric.json` at the repo root carries the five weighted categories from the `cv-rubric` skill, each with a measurement and a scoring rule. `fixtures/` holds three CV-JD pairs — one per score band — each with an `expected.json` giving score ranges, required matched/missing keywords, and required gaps:

- `case-01-backend-strong` — senior backend engineer, strong match
- `case-02-marketing-partial` — digital marketing manager, partial match; this is the designated demo case, and it additionally ships a `cv.pdf` plus a `build_pdf.py`
- `case-03-data-weak` — data analyst applying for a data scientist role, weak match

`fixtures/index.json` lists all three. A pypdf parity test at `backend/tests/test_pdf_md_parity.py` guards the extractor → scorer seam for case-02 by asserting canonical text extracted from `cv.pdf` matches canonical text of `cv.md`; deterministic scoring turns that into "same score".

### #3 — V1 technical foundation (PR #7)

Whole app skeleton up. FastAPI serves the API and the built frontend from a single process on port 8000.

- `POST /api/session` — fake login; creates a `users` row from a name and returns the id
- `POST /api/uploads` — multipart PDF + `jd_text`; extracts text with pypdf and stores the pair in `uploads`
- `GET /api/health` — liveness probe

Frontend is Next.js 15 App Router with Tailwind and `output: 'export'`. `/` is the login page (name field, localStorage session). `/app` is the authenticated screen: CV upload, JD paste, extracted-text preview, and a disabled Score button that flags scoring as the next ticket. Visual tokens from the table above flow through CSS variables so all colour choices live in one place.

SQLite lives at `/data/jobfit.sqlite3` inside the container. Schema (`users`, `uploads`) is dropped and recreated on every boot — that changes when real accounts land.

Packaging is a single multi-stage Docker image (node builds the frontend, python serves both). `scripts/start-{mac,linux}.sh` / `scripts/start-windows.ps1` and matching `stop-*` counterparts wrap `docker build` and `docker run` with a `jobfit-data` named volume.

Scoring itself is not wired up yet.

### #4 — Deterministic scoring end-to-end

`backend/app/scoring.py` owns the scoring path. It loads `rubric.json` at import, builds the OpenRouter Structured Outputs schema (category names enum-locked, `overall_score` omitted — Python computes it), and calls OpenRouter at `temperature=0` with a retry-once policy. Weights come from the rubric and are injected over the model output, so the model cannot drift. Results are cached by `sha256(cv || jd || model || rubric_version)` in a `scores` table so rubric edits invalidate stale rows.

`POST /api/uploads` now scores inline: scoring runs before the upload row lands, so a `ScoringError` returns 502 with no orphan upload. `GET /api/uploads/{id}/score` reads the persisted `ScoreResult`. `create_app(settings, score_fn=None)` accepts an injected scorer for tests; `score(..., call=None)` accepts an injected HTTP call so cache behaviour can be exercised without network.

Fixtures gain a `scored.json` per case (hand-crafted to satisfy the existing `expected.json` bands); `backend/tests/test_fixture_replay.py` replays them offline and, under `OPENROUTER_LIVE=1`, hits OpenRouter for real and writes back missing `scored.json` files. `.env.example` at the repo root shows the required `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` values.

The frontend renders the score panel from `/api/uploads` directly: `ScoreRing` (SVG), five `CategoryBar`s, matched/missing keyword pills, and `GapCard` items. Colours flow from the visual-language tokens: `strong` ≥ 75, `partial` 50–74, `weak` < 50.

Packaging shakedown from running the built image locally: the Dockerfile now copies `rubric.json` into `/app` (without it, `scoring.py` crashed at import and the container exited before uvicorn bound the port), and `scripts/start-{mac,linux}.sh` / `start-windows.ps1` pass `--env-file .env` when present so `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` reach the container. Stale-session UX after a container rebuild: `POST /api/uploads` returns 422 (not 404) with detail `"Unknown user."` when the form's `user_id` no longer exists, the frontend maps that to a `StaleSessionError`, clears localStorage, and bounces to `/?stale=1` where the login page shows a helpful notice. This shakes out cleanly against the SQLite drop-on-boot until real accounts land.

FastAPI now sets explicit cache headers on the served frontend: HTML routes (`/`, `/app`, `/app/`) send `Cache-Control: no-cache` so the browser always revalidates, and content-hashed `/_next/static/*` assets go out as `public, max-age=31536000, immutable`. Fixes a class of stale-chunk 404s where a heuristic-cached `/app/index.html` from a prior build kept requesting webpack chunks that no longer existed in the new image.

### #5 — Multi-user accounts, application history, comparison, SaaS polish (PR #9)

Real accounts replace the name-only fake session. `users` gains `email UNIQUE` and `password_hash` (bcrypt via the `bcrypt` package — passlib is EOL). A new `sessions(token, user_id, expires_at)` table backs opaque HTTP-only cookies (`jobfit_session`, `SameSite=Lax`, 30-day TTL, `Secure` when `JOBFIT_COOKIE_SECURE=1`). `init_db` is now idempotent (`CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version = 1`) so user data and history survive container restarts — the drop-on-boot behaviour from #3 is gone. A pre-#5 database on disk (no `user_version`, no `email` column) is detected and reset once on boot; those rows only ever held fake sessions with no real credentials.

`uploads` gains `company` and `role_title`, both required and indexed by `(user_id, company, role_title)`. Endpoints under `/api/auth` handle register/login/logout/me. `/api/uploads` no longer takes a `user_id` form field — the current user comes from the cookie via a FastAPI dependency (`app.auth.current_user`). New endpoints: `GET /api/uploads` (list, optional `company` + `role_title` filter), `GET /api/uploads/{id}` (detail), `DELETE /api/uploads/{id}`. All per-upload reads enforce ownership and return 404 for the wrong user. The `StaleSessionError` / `?stale=1` path is retired: 401s just redirect to `/login`.

The frontend gets a proper shell. Routes: `/` (marketing landing), `/login`, `/register`, `/app` (dashboard of applications grouped by company/role), `/app/new` (score a new CV), `/app/applications?company=&role=` (versions list + side-by-side comparison + delete). `AppShell` provides the topbar and footer disclaimer on every authed page and runs the client-side auth guard (fetches `/api/auth/me` on mount). `groupByApplication` bundles uploads by `(company, role_title)`; `ComparisonPanel` renders two `ScoreRing`s and their `CategoryBar`s side by side. `ScorePanel` is factored out of the old app page so the new-score and application-detail routes share it. `Disclaimer` renders in the footer everywhere; `DisclaimerBanner` sits inline on the upload form and on the landing page.

Auth-model dependency: `bcrypt==4.2.1` and `email-validator==2.2.0` in `backend/requirements.txt`. Passlib was tried first and fails on Python 3.14 + modern bcrypt (`AttributeError: module 'bcrypt' has no attribute '__about__'`); calling the `bcrypt` package directly is a smaller, better-maintained dependency and one function each for hash/verify.

Login is timing-safe: `verify_password_or_dummy` always runs one bcrypt check, even when the email is unknown, hashing against a module-level dummy hash computed at import. Wrong-password and unknown-email paths return 401 in comparable time, so an attacker cannot enumerate accounts by response latency. `test_login_wrong_and_missing_email_take_similar_time` asserts the ratio stays under 5×.

Next.js static-export constraint: `/app/applications` uses `useSearchParams` (for `?company=&role=`), which Next 15 will not prerender without a Suspense boundary. The page's default export wraps `ApplicationInner` in `<Suspense>` — same pattern will apply to any future route that reads search params under `output: "export"`.

### #10 — JD fetch from URL

`backend/app/jd_fetch.py` owns the fetch pipeline. `fetch_jd(url, *, resolve_fn=None, http_call=None, browser_call=None)` runs an HTTP-first, browser-fallback flow: `_validate_url` blocks non-`http(s)` schemes and resolves the host (via an injectable `Resolver` so unit tests never touch DNS) to reject private, loopback, link-local (including the `169.254.169.254` cloud-metadata address, IPv4 and IPv6 `::1` / `fe80::`) and multicast targets. httpx GETs with `follow_redirects=False` and a manual `_walk_redirects` loop re-runs `_validate_url` on each hop — a public host that 302s to `http://169.254.169.254/` is rejected before the second request goes out. `trafilatura.extract(favor_precision=True)` pulls the main article body; if the extracted text is under `MIN_EXTRACTED_CHARS = 200`, a lazy `playwright.sync_api` Chromium session renders the page, re-validates `page.url`, and re-extracts. Output is capped at `max_bytes = 20 * 1024` and returned as a `FetchedJd(jd_text, final_url, used_browser)` Pydantic model. All failures raise `JdFetchError(status_code)` — user-facing 400 for validation / not-enough-text, 502 for browser crashes.

`POST /api/jd/fetch` (in `backend/app/routers/jd.py`) is the thin auth-gated wrapper: `current_user` dependency, takes `{"url": ...}`, calls `request.app.state.jd_fetch_fn(url)`, maps `JdFetchError` to `HTTPException` with the right status. `create_app(..., jd_fetch_fn=None)` accepts an injected fetcher for tests; the real one closes over `settings.jd_fetch_{http_timeout,browser_timeout,max_bytes}`.

`uploads` gains a nullable `jd_url TEXT` column via an additive migration: `SCHEMA_VERSION` bumps to `2`, and `init_db()` gets a `_apply_migrations(conn, from_version)` step that `ALTER TABLE uploads ADD COLUMN jd_url` when the on-disk version is `1`. The pre-#5 reset path is preserved. `POST /api/uploads` takes an optional `jd_url` form field which round-trips through `UploadResponse` and `UploadDetail`.

The `/app/new` page grows a URL input plus a "Fetch JD" button that calls `fetchJd(url)` (in `frontend/app/lib/api.ts`) and writes the returned text into the existing JD textarea — the user can still edit it before submitting. `uploadCv(..., jdUrl)` forwards the URL as a form field so we can distinguish "user typed the JD" from "user pasted a link we fetched".

Runtime cost: Playwright ships as a dep pinned to `1.62.0` (older releases build `greenlet` from source and fail on Python 3.14). The Dockerfile installs Chromium via `playwright install chromium` into `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers` with the required Debian shared libs (`libnss3`, `libatk-bridge2.0-0`, etc.); `dumb-init` becomes PID 1 so orphaned browser subprocesses get reaped. Env knobs `JOBFIT_JD_FETCH_HTTP_TIMEOUT`, `JOBFIT_JD_FETCH_BROWSER_TIMEOUT`, `JOBFIT_JD_FETCH_MAX_BYTES` tune the fetch loop without a code change.

Tests inject fake `http_call`, `browser_call`, and `resolve_fn` so no network and no Chromium is required in CI: `test_jd_fetch.py` covers happy HTTP, HTTP-too-short → browser fallback, both-passes-too-short → 400, non-`http` scheme, IPv4 loopback, IPv6 loopback (`::1`), IPv6 link-local (`fe80::`), link-local metadata (`169.254.169.254`), over-max-bytes, HTTP error → 400, browser crash → 502; plus a `httpx.MockTransport`-driven suite over `_walk_redirects` that proves a public 302 → private-IP chain is blocked before the second request, that redirect loops hit the hop cap, and that missing `Location` and 4xx statuses map cleanly. `test_jd_endpoint.py` covers auth-required, happy stub, 400 mapping, 502 mapping. `test_db_init.py` gains a v1→v2 migration case that writes a schema-v1 database with rows, runs `init_db()`, and asserts `jd_url` exists as NULL and `user_version == 2`.

### #11 — Gap-driven Optimise chat with anti-fabrication guard (PR #14)

After scoring surfaces gaps, an **Optimise** button appears on `ScorePanel` (never before, and only when at least one high- or medium-severity gap exists). Clicking it opens a right-side chat drawer (`OptimiseDrawer`) that walks those gaps one at a time; low-severity gaps are not walked. Each turn the model may **ask** one targeted question, **rewrite** an existing bullet, **add** a new one, or **skip** when the candidate has no experience. Rewrites accumulate below the chat as `BulletDiff` before/after cards.

`backend/app/optimise.py` owns the LLM path. `rewrite()` calls OpenRouter Structured Outputs at `temperature=0` with a single retry and **is not cached** (conversation state changes every turn — a content-hash cache would only ever miss). Scoring and rewrite stay two separate calls with two separate schemas.

The model never copies CV text back at us. It picks an existing bullet by `bullet_index` into a numbered `CV BULLETS` list built from `extract_bullets(cv_text)`; the schema enum-locks `bullet_index` to the exact set of valid indices (plus null). No `sources` array, no model-supplied `original_bullet` string. That closes off an entire class of false positives where LLMs paraphrased when asked to copy — the moment "does the model's string appear verbatim in the CV?" is a load-bearing check, pypdf whitespace and LLM paraphrase drift will fail otherwise-grounded rewrites. The backend resolves `bullet_index` to a real CV substring, which is what downstream `apply_rewrites` uses as its `str.replace` target.

Anti-fabrication is enforced at the **entity level**, not the string level. `verify_grounding(rewritten, *, cv_text, original_bullet, user_messages)` extracts atomic facts from the rewritten bullet — numbers with units and currency via `_NUMBER_RE`, ALLCAPS / CamelCase tokens always, plain-Capitalized tokens only when they are *not* the first word of a sentence (so ordinary English verbs like "Deployed" or "Applied" starting a bullet are exempt). Each fact is normalised (`_norm`: NFC, strip bullet markers, collapse whitespace, lowercase) and looked up in a normalised concatenation of the CV, the resolved `original_bullet` and every user message. Failures raise `FabricationError`, which the router converts into a "cannot fill this gap" skip and moves on. The product never salvages by rephrasing.

A **denial short-circuit** in the router runs before any model call. `is_denial(message)` matches conservative first-person negatives ("I don't have that", "I've never used", "I have no experience with", "no such experience"). When the current user message reads as a denial, `send_message` immediately records a skip with reason "Candidate indicated no relevant experience for this gap." and advances — no LLM turn, no risk of the model asking a follow-up or rephrasing the denial into a claim. Ambiguous replies ("not sure", bare "no") are left to the model.

`backend/app/routers/optimise.py` exposes four cookie-gated endpoints, all 404 on other users' sessions:

- `POST /api/optimise/start` — idempotent per upload; returns the existing session if one already exists. 409 if the upload has no walkable gaps.
- `POST /api/optimise/{session_id}/message` — user reply; runs the denial short-circuit, otherwise calls the model and produces ask / rewrite / skip. `_advance()` uses a conditional `UPDATE ... WHERE current_gap_index = ?` for race-safety and `_walked_gaps()` filters low + sorts high-before-medium in one pass.
- `POST /api/optimise/{session_id}/skip` — user-initiated skip; reuses `_record_skip()`.
- `GET /api/optimise/{session_id}` — full state reload (messages + rewrites).

Session state survives container restarts via three tables — `optimise_sessions` (one per upload), `optimise_messages`, `optimise_rewrites` — added by an additive `v2 → v3` migration. Ticket #11's redesign additionally drops the now-unused `sources_json` column via a `v3 → v4` migration (`ALTER TABLE optimise_rewrites DROP COLUMN sources_json`, guarded by a `PRAGMA table_info` check so the migration is safe on a v4 database on disk). `SCHEMA_VERSION = 4`. `create_app(..., optimise_fn=None)` accepts an injected rewriter for tests.

Frontend: `OptimiseDrawer` calls `startOptimise()` on mount, then `sendOptimiseMessage()` / `skipOptimiseGap()`, auto-scrolls on new messages, and is mounted from both `/app/new` and `/app/applications`. `ScorePanel` computes `walkableGaps = high + medium` and hides the Optimise button entirely when the list is empty. `BulletDiff` shows just the original + rewritten pair with the gap evidence — no sources pill list (the guard no longer produces them).

Tests (176 pass, 3 skipped): `test_optimise_grounding.py` locks the entity-level guard (paraphrased-lookup still passes when the fact is in the haystack, invented tokens rejected, sentence-initial verbs not flagged, common verbs not flagged, preserved metric passes). `test_optimise_bullets.py` is the case-02 reproduction test: a stub returning a rewrite grounded in a paraphrased user answer no longer trips `FabricationError`. `test_optimise_unit.py` covers `rewrite()`: ask, grounded rewrite, bullet_index resolution, out-of-range index → error, `add` leaves `original_bullet` null, fabricated metric → `FabricationError`, missing api_key fails fast without calling the stub, retry-once, gives-up-after-second-failure, missing required field; plus `is_denial()` matches "I don't have...", "I've never used...", "no such experience", and does not match "yes I used it", bare "no", or empty. `test_optimise_endpoint.py` covers auth, ownership, low-gap filtering, high-before-medium ordering, 409 no-walkable-gaps, start idempotency, ask-does-not-advance, rewrite-persists-and-advances, denial-forces-skip-without-calling-model, model-skip on ambiguous-yes, `FabricationError` → unfillable skip, user-skip advances without a model call, completing the last gap marks the session done, blank message → 422, OpenRouter error → 502. `test_db_init.py` gains a v3 → v4 migration case that asserts `sources_json` is gone and existing rows survive.

### #12 — Download optimised CV as a PDF (PR #15)

Once Optimise produces at least one `action='rewrite'` row, a "Download PDF" button appears in the `OptimiseDrawer` header. It calls `GET /api/uploads/{upload_id}/rewritten.pdf`, which is a cookie-gated route on the uploads router: `_fetch_owned_upload` enforces ownership (404 for other users' uploads), the endpoint 404s when no `optimise_sessions` row exists for the upload, and 409s when the session has no `action='rewrite'` rows with both bullets non-null. Only `rewrite` is applied in v1 — `add` needs a placement decision the flat pypdf text stream can't answer, so it's ignored for now.

`backend/app/cv_pdf.py` is the pure PDF-building module (deliberately dependency-free — no FastAPI, no DB — so it tests without spinning either up). `apply_rewrites(cv_text, rewrites)` walks the rewrite rows in order and uses `str.replace(original, rewritten, 1)` so a bullet phrase that happens to appear twice in the CV only gets replaced at its first occurrence. `render_cv_pdf(text)` uses `fpdf2==2.8.8` with A4, 54pt margins, and a bundled `DejaVuSans` TTF at 11pt so Vietnamese diacritics render — fpdf2's default Helvetica does not carry Latin-Extended glyphs. The font lives at `backend/app/fonts/DejaVuSans.ttf` (public domain / Bitstream Vera, ~757KB, DejaVu 2.37) with the LICENSE file committed alongside. `cv_pdf.py` checks for the font at import and raises `FileNotFoundError` if it's missing — same pattern as `scoring.py`'s rubric-at-import, so a broken deploy fails fast rather than at first download.

Filenames follow `<name>-<company>-<role>.pdf`. `sanitize_filename` NFC-normalises each segment, collapses whitespace to `_`, and strips anything outside Unicode `\w`, `-`, `.` — so diacritics survive (`Nguyễn_Văn_A-Acme-Kỹ_sư.pdf`), quotes / slashes / colons don't. `content_disposition` handles the RFC 6266 rule that `filename=` must be ASCII: it always emits an ASCII fallback via `unicodedata.normalize("NFKD", ...).encode("ascii", "ignore")`, and when the slug isn't ASCII it also emits `filename*=UTF-8''<pct-encoded>` so modern browsers use the accented name and older clients still get a sensible download.

Frontend: `downloadRewrittenCv(uploadId)` in `frontend/app/lib/api.ts` does the fetch-blob-click dance and defers `URL.revokeObjectURL` via `setTimeout(..., 0)` — Firefox cancels the download if the object URL is revoked in the same tick as `anchor.click()`. `filenameFromContentDisposition` prefers the `filename*=UTF-8''` value when present, falling back to `filename="..."`. The button in `OptimiseDrawer` is gated on `session.rewrites.some(rw => rw.action === "rewrite")` so it never appears before the model produces a real rewrite.

No Dockerfile change: `backend/` is already copied into the image, so the bundled font ships with the existing build. `fpdf2==2.8.8` lands in `backend/requirements.txt`.

Tests (152 pass, 3 skipped, up from 134): `test_cv_pdf.py` (14 unit) covers first-occurrence substitution, `add` / `skip` filtering, missing original / rewritten rows, multiline originals, valid PDF bytes, a `pypdf` round-trip that proves the text really lands in the rendered document (including diacritics), and every filename / header edge case. `test_rewritten_pdf_endpoint.py` (6 endpoint) covers auth-required, ownership 404, no-session 404, no-rewrites 409, skip-only-rows 409, and the happy 200 path that asserts `%PDF-` magic, `Content-Disposition`, `Cache-Control: no-store`, and that the rewritten bullet round-trips through `pypdf.PdfReader`.