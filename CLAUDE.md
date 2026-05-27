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

### Prerequisites
- Python 3.9+
- FFmpeg installed and available in PATH (`ffmpeg -version` to verify)

## Environment Variables

Required in `.env`:
```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=video-storage
GITHUB_TOKEN=                    # Used as API key for GitHub Models inference endpoint
OPENAI_API_KEY=                  # May be needed by LangChain
MAX_VIDEO_DURATION_SECONDS=1800  # Default: 30 minutes
MAX_CONCURRENT_JOBS=2
WORKER_POLL_INTERVAL=3
JOB_STALE_TIMEOUT_MINUTES=15
```

## Architecture

### Request Flow

1. **`POST /process-video`** — Enqueues a job (returns 202). The background worker picks it up and runs the LangGraph workflow asynchronously.
2. **`GET /process-video/status/{session_id}`** — Polls LangGraph checkpointer state (in-memory `MemorySaver`).
3. **`GET /process-video/queue-position/{session_id}`** — Polls `job_queue` table in Supabase.

There are also standalone direct endpoints (`/transcribe`, `/render`, `/generate-captions`, `/validate-youtube`) used independently by the frontend for manual operations.

### LangGraph Workflow (`workflow/`)

Linear pipeline with 4 nodes — no conditional edges; errors are stored in state rather than raised:

```
transcribe -> identifyClips -> generateCaptions -> render -> END
```

- **`transcribe_node`**: Downloads YouTube video (once, stores `localVideoPath` in state for reuse), extracts audio with FFmpeg, transcribes with faster-whisper.
- **`identify_clips_node`**: Sends transcript to an LLM (GitHub Models API via `https://models.inference.ai.azure.com`) to select 3 best clips (30–75s each). Uses tiered model rotation (`utils/model_selector.py`) with in-memory quota tracking.
- **`generate_captions_node`**: Creates ASS subtitle files per clip, uploads to Supabase.
- **`render_node`**: Trims video with FFmpeg, burns in subtitles, uploads clips to Supabase, calls `complete_session()`.

State is defined in `workflow/state.py` as `VideoProcessingState` (TypedDict). Nodes return partial dicts that LangGraph merges into state.

### Queue Manager (`utils/queue_manager.py`)

Uses Supabase `job_queue` table as persistent queue backend. A single asyncio background task (`_worker_loop`) polls every `WORKER_POLL_INTERVAL` seconds, claims jobs with optimistic locking, and dispatches up to `MAX_CONCURRENT_JOBS` concurrent workflow invocations. Stale `processing` jobs are automatically recycled after `JOB_STALE_TIMEOUT_MINUTES`.

### Model Selection (`utils/model_selector.py` + `utils/model_registry.py`)

Models are tiered: `low -> high -> special`. Selection picks the least-used available model respecting per-minute (RPM) and per-day (RPD) limits. Windows reset lazily on each read. If a model returns an `unknown_model` error, it is exhausted via `exhaust_model()` and the next is tried.

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
| `schemas.py` | Shared Pydantic models (single source of truth for API + workflow) |
| `workflow/graph.py` | LangGraph graph definition; singleton `_graph_instance` with `MemorySaver` |
| `workflow/nodes.py` | All 4 pipeline node implementations |
| `workflow/state.py` | `VideoProcessingState` TypedDict |
| `tasks/transcribe.py` | Whisper model (lazy singleton), FFmpeg audio extraction |
| `tasks/render.py` | FFmpeg video trimming + subtitle burning |
| `utils/caption_generator.py` | ASS subtitle file generation |
| `utils/model_registry.py` | Static list of GitHub Models with tier/RPM/RPD limits |
| `utils/quota.py` | Session ownership verification |

### Windows-specific

`main.py` sets `asyncio.WindowsSelectorEventLoopPolicy` before any async imports — this is required for psycopg/langgraph compatibility. `uvicorn` is launched with `loop="none"` in `__main__`.
