"""
Input validation helpers shared across endpoints.
"""
import os
import uuid
from urllib.parse import urlparse

from fastapi import HTTPException

from utils.file_utils import is_youtube_url

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SUPABASE_STORAGE_PREFIX = f"{_SUPABASE_URL}/storage/v1/object/public/" if _SUPABASE_URL else None


def validate_session_id(session_id: str) -> None:
    """Raise 400 if session_id isn't a well-formed UUID (it's interpolated into storage paths)."""
    try:
        uuid.UUID(str(session_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="session_id must be a valid UUID")


def validate_video_url(url: str) -> None:
    """
    Only allow YouTube links or URLs pointing at this app's own Supabase Storage bucket.

    Without this, video_url is handed straight to FFmpeg/aiohttp, which can fetch
    arbitrary URLs (internal/metadata addresses, other protocols) — an SSRF vector.
    """
    if is_youtube_url(url):
        return
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="video_url must be an https URL")
    if not _SUPABASE_STORAGE_PREFIX or not url.startswith(_SUPABASE_STORAGE_PREFIX):
        raise HTTPException(
            status_code=400,
            detail="video_url must be a YouTube link or a URL from this app's storage",
        )
