"""
Video Processing Pipeline Package

Contains the domain type definitions (workflow/state.py) and the sequential
pipeline (workflow/pipeline.py): transcribe -> identify clips -> generate
captions -> render.
"""

from workflow.state import (
    TranscriptWord,
    Transcript,
    Clip,
    CaptionData,
    RenderedVideo,
    ExistingClip,
)

__all__ = [
    "TranscriptWord",
    "Transcript",
    "Clip",
    "CaptionData",
    "RenderedVideo",
    "ExistingClip",
]
