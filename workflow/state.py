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
    points: Optional[List[str]]  # 5 single words from transcript; timestamps resolved at render time


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


class VideoProcessingState(TypedDict):
    """
    LangGraph State for video processing workflow.

    This represents the complete state that flows through the workflow,
    being updated by each node.
    """
    # Input
    videoUrl: str
    videoPath: Optional[str]
    sessionId: Optional[str]
    existingClips: Optional[List[ExistingClip]]  # Clips already generated for this video

    # Processing stages
    transcript: Optional[Transcript]
    clips: Optional[List[Clip]]
    captions: Optional[List[CaptionData]]
    renderedVideos: Optional[List[RenderedVideo]]

    # Metadata
    currentStage: Optional[str]
    errors: Optional[List[str]]
    llmRawResponse: Optional[str]  # Debug: raw LLM response
    selectedModel: Optional[str]   # Which model was used for clip identification
