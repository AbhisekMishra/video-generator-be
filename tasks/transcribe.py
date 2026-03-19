import os
import tempfile
import asyncio
from typing import Optional, List, Dict
import whisper
import torch

from utils.file_utils import download_video, cleanup_file


# Initialize Whisper model (lazy loading)
_whisper_model = None

def get_whisper_model():
    """Get or initialize the Whisper model"""
    global _whisper_model
    if _whisper_model is None:
        # Use 'base' model for faster transcription
        # Options: tiny, base, small, medium, large, large-v2, large-v3
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _whisper_model = whisper.load_model("base", device=device)
        print(f"Loaded Whisper model on {device}")
    return _whisper_model


async def transcribe_video(
    video_url: Optional[str] = None,
    video_path: Optional[str] = None
) -> Dict:
    """
    Transcribe video using faster-whisper.

    Args:
        video_url: URL to download video from
        video_path: Local path to video file

    Returns:
        Dictionary with text, words, and language
    """
    temp_video_path = None
    temp_audio_path = None

    try:
        # Download video if URL provided
        if video_url:
            temp_video_path = await download_video(video_url)
            input_path = temp_video_path
        elif video_path:
            input_path = video_path
        else:
            raise ValueError("Either video_url or video_path must be provided")

        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Video file not found: {input_path}")

        # Extract audio from video using FFmpeg
        temp_audio_path = tempfile.mktemp(suffix=".wav")
        extract_audio_cmd = [
            "ffmpeg",
            "-i", input_path,
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # PCM 16-bit
            "-ar", "16000",  # 16kHz sample rate
            "-ac", "1",  # Mono
            "-y",  # Overwrite output file
            temp_audio_path
        ]

        # Run FFmpeg to extract audio (use subprocess.run in executor for Windows compatibility)
        import subprocess

        def run_ffmpeg():
            result = subprocess.run(
                extract_audio_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            return result

        loop = asyncio.get_event_loop()
        ffmpeg_result = await loop.run_in_executor(None, run_ffmpeg)

        if ffmpeg_result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed: {ffmpeg_result.stderr.decode()}")

        # Transcribe using openai-whisper
        model = get_whisper_model()

        # Run transcription in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result_data = await loop.run_in_executor(
            None,
            lambda: model.transcribe(
                temp_audio_path,
                word_timestamps=True,
                verbose=False
            )
        )

        # Extract segments and words
        all_words = []

        # OpenAI Whisper returns segments with word-level timestamps
        if "segments" in result_data:
            for segment in result_data["segments"]:
                if "words" in segment:
                    for word_data in segment["words"]:
                        # Convert numpy floats to Python floats for msgpack serialization
                        all_words.append({
                            "word": word_data.get("word", "").strip(),
                            "start": float(word_data.get("start", 0.0)),
                            "end": float(word_data.get("end", 0.0))
                        })

        result = {
            "text": result_data["text"].strip(),
            "words": all_words,
            "language": result_data.get("language")
        }

        return result

    finally:
        # Cleanup temporary files
        if temp_video_path:
            await cleanup_file(temp_video_path)
        if temp_audio_path:
            await cleanup_file(temp_audio_path)
