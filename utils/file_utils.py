import os
import tempfile
import asyncio
import aiohttp
from typing import Optional


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
            print(f"Cleaned up file: {file_path}")
        except Exception as e:
            print(f"Warning: Failed to cleanup file {file_path}: {e}")


async def cleanup_files(*file_paths: str) -> None:
    """
    Delete multiple files asynchronously.

    Args:
        *file_paths: Paths to files to delete
    """
    tasks = [cleanup_file(fp) for fp in file_paths if fp]
    await asyncio.gather(*tasks, return_exceptions=True)
