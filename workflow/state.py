from typing import TypedDict, Optional, List


class TranscriptWord(TypedDict):
    """Word-level timestamp from transcription."""
    word: str
    start: float
    end: float


class Transcript(TypedDict):
    """Transcription result from Whisper."""
    text: str
    words: List[TranscriptWord]
    language: Optional[str]


class Clip(TypedDict):
    """Identified clip with timestamps and metadata."""
    start: float
    end: float
    score: int
    reason: str
    hook: Optional[str]
    title: Optional[str]       # Header text shown at top of video


class CaptionData(TypedDict):
    """Caption data for a clip."""
    clipIndex: int
    captionUrl: str
    storagePath: str


class RenderedVideo(TypedDict):
    """Rendered video output."""
    url: str
    duration: float
    clip: Optional[Clip]


class ExistingClip(TypedDict):
    """Metadata for an already-generated clip, used to prevent duplicates on regeneration."""
    start: float
    end: float
    title: Optional[str]
    score: int
