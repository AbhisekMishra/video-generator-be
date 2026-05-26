"""
Job queue manager with asyncio-based background worker.
Uses Supabase job_queue table as the persistent queue backend.

Configuration via environment variables:
  MAX_CONCURRENT_JOBS      — how many workflow jobs run in parallel (default: 2)
  WORKER_POLL_INTERVAL     — seconds between queue polls (default: 3)
  JOB_STALE_TIMEOUT_MINUTES — minutes before a stuck 'processing' job is recycled (default: 15)
"""
import asyncio
import os
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from utils.supabase_client import supabase
from utils.logger import get_logger, set_request_context

logger = get_logger(__name__)

MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "3"))
JOB_STALE_TIMEOUT_MINUTES = int(os.getenv("JOB_STALE_TIMEOUT_MINUTES", "15"))

_worker_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def enqueue_job(
    user_id: str,
    session_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a video processing job to the queue.

    Returns:
        {"queue_position": int, "job_id": str, "estimated_wait_seconds": int}

    Raises:
        ValueError("duplicate_job") if user already has an active job.
    """
    existing = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .select("id")
        .eq("user_id", user_id)
        .in_("status", ["pending", "processing"])
        .execute()
    )
    if existing.data:
        raise ValueError("duplicate_job")

    # Count jobs ahead to determine position
    pending_result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
    )
    position = (pending_result.count or 0) + 1

    insert_result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .insert(
            {
                "user_id": user_id,
                "session_id": session_id,
                "payload": payload,
                "status": "pending",
                "queue_position": position,
            }
        )
        .execute()
    )

    job_id = insert_result.data[0]["id"]
    estimated_wait = position * 3 * 60  # rough estimate: ~3 min per job
    return {
        "queue_position": position,
        "job_id": job_id,
        "estimated_wait_seconds": estimated_wait,
    }


async def get_queue_status(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Return current queue status for a session.
    Returns None if no job is found for this session.
    """
    result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .select("id, status, created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    job = result.data[0]

    if job["status"] == "pending":
        ahead_result = await asyncio.to_thread(
            lambda: supabase.table("job_queue")
            .select("id", count="exact")
            .eq("status", "pending")
            .lt("created_at", job["created_at"])
            .execute()
        )
        position = (ahead_result.count or 0) + 1
        return {
            "status": "pending",
            "queue_position": position,
            "estimated_wait_seconds": position * 3 * 60,
        }

    return {
        "status": job["status"],
        "queue_position": 0,
        "estimated_wait_seconds": 0,
    }


def start_worker() -> asyncio.Task:
    """Start the background queue worker. Call once from FastAPI lifespan startup."""
    global _worker_task
    _worker_task = asyncio.create_task(_worker_loop())
    return _worker_task


def stop_worker() -> None:
    """Cancel the queue worker. Call from FastAPI lifespan shutdown."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None


# ---------------------------------------------------------------------------
# Internal worker
# ---------------------------------------------------------------------------

async def _count_active_jobs() -> int:
    result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .select("id", count="exact")
        .eq("status", "processing")
        .execute()
    )
    return result.count or 0


async def _recover_stale_jobs() -> None:
    """Reset jobs stuck in 'processing' beyond the stale timeout."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=JOB_STALE_TIMEOUT_MINUTES)
    ).isoformat()

    result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .update({"status": "pending", "started_at": None})
        .eq("status", "processing")
        .lt("started_at", cutoff)
        .execute()
    )
    if result.data:
        logger.info(f"♻️  Recovered {len(result.data)} stale job(s)")


async def _claim_next_job() -> Optional[Dict[str, Any]]:
    """
    Atomically claim the oldest pending job.
    Uses optimistic locking: fetch-then-update-with-condition to handle
    concurrent worker instances.
    """
    fetch_result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .limit(1)
        .execute()
    )

    if not fetch_result.data:
        return None

    job = fetch_result.data[0]
    now = datetime.now(timezone.utc).isoformat()

    claim_result = await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .update({"status": "processing", "started_at": now})
        .eq("id", job["id"])
        .eq("status", "pending")  # only claim if still pending (optimistic lock)
        .execute()
    )

    return claim_result.data[0] if claim_result.data else None


async def _mark_completed(job_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .update({"status": "completed", "completed_at": now})
        .eq("id", job_id)
        .execute()
    )


async def _mark_failed(job_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(
        lambda: supabase.table("job_queue")
        .update({"status": "failed", "completed_at": now, "error": error[:2000]})
        .eq("id", job_id)
        .execute()
    )


async def _process_job(job: Dict[str, Any]) -> None:
    """Run the LangGraph workflow for a queued job."""
    from workflow.graph import get_workflow, get_pool

    job_id = job["id"]
    session_id = job["session_id"]
    payload = job["payload"]

    user_id = job.get("user_id", "anonymous")
    set_request_context(user_id, session_id)
    logger.info(f"⚙️  Processing job {job_id}  session={session_id}  user={user_id}")

    try:
        workflow = await get_workflow()
        await get_pool()

        # Transition session from 'queued' → 'processing' now that work begins
        # video_url stored here so it's available on failure for debugging
        await asyncio.to_thread(
            lambda: supabase.table("sessions")
            .update({
                "status": "processing",
                "current_stage": "transcribe",
                "progress": 10,
                "video_url": payload.get("video_url"),
            })
            .eq("id", session_id)
            .execute()
        )

        config = {"configurable": {"thread_id": session_id}}
        await workflow.ainvoke(
            {
                "videoUrl": payload["video_url"],
                "sessionId": session_id,
                "existingClips": payload.get("existing_clips", []),
            },
            config,
        )

        await _mark_completed(job_id)
        logger.info(f"✅ Job {job_id} completed  session={session_id}")

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.exception(f"❌ Job {job_id} FAILED  session={session_id}")
        await _mark_failed(job_id, err)


async def _worker_loop() -> None:
    """
    Background loop: every WORKER_POLL_INTERVAL seconds, recover stale jobs
    and dispatch pending jobs up to MAX_CONCURRENT_JOBS.
    """
    logger.info(
        f"🔄 Queue worker started  max_concurrent={MAX_CONCURRENT_JOBS}  "
        f"poll={WORKER_POLL_INTERVAL}s  stale_timeout={JOB_STALE_TIMEOUT_MINUTES}min"
    )

    while True:
        try:
            await _recover_stale_jobs()

            active = await _count_active_jobs()
            if active < MAX_CONCURRENT_JOBS:
                job = await _claim_next_job()
                if job:
                    logger.info(f"📥 Claimed job {job['id']}  session={job['session_id']}  user={job.get('user_id', 'unknown')}")
                    asyncio.create_task(_process_job(job))

        except Exception as e:
            logger.warning(f"⚠️  Worker loop error: {e}")

        await asyncio.sleep(WORKER_POLL_INTERVAL)
