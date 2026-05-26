import os
import re
import tempfile
import asyncio
import aiohttp
from typing import Optional

from utils.logger import get_logger
logger = get_logger(__name__)

_YOUTUBE_PATTERN = re.compile(
    r'(youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)'
)

MAX_VIDEO_DURATION_SECONDS = int(os.getenv("MAX_VIDEO_DURATION_SECONDS", str(30 * 60)))


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_PATTERN.search(url))


async def get_youtube_info(url: str) -> dict:
    """
    Fetch YouTube video metadata without downloading.
    Returns dict with 'duration' (seconds) and 'title'.
    """
    import yt_dlp

    ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = await asyncio.to_thread(_extract)
    return {
        'duration': info.get('duration') or 0,
        'title': info.get('title') or 'Unknown',
    }


async def download_youtube_video(url: str) -> str:
    """
    Download a YouTube video using yt-dlp. Returns path to the downloaded file.
    Caller is responsible for cleanup.
    Raises ValueError if the video exceeds MAX_VIDEO_DURATION_SECONDS.
    """
    import yt_dlp

    # Check duration before downloading to avoid wasting bandwidth on long videos.
    # If metadata fetch fails (e.g. bot-check), skip the pre-check and let the download proceed.
    try:
        info = await get_youtube_info(url)
        duration = info['duration']
        if duration > MAX_VIDEO_DURATION_SECONDS:
            minutes = int(duration // 60)
            limit_minutes = MAX_VIDEO_DURATION_SECONDS // 60
            raise ValueError(f"video_too_long:{minutes}:{limit_minutes}")
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"⚠️  Could not fetch YouTube metadata before download (skipping duration check): {e}")

    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, 'video.%(ext)s')

    ydl_opts = {
        # Cap at 480p to keep rendered clips well under Supabase's 50 MB upload limit.
        # 480p is sufficient for 9:16 short-form clips and dramatically reduces file size vs 1080p.
        'format': (
            'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]'
            '/best[height<=480][ext=mp4]'
            '/best[height<=480]'
            '/worst'
        ),
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'quiet': False,
        'no_warnings': False,
    }

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    await asyncio.to_thread(_download)

    files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
    if not files:
        raise RuntimeError(f"yt-dlp produced no output for: {url}")

    return files[0]


async def download_video(url: str) -> str:
    """
    Download video from URL to temporary file.

    Args:
        url: URL to download from

    Returns:
        Path to temporary file
    """
    temp_file = tempfile.mktemp(suffix=".mp4")

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download video: HTTP {response.status}")

            with open(temp_file, 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)

    return temp_file


async def cleanup_file(file_path: str) -> None:
    """
    Delete file asynchronously.

    Args:
        file_path: Path to file to delete
    """
    if file_path and os.path.exists(file_path):
        try:
            await asyncio.to_thread(os.remove, file_path)
            logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Warning: Failed to cleanup file {file_path}: {e}")


async def cleanup_files(*file_paths: str) -> None:
    """
    Delete multiple files asynchronously.

    Args:
        *file_paths: Paths to files to delete
    """
    tasks = [cleanup_file(fp) for fp in file_paths if fp]
    await asyncio.gather(*tasks, return_exceptions=True)
