"""
Workflow Nodes for Video Processing

Each node represents a stage in the video processing pipeline.
Nodes receive the current state and return updates to merge into the state.
"""

import json
import os
import re
from typing import Dict, Any
from langchain_openai import ChatOpenAI

from workflow.state import VideoProcessingState, Clip
from tasks.transcribe import transcribe_video
from utils.caption_generator import create_ass_file_for_clip
from utils.supabase_client import upload_to_supabase, download_from_supabase
from utils.model_selector import select_model, exhaust_model, ModelQuotaExhaustedError
from utils.supabase_client import update_session_model, update_session_status, update_session_clips_metadata
from tasks.render import render_video


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
    print("🎤 Transcribing video...")
    print(f"  Video URL: {state.get('videoUrl')}")
    print(f"  Video Path: {state.get('videoPath')}")
    print(f"  Session ID: {state.get('sessionId')}")

    try:
        # Call the transcription task (this does the actual work)
        result = await transcribe_video(
            video_url=state.get("videoUrl"),
            video_path=state.get("videoPath")
        )

        print(f"✅ Transcription successful! Got {len(result.get('words', []))} words")

        # Return updates to merge into workflow state
        # LangGraph will automatically merge this dict into the existing state
        return {
            "transcript": {
                "text": result["text"],              # Full transcript text
                "words": result.get("words", []),     # Word-level timestamps
                "language": result.get("language")    # Detected language
            },
            "currentStage": "identifyClips"  # Tell LangGraph to move to next stage
        }
    except Exception as e:
        # Python's exception handling (like try/catch in JavaScript)
        import traceback
        print(f"❌ ERROR: Transcription failed!")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Traceback:\n{traceback.format_exc()}")

        # Return error state (stays on current stage for retry)
        return {
            "errors": [str(e)],
            "currentStage": "transcribe"  # Stay on this stage
        }


async def identify_clips_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 2: Identify best clips using AI (GPT-4o-mini).

    This node uses a Large Language Model (LLM) to analyze the transcript
    and identify the 3 most engaging clips for short-form content.

    Args:
        state: Current workflow state (must contain transcript)

    Returns:
        Dictionary with updates:
        - clips: List of 3 clips with {start, end, score, reason, hook}
        - currentStage: "generateCaptions" (move to next stage)
    """
    print("🔍 Identifying clips with AI...")

    # Get transcript from state (like state.transcript in JavaScript)
    transcript = state.get("transcript")
    if not transcript:
        print("❌ ERROR: No transcript found in state")
        return {
            "errors": ["No transcript available"],
            "currentStage": "identifyClips"
        }

    try:
        # Import here to avoid circular import (graph -> nodes -> graph)
        from workflow.graph import get_pool

        pool = await get_pool()
        session_id = state.get("sessionId")

        # Detect where speech actually starts so we don't pick music-only sections
        words = transcript.get("words", [])
        first_word_at = words[0]["start"] if words else 0.0
        last_word_at = words[-1]["end"] if words else 0.0

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
{transcript['text']}
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
- points: exactly 5 single impactful words from this clip's spoken dialogue. These appear as numbered bullets on screen when each word is spoken.
  Rules for points:
  * Every word MUST actually be spoken in this clip
  * NO filler or stop words: avoid "and", "the", "a", "so", "then", "just", "like", "okay", "yeah", "is", "it", "in", "on", "at", "to", "or", "but", "we", "i", "you", "he", "she", "they", "um", "uh", "got", "get", "gonna", "well", "now", "here", "there", "very", "really"
  * Choose nouns, verbs, or adjectives that are surprising, emotional, or meaningful
  * The 5 words should collectively tell the story of the clip

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

        # Retry loop: if the selected model returns unknown_model, exhaust it and try the next one
        import asyncio
        from openai import BadRequestError

        excluded_models: set[str] = set()

        for attempt in range(len(excluded_models) + 10):  # generous upper bound
            try:
                model_name = await select_model(pool, excluded=excluded_models)
            except ModelQuotaExhaustedError:
                raise

            print(f"🧠 Using model: {model_name} (attempt {attempt + 1})")

            llm = ChatOpenAI(
                model=model_name,
                temperature=0.7,
                base_url="https://models.inference.ai.azure.com",
                api_key=os.getenv("GITHUB_TOKEN")
            )

            print(f"📡 Calling LLM ({model_name})...")
            try:
                response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
                content = str(response.content)
            except asyncio.TimeoutError:
                print(f"⏱️ {model_name} timed out — trying next model")
                excluded_models.add(model_name)
                continue
            except BadRequestError as e:
                err_body = getattr(e, "body", {}) or {}
                if err_body.get("code") == "unknown_model" or "unknown_model" in str(e):
                    print(f"⚠️ Model '{model_name}' rejected as unknown — exhausting and retrying...")
                    await exhaust_model(pool, model_name)
                    excluded_models.add(model_name)
                    continue
                raise
            except Exception as e:
                print(f"⚠️ {model_name} unexpected error: {e} — trying next model")
                excluded_models.add(model_name)
                continue

            # Debug logging
            print("🤖 LLM Raw Response:")
            print(content)
            print("=" * 80)

            # Parse JSON — if unparseable, try next model
            json_match = re.search(r'\[[\s\S]*\]', content)
            if not json_match:
                print(f"⚠️ {model_name} returned unparseable response — trying next model")
                excluded_models.add(model_name)
                continue

            try:
                clips = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                print(f"⚠️ {model_name} returned invalid JSON — trying next model")
                excluded_models.add(model_name)
                continue

            normalized_clips = []
            for clip in clips:
                raw_start = float(clip["start"])
                raw_end   = float(clip["end"])
                duration  = raw_end - raw_start

                # ── Hard duration enforcement ───────────────────────────────
                # Reject clips shorter than 20s (not enough content)
                if duration < 20:
                    print(f"  ⚠️  Skipping clip {raw_start:.1f}–{raw_end:.1f}s: too short ({duration:.0f}s)")
                    continue
                # Trim clips longer than 75s — keep from start, cap the end
                if duration > 75:
                    print(f"  ⚠️  Trimming clip {raw_start:.1f}–{raw_end:.1f}s ({duration:.0f}s) → 60s")
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
                            print(f"  ⚠️  Dropping clip {nc['start']:.1f}–{nc['end']:.1f}s: overlaps existing clip {ec['start']:.1f}–{ec['end']:.1f}s by {overlap:.0f}s")
                            overlapping = True
                            break
                    if not overlapping:
                        filtered.append(nc)
                normalized_clips = filtered

            print("✅ Parsed Clips (after duration enforcement):")
            print(json.dumps(normalized_clips, indent=2))

            if session_id:
                update_session_model(session_id, model_name)

            return {
                "clips": normalized_clips,
                "currentStage": "generateCaptions",
                "llmRawResponse": content,
                "selectedModel": model_name
            }

        raise RuntimeError("All available models failed to produce a valid response")

    except ModelQuotaExhaustedError as e:
        print(f"🚫 All model quotas exhausted: {e}")
        return {
            "errors": [str(e)],
            "currentStage": "identifyClips"
        }
    except Exception as e:
        import traceback
        print(f"ERROR: Clip identification failed!")
        print(f"Error: {str(e)}")
        print(f"Traceback:\n{traceback.format_exc()}")
        return {
            "errors": [str(e)],
            "currentStage": "identifyClips"
        }


async def generate_captions_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 3: Generate ASS captions for each clip.

    Creates word-by-word karaoke-style captions and uploads to Supabase.
    """
    print("📝 Generating captions for clips...")

    transcript = state.get("transcript")
    clips = state.get("clips")
    session_id = state.get("sessionId")

    if not transcript or not transcript.get("words"):
        print("ERROR: No transcript words available")
        return {
            "errors": ["No transcript words available"],
            "currentStage": "generateCaptions"
        }

    if not clips:
        print("ERROR: No clips available")
        return {
            "errors": ["No clips available"],
            "currentStage": "generateCaptions"
        }

    if not session_id:
        print("ERROR: No sessionId provided")
        return {
            "errors": ["No sessionId provided"],
            "currentStage": "generateCaptions"
        }

    try:
        captions = []

        for i, clip in enumerate(clips):
            print(f"📝 Generating captions for clip {i + 1}/{len(clips)}...")

            bullet_words = clip.get("points") or []
            print(f"🔤 Clip {i + 1} title: '{clip.get('title')}'")
            print(f"🔤 Clip {i + 1} bullet words from LLM: {bullet_words}")

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
                raise ValueError(f"No words found in clip {i} timerange")

            # Upload to Supabase
            storage_path = f"sessions/{session_id}/captions/clip-{i}.ass"
            caption_url = upload_to_supabase(ass_file_path, storage_path)

            # Cleanup temp file
            if os.path.exists(ass_file_path):
                os.remove(ass_file_path)

            print(f"✅ Captions for clip {i + 1} generated: {storage_path}")

            captions.append({
                "clipIndex": i,
                "captionUrl": caption_url,
                "storagePath": storage_path
            })

        print(f"🎉 All {len(captions)} caption files generated successfully!")

        return {
            "captions": captions,
            "currentStage": "render"
        }

    except Exception as e:
        import traceback
        print(f"ERROR: Caption generation failed!")
        print(f"Error: {str(e)}")
        print(f"Traceback:\n{traceback.format_exc()}")
        return {
            "errors": [str(e)],
            "currentStage": "generateCaptions"
        }


async def render_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Node 4: Render final videos with burned-in captions.

    Downloads video and captions, renders with FFmpeg, uploads to Supabase.
    """
    print("🎬 Rendering videos...")

    clips = state.get("clips")
    captions = state.get("captions")
    session_id = state.get("sessionId")
    video_url = state.get("videoUrl")
    video_path = state.get("videoPath")

    if not clips:
        print("ERROR: No clips available")
        return {
            "errors": ["No clips available"],
            "currentStage": "render"
        }

    if not session_id:
        print("ERROR: No sessionId provided")
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

            print(f"📹 Rendering clip {i + 1}/{len(clips)}{' with captions' if caption_url else ''}...")

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
                        print(f"✅ Downloaded caption file to: {local_caption_path}")

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

            print(f"✅ Clip {i + 1} rendered and uploaded: {public_url}")

            rendered_videos.append({
                "url": public_url,
                "duration": float(duration),
                "clip": clip
            })

        print(f"🎉 All {len(rendered_videos)} clips rendered successfully!")

        # Persist clip metadata so regeneration can exclude these time ranges
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
            update_session_clips_metadata(session_id, clips_metadata)
            update_session_status(session_id, "completed", completed=True)

        return {
            "renderedVideos": rendered_videos,
            "currentStage": "completed"
        }

    except Exception as e:
        import traceback
        print(f"ERROR: Rendering failed!")
        print(f"Error: {str(e)}")
        print(f"Traceback:\n{traceback.format_exc()}")

        if session_id:
            update_session_status(session_id, "failed")

        return {
            "errors": [str(e)],
            "currentStage": "render"
        }
