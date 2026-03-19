"""
ASS subtitle generator for video captions with animations.

Generates Advanced SubStation Alpha (ASS) subtitle files from Whisper transcripts
with word-level timing and styling animations.
"""

from typing import List, Dict, Optional
import os
import re
import tempfile


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
    print(f"🔍 filter_words_for_clip called with clip_start={clip_start}, clip_end={clip_end}")
    print(f"🔍 Total words in transcript: {len(words)}")

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

    print(f"🔍 Filtered words: {len(filtered_words)}")
    if len(filtered_words) > 0:
        print(f"🔍 First word: '{filtered_words[0]['word']}' at {filtered_words[0]['start']:.2f}s (original: {words[0]['start']:.2f}s)")
        print(f"🔍 Last word: '{filtered_words[-1]['word']}' at {filtered_words[-1]['end']:.2f}s")

    return filtered_words


STOP_WORDS = {
    # Articles, conjunctions, prepositions
    "a", "an", "the", "and", "but", "or", "so", "yet", "for", "nor",
    "in", "on", "at", "to", "of", "by", "up", "out", "as", "if",
    "into", "from", "with", "about", "than", "then", "when", "where",
    # Pronouns
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their", "this", "that",
    # Common verbs (weak)
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can",
    "get", "got", "go", "going", "come", "came", "say", "said",
    # Filler / spoken-word artifacts
    "um", "uh", "oh", "ah", "yeah", "yep", "yup", "nope",
    "okay", "ok", "well", "like", "just", "really", "very",
    "gonna", "wanna", "gotta", "kinda", "sorta",
    "now", "here", "there", "also", "too", "not", "no", "yes",
    "know", "think", "right", "mean",
}


def resolve_bullet_timestamps(
    bullet_words: List[str],
    clip_words: List[Dict],
    clip_duration: float = None,
) -> List[Dict]:
    """
    Return exactly 5 evenly-spaced bullet dicts from the clip transcript.

    Algorithm (bucket-based):
      - Usable window = clip start → clip_end minus a trailing buffer (no bullets near the end)
      - Divide usable window into 5 equal time buckets
      - For each bucket: prefer an LLM-chosen word found in that bucket; fall back to
        the longest meaningful (non-stop-word) transcript word in the bucket
      - This guarantees 5 bullets, evenly spread, with no fillers, never at the end

    Args:
        bullet_words: Words suggested by the LLM
        clip_words: Transcript words filtered to this clip (timestamps from 0.0)
        clip_duration: Total clip duration in seconds

    Returns:
        List of up to 5 {text, appear_at} dicts sorted by appearance time
    """
    def normalize(w: str) -> str:
        return re.sub(r'[^\w]', '', w).lower()

    def is_meaningful(norm: str) -> bool:
        return bool(norm) and len(norm) >= 2 and norm not in STOP_WORDS

    # Trailing buffer: exclude last 5s or 12% of clip, whichever is larger
    if clip_duration and clip_duration > 10:
        buffer = max(5.0, clip_duration * 0.12)
        usable_end = clip_duration - buffer
    else:
        usable_end = clip_words[-1]['start'] if clip_words else 60.0

    # Filter to meaningful words within usable window
    usable_words = [
        w for w in clip_words
        if w['start'] <= usable_end and is_meaningful(normalize(w['word']))
    ]

    if not usable_words:
        print("⚠️  No usable words for bullet points after filtering")
        return []

    # Normalised LLM words → original text, keyed for fast lookup
    lm_lookup = {}
    for word in (bullet_words or []):
        norm = normalize(word)
        if is_meaningful(norm):
            lm_lookup[norm] = word

    t_start = usable_words[0]['start']
    t_end = usable_words[-1]['start']
    # Avoid dividing by zero for very short clips
    span = max(t_end - t_start, 1.0)
    bucket_size = span / 5

    resolved = []
    for bucket_idx in range(5):
        b_start = t_start + bucket_idx * bucket_size
        b_end = b_start + bucket_size

        bucket_words = [w for w in usable_words if b_start <= w['start'] < b_end]
        # If bucket is empty, grab the nearest word after b_start
        if not bucket_words:
            later = [w for w in usable_words if w['start'] >= b_start]
            bucket_words = [later[0]] if later else []
        if not bucket_words:
            continue

        matched_text = None
        matched_word = None

        # Prefer LLM word found in this bucket
        for w in bucket_words:
            wn = normalize(w['word'])
            if wn in lm_lookup:
                matched_text = lm_lookup[wn]
                matched_word = w
                break
            # Substring match
            for lm_norm, lm_text in lm_lookup.items():
                if wn in lm_norm or lm_norm in wn:
                    matched_text = lm_text
                    matched_word = w
                    break
            if matched_word:
                break

        # Fallback: longest meaningful word in bucket
        if not matched_word:
            matched_word = max(bucket_words, key=lambda w: len(normalize(w['word'])))
            matched_text = re.sub(r'[^\w]', '', matched_word['word']).strip()

        if matched_text and matched_word:
            print(f"  Bucket {bucket_idx + 1} ({b_start:.1f}s–{b_end:.1f}s): '{matched_text}' at {matched_word['start']:.2f}s")
            resolved.append({"text": matched_text, "appear_at": matched_word['start']})

    print(f"📋 Final bullets: {[(p['text'], round(p['appear_at'], 2)) for p in resolved]}")
    return resolved


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
    points: List[Dict] = None,
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
        points: Optional list of {text, appear_at} bullet points shown on the left
        clip_duration: Total clip duration in seconds (used to set end time for overlays)

    Returns:
        Complete ASS subtitle file content as string
    """

    # Calculate margin from bottom (10% of video height)
    margin_v = int(video_height * 0.1)

    # Sizes for overlay elements (scale with video height)
    header_fontsize = max(36, int(video_height / 34))
    bullet_fontsize = max(28, int(video_height / 44))
    header_margin_v = max(20, int(video_height * 0.03))

    # ASS file header with three styles: Default (captions), Header, BulletPoint
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
Style: BulletPoint,Arial Black,{bullet_fontsize},&H00FFFFFF,&H00FFFFFF,&H00{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,7,40,10,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Determine the end time for persistent overlay elements (header + bullet points)
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

    # --- Bullet points (each appears at its timestamp, stays visible till end) ---
    if points:
        bullet_x = max(30, int(video_width * 0.05))
        bullet_y_start = max(150, int(video_height * 0.18))
        bullet_y_step = max(70, int(video_height * 0.07))

        for idx, point in enumerate(points):
            appear_at = float(point.get("appear_at", 0.0))
            text = str(point.get("text", ""))
            y_pos = bullet_y_start + idx * bullet_y_step
            numbered_text = f"{idx + 1}. {text}"
            # \pos sets absolute position; \fad(300,0) fades in over 300ms, no fade out
            dialogue_text = f"{{\\pos({bullet_x},{y_pos})\\fad(300,0)}}{numbered_text}"
            ass_content += f"Dialogue: 0,{format_ass_time(appear_at)},{overlay_end_str},BulletPoint,,0,0,0,,{dialogue_text}\n"

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
    bullet_words: List[str] = None,
) -> str:
    """
    Create temporary ASS subtitle file for a video clip.

    Args:
        words: Full transcript words from Whisper
        clip_start: Clip start time in original video
        clip_end: Clip end time in original video
        style: Caption style to use
        title: Optional header text to display at top of video
        bullet_words: Optional list of 5 single words from the transcript.
                      Each word's on-screen appearance time is resolved from
                      Whisper's word-level timestamps so it renders exactly
                      when the word is spoken.

    Returns:
        Path to temporary ASS file
    """
    # Filter and adjust words for this clip
    clip_words = filter_words_for_clip(words, clip_start, clip_end)

    if not clip_words:
        return None

    clip_duration = clip_end - clip_start

    # Resolve exact appearance timestamps for bullet words from the transcript
    resolved_points = resolve_bullet_timestamps(bullet_words or [], clip_words, clip_duration=clip_duration)

    # Generate ASS content with video dimensions
    ass_content = generate_ass_subtitle(
        clip_words,
        style=style,
        video_width=video_width,
        video_height=video_height,
        title=title,
        points=resolved_points,
        clip_duration=clip_duration,
    )

    # Create temporary file
    temp_fd, temp_path = tempfile.mkstemp(suffix='.ass', text=True)

    with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    # Debug: show styles + all overlay lines (header/bullets) + first caption line
    lines = ass_content.splitlines()
    overlay_lines = [l for l in lines if "Header" in l or "BulletPoint" in l]
    print(f"📝 ASS overlay lines ({len(overlay_lines)}):")
    for l in overlay_lines:
        print(f"   {l}")
    print(f"📝 ASS file saved to: {temp_path}")

    return temp_path
