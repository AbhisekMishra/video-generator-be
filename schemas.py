"""
Pydantic schemas for all data structures in the video generator.

These serve as the typed interfaces used across API request/response models
and the LangGraph workflow state.
"""
from pydantic import BaseModel
from typing import Optional, List


class TranscriptWordSchema(BaseModel):
    word: str
    start: float
    end: float


class TranscriptSchema(BaseModel):
    text: str
    words: List[TranscriptWordSchema]
    language: Optional[str] = None


class ClipSchema(BaseModel):
    start: float
    end: float
    score: int
    reason: str
    hook: Optional[str] = None
    title: Optional[str] = None
    points: Optional[List[str]] = None


class CaptionDataSchema(BaseModel):
    clipIndex: int
    captionUrl: str
    storagePath: str


class RenderedVideoSchema(BaseModel):
    url: str
    duration: float
    clip: Optional[ClipSchema] = None
