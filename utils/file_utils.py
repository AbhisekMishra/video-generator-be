import os
import re
import shutil
import tempfile
import time
import asyncio
import aiohttp
from typing import Optional

from utils.logger import get_logger
logger = get_logger(__name__)

_YOUTUBE_PATTERN = re.compile(
    r'(youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)'
)

MAX_VIDEO_DURATION_SECONDS = int(os.getenv("MAX_VIDEO_DURATION_SECONDS", str(30 * 60)))

# YouTube's bot-detection block ("Sign in to confirm you're not a bot") is largely
# IP-reputation-based on cloud hosts (Railway/Render/AWS/etc.) rather than tied to a
# specific video — it can clear up within seconds, so a few retries with backoff
# meaningfully improve success without needing cookies or a proxy.
YT_DLP_MAX_ATTEMPTS = 5
YT_DLP_RETRY_DELAY_SECONDS = 5

# A resumed job (retry, or the queue's stale-job recovery) skips straight to whatever
# stage isn't cached yet — if that's render, it needs the source video again. Keying
# downloads by session_id here lets it reuse the file already downloaded during
# transcribe instead of hitting YouTube's bot-check a second time. Bounded by both a
# TTL and a hard size cap (checked on every write) so many concurrent/failed sessions
# can't fill the disk and crash the pod — see _enforce_video_cache_limits().
VIDEO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "clipai_video_cache")
VIDEO_CACHE_MAX_AGE_MINUTES = int(os.getenv("VIDEO_CACHE_MAX_AGE_MINUTES", "60"))
VIDEO_CACHE_MAX_TOTAL_MB = int(os.getenv("VIDEO_CACHE_MAX_TOTAL_MB", "3000"))


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_PATTERN.search(url))


def get_cached_video_path(session_id: str) -> Optional[str]:
    """Return a previously-downloaded video for this session, if still cached."""
    if not session_id or not os.path.isdir(VIDEO_CACHE_DIR):
        return None
    for name in os.listdir(VIDEO_CACHE_DIR):
        if os.path.splitext(name)[0] == session_id:
            path = os.path.join(VIDEO_CACHE_DIR, name)
            if os.path.isfile(path):
                return path
    return None


def _enforce_video_cache_limits() -> None:
    """
    Bound the video cache's disk footprint: drop entries older than
    VIDEO_CACHE_MAX_AGE_MINUTES, then evict oldest-first if the total size is still
    over VIDEO_CACHE_MAX_TOTAL_MB. Called after every write so the cache self-cleans
    without needing a separate background sweep.
    """
    if not os.path.isdir(VIDEO_CACHE_DIR):
        return

    now = time.time()
    max_age_seconds = VIDEO_CACHE_MAX_AGE_MINUTES * 60
    entries = []
    for name in os.listdir(VIDEO_CACHE_DIR):
        path = os.path.join(VIDEO_CACHE_DIR, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if now - stat.st_mtime > max_age_seconds:
            try:
                os.remove(path)
                logger.info(f"🗑️  Video cache: evicted expired entry {name}")
            except OSError:
                pass
            continue
        entries.append((path, stat.st_mtime, stat.st_size))

    total_bytes = sum(e[2] for e in entries)
    max_bytes = VIDEO_CACHE_MAX_TOTAL_MB * 1024 * 1024
    if total_bytes <= max_bytes:
        return

    entries.sort(key=lambda e: e[1])  # oldest first
    for path, _mtime, size in entries:
        if total_bytes <= max_bytes:
            break
        try:
            os.remove(path)
            total_bytes -= size
            logger.info(f"🗑️  Video cache: evicted {os.path.basename(path)} to stay under {VIDEO_CACHE_MAX_TOTAL_MB}MB cap")
        except OSError:
            pass


async def _retry_yt_dlp(attempt_fn, description: str):
    """Run attempt_fn() (async, does its own setup/cleanup) up to YT_DLP_MAX_ATTEMPTS
    times with linear backoff, for the transient-bot-check case described above."""
    last_error = None
    for attempt in range(1, YT_DLP_MAX_ATTEMPTS + 1):
        try:
            return await attempt_fn()
        except Exception as e:
            last_error = e
            if attempt < YT_DLP_MAX_ATTEMPTS:
                delay = YT_DLP_RETRY_DELAY_SECONDS * attempt
                logger.warning(f"⚠️  {description} failed (attempt {attempt}/{YT_DLP_MAX_ATTEMPTS}): {e} — retrying in {delay}s")
                await asyncio.sleep(delay)
    raise last_error


async def get_youtube_info(url: str) -> dict:
    """
    Fetch YouTube video metadata without downloading.
    Returns dict with 'duration' (seconds) and 'title'.
    """
    import yt_dlp

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        # android/ios clients skip the web client's JS-signature challenge and bot-check
        # gate entirely — they serve pre-signed URLs, which is why they dodge YouTube's
        # "Sign in to confirm you're not a bot" block that the web client hits.
        'extractor_args': {'youtube': {'player_client': ['android', 'ios', 'web']}},
    }

    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = await _retry_yt_dlp(lambda: asyncio.to_thread(_extract), "YouTube metadata fetch")
    return {
        'duration': info.get('duration') or 0,
        'title': info.get('title') or 'Unknown',
    }


async def download_youtube_video(url: str, session_id: Optional[str] = None) -> str:
    """
    Download a YouTube video using yt-dlp. Returns path to the downloaded file.

    If session_id is given, the file is saved under VIDEO_CACHE_DIR keyed by that id
    (bounded by a TTL + size cap, not caller-cleaned) so a later stage or a retry can
    reuse it via get_cached_video_path() instead of downloading again. Without a
    session_id, behaves as before: a plain temp file the caller is responsible for
    cleaning up.

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

    async def _attempt() -> str:
        # A fresh temp_dir per attempt — reusing one across retries risks yt-dlp
        # tripping over a partial file left by the previous failed attempt.
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
            # See get_youtube_info's comment — same bot-check bypass for the actual download.
            'extractor_args': {'youtube': {'player_client': ['android', 'ios', 'web']}},
        }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        try:
            await asyncio.to_thread(_download)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
        if not files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"yt-dlp produced no output for: {url}")

        # Move the result out of the per-download directory (and any extra files
        # yt-dlp leaves alongside it) so nothing here leaks on disk forever.
        src = files[0]
        ext = os.path.splitext(src)[1] or ".mp4"

        if session_id:
            os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)
            dest = os.path.join(VIDEO_CACHE_DIR, f"{session_id}{ext}")
        else:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=True) as _tmp:
                dest = _tmp.name

        shutil.move(src, dest)
        shutil.rmtree(temp_dir, ignore_errors=True)

        if session_id:
            _enforce_video_cache_limits()

        return dest

    return await _retry_yt_dlp(_attempt, "YouTube video download")


async def download_video(url: str) -> str:
    """
    Download video from URL to temporary file.

    Args:
        url: URL to download from

    Returns:
        Path to temporary file
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as _tmp:
        temp_file = _tmp.name

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
