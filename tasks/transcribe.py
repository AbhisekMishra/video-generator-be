import json
import os
import subprocess
import tempfile
import asyncio
from typing import Optional, Dict
from faster_whisper import WhisperModel

from utils.file_utils import cleanup_file, is_youtube_url, download_youtube_video
from utils.logger import get_logger
logger = get_logger(__name__)


MIN_VIDEO_DURATION_SECONDS = 20


async def _validate_video(video_path: str) -> None:
    """
    Run ffprobe to verify the video has an audio stream and meets the minimum duration.
    Raises ValueError with a structured error code on failure.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        video_path,
    ]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False),
    )

    if result.returncode != 0:
        # ffprobe couldn't read the file — let FFmpeg surface a proper error downstream
        return

    try:
        info = json.loads(result.stdout.decode())
    except json.JSONDecodeError:
        return

    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if 0 < duration < MIN_VIDEO_DURATION_SECONDS:
        raise ValueError(f"video_too_short:{duration:.1f}")

    streams = info.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if streams and not has_audio:
        raise ValueError("no_audio_track")


_whisper_model = None

def get_whisper_model():
    """Get or initialize the Whisper model (loaded once, reused across requests)."""
    global _whisper_model
    if _whisper_model is None:
        # int8 quantization: ~70 MB RAM vs ~350 MB for torch+openai-whisper base
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("Loaded faster-whisper base model (int8, cpu)")
    return _whisper_model


async def transcribe_video(
    video_url: Optional[str] = None,
    video_path: Optional[str] = None
) -> Dict:
    """
    Transcribe video using faster-whisper (CTranslate2, no PyTorch).

    Args:
        video_url: URL to download video from
        video_path: Local path to video file

    Returns:
        Dictionary with text, words, and language
    """
    temp_audio_path = None
    downloaded_video_path = None

    try:
        if video_url:
            if is_youtube_url(video_url):
                logger.info(f"📥 Downloading YouTube video: {video_url}")
                downloaded_video_path = await download_youtube_video(video_url)
                input_path = downloaded_video_path
                logger.info(f"✅ YouTube video downloaded to: {input_path}")
            else:
                input_path = video_url
        elif video_path:
            input_path = video_path
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Video file not found: {input_path}")
        else:
            raise ValueError("Either video_url or video_path must be provided")

        # Validate duration and audio presence before spending time on extraction
        if os.path.exists(input_path):
            await _validate_video(input_path)

        # Extract audio from video using FFmpeg
        temp_audio_path = tempfile.mktemp(suffix=".wav")
        extract_audio_cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            temp_audio_path
        ]

        def run_ffmpeg():
            return subprocess.run(
                extract_audio_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )

        loop = asyncio.get_event_loop()
        ffmpeg_result = await loop.run_in_executor(None, run_ffmpeg)

        if ffmpeg_result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed: {ffmpeg_result.stderr.decode()}")

        model = get_whisper_model()

        def run_transcribe():
            # vad_filter skips silence — faster and uses less memory during inference
            segments, info = model.transcribe(
                temp_audio_path,
                word_timestamps=True,
                vad_filter=True,
                language=None,
            )

            all_words = []
            full_text_parts = []

            # segments is a generator — consume it fully inside this thread
            for segment in segments:
                full_text_parts.append(segment.text)
                if segment.words:
                    for word in segment.words:
                        all_words.append({
                            "word": word.word.strip(),
                            "start": float(word.start),
                            "end": float(word.end)
                        })

            return {
                "text": " ".join(full_text_parts).strip(),
                "words": all_words,
                "language": info.language
            }

        result = await loop.run_in_executor(None, run_transcribe)

        logger.info(f"Transcription complete: {len(result['words'])} words  language={result['language']}")
        return result

    finally:
        if temp_audio_path:
            await cleanup_file(temp_audio_path)
        if downloaded_video_path:
            await cleanup_file(downloaded_video_path)
