import os
import tempfile
import asyncio
from typing import Optional, Dict
from faster_whisper import WhisperModel

from utils.file_utils import cleanup_file


_whisper_model = None

def get_whisper_model():
    """Get or initialize the Whisper model (loaded once, reused across requests)."""
    global _whisper_model
    if _whisper_model is None:
        # int8 quantization: ~70 MB RAM vs ~350 MB for torch+openai-whisper base
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        print("Loaded faster-whisper base model (int8, cpu)")
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

    try:
        if video_url:
            input_path = video_url
        elif video_path:
            input_path = video_path
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Video file not found: {input_path}")
        else:
            raise ValueError("Either video_url or video_path must be provided")

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

        import subprocess

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

        print(f"Transcription complete: {len(result['words'])} words, language={result['language']}")
        return result

    finally:
        if temp_audio_path:
            await cleanup_file(temp_audio_path)
