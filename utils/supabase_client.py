"""
Supabase client utilities for storage operations.
"""
import os
import tempfile
from typing import Optional
from supabase import create_client, Client
import aiohttp

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "video-storage")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables"
    )

# Create Supabase client with service role key (bypasses RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


async def download_from_supabase(file_path: str) -> str:
    """
    Download a file from Supabase storage to a temporary local file.

    Args:
        file_path: Path in Supabase storage (e.g., "sessions/abc/original/video.mp4")

    Returns:
        str: Path to the downloaded temporary file

    Raises:
        Exception: If download fails
    """
    try:
        # Get public URL
        response = supabase.storage.from_(STORAGE_BUCKET).get_public_url(file_path)
        public_url = response

        print(f"📥 Downloading from Supabase: {file_path}")

        # Download the file using aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(public_url) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to download file: HTTP {resp.status}")

                # Create temporary file
                suffix = os.path.splitext(file_path)[1] or ".mp4"
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

                # Stream to disk in 64 KB chunks — avoids loading entire file into RAM
                try:
                    async for chunk in resp.content.iter_chunked(65536):
                        temp_file.write(chunk)
                finally:
                    temp_file.close()

                print(f"✅ Downloaded to temporary file: {temp_file.name}")
                return temp_file.name

    except Exception as e:
        print(f"❌ Error downloading from Supabase: {e}")
        raise Exception(f"Failed to download from Supabase: {str(e)}")


def upload_to_supabase(local_file_path: str, storage_path: str) -> str:
    """
    Upload a local file to Supabase storage.

    Args:
        local_file_path: Path to the local file to upload
        storage_path: Destination path in Supabase storage (e.g., "sessions/abc/clips/clip-0.mp4")

    Returns:
        str: Public URL of the uploaded file

    Raises:
        Exception: If upload fails
    """
    try:
        print(f"📤 Uploading to Supabase: {storage_path}")

        # Pass the file object directly — avoids loading entire file into RAM
        with open(local_file_path, 'rb') as f:
            response = supabase.storage.from_(STORAGE_BUCKET).upload(
                path=storage_path,
                file=f,
                file_options={"content-type": "video/mp4", "cache-control": "3600"}
            )

        # Get public URL
        public_url_response = supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        public_url = public_url_response

        print(f"✅ Uploaded successfully: {public_url}")
        return public_url

    except Exception as e:
        print(f"❌ Error uploading to Supabase: {e}")
        raise Exception(f"Failed to upload to Supabase: {str(e)}")


def update_session_model(thread_id: str, model_name: str) -> None:
    """Update model_used on the sessions row identified by thread_id."""
    try:
        supabase.table("sessions").update({"model_used": model_name}).eq("thread_id", thread_id).execute()
        print(f"✅ Session {thread_id}: model_used = {model_name}")
    except Exception as e:
        print(f"⚠️  Failed to update session model: {e}")


def update_session_status(thread_id: str, status: str, completed: bool = False) -> None:
    """Update status (and optionally completed_at) on the sessions row identified by thread_id."""
    try:
        data = {"status": status}
        if completed:
            from datetime import datetime, timezone
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
        supabase.table("sessions").update(data).eq("thread_id", thread_id).execute()
        print(f"✅ Session {thread_id}: status = {status}")
    except Exception as e:
        print(f"⚠️  Failed to update session status: {e}")


def update_session_clips_metadata(session_id: str, clips_metadata: list) -> None:
    """Store clip start/end/title/score metadata on the session row (queried by id)."""
    try:
        supabase.table("sessions").update({"clips_metadata": clips_metadata}).eq("id", session_id).execute()
        print(f"✅ Session {session_id}: clips_metadata updated ({len(clips_metadata)} clips)")
    except Exception as e:
        print(f"⚠️  Failed to update session clips_metadata: {e}")


def complete_session(session_id: str, clip_paths: list, clips_metadata: list) -> None:
    """Mark session as completed and persist clip URLs and metadata (queried by id)."""
    from datetime import datetime, timezone
    try:
        supabase.table("sessions").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "clip_paths": clip_paths,
            "clips_metadata": clips_metadata,
            "progress": 100,
            "current_stage": "completed",
        }).eq("id", session_id).execute()
        print(f"✅ Session {session_id}: completed with {len(clip_paths)} clips")
    except Exception as e:
        print(f"⚠️  Failed to complete session: {e}")


def delete_from_supabase(storage_path: str) -> bool:
    """
    Delete a file from Supabase storage.

    Args:
        storage_path: Path in Supabase storage to delete

    Returns:
        bool: True if successful
    """
    try:
        print(f"🗑️  Deleting from Supabase: {storage_path}")

        response = supabase.storage.from_(STORAGE_BUCKET).remove([storage_path])

        print(f"✅ Deleted successfully")
        return True

    except Exception as e:
        print(f"⚠️  Error deleting from Supabase: {e}")
        return False
