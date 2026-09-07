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

Fresh repository. Nothing implemented yet. This file gets a Status section per shipped issue as we go.