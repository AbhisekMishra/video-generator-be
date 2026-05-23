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


def _write_cookies_file() -> Optional[str]:
    """Write YOUTUBE_COOKIES env var to a temp Netscape-format cookie file. Returns path or None."""
    cookies_content = os.getenv("YOUTUBE_COOKIES", "").strip()
    if not cookies_content:
        return None
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    if not cookies_content.startswith("# Netscape HTTP Cookie File"):
        tmp.write("# Netscape HTTP Cookie File\n")
    tmp.write(cookies_content)
    tmp.close()
    return tmp.name


async def download_youtube_video(url: str) -> str:
    """
    Download a YouTube video to a temp MP4 file using yt-dlp.

    Returns the local path to the downloaded file.
    Raises RuntimeError if download fails.
    """
    import subprocess

    output_path = tempfile.mktemp(suffix=".mp4")
    cookies_file = _write_cookies_file()

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--extractor-args", "youtube:player_client=android,tv_embedded,web",
        "--no-check-certificate",
    ]

    if cookies_file:
        cmd += ["--cookies", cookies_file]
        print("🍪 Using YouTube cookies for authentication")
    else:
        print("⚠️  No YOUTUBE_COOKIES env var set — download may fail on server IPs")

    cmd += ["-o", output_path, url]

    print(f"⬇️  Downloading YouTube video: {url}")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        )
    finally:
        if cookies_file and os.path.exists(cookies_file):
            os.remove(cookies_file)

    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp failed (exit {result.returncode}): {result.stderr.decode()[-500:]}"
        )

    if not os.path.exists(output_path):
        raise RuntimeError("yt-dlp completed but output file not found")

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"✅ YouTube download complete: {output_path} ({size_mb:.1f} MB)")
    return output_path
