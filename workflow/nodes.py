"""
Workflow Nodes for Video Processing

Each node represents a stage in the video processing pipeline.
Nodes receive the current state and return updates to merge into the state.
"""

import asyncio
import json
import os
import re
import traceback
from typing import Dict, Any
from langchain_anthropic import ChatAnthropic

from utils.logger import get_logger, log_conversion_success
logger = get_logger(__name__)

from workflow.state import VideoProcessingState, Clip
from tasks.transcribe import transcribe_video
from utils.file_utils import is_youtube_url, download_youtube_video
from utils.caption_generator import create_ass_file_for_clip
from utils.supabase_client import upload_to_supabase, download_from_supabase
from utils.supabase_client import update_session_model, complete_session, fail_session
from tasks.render import render_video

CLIPS_MODEL = "claude-haiku-4-5-20251001"


async def transcribe_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 1: Transcribe video using Whisper AI.

    This is the first step in the workflow. It takes the video and:
    1. Downloads the video from the URL
    2. Extracts audio using FFmpeg
    3. Transcribes with Whisper to get word-level timestamps

    Args:
        state: Current workflow state (contains videoUrl, sessionId, etc.)

    Returns:
        Dictionary with updates to merge into state:
        - transcript: {text, words, language}
        - currentStage: "identifyClips" (move to next stage)
    """
    logger.info(f"🎤 Transcribing video...  url={state.get('videoUrl')}  path={state.get('videoPath')}  session={state.get('sessionId')}")

    video_url = state.get("videoUrl")
    local_video_path = None

    try:
        # Download YouTube videos once here so render_node can reuse the same file
        if video_url and is_youtube_url(video_url):
            logger.info(f"📥 Downloading YouTube video (once for full pipeline): {video_url}")
            local_video_path = await download_youtube_video(video_url)
            logger.info(f"✅ YouTube video downloaded to: {local_video_path}")

        result = await transcribe_video(
            video_url=video_url if not local_video_path else None,
            video_path=local_video_path or state.get("videoPath")
        )

        words = result.get("words", [])
        logger.info(f"✅ Transcription successful! Got {len(words)} words  language={result.get('language')}")

        # Fail fast if Whisper found no speech — downstream nodes can't work without words
        if not words:
            session_id = state.get("sessionId")
            if local_video_path and os.path.exists(local_video_path):
                os.remove(local_video_path)
            if session_id:
                fail_session(session_id, "no_speech_detected", "transcribe")
            return {
                "errors": ["no_speech_detected"],
                "currentStage": "transcribe"
            }

        log_conversion_success(
            logger, "transcribe",
            words=len(words),
            language=result.get("language", "unknown"),
            video_url=video_url or state.get("videoPath", ""),
        )

        updates: Dict[str, Any] = {
            "transcript": {
                "text": result["text"],
                "words": words,
                "language": result.get("language")
            },
            "localVideoPath": local_video_path,  # None for non-YouTube; render_node reuses this
            "currentStage": "identifyClips"
        }

        return updates

    except ValueError as e:
        # Structured validation errors from ffprobe checks or duration limits
        error_code = str(e)
        # Translate video_too_long:<minutes>:<limit> into a human-readable message
        if error_code.startswith("video_too_long:"):
            parts = error_code.split(":")
            minutes = parts[1] if len(parts) > 1 else "?"
            limit = parts[2] if len(parts) > 2 else "30"
            error_code = f"Video is too long ({minutes} min). Maximum supported length is {limit} minutes. Please use a shorter clip."
        logger.error(f"❌ Video validation failed: {error_code}  video_url={video_url}")
        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)
        session_id = state.get("sessionId")
        if session_id:
            fail_session(session_id, error_code, "transcribe")
        return {
            "errors": [error_code],
            "currentStage": "transcribe"
        }

    except Exception as e:
        logger.exception(f"❌ Transcription failed  video_url={video_url}")

        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)

        session_id = state.get("sessionId")
        if session_id:
            fail_session(session_id, str(e), "transcribe")

        return {
            "errors": [str(e)],
            "currentStage": "transcribe"
        }


async def identify_clips_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 2: Identify best clips using AI (Claude Haiku).

    This node uses a Large Language Model (LLM) to analyze the transcript
    and identify the 3 most engaging clips for short-form content.

    Args:
        state: Current workflow state (must contain transcript)

    Returns:
        Dictionary with updates:
        - clips: List of 3 clips with {start, end, score, reason, hook}
        - currentStage: "generateCaptions" (move to next stage)
    """
    # The graph is linear with no conditional edges, so a failure in an earlier node
    # still reaches this one. Pass through untouched rather than overwriting the real
    # error/stage a prior node already recorded with a misleading downstream one.
    if state.get("errors"):
        return {}

    logger.info("🔍 Identifying clips with AI...")

    # Get transcript from state (like state.transcript in JavaScript)
    transcript = state.get("transcript")
    if not transcript:
        logger.error("❌ No transcript found in state")
        return {
            "errors": ["No transcript available"],
            "currentStage": "identifyClips"
        }

    try:
        session_id = state.get("sessionId")

        # Detect where speech actually starts so we don't pick music-only sections
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

        # Build existing clips exclusion section for the prompt
        existing_clips = state.get("existingClips") or []
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

        # Construct prompt (instructions for the AI)
        prompt = f"""You are an expert video editor analyzing a transcript to identify the best 3 short-form clips for social media.

Transcript:
{transcript_text_for_prompt}
{existing_clips_section}
CRITICAL RULES:
- Speech in this video begins at {first_word_at:.1f}s. Do NOT start any clip before {first_word_at:.1f}s.
- Every clip MUST start and end where someone is actively speaking. NEVER clip into music, silence, or intro sequences.
- Each clip MUST contain dense, continuous dialogue from start to end — no long pauses or music sections inside the clip.
- DURATION: Each clip MUST be between 30 and 60 seconds. Aim for 45 seconds. NEVER exceed 75 seconds.
  - If a good moment is longer than 60 seconds, pick only the best 45-second portion of it.
  - Double-check: (end - start) must be between 30 and 60 for every clip.

For each clip provide:
- start: timestamp in seconds (must be >= {first_word_at:.1f})
- end: timestamp in seconds (must be <= {last_word_at:.1f})
- score: engagement score (0-100)
- reason: why this clip is engaging
- hook: the catchy opening line or topic
- title: a short catchy header (3-5 words) shown at the top of the video
- points: exactly 5 single HIGH-IMPACT words from this clip's spoken dialogue. These appear as numbered bullets on screen — they must make a viewer stop scrolling.
  Rules for points:
  * Every word MUST actually be spoken in this clip
  * ABSOLUTE BAN — never use these: "and", "the", "a", "an", "so", "then", "just", "like", "okay", "yeah", "yes", "no", "is", "it", "in", "on", "at", "to", "or", "but", "we", "i", "you", "he", "she", "they", "um", "uh", "got", "get", "gonna", "well", "now", "here", "there", "very", "really", "actually", "basically", "literally", "things", "something", "anything", "everything", "people", "person", "time", "way", "make", "made", "said", "says", "want", "wanted", "need", "know", "think", "thought", "feel", "felt", "went", "come", "came", "look", "looked", "right", "good", "great", "bad", "big", "new", "old", "first", "last", "one", "two", "three", "also", "even", "still", "back", "over", "about", "because", "when", "what", "that", "this", "these", "those"
  * PREFER words that are: shocking, counterintuitive, emotionally charged, highly specific, or reveal something unexpected
  * STRONG word types: concrete nouns (a specific person/place/thing), vivid action verbs, stark adjectives with strong connotation
  * ASK YOURSELF: "If someone saw only this word on screen, would it make them curious or emotional?" — only use it if the answer is YES
  * The 5 words together should feel like a teaser that hints at the clip's core revelation or emotion
  * BAD example: ["make", "things", "really", "good", "time"] — generic, forgettable
  * GOOD example: ["betrayed", "collapsed", "millions", "exposed", "survived"] — specific, visceral, curiosity-inducing

Return your response as a JSON array of clips. Example:
[
  {{
    "start": 45.0,
    "end": 90.5,
    "score": 95,
    "reason": "Strong emotional hook with clear value proposition",
    "hook": "Here's the secret that changed everything",
    "title": "The secret nobody tells you",
    "points": ["secret", "broke", "discovered", "finally", "works"]
  }}
]

IMPORTANT: Return ONLY the JSON array, no additional text."""

        model_name = CLIPS_MODEL
        llm = ChatAnthropic(
            model=model_name,
            temperature=0.7,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

        MAX_ATTEMPTS = 3
        content = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"📡 Calling LLM ({model_name}, attempt {attempt}/{MAX_ATTEMPTS})...")
            try:
                response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
                content = str(response.content)
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ {model_name} timed out (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                continue
            except Exception as e:
                logger.warning(f"⚠️ {model_name} error (attempt {attempt}/{MAX_ATTEMPTS}): {e} — retrying")
                content = None
                continue

            logger.info(f"🤖 LLM raw response ({model_name}):\n{content}\n{'=' * 80}")

            # Parse JSON — if unparseable, retry
            json_match = re.search(r'\[[\s\S]*\]', content)
            if not json_match:
                logger.warning(f"⚠️ {model_name} returned unparseable response (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                continue

            try:
                clips = json.loads(json_match.group(0))
                break
            except json.JSONDecodeError:
                logger.warning(f"⚠️ {model_name} returned invalid JSON (attempt {attempt}/{MAX_ATTEMPTS}) — retrying")
                content = None
                continue

        if content is None:
            raise RuntimeError(f"{model_name} failed to produce a valid response after {MAX_ATTEMPTS} attempts")

        normalized_clips = []
        for clip in clips:
            raw_start = float(clip["start"])
            raw_end   = float(clip["end"])
            duration  = raw_end - raw_start

            # ── Hard duration enforcement ───────────────────────────────
            # Reject clips shorter than 20s (not enough content)
            if duration < 20:
                logger.warning(f"  ⚠️  Skipping clip {raw_start:.1f}–{raw_end:.1f}s: too short ({duration:.0f}s)")
                continue
            # Trim clips longer than 75s — keep from start, cap the end
            if duration > 75:
                logger.warning(f"  ⚠️  Trimming clip {raw_start:.1f}–{raw_end:.1f}s ({duration:.0f}s) → 60s")
                raw_end = raw_start + 60.0

            raw_points = clip.get("points") or []
            normalized_points = [str(p) for p in raw_points if str(p).strip()]
            normalized_clips.append({
                "start": raw_start,
                "end":   raw_end,
                "score": int(clip["score"]),
                "reason": str(clip["reason"]),
                "hook": str(clip.get("hook", "")) if clip.get("hook") else None,
                "title": str(clip["title"]) if clip.get("title") else None,
                "points": normalized_points
            })

        # Post-validation: drop clips that overlap existing clips by more than 5s
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

        if session_id:
            update_session_model(session_id, model_name)

        log_conversion_success(
            logger, "identify_clips",
            clips=len(normalized_clips),
            model=model_name,
        )

        return {
            "clips": normalized_clips,
            "currentStage": "generateCaptions",
            "llmRawResponse": content,
            "selectedModel": model_name
        }

    except Exception as e:
        logger.exception("❌ Clip identification failed")
        return {
            "errors": [str(e)],
            "currentStage": "identifyClips"
        }


async def generate_captions_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 3: Generate ASS captions for each clip.

    Creates word-by-word karaoke-style captions and uploads to Supabase.
    """
    if state.get("errors"):
        return {}

    logger.info("📝 Generating captions for clips...")

    transcript = state.get("transcript")
    clips = state.get("clips")
    session_id = state.get("sessionId")

    if not transcript or not transcript.get("words"):
        logger.error("❌ No transcript words available")
        return {
            "errors": ["No transcript words available"],
            "currentStage": "generateCaptions"
        }

    if not clips:
        logger.error("❌ No clips available for caption generation")
        return {
            "errors": ["No clips available"],
            "currentStage": "generateCaptions"
        }

    if not session_id:
        logger.error("❌ No sessionId provided for caption generation")
        return {
            "errors": ["No sessionId provided"],
            "currentStage": "generateCaptions"
        }

    try:
        captions = []

        for i, clip in enumerate(clips):
            logger.info(f"📝 Generating captions for clip {i + 1}/{len(clips)}...")

            bullet_words = clip.get("points") or []
            logger.info(f"🔤 Clip {i + 1} title='{clip.get('title')}'  bullet_words={bullet_words}")

            # Generate ASS file (includes header, bullet points, and word captions)
            ass_file_path = create_ass_file_for_clip(
                words=transcript["words"],
                clip_start=clip["start"],
                clip_end=clip["end"],
                style="highlight",
                title=clip.get("title"),
                bullet_words=bullet_words,
            )

            if not ass_file_path:
                logger.warning(f"⚠️ No words found in clip {i} timerange — skipping captions for this clip")
                continue

            # Upload to Supabase
            storage_path = f"sessions/{session_id}/captions/clip-{i}.ass"
            caption_url = upload_to_supabase(ass_file_path, storage_path)

            # Cleanup temp file
            if os.path.exists(ass_file_path):
                os.remove(ass_file_path)

            logger.info(f"✅ Captions for clip {i + 1} generated: {storage_path}")

            captions.append({
                "clipIndex": i,
                "captionUrl": caption_url,
                "storagePath": storage_path
            })

        logger.info(f"🎉 All {len(captions)} caption files generated successfully!")
        log_conversion_success(logger, "generate_captions", clips=len(captions))

        return {
            "captions": captions,
            "currentStage": "render"
        }

    except Exception as e:
        logger.exception("❌ Caption generation failed")
        return {
            "errors": [str(e)],
            "currentStage": "generateCaptions"
        }


async def render_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 4: Render final videos with burned-in captions.

    Downloads video and captions, renders with FFmpeg, uploads to Supabase.
    """
    if state.get("errors"):
        return {}

    logger.info("🎬 Rendering videos...")

    clips = state.get("clips")
    captions = state.get("captions")
    session_id = state.get("sessionId")
    local_video_path = state.get("localVideoPath")  # pre-downloaded YouTube file from transcribe_node
    # If transcribe_node already downloaded the video, use that local file; avoids re-downloading per clip
    video_url = None if local_video_path else state.get("videoUrl")
    video_path = local_video_path or state.get("videoPath")

    if not clips:
        logger.error("❌ No clips available for rendering")
        return {
            "errors": ["No clips available"],
            "currentStage": "render"
        }

    if not session_id:
        logger.error("❌ No sessionId provided for rendering")
        return {
            "errors": ["No sessionId provided"],
            "currentStage": "render"
        }

    try:
        rendered_videos = []

        for i, clip in enumerate(clips):
            # Find caption for this clip
            caption_data = next((c for c in (captions or []) if c["clipIndex"] == i), None)
            caption_url = caption_data["captionUrl"] if caption_data else None

            logger.info(f"📹 Rendering clip {i + 1}/{len(clips)}{' with captions' if caption_url else ''}  start={clip['start']:.1f}s  end={clip['end']:.1f}s")

            # Download caption file if provided
            local_caption_path = None
            if caption_url and "supabase" in caption_url:
                # Extract storage path from Supabase URL
                parts = caption_url.split("/storage/v1/object/public/")
                if len(parts) == 2:
                    full_path = parts[1].split("?")[0]
                    path_parts = full_path.split("/", 1)
                    if len(path_parts) == 2:
                        caption_storage_path = path_parts[1]
                        local_caption_path = await download_from_supabase(caption_storage_path)
                        logger.info(f"✅ Downloaded caption file to: {local_caption_path}")

            # Render video
            result = await render_video(
                video_url=video_url,
                video_path=video_path,
                start=clip["start"],
                end=clip["end"],
                subtitle_path=local_caption_path
            )

            rendered_path = result["output_path"]
            duration = result["duration"]

            # Upload to Supabase
            storage_path = f"sessions/{session_id}/clips/clip-{i}.mp4"
            public_url = upload_to_supabase(rendered_path, storage_path)

            # Cleanup local files
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

            rendered_videos.append({
                "url": public_url,
                "duration": float(duration),
                "clip": clip
            })

        logger.info(f"🎉 All {len(rendered_videos)} clips rendered successfully!")

        # Clean up the pre-downloaded YouTube video now that all clips are rendered
        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)
            logger.info(f"🗑️  Cleaned up downloaded video: {local_video_path}")

        # Persist clip URLs and metadata
        clip_paths = [rv["url"] for rv in rendered_videos]
        clips_metadata = [
            {
                "start": rv["clip"]["start"],
                "end": rv["clip"]["end"],
                "title": rv["clip"].get("title"),
                "score": rv["clip"].get("score", 0),
            }
            for rv in rendered_videos
            if rv.get("clip")
        ]

        if session_id:
            complete_session(session_id, clip_paths, clips_metadata)

        log_conversion_success(logger, "render_complete", clips=len(rendered_videos))

        return {
            "renderedVideos": rendered_videos,
            "currentStage": "completed"
        }

    except Exception as e:
        logger.exception("❌ Rendering failed")

        if local_video_path and os.path.exists(local_video_path):
            os.remove(local_video_path)

        if session_id:
            fail_session(session_id, str(e), "render")

        return {
            "errors": [str(e)],
            "currentStage": "render"
        }
