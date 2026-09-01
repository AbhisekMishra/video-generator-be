import pytest

from utils.file_utils import is_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ],
)
def test_is_youtube_url_accepts_known_formats(url):
    assert is_youtube_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video.mp4",
        "https://vimeo.com/12345",
        "not a url at all",
    ],
)
def test_is_youtube_url_rejects_non_youtube(url):
    assert is_youtube_url(url) is False
