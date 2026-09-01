# Backend TODO / technical debt backlog

Remaining items from the production-readiness audit (2026-09) that are **not yet done**.
P0 and most P1 items were already fixed — see `CLAUDE.md` and git history for what changed.
This list is what's left.

## Needs a product/infra decision first

- [ ] **Observability (Sentry/APM)** — logs are stdout-only, no error tracking. Needs a
      Sentry DSN (or equivalent) from the team before wiring anything up.
- [x] ~~**Persistent LangGraph checkpointer**~~ — RESOLVED 2026-09-01, differently than
      planned: rather than swapping to a Postgres-backed LangGraph checkpointer,
      LangGraph was dropped entirely (see `CLAUDE.md`). `sessions.pipeline_state`
      (new JSONB column) now caches each pipeline stage's real output, and a retried
      job resumes from the first stage not already cached — including per-clip resume
      in the render stage. This is durable (real Postgres, unlike the old in-memory
      `MemorySaver`, which was wiped before every run anyway and never actually enabled
      resuming).
- [ ] **Crash/kill mid-job stuck window** — `JOB_STALE_TIMEOUT_MINUTES` (default 15 min)
      is how long a user sees "processing" with no feedback if the worker dies
      mid-render. Graceful shutdown (added) reduces how often this happens on a normal
      deploy, but doesn't eliminate the window for a hard crash/OOM kill. Now that a
      recycled stale job resumes via `pipeline_state` instead of restarting from
      scratch (see above), a shorter timeout is less costly than it used to be —
      worth revisiting.

## Code quality / maintainability (P2 — safe to defer indefinitely)

- [ ] **Duplicate YouTube-download implementations.** `utils/file_utils.py` (the one
      actually used everywhere) lacks the `YOUTUBE_COOKIES`-based bot-detection
      workaround that the *unused* `utils/youtube.py` already has. Either delete the
      dead file, or port the cookie support into the live implementation — right now
      the fix for a real reliability gap is sitting unused right next to the bug.
- [x] ~~**Business logic duplicated 3+ places**~~ — RESOLVED as a side effect of the
      2026-09-01 pipeline rewrite: the standalone `/render` endpoint (which had its own
      copy of the Supabase-URL-to-storage-path extraction) was deleted entirely (zero
      frontend callers). The only remaining copy is in `workflow/pipeline.py`'s
      `_render_stage`.
- [ ] **Repo clutter partially cleaned** — `SIMPLE_EXAMPLES.py` was removed. `PYTHON_GUIDE.md`
      and `README_BEGINNER.md` are still in the repo root and get copied into the Docker
      image (no `.dockerignore` exists). Low priority, but worth a `.dockerignore` at
      some point regardless.
- [ ] **Logo-rendering fallback chain** (`tasks/render.py:_logo_as_png`) tries 5 backends
      (3 of which shell out to external CLIs — Inkscape, ImageMagick) just to render a
      static logo overlay. A single pre-rendered `logo.png` dropped into `utils/assets/`
      would make backends 1-4 dead weight and remove that whole code path.

## Also worth knowing
- `langgraph`/`langchain-anthropic`/`langchain-core` are gone as of 2026-09-01 (see
  `CLAUDE.md`) — `anthropic` is called directly now. The note that used to be here about
  not pinning their upper bounds no longer applies.
- `utils/youtube.py` has a `YOUTUBE_COOKIES`-based bot-detection workaround that was
  never wired up — `utils/file_utils.py` (the one actually used) instead uses yt-dlp's
  `player_client: [android, ios, web]` extractor args (added 2026-09-01), which fixed a
  live "Sign in to confirm you're not a bot" failure without needing cookies. Given that,
  `utils/youtube.py` is very likely just dead weight now — worth confirming and deleting
  rather than porting its cookie support over.
