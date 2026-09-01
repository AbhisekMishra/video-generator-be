"""
Video Generator Worker API

CRITICAL: Event loop policy must be set BEFORE any other imports on Windows
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE any async imports (psycopg, langgraph, etc.)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from contextlib import asynccontextmanager
import uvicorn
import os
import uuid
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from utils.logger import setup_logging, get_logger, set_request_context
setup_logging()
logger = get_logger(__name__)

from utils.file_utils import get_youtube_info, is_youtube_url, MAX_VIDEO_DURATION_SECONDS
from utils.quota import verify_session_owner
from utils.queue_manager import enqueue_job, get_queue_status, start_worker, stop_worker, worker_health
from utils.validation import validate_session_id, validate_video_url
from utils.supabase_client import supabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    Handles startup and shutdown events.
    """
    logger.info("Starting up Video Generator Worker API...")
    start_worker()
    yield
    # Shutdown: stop queue worker, draining in-flight jobs briefly
    logger.info("Shutting down application...")
    await stop_worker()
    logger.info("Cleanup complete")


app = FastAPI(
    title="Video Generator Worker",
    lifespan=lifespan
)

# CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://clip-ai-5py6.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This service is a backend-for-backend: only the Next.js server (never a browser)
# should ever call it directly. Every route except the platform health check requires
# a shared secret so the API can't be driven directly by anyone who can reach the host.
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
if not INTERNAL_API_KEY:
    raise RuntimeError(
        "INTERNAL_API_KEY environment variable is required — set it to a long random "
        "secret shared with the Next.js frontend (sent as the X-Internal-Api-Key header)."
    )

_PUBLIC_PATHS = {"/health", "/"}


@app.middleware("http")
async def require_internal_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    if request.headers.get("x-internal-api-key") != INTERNAL_API_KEY:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
async def health():
    checks: dict = {"worker": worker_health()}
    try:
        await asyncio.to_thread(
            lambda: supabase.table("sessions").select("id").limit(1).execute()
        )
        checks["supabase"] = {"ok": True}
    except Exception as e:
        checks["supabase"] = {"ok": False, "error": str(e)}

    healthy = checks["worker"]["alive"] and checks["supabase"]["ok"]
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


class ValidateYoutubeRequest(BaseModel):
    url: str


@app.post("/validate-youtube")
async def validate_youtube(request: ValidateYoutubeRequest):
    """
    Check a YouTube URL's duration before creating a session.
    Returns 400 if the video exceeds MAX_VIDEO_DURATION_SECONDS.
    """
    if not is_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")

    try:
        info = await get_youtube_info(request.url)
    except Exception as e:
        # Can't fetch metadata (e.g. bot-check, geo-block) — don't block the user.
        # The download step will surface a real error if the video is truly inaccessible.
        logger.warning(f"⚠️  Could not fetch YouTube metadata for validation (skipping): {e}")
        return {"duration": None, "title": None, "skipped": True}

    duration = info["duration"]
    if duration > MAX_VIDEO_DURATION_SECONDS:
        minutes = int(duration // 60)
        limit_minutes = MAX_VIDEO_DURATION_SECONDS // 60
        raise HTTPException(
            status_code=400,
            detail=(
                f"This video is {minutes} minutes long. "
                f"We support videos up to {limit_minutes} minutes. "
                f"Please try a shorter clip or a specific section of the video."
            ),
        )

    return {"duration": duration, "title": info["title"]}


@app.get("/")
async def root():
    return {"message": "Video Generator Worker API", "status": "running"}


class ExistingClipSchema(BaseModel):
    start: float
    end: float
    title: Optional[str] = None
    score: int = 0


class ProcessVideoRequest(BaseModel):
    video_url: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    existing_clips: Optional[List[ExistingClipSchema]] = None


class ProcessVideoResponse(BaseModel):
    session_id: str
    status: str
    message: str
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[int] = None


@app.post("/process-video", response_model=ProcessVideoResponse, status_code=202)
async def process_video_workflow(request: ProcessVideoRequest):
    """
    Enqueue a video processing job. Returns 202 immediately with queue position.
    Poll session status via Supabase or GET /process-video/queue-position/{session_id}
    to track progress.
    """
    if not request.session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if not request.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        uuid.UUID(request.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a valid UUID")
    validate_session_id(request.session_id)
    validate_video_url(request.video_url)

    session_id = request.session_id
    user_id = request.user_id
    set_request_context(user_id, session_id)
    logger.info(f"🚀 POST /process-video  session={session_id}  url={request.video_url}")

    try:
        # Always verify the session belongs to this user before enqueueing work for it.
        verify_session_owner(session_id, user_id)

        existing_clips = [c.model_dump() for c in request.existing_clips] if request.existing_clips else []

        queue_info = await enqueue_job(
            user_id=user_id,
            session_id=session_id,
            payload={
                "video_url": request.video_url,
                "existing_clips": existing_clips,
            },
        )

        logger.info(f"✅ Job queued  session={session_id}  position={queue_info['queue_position']}")

        return {
            "session_id": session_id,
            "status": "queued",
            "message": f"Job queued at position {queue_info['queue_position']}",
            "queue_position": queue_info["queue_position"],
            "estimated_wait_seconds": queue_info["estimated_wait_seconds"],
        }

    except ValueError as e:
        if str(e) == "duplicate_job":
            raise HTTPException(
                status_code=429,
                detail="You already have an active job. Please wait for it to complete.",
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"❌ /process-video FAILED at session={session_id}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/process-video/queue-position/{session_id}")
async def get_queue_position(session_id: str):
    """Return the current queue position and estimated wait for a session."""
    try:
        status = await get_queue_status(session_id)
        if status is None:
            raise HTTPException(status_code=404, detail="No queue entry found for this session")
        return {"session_id": session_id, **status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, loop="none")
