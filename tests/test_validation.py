"""
Real, automated tests (pytest) for the pure validation/parsing logic used to
guard the API endpoints. These replace the old test_api.py/test_workflow.py,
which were manual print()-based scripts that posted to a /process endpoint
that no longer exists.
"""
import os
import uuid

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")

from utils.validation import validate_session_id, validate_video_url  # noqa: E402


def test_validate_session_id_accepts_uuid():
    validate_session_id(str(uuid.uuid4()))  # should not raise


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "", "../../etc/passwd", "123"])
def test_validate_session_id_rejects_non_uuid(bad_id):
    with pytest.raises(HTTPException) as exc:
        validate_session_id(bad_id)
    assert exc.value.status_code == 400


def test_validate_video_url_accepts_youtube():
    validate_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")  # should not raise


def test_validate_video_url_accepts_own_supabase_storage():
    url = "https://example.supabase.co/storage/v1/object/public/video-storage/sessions/abc/original/video.mp4"
    validate_video_url(url)  # should not raise


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://internal-service.local/secrets",
        "https://evil.example.com/video.mp4",
        "file:///etc/passwd",
        "ftp://example.com/video.mp4",
    ],
)
def test_validate_video_url_rejects_untrusted_urls(bad_url):
    with pytest.raises(HTTPException) as exc:
        validate_video_url(bad_url)
    assert exc.value.status_code == 400
