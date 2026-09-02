"""
Video Processing Pipeline

Plain sequential pipeline: transcribe -> identify clips -> generate captions -> render.
Each stage's output is cached in the session's `pipeline_state` (Supabase) as it
completes, so a retried job resumes from the first incomplete stage instead of
redoing expensive work (Whisper, an LLM call, FFmpeg renders) from scratch.

A stage raises _StageFailed after calling fail_session() with a specific, real error —
the caller (utils/queue_manager.py) doesn't need to inspect anything to know what
happened or where; the first failure stops the pipeline immediately.
"""

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from anthropic import AsyncAnthropic

from utils.logger import get_logger, log_conversion_success
logger = get_logger(__name__)

from tasks.transcribe import transcribe_video
from tasks.render import render_video
from utils.file_utils import is_youtube_url, download_youtube_video, get_cached_video_path
from utils.caption_generator import create_ass_file_for_clip
from workflow.state import Transcript, TranscriptWord, Clip, CaptionData, ExistingClip
from utils.supabase_client import (
    upload_to_supabase,
    download_from_supabase,
    update_session_model,
    complete_session,
    fail_session,
    get_pipeline_state,
    save_pipeline_state,
)

CLIPS_MODEL = "claude-haiku-4-5-20251001"
CLIPS_RETRY_DELAY_SECONDS = 3  # linear backoff between LLM retries — a rate limit or
                                # transient error retried with zero delay just hits the
                                # same wall again immediately

_SENTENCE_ENDERS = (".", "!", "?")

_anthropic_client: Optional[AsyncAnthropic] = None


class _StageFailed(Exception):
    """A stage already called fail_session() with a specific error before raising this —
    callers should stop without recording a second, less specific one."""
    pass


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


def _snap_to_sentence_end(end_time: float, words: List[Dict], max_extend: float = 10.0) -> float:
    """
    Extend end_time forward to the end of the nearest sentence-ending word (., !, or ?)
    so a clip closes its thought instead of cutting off mid-dialogue. Only searches
    forward within max_extend seconds; leaves end_time unchanged if no sentence
    boundary is found in that window.
    """
    for word in words:
        w_end = word.get("end", 0.0)
        if w_end < end_time:
            continue
        if w_end - end_time > max_extend:
            break
        if str(word.get("word", "")).strip().endswith(_SENTENCE_ENDERS):
            return w_end
    return end_time


async def _transcribe_stage(video_url: str, session_id: str) -> Tuple[Transcript, Optional[str]]:
    """
    Download (if YouTube) and transcribe the video with Whisper.

    Returns (transcript, local_video_path). local_video_path is the downloaded YouTube
    file (cached under session_id — see utils/file_utils.py's video cache — so a later
    stage or a retry can reuse it via get_cached_video_path() instead of re-downloading);
    it's None for non-YouTube URLs (FFmpeg streams directly from video_url instead).

    A failure here deliberately does NOT delete an already-downloaded video — it's left
    cached (bounded by a TTL/size cap, not this function) so a retry doesn't need to
    hit YouTube's bot-check a second time for the same session.
    """
    logger.info(f"🎤 Transcribing video...  url={video_url}  session={session_id}")
    local_video_path = None

    try:
        if is_youtube_url(video_url):
            logger.info(f"📥 Downloading YouTube video (once for full pipeline): {video_url}")
            local_video_path = await download_youtube_video(video_url, session_id=session_id)
            logger.info(f"✅ YouTube video downloaded to: {local_video_path}")

        result = await transcribe_video(
            video_url=video_url if not local_video_path else None,
            video_path=local_video_path,
        )

        words = result.get("words", [])
        logger.info(f"✅ Transcription successful! Got {len(words)} words  language={result.get('language')}")

        if not words:
            fail_session(session_id, "no_speech_detected", "transcribe")
            raise _StageFailed("no_speech_detected")

        log_conversion_success(
            logger, "transcribe",
            words=len(words),
            language=result.get("language", "unknown"),
            video_url=video_url,
        )

        transcript = {
            "text": result["text"],
            "words": words,
            "language": result.get("language"),
        }
        return transcript, local_video_path

    except _StageFailed:
        raise

    except ValueError as e:
        # Structured validation errors from ffprobe checks or duration limits
        error_code = str(e)
        if error_code.startswith("video_too_long:"):
            parts = error_code.split(":")
            minutes = parts[1] if len(parts) > 1 else "?"
            limit = parts[2] if len(parts) > 2 else "30"
            error_code = f"Video is too long ({minutes} min). Maximum supported length is {limit} minutes. Please use a shorter clip."
        logger.error(f"❌ Video validation failed: {error_code}  video_url={video_url}")
        fail_session(session_id, error_code, "transcribe")
        raise _StageFailed(error_code) from e

    except Exception as e:
        logger.exception(f"❌ Transcription failed  video_url={video_url}")
        fail_session(session_id, str(e), "transcribe")
        raise _StageFailed(str(e)) from e


async def _identify_clips_stage(
    session_id: str,
    transcript: Transcript,
    existing_clips: List[ExistingClip],
) -> Tuple[List[Clip], str]:
    """Use Claude to pick the best clips from the transcript. Returns (clips, model_name)."""
    logger.info("🔍 Identifying clips with AI...")

    try:
        words = transcript.get("words", [])
        first_word_at = words[0]["start"] if words else 0.0
        last_word_at = words[-1]["end"] if words else 0.0

        # Build transcript text for the prompt.
        # Long transcripts exceed model token limits (8 000 tokens max), so for videos
        # whose transcript exceeds the budget we sample evenly-spaced time segments with
        # [MM:SS] markers so the LLM still sees content from the full video and can
        # return accurate timestamps.
        MAX_TRANSCRIPT_CHARS = 18_000  # leaves ~2 000 tokens headroom for the rest of the prompt
        raw_transcript_text = transcript.get("text", "")
        if len(raw_transcript_text) <= MAX_TRANSCRIPT_CHARS:
            transcript_text_for_prompt = raw_transcript_text
        else:
            num_segments = 6
            total_duration = last_word_at - first_word_at
            segment_duration = total_duration / num_segments
            chars_per_segment = MAX_TRANSCRIPT_CHARS // num_segments
            segments = []
            for i in range(num_segments):
                seg_start = first_word_at + i * segment_duration
                seg_end = seg_start + segment_duration
                seg_words = [w["word"] for w in words if seg_start <= w["start"] < seg_end]
                seg_text = " ".join(seg_words)[:chars_per_segment]
                if seg_text.strip():
                    mm, ss = divmod(int(seg_start), 60)
                    segments.append(f"[{mm:02d}:{ss:02d}] {seg_text}")
            total_minutes = int(last_word_at / 60)
            transcript_text_for_prompt = (
                f"[{total_minutes}-minute video — transcript sampled across all sections]\n\n"
                + "\n\n".join(segments)
            )
            logger.info(
                f"✂️  Transcript truncated for LLM: {len(raw_transcript_text)} → "
                f"{len(transcript_text_for_prompt)} chars across {len(segments)} segments"
            )

        existing_clips_section = ""
        if existing_clips:
            lines = "\n".join(
                f'- [{c["start"]:.1f}s – {c["end"]:.1f}s]: "{c.get("title") or "untitled"}"'
                for c in existing_clips
            )
            existing_clips_section = f"""
ALREADY GENERATED CLIPS (DO NOT overlap these — find different moments):
{lines}

Each new clip must not overlap any existing clip by more than 5 seconds.
"""

        prompt = f"""You are an expert video editor analyzing a transcript to identify the best 3 short-form clips for social media.

Transcript:
{transcript_text_for_prompt}
{existing_clips_section}
CRITICAL RULES:
- Speech in this video begins at {first_word_at:.1f}s. Do NOT start any clip before {first_word_at:.1f}s.
- Every clip MUST start and end where someone is actively speaking. NEVER clip into music, silence, or intro sequences.
- Each clip MUST contain dense, continuous dialogue from start to end — no long pauses or music sections inside the clip.
- ENDING: The clip MUST end at the completion of a full sentence, joke, or thought — never cut off mid-word, mid-sentence, or mid-punchline. Choose the end timestamp right after the speaker (or the person responding to them) finishes that point, even if it means running a few seconds longer than the target duration. A clip that ends abruptly, with the conversation still open, is a failure.
- DURATION: Each clip MUST be between 30 and 60 seconds. Aim for 45 seconds. NEVER exceed 75 seconds.
  - If a good moment is longer than 60 seconds, pick only the best 45-second portion of it — but still end that portion on a completed thought, not an arbitrary cutoff.
  - Double-check: (end - start) must be between 30 and 60 for every clip.

For each clip provide:
- start: timestamp in seconds (must be >= {first_word_at:.1f})
- end: timestamp in seconds (must be <= {last_word_at:.1f}), landing exactly where the thought/sentence completes
- score: engagement score (0-100)
- reason: why this clip is engaging
- hook: the catchy opening line or topic
- title: a short catchy header (3-5 words) shown at the top of the video

Return your response as a JSON array of clips. Example:
[
  {{
    "start": 45.0,
    "end": 90.5,
    "score": 95,
    "reason": "Strong emotional hook with clear value proposition",
    "hook": "Here's the secret that changed everything",
    "title": "The secret nobody tells you"
  }}
]

IMPORTANT: Return ONLY the JSON array, no additional text."""

        client = _get_anthropic_client()
        model_name = CLIPS_MODEL
        MAX_ATTEMPTS = 3
        content = None
        clips = None

        async def _wait_before_retry(attempt: int) -> None:
            if attempt < MAX_ATTEMPTS:
                delay = CLIPS_RETRY_DELAY_SECONDS * attempt
                logger.info(f"⏳ Waiting {delay}s before retrying...")
                await asyncio.sleep(delay)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"📡 Calling LLM ({model_name}, attempt {attempt}/{MAX_ATTEMPTS})...")
            try:
                # anthropic SDK v1.0+ removed temperature/top_p/top_k from Messages
                # methods entirely (TypeError if passed) — current models don't use
                # them anyway, so there's nothing to replace this with.
                response = await asyncio.wait_for(
                    client.messages.create(
                        model=model_name,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=60,
                )
                # Take only text blocks — content can be empty (e.g. a refusal, or a
                # stop_reason other than "end_turn") or contain non-text blocks, and
                # response.content[0].text would raise IndexError/AttributeError on
                # those instead of falling into the "unparseable, retry" path below.
                content = "".join(
                    block.text for block in response.content
                    if getattr(block, "type", None) == "text"
                )
                if not content:
                    logger.warning(
                        f"⚠️ {model_name} returned no text content (attempt {attempt}/{MAX_ATTEMPTS}, "
                        f"stop_reason={getattr(response, 'stop_reason', 'unknown')}) — retrying"
                    )
                    content = None
                    await _wait_before_retry(attempt)
                    continue
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ {model_name} timed out (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                await _wait_before_retry(attempt)
                continue
            except Exception as e:
                logger.warning(f"⚠️ {model_name} error (attempt {attempt}/{MAX_ATTEMPTS}): {type(e).__name__}: {e} — retrying")
                content = None
                await _wait_before_retry(attempt)
                continue

            logger.info(f"🤖 LLM raw response ({model_name}):\n{content}\n{'=' * 80}")

            json_match = re.search(r'\[[\s\S]*\]', content)
            if not json_match:
                logger.warning(f"⚠️ {model_name} returned unparseable response (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                await _wait_before_retry(attempt)
                continue

            try:
                clips = json.loads(json_match.group(0))
                break
            except json.JSONDecodeError:
                logger.warning(f"⚠️ {model_name} returned invalid JSON (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                await _wait_before_retry(attempt)
                continue

        if content is None:
            msg = f"{model_name} failed to produce a valid response after {MAX_ATTEMPTS} attempts"
            fail_session(session_id, msg, "identifyClips")
            raise _StageFailed(msg)

        normalized_clips = []
        for clip in clips:
            raw_start = float(clip["start"])
            raw_end   = float(clip["end"])
            duration  = raw_end - raw_start

            # Reject clips shorter than 20s (not enough content)
            if duration < 20:
                logger.warning(f"  ⚠️  Skipping clip {raw_start:.1f}–{raw_end:.1f}s: too short ({duration:.0f}s)")
                continue

            # Extend to the next sentence-ending word so the clip closes its thought
            # instead of cutting off mid-dialogue — still capped at 75s total.
            snapped_end = _snap_to_sentence_end(raw_end, words, max_extend=10.0)
            if snapped_end > raw_start + 75.0:
                logger.warning(f"  ⚠️  Sentence end for clip at {raw_start:.1f}s was past the 75s cap — capping there instead")
                snapped_end = raw_start + 75.0
            raw_end = snapped_end

            normalized_clips.append({
                "start": raw_start,
                "end":   raw_end,
                "score": int(clip["score"]),
                "reason": str(clip["reason"]),
                "hook": str(clip.get("hook", "")) if clip.get("hook") else None,
                "title": str(clip["title"]) if clip.get("title") else None,
            })

        # Drop clips that overlap existing clips (regeneration) by more than 5s
        if existing_clips:
            filtered = []
            for nc in normalized_clips:
                overlapping = False
                for ec in existing_clips:
                    overlap = min(nc["end"], ec["end"]) - max(nc["start"], ec["start"])
                    if overlap > 5:
                        logger.warning(f"  ⚠️  Dropping clip {nc['start']:.1f}–{nc['end']:.1f}s: overlaps existing clip {ec['start']:.1f}–{ec['end']:.1f}s by {overlap:.0f}s")
                        overlapping = True
                        break
                if not overlapping:
                    filtered.append(nc)
            normalized_clips = filtered

        logger.info(f"✅ Parsed Clips (after duration enforcement):\n{json.dumps(normalized_clips, indent=2)}")

        if not normalized_clips:
            fail_session(session_id, "No clips available", "identifyClips")
            raise _StageFailed("No clips available")

        update_session_model(session_id, model_name)
        log_conversion_success(logger, "identify_clips", clips=len(normalized_clips), model=model_name)

        return normalized_clips, model_name

    except _StageFailed:
        raise
    except Exception as e:
        logger.exception("❌ Clip identification failed")
        fail_session(session_id, str(e), "identifyClips")
        raise _StageFailed(str(e)) from e


async def _generate_captions_stage(session_id: str, transcript_words: List[TranscriptWord], clips: List[Clip]) -> List[CaptionData]:
    """Generate an ASS caption file per clip and upload it to Supabase."""
    logger.info("📝 Generating captions for clips...")

    try:
        captions = []
        for i, clip in enumerate(clips):
            logger.info(f"📝 Generating captions for clip {i + 1}/{len(clips)}...  title='{clip.get('title')}'")

            ass_file_path = create_ass_file_for_clip(
                words=transcript_words,
                clip_start=clip["start"],
                clip_end=clip["end"],
                style="highlight",
                title=clip.get("title"),
            )

            if not ass_file_path:
                logger.warning(f"⚠️ No words found in clip {i} timerange — skipping captions for this clip")
                continue

            storage_path = f"sessions/{session_id}/captions/clip-{i}.ass"
            caption_url = upload_to_supabase(ass_file_path, storage_path)

            if os.path.exists(ass_file_path):
                os.remove(ass_file_path)

            logger.info(f"✅ Captions for clip {i + 1} generated: {storage_path}")
            captions.append({"clipIndex": i, "captionUrl": caption_url, "storagePath": storage_path})

        logger.info(f"🎉 All {len(captions)} caption files generated successfully!")
        log_conversion_success(logger, "generate_captions", clips=len(captions))
        return captions

    except Exception as e:
        logger.exception("❌ Caption generation failed")
        fail_session(session_id, str(e), "generateCaptions")
        raise _StageFailed(str(e)) from e


async def _render_stage(
    session_id: str,
    clips: List[Clip],
    captions: List[CaptionData],
    local_video_path: Optional[str],
    video_url: str,
    pipeline_state: Dict[str, Any],
) -> Tuple[List[str], List[Dict]]:
    """
    Render each clip with FFmpeg and upload it. Already-rendered clips (from a prior
    attempt that crashed partway through) are persisted in pipeline_state["rendered"]
    and skipped — a retry only re-renders what's actually missing.
    """
    logger.info("🎬 Rendering videos...")
    rendered: Dict[str, Dict] = pipeline_state.setdefault("rendered", {})
    render_video_url = None if local_video_path else video_url

    try:
        for i, clip in enumerate(clips):
            if str(i) in rendered:
                logger.info(f"⏭️  Clip {i + 1}/{len(clips)} already rendered — skipping")
                continue

            caption_data = next((c for c in captions if c["clipIndex"] == i), None)
            caption_url = caption_data["captionUrl"] if caption_data else None

            logger.info(f"📹 Rendering clip {i + 1}/{len(clips)}{' with captions' if caption_url else ''}  start={clip['start']:.1f}s  end={clip['end']:.1f}s")

            local_caption_path = None
            if caption_url and "supabase" in caption_url:
                parts = caption_url.split("/storage/v1/object/public/")
                if len(parts) == 2:
                    full_path = parts[1].split("?")[0]
                    path_parts = full_path.split("/", 1)
                    if len(path_parts) == 2:
                        local_caption_path = await download_from_supabase(path_parts[1])
                        logger.info(f"✅ Downloaded caption file to: {local_caption_path}")

            result = await render_video(
                video_url=render_video_url,
                video_path=local_video_path,
                start=clip["start"],
                end=clip["end"],
                subtitle_path=local_caption_path,
            )
            rendered_path = result["output_path"]
            duration = result["duration"]

            storage_path = f"sessions/{session_id}/clips/clip-{i}.mp4"
            public_url = upload_to_supabase(rendered_path, storage_path)

            if local_caption_path and os.path.exists(local_caption_path):
                os.remove(local_caption_path)
            if rendered_path and os.path.exists(rendered_path):
                os.remove(rendered_path)

            logger.info(f"✅ Clip {i + 1} rendered and uploaded: {public_url}")
            log_conversion_success(
                logger, "render_clip",
                clip_index=i,
                duration_s=f"{duration:.1f}",
                clip_start=f"{clip['start']:.1f}",
                clip_end=f"{clip['end']:.1f}",
                url=public_url,
            )

            rendered[str(i)] = {"url": public_url, "duration": float(duration), "clip": clip}
            # Persist after each clip so a crash mid-render doesn't lose already-uploaded ones
            save_pipeline_state(session_id, pipeline_state, "render", 80 + int(20 * (i + 1) / len(clips)))

        logger.info(f"🎉 All {len(clips)} clips rendered successfully!")

        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)
            logger.info(f"🗑️  Cleaned up downloaded video: {local_video_path}")

        rendered_videos = [rendered[str(i)] for i in range(len(clips)) if str(i) in rendered]
        clip_paths = [rv["url"] for rv in rendered_videos]
        clips_metadata = [
            {
                "start": rv["clip"]["start"],
                "end": rv["clip"]["end"],
                "title": rv["clip"].get("title"),
                "score": rv["clip"].get("score", 0),
            }
            for rv in rendered_videos
        ]
        return clip_paths, clips_metadata

    except Exception as e:
        logger.exception("❌ Rendering failed")
        # Deliberately not deleting local_video_path here — leave it cached (bounded
        # by the video cache's TTL/size cap) so a retry doesn't need to re-download.
        fail_session(session_id, str(e), "render")
        raise _StageFailed(str(e)) from e


async def run_pipeline(session_id: str, video_url: str, existing_clips: List[ExistingClip]) -> None:
    """
    Run the full pipeline for a session: transcribe -> identify clips -> generate
    captions -> render. Resumes from the first stage not already cached in
    pipeline_state, so a retried job after a crash or transient failure doesn't
    redo completed work.

    Raises _StageFailed if a stage failed (it has already called fail_session() with a
    specific error) or any other exception for a truly unexpected failure — callers
    should treat both as "the job failed", the difference only matters for logging.
    """
    pipeline_state = get_pipeline_state(session_id)
    local_video_path = None

    if "transcript" in pipeline_state:
        logger.info(f"⏭️  Session {session_id}: transcript already cached — skipping transcribe")
        transcript = pipeline_state["transcript"]
        # transcribe_stage isn't re-run, but its downloaded video may still be
        # cached (see utils/file_utils.py) — reuse it for render if so.
        local_video_path = get_cached_video_path(session_id)
    else:
        transcript, local_video_path = await _transcribe_stage(video_url, session_id)
        pipeline_state["transcript"] = transcript
        save_pipeline_state(session_id, pipeline_state, "identifyClips", 35)

    if "clips" in pipeline_state:
        logger.info(f"⏭️  Session {session_id}: clips already cached — skipping identify_clips")
        clips = pipeline_state["clips"]
    else:
        clips, _model_name = await _identify_clips_stage(session_id, transcript, existing_clips)
        pipeline_state["clips"] = clips
        save_pipeline_state(session_id, pipeline_state, "generateCaptions", 60)

    if "captions" in pipeline_state:
        logger.info(f"⏭️  Session {session_id}: captions already cached — skipping generate_captions")
        captions = pipeline_state["captions"]
    else:
        captions = await _generate_captions_stage(session_id, transcript["words"], clips)
        pipeline_state["captions"] = captions
        save_pipeline_state(session_id, pipeline_state, "render", 80)

    clip_paths, clips_metadata = await _render_stage(
        session_id, clips, captions, local_video_path, video_url, pipeline_state
    )

    complete_session(session_id, clip_paths, clips_metadata)
    log_conversion_success(logger, "render_complete", clips=len(clip_paths))
