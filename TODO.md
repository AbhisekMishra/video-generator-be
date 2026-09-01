# Backend TODO / technical debt backlog

Remaining items from the production-readiness audit (2026-09) that are **not yet done**.
P0 and most P1 items were already fixed — see `CLAUDE.md` and git history for what changed.
This list is what's left.

## Needs a product/infra decision first

- [ ] **Observability (Sentry/APM)** — logs are stdout-only, no error tracking. Needs a
      Sentry DSN (or equivalent) from the team before wiring anything up.
- [ ] **Persistent LangGraph checkpointer** — the in-memory `MemorySaver` loses all
      workflow state on restart/redeploy. `GET /process-video/status/{session_id}` now
      falls back to the `sessions` table when the checkpoint is empty (good enough for
      status *display*), but a job actually killed mid-restart still relies on the
      15-minute stale-job recovery to self-heal, not a clean resume. Fixing this
      properly means swapping to a Postgres-backed checkpointer
      (`langgraph-checkpoint-postgres` or similar) — a real architecture change, not a
      quick patch.
- [ ] **Crash/kill mid-job stuck window** — `JOB_STALE_TIMEOUT_MINUTES` (default 15 min)
      is how long a user sees "processing" with no feedback if the worker dies
      mid-render. Graceful shutdown (added) reduces how often this happens on a normal
      deploy, but doesn't eliminate the window for a hard crash/OOM kill. Consider
      lowering the timeout or surfacing a "this is taking longer than usual" UI state
      after some threshold instead.

## Code quality / maintainability (P2 — safe to defer indefinitely)

- [ ] **Duplicate YouTube-download implementations.** `utils/file_utils.py` (the one
      actually used everywhere) lacks the `YOUTUBE_COOKIES`-based bot-detection
      workaround that the *unused* `utils/youtube.py` already has. Either delete the
      dead file, or port the cookie support into the live implementation — right now
      the fix for a real reliability gap is sitting unused right next to the bug.
- [ ] **Business logic duplicated 3+ places** — Supabase-URL-to-storage-path extraction
      is copy-pasted in `main.py` (`/render` endpoint, twice) and `workflow/nodes.py`'s
      `render_node`. Extract to a shared helper.
- [ ] **Repo clutter partially cleaned** — `SIMPLE_EXAMPLES.py` was removed. `PYTHON_GUIDE.md`
      and `README_BEGINNER.md` are still in the repo root and get copied into the Docker
      image (no `.dockerignore` exists). Low priority, but worth a `.dockerignore` at
      some point regardless.
- [ ] **Logo-rendering fallback chain** (`tasks/render.py:_logo_as_png`) tries 5 backends
      (3 of which shell out to external CLIs — Inkscape, ImageMagick) just to render a
      static logo overlay. A single pre-rendered `logo.png` dropped into `utils/assets/`
      would make backends 1-4 dead weight and remove that whole code path.

## Also worth knowing
- `requirements.txt` intentionally does NOT pin upper bounds on `langgraph`,
  `langchain-anthropic`, `langchain-core` — the versions actually deployed in production
  couldn't be verified from this environment (the local venv found here didn't even have
  these installed). Before adding a ceiling, run `pip freeze` against the real deployment
  and pin exact versions instead of guessing.
