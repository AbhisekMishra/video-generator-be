import re
import asyncio
import tempfile
import os
from typing import Optional


_YOUTUBE_PATTERN = re.compile(
    r'(youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)'
)


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_PATTERN.search(url))


def extract_video_id(url: str) -> Optional[str]:
    patterns = [
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        r'youtube\.com/live/([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


async def download_youtube_video(url: str) -> str:
    """
    Download a YouTube video to a temp MP4 file using yt-dlp.

    Returns the local path to the downloaded file.
    Raises RuntimeError if download fails.
    """
    import subprocess

    output_path = tempfile.mktemp(suffix=".mp4")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", output_path,
        url,
    ]

    print(f"⬇️  Downloading YouTube video: {url}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp failed (exit {result.returncode}): {result.stderr.decode()[-500:]}"
        )

    if not os.path.exists(output_path):
        raise RuntimeError("yt-dlp completed but output file not found")

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"✅ YouTube download complete: {output_path} ({size_mb:.1f} MB)")
    return output_path
