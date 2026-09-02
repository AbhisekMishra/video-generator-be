# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Run the server
```bash
python main.py
# or
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Run tests
```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```
CI (`.github/workflows/ci.yml`) runs this plus a full `py_compile` syntax check on every push/PR. Tests only cover pure validation/parsing logic (`utils/validation.py`, `utils/file_utils.py`) — nothing exercises the queue worker or the FFmpeg/Whisper/Claude pipeline end-to-end yet.

### Prerequisites
- Python 3.9+
- FFmpeg installed and available in PATH (`ffmpeg -version` to verify)

## Environment Variables

Required in `.env`:
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=video-storage
ANTHROPIC_API_KEY=               # API key for Claude (used by _identify_clips_stage in workflow/pipeline.py)
INTERNAL_API_KEY=                # Shared secret required on every request (X-Internal-Api-Key header). Must match FASTAPI_INTERNAL_API_KEY on the frontend. Required — the app fails to start without it.
MAX_VIDEO_DURATION_SECONDS=1800  # Default: 30 minutes
MAX_CONCURRENT_JOBS=2
WORKER_POLL_INTERVAL=3
JOB_STALE_TIMEOUT_MINUTES=15
```

## Architecture

### Request Flow

1. **`POST /process-video`** — Enqueues a job (returns 202). The background worker picks it up and runs the pipeline asynchronously.
2. **`GET /process-video/queue-position/{session_id}`** — Polls `job_queue` table in Supabase.
3. **`POST /validate-youtube`** — Checks a YouTube video's duration before a session is created.

That's the entire API surface (plus `/health` and `/`). There used to be standalone `/transcribe`, `/render`, `/generate-captions`, and `/process-video/status/{id}` endpoints — they were deleted (2026-09) because nothing called them; the frontend only ever used the three routes above.

### Pipeline (`workflow/pipeline.py`)

Plain sequential async pipeline — no framework, no state-merging, just `await` and real `try/except`:

```
_transcribe_stage -> _identify_clips_stage -> _generate_captions_stage -> _render_stage
```

`run_pipeline(session_id, video_url, existing_clips)` is the entry point, called from `utils/queue_manager.py`. Each stage:
- **`_transcribe_stage`**: Downloads YouTube video (once, returns `local_video_path` for the render stage to reuse), extracts audio with FFmpeg, transcribes with faster-whisper.
- **`_identify_clips_stage`**: Sends the transcript to Claude (`claude-haiku-4-5-20251001` via the `anthropic` SDK directly) to select 3 best clips (30–75s each, snapped to end on a complete sentence via `_snap_to_sentence_end`). Retries up to 3 times on timeout, error, or unparseable/invalid JSON.
- **`_generate_captions_stage`**: Creates ASS subtitle files per clip, uploads to Supabase.
- **`_render_stage`**: Trims each clip with FFmpeg, burns in subtitles, uploads to Supabase.

**A stage that fails calls `fail_session()` with the real error and stage name, then raises `_StageFailed`** — the pipeline stops immediately at the first failure. This replaced an earlier LangGraph-based version whose linear-graph-with-no-conditional-edges design meant every stage ran regardless of upstream failure, and the *last* stage's generic error silently overwrote whatever specific error an earlier stage had already recorded (e.g. a YouTube download failure would surface to the user as "No clips available" from the render stage). Domain types (`Transcript`, `Clip`, `CaptionData`, etc.) live in `workflow/state.py`.

**Resumability**: each stage's output is cached in the session's `pipeline_state` (JSONB column) as it completes — `get_pipeline_state()`/`save_pipeline_state()` in `utils/supabase_client.py`. A retried job checks this cache before redoing a stage, so a crash after transcription (the expensive Whisper step) doesn't force a full redo. The render stage goes further: it caches each *individual* rendered clip's URL, so a crash partway through rendering only re-renders the clips that didn't finish. This is real, durable resumability — unlike the LangGraph version it replaced, whose in-memory `MemorySaver` checkpoint was explicitly wiped before every run anyway and never actually enabled resuming.

### YouTube bot-detection mitigations (`utils/file_utils.py`)

Cloud host IPs (Railway, Render, AWS, etc.) intermittently get blocked by YouTube with `"Sign in to confirm you're not a bot"` — this is IP-reputation-based, not tied to a specific video (verified: an affected download succeeds immediately from a residential IP with identical yt-dlp options). Three layered mitigations, roughly in order of how much they help:

1. **`extractor_args: {player_client: [android, ios, web]}`** on every yt-dlp call — the android/ios clients skip the web client's JS-signature/bot-check gate entirely.
2. **`_retry_yt_dlp()`** wraps both `get_youtube_info()` and `download_youtube_video()`: 3 attempts, linear backoff (5s, 10s). Helps with brief blips; does not reliably beat a sustained block.
3. **Dockerfile pins yt-dlp to the nightly channel** (`pip install --pre --upgrade yt-dlp`, separate from the main `requirements.txt` install so `--pre` doesn't leak into other dependencies) — YouTube-facing extractor fixes land in nightly first, often days before a stable release.

None of this is a guaranteed fix — that would require either a residential/rotating proxy (cost + infra, no account risk) or cookies from a dedicated YouTube account (free, but account-ban risk and needs periodic manual refresh as cookies expire). Both were discussed with the user (2026-09-02) and deliberately not implemented yet — revisit if failures are still frequent after the mitigations above.

### Queue Manager (`utils/queue_manager.py`)

Uses Supabase `job_queue` table as persistent queue backend. A single asyncio background task (`_worker_loop`) polls every `WORKER_POLL_INTERVAL` seconds, claims jobs with optimistic locking, and dispatches up to `MAX_CONCURRENT_JOBS` concurrent pipeline runs. Stale `processing` jobs are automatically recycled after `JOB_STALE_TIMEOUT_MINUTES`. `_process_job()` catches `_StageFailed` (a stage already recorded the real error) separately from any other exception (a true crash, for which it writes a generic fallback error to the session as a safety net).

### Supabase Storage Layout

```
video-storage/
  sessions/{session_id}/
    original/          # Uploaded source video
    captions/clip-N.ass
    clips/clip-N.mp4
```

Session status is tracked in the `sessions` table; `fail_session()` / `complete_session()` in `utils/supabase_client.py` write directly to it using the service role key (bypasses RLS).

### Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, all route definitions, lifespan startup/shutdown |
| `workflow/pipeline.py` | The 4 pipeline stages + `run_pipeline()` orchestrator + `_StageFailed` |
| `workflow/state.py` | Domain TypedDicts (`Transcript`, `Clip`, `CaptionData`, `RenderedVideo`, `ExistingClip`) |
| `utils/queue_manager.py` | Job queue worker loop; calls `run_pipeline()` per claimed job |
| `utils/supabase_client.py` | All `sessions` table writes, incl. `pipeline_state` cache read/write |
| `tasks/transcribe.py` | Whisper model (lazy singleton), FFmpeg audio extraction |
| `tasks/render.py` | FFmpeg video trimming + subtitle burning |
| `utils/caption_generator.py` | ASS subtitle file generation |
| `utils/quota.py` | Session ownership verification (quota enforcement itself lives in the frontend) |

### Windows-specific

`main.py` sets `asyncio.WindowsSelectorEventLoopPolicy` before any async imports — this is required for psycopg (used indirectly by the `supabase` client) compatibility. `uvicorn` is launched with `loop="none"` in `__main__`.
