"""
Video Generator Worker API

CRITICAL: Event loop policy must be set BEFORE any other imports on Windows
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE any async imports (psycopg, langgraph, etc.)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from contextlib import asynccontextmanager
import uvicorn
import os
import uuid
from dotenv import load_dotenv
from schemas import ClipSchema, CaptionDataSchema, RenderedVideoSchema, TranscriptWordSchema

# Load environment variables from .env file
load_dotenv()

from tasks.transcribe import transcribe_video
from tasks.render import render_video
from utils.supabase_client import upload_to_supabase, download_from_supabase
from utils.caption_generator import create_ass_file_for_clip
from workflow.graph import get_workflow, get_pool, cleanup_connections, cleanup_thread_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    Handles startup and shutdown events.
    """
    # Startup: Initialize workflow (lazy initialization will happen on first use)
    print("Starting up Video Generator Worker API...")
    yield
    # Shutdown: Cleanup database connections
    print("Shutting down application...")
    await cleanup_connections()
    print("Cleanup complete")


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


@app.get("/health")
async def health():
    return {"status": "ok"}


class TranscribeRequest(BaseModel):
    video_url: Optional[str] = None
    video_path: Optional[str] = None


class RenderRequest(BaseModel):
    video_url: Optional[str] = None
    video_path: Optional[str] = None
    center_x: Optional[int] = None
    start: float
    end: float
    session_id: Optional[str] = None  # For Supabase storage path
    clip_index: Optional[int] = None  # For naming the clip file
    caption_url: Optional[str] = None  # Supabase URL of ASS subtitle file


TranscriptWord = TranscriptWordSchema


class TranscribeResponse(BaseModel):
    text: str
    words: List[TranscriptWordSchema]
    language: Optional[str] = None


class RenderResponse(BaseModel):
    url: str  # Supabase public URL
    duration: float
    storage_path: str  # Path in Supabase storage


class GenerateCaptionsRequest(BaseModel):
    words: List[TranscriptWordSchema]
    clip_start: float
    clip_end: float
    session_id: str
    clip_index: int
    style: Optional[str] = "highlight"  # 'highlight', 'phrase', or 'static'


class GenerateCaptionsResponse(BaseModel):
    caption_url: str  # Supabase public URL of ASS file
    storage_path: str  # Path in Supabase storage


@app.get("/")
async def root():
    return {"message": "Video Generator Worker API", "status": "running"}


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(request: TranscribeRequest):
    """
    Transcribe video using Whisper AI.

    Returns transcript text with word-level timestamps and detected language.
    """
    try:
        if not request.video_url and not request.video_path:
            raise HTTPException(
                status_code=400,
                detail="video_url or video_path is required"
            )

        result = await transcribe_video(
            video_url=request.video_url,
            video_path=request.video_path
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-captions", response_model=GenerateCaptionsResponse)
async def generate_captions_endpoint(request: GenerateCaptionsRequest):
    """
    Generate ASS subtitle file for a video clip and upload to Supabase.

    Parameters:
    - words: Transcript words with timestamps
    - clip_start: Start time of clip in original video
    - clip_end: End time of clip in original video
    - session_id: Session ID for storage path organization
    - clip_index: Index of the clip for naming
    - style: Caption style ('highlight', 'phrase', or 'static')

    Returns Supabase public URL and storage path of ASS file.
    """
    ass_file_path = None

    try:
        # Convert Pydantic models to dicts for caption generator
        words_dict = [word.model_dump() for word in request.words]

        # Generate ASS subtitle file
        ass_file_path = create_ass_file_for_clip(
            words=words_dict,
            clip_start=request.clip_start,
            clip_end=request.clip_end,
            style=request.style
        )

        if not ass_file_path:
            raise HTTPException(
                status_code=400,
                detail="No words found in clip timerange"
            )

        # Upload to Supabase
        storage_path = f"sessions/{request.session_id}/captions/clip-{request.clip_index}.ass"
        caption_url = upload_to_supabase(ass_file_path, storage_path)

        # Cleanup temp file
        if ass_file_path and os.path.exists(ass_file_path):
            os.remove(ass_file_path)

        return {
            "caption_url": caption_url,
            "storage_path": storage_path
        }

    except HTTPException:
        # Cleanup on error
        if ass_file_path and os.path.exists(ass_file_path):
            os.remove(ass_file_path)
        raise
    except Exception as e:
        # Cleanup on error
        if ass_file_path and os.path.exists(ass_file_path):
            os.remove(ass_file_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/render", response_model=RenderResponse)
async def render_endpoint(request: RenderRequest):
    """
    Trim video to specified time range, burn captions, and upload to Supabase.

    Parameters:
    - video_url: URL of video in Supabase storage (or external URL)
    - video_path: Optional local path (if not using video_url)
    - center_x: (Optional) X coordinate for center of crop - crops to 9:16 aspect ratio
    - start: Start time in seconds
    - end: End time in seconds
    - session_id: Session ID for storage path organization
    - clip_index: Index of the clip for naming
    - caption_url: (Optional) Supabase URL of ASS subtitle file to burn into video

    Returns Supabase public URL, duration, and storage path.
    """
    local_video_path = None
    rendered_video_path = None
    local_caption_path = None

    try:
        if not request.video_url and not request.video_path:
            raise HTTPException(
                status_code=400,
                detail="video_url or video_path is required"
            )

        # If video_url is provided and looks like a Supabase URL, download it first
        if request.video_url and "supabase" in request.video_url:
            # Extract storage path from Supabase URL
            # URL format: https://PROJECT.supabase.co/storage/v1/object/public/BUCKET/PATH
            parts = request.video_url.split("/storage/v1/object/public/")
            if len(parts) == 2:
                full_path = parts[1].split("?")[0]  # Remove query params if any
                # Remove bucket name from path (first segment)
                path_parts = full_path.split("/", 1)
                if len(path_parts) == 2:
                    storage_path = path_parts[1]  # Path without bucket name
                else:
                    storage_path = full_path

                print(f"🔍 Extracted storage path: {storage_path}")
                local_video_path = await download_from_supabase(storage_path)
            else:
                # External URL, let render_video handle the download
                local_video_path = None
        elif request.video_path:
            local_video_path = request.video_path

        # Download caption file if provided
        if request.caption_url and "supabase" in request.caption_url:
            # Extract storage path from Supabase URL
            parts = request.caption_url.split("/storage/v1/object/public/")
            if len(parts) == 2:
                full_path = parts[1].split("?")[0]  # Remove query params if any
                # Remove bucket name from path (first segment)
                path_parts = full_path.split("/", 1)
                if len(path_parts) == 2:
                    caption_storage_path = path_parts[1]  # Path without bucket name
                else:
                    caption_storage_path = full_path

                print(f"🔍 Extracted caption storage path: {caption_storage_path}")
                local_caption_path = await download_from_supabase(caption_storage_path)
                print(f"✅ Downloaded caption file to: {local_caption_path}")

        # Render the video (with optional captions)
        result = await render_video(
            video_url=request.video_url if not local_video_path else None,
            video_path=local_video_path,
            center_x=request.center_x,
            start=request.start,
            end=request.end,
            subtitle_path=local_caption_path
        )

        rendered_video_path = result["output_path"]
        duration = result["duration"]

        # Upload to Supabase if session_id is provided
        if request.session_id is not None and request.clip_index is not None:
            storage_path = f"sessions/{request.session_id}/clips/clip-{request.clip_index}.mp4"
            public_url = upload_to_supabase(rendered_video_path, storage_path)

            # Cleanup local files
            if local_video_path and os.path.exists(local_video_path):
                os.remove(local_video_path)
            if local_caption_path and os.path.exists(local_caption_path):
                os.remove(local_caption_path)
            if rendered_video_path and os.path.exists(rendered_video_path):
                os.remove(rendered_video_path)

            return {
                "url": public_url,
                "duration": duration,
                "storage_path": storage_path
            }
        else:
            # Fallback: return local path if no session_id (for testing)
            return {
                "url": rendered_video_path,
                "duration": duration,
                "storage_path": ""
            }

    except HTTPException:
        # Cleanup on error
        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)
        if local_caption_path and os.path.exists(local_caption_path):
            os.remove(local_caption_path)
        if rendered_video_path and os.path.exists(rendered_video_path):
            os.remove(rendered_video_path)
        raise
    except Exception as e:
        # Cleanup on error
        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)
        if local_caption_path and os.path.exists(local_caption_path):
            os.remove(local_caption_path)
        if rendered_video_path and os.path.exists(rendered_video_path):
            os.remove(rendered_video_path)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== LangGraph Workflow Endpoints ====================

class ExistingClipSchema(BaseModel):
    start: float
    end: float
    title: Optional[str] = None
    score: int = 0


class ProcessVideoRequest(BaseModel):
    video_url: str
    session_id: Optional[str] = None
    existing_clips: Optional[List[ExistingClipSchema]] = None


class ProcessVideoResponse(BaseModel):
    session_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    session_id: str
    current_stage: Optional[str]
    clips: Optional[List[ClipSchema]]
    captions: Optional[List[CaptionDataSchema]]
    rendered_videos: Optional[List[RenderedVideoSchema]]
    errors: Optional[List[str]]
    is_complete: bool


@app.post("/process-video", response_model=ProcessVideoResponse, status_code=202)
async def process_video_workflow(request: ProcessVideoRequest):
    """
    Start video processing workflow. Returns 202 immediately; poll the session
    status via Supabase to track progress.
    """
    import traceback

    session_id = request.session_id or str(uuid.uuid4())
    print(f"\n🚀 POST /process-video  session={session_id}  url={request.video_url}")

    try:
        workflow = await get_workflow()
        await get_pool()

        config = {"configurable": {"thread_id": session_id}}
        existing_clips = [c.model_dump() for c in request.existing_clips] if request.existing_clips else []

        async def _run_workflow():
            try:
                await workflow.ainvoke(
                    {
                        "videoUrl": request.video_url,
                        "sessionId": session_id,
                        "existingClips": existing_clips,
                    },
                    config
                )
            except Exception as bg_err:
                print(f"\n❌ Background workflow FAILED  session={session_id}")
                print(f"   Error type : {type(bg_err).__name__}")
                print(f"   Error msg  : {bg_err}")
                print(f"   Traceback  :\n{traceback.format_exc()}")
            finally:
                cleanup_thread_state(session_id)

        asyncio.create_task(_run_workflow())
        print(f"  ✅ Background task started for session {session_id}\n")

        return {
            "session_id": session_id,
            "status": "accepted",
            "message": f"Video processing started for session {session_id}"
        }

    except Exception as e:
        print(f"\n❌ /process-video FAILED at session={session_id}")
        print(f"   Error type : {type(e).__name__}")
        print(f"   Error msg  : {e}")
        print(f"   Traceback  :\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, loop="none")
