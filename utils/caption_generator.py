"""
ASS subtitle generator for video captions with animations.

Generates Advanced SubStation Alpha (ASS) subtitle files from Whisper transcripts
with word-level timing and styling animations.
"""

from typing import List, Dict, Optional
import os
import tempfile

from utils.logger import get_logger
logger = get_logger(__name__)


def format_ass_time(seconds: float) -> str:
    """
    Convert seconds to ASS timestamp format (H:MM:SS.CS)

    Args:
        seconds: Time in seconds

    Returns:
        Formatted timestamp like "0:00:12.50"
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int((seconds % 1) * 100)

    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def filter_words_for_clip(words: List[Dict], clip_start: float, clip_end: float) -> List[Dict]:
    """
    Filter transcript words that fall within clip time range and adjust timestamps.

    Args:
        words: List of word dicts with 'word', 'start', 'end' keys
        clip_start: Clip start time in seconds
        clip_end: Clip end time in seconds

    Returns:
        List of words with timestamps adjusted relative to clip start (0.0)
    """
    logger.info(f"🔍 filter_words_for_clip  clip_start={clip_start}  clip_end={clip_end}  total_words={len(words)}")

    filtered_words = []

    for word in words:
        word_start = word['start']
        word_end = word['end']

        # Check if word overlaps with clip timerange
        if word_end >= clip_start and word_start <= clip_end:
            # Adjust timestamps relative to clip start
            adjusted_word = {
                'word': word['word'],
                'start': max(0, word_start - clip_start),
                'end': min(clip_end - clip_start, word_end - clip_start)
            }
            filtered_words.append(adjusted_word)

    if filtered_words:
        logger.info(f"🔍 Filtered words: {len(filtered_words)}  first='{filtered_words[0]['word']}' at {filtered_words[0]['start']:.2f}s  last='{filtered_words[-1]['word']}' at {filtered_words[-1]['end']:.2f}s")
    else:
        logger.warning("🔍 Filtered words: 0 — no words found in clip timerange")

    return filtered_words


def generate_ass_subtitle(
    words: List[Dict],
    style: str = "highlight",
    fontsize: int = 52,
    primary_color: str = "FFFFFF",  # White
    highlight_color: str = "00FFFF",  # Cyan (BGR format)
    outline_color: str = "000000",  # Black
    video_width: int = 1080,  # Default for 9:16 format
    video_height: int = 1920,  # Default for 9:16 format
    title: str = None,
    clip_duration: float = None,
) -> str:
    """
    Generate ASS subtitle content from word-level timestamps.

    Args:
        words: List of word dicts with 'word', 'start', 'end' keys (already adjusted to clip time)
        style: Caption style - 'highlight' (word-by-word), 'phrase' (multi-word), or 'static'
        fontsize: Font size for captions
        primary_color: Primary text color (BGR hex without #)
        highlight_color: Highlight color for current word (BGR hex without #)
        outline_color: Outline/border color (BGR hex without #)
        title: Optional header text displayed at top throughout the clip
        clip_duration: Total clip duration in seconds (used to set end time for overlays)

    Returns:
        Complete ASS subtitle file content as string
    """

    # Calculate margin from bottom (10% of video height)
    margin_v = int(video_height * 0.1)

    # Sizes for overlay elements (scale with video height)
    header_fontsize = max(36, int(video_height / 34))
    header_margin_v = max(20, int(video_height * 0.03))

    # ASS file header with two styles: Default (captions), Header
    ass_content = f"""[Script Info]
Title: Video Captions
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{fontsize},&H00{primary_color},&H00{highlight_color},&H00{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,10,10,{margin_v},1
Style: Header,Arial Black,{header_fontsize},&H0000FFFF,&H0000FFFF,&H00{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,4,2,8,10,10,{header_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Determine the end time for the persistent header overlay
    if clip_duration is not None:
        overlay_end = clip_duration
    elif words:
        overlay_end = words[-1]['end'] + 1.0
    else:
        overlay_end = 60.0
    overlay_end_str = format_ass_time(overlay_end)

    # --- Header (spans entire clip) ---
    if title:
        ass_content += f"Dialogue: 0,{format_ass_time(0)},{overlay_end_str},Header,,0,0,0,,{title}\n"

    if style == "highlight":
        # Word-by-word highlighting with karaoke effect
        # Group words into phrases (2-4 words at a time for readability)
        phrase_length = 3

        for i in range(0, len(words), phrase_length):
            phrase_words = words[i:i + phrase_length]
            phrase_start = phrase_words[0]['start']
            phrase_end = phrase_words[-1]['end']

            # Build the dialogue line with karaoke effect
            # Each word gets highlighted when its time comes
            dialogue_text = ""

            for j, word in enumerate(phrase_words):
                word_duration = int((word['end'] - word['start']) * 100)  # in centiseconds

                # Karaoke effect: \k<duration> highlights word for duration
                dialogue_text += f"{{\\k{word_duration}}}{word['word']} "

            # Add dialogue line
            ass_content += f"Dialogue: 0,{format_ass_time(phrase_start)},{format_ass_time(phrase_end)},Default,,0,0,0,,{dialogue_text.strip()}\n"

    elif style == "phrase":
        # Multi-word phrases with slide-up animation
        phrase_length = 4

        # Calculate center position and slide animation based on video dimensions
        center_x = video_width // 2
        start_y = int(video_height * 0.75)  # Start at 75% from top
        end_y = int(video_height * 0.70)    # End at 70% from top

        for i in range(0, len(words), phrase_length):
            phrase_words = words[i:i + phrase_length]
            phrase_start = phrase_words[0]['start']
            phrase_end = phrase_words[-1]['end']

            # Combine words into phrase
            phrase_text = " ".join([w['word'] for w in phrase_words])

            # Add slide-up animation with fade
            # \move(x1,y1,x2,y2,t1,t2) + \fad(fadein,fadeout)
            dialogue_text = f"{{\\fad(200,200)\\move({center_x},{start_y},{center_x},{end_y},0,200)}}{phrase_text}"

            ass_content += f"Dialogue: 0,{format_ass_time(phrase_start)},{format_ass_time(phrase_end)},Default,,0,0,0,,{dialogue_text}\n"

    else:  # static
        # Simple static captions, one word at a time
        for word in words:
            word_text = word['word']
            word_start = word['start']
            word_end = word['end']

            # Simple fade in/out
            dialogue_text = f"{{\\fad(100,100)}}{word_text}"

            ass_content += f"Dialogue: 0,{format_ass_time(word_start)},{format_ass_time(word_end)},Default,,0,0,0,,{dialogue_text}\n"

    return ass_content


def create_ass_file_for_clip(
    words: List[Dict],
    clip_start: float,
    clip_end: float,
    style: str = "highlight",
    video_width: int = 1920,  # Source video width  (standard 16:9)
    video_height: int = 1080,  # Source video height (standard 16:9)
    title: str = None,
) -> str:
    """
    Create temporary ASS subtitle file for a video clip.

    Args:
        words: Full transcript words from Whisper
        clip_start: Clip start time in original video
        clip_end: Clip end time in original video
        style: Caption style to use
        title: Optional header text to display at top of video

    Returns:
        Path to temporary ASS file
    """
    # Filter and adjust words for this clip
    clip_words = filter_words_for_clip(words, clip_start, clip_end)

    if not clip_words:
        return None

    clip_duration = clip_end - clip_start

    # Generate ASS content with video dimensions
    ass_content = generate_ass_subtitle(
        clip_words,
        style=style,
        video_width=video_width,
        video_height=video_height,
        title=title,
        clip_duration=clip_duration,
    )

    # Create temporary file
    temp_fd, temp_path = tempfile.mkstemp(suffix='.ass', text=True)

    with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    # Debug: show styles + header overlay line + first caption line
    lines = ass_content.splitlines()
    overlay_lines = [l for l in lines if "Header" in l]
    logger.info(f"📝 ASS file saved to: {temp_path}  overlay_lines={len(overlay_lines)}")

    return temp_path
