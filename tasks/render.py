import os
import tempfile
import asyncio
from typing import Optional, Dict
import subprocess

from utils.file_utils import download_video, cleanup_file

# ── Gap proportions (fraction of source video height) ────────────────────────
# Applied at render time based on actual source dimensions.
TOP_GAP_RATIO    = 0.09   # ~9 % of source height  → logo + title bar
BOTTOM_GAP_RATIO = 0.055  # ~5.5 % of source height → breathing room

# Path to logo assets (relative to this file)
_ASSETS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'utils', 'assets'))
_LOGO_SVG = os.path.join(_ASSETS_DIR, 'logo.svg')
_LOGO_PNG = os.path.join(_ASSETS_DIR, 'logo.png')   # pre-rendered drop-in


def _pillow_am_logo(png_path: str) -> bool:
    """
    Render the AM mountain-peak logo using Pillow + numpy.

    Draws the exact SVG polygon/gradient geometry (legs, crossbar, accent dots)
    without needing Cairo, Inkscape, or ImageMagick.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter  # type: ignore
        import numpy as np                             # type: ignore
    except ImportError:
        return False

    try:
        W, H = 520, 340
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        def poly_layer(points, c1, c2, direction='d'):
            """RGBA image: gradient-filled polygon, transparent elsewhere."""
            mask = Image.new('L', (W, H), 0)
            ImageDraw.Draw(mask).polygon(points, fill=255)
            m = np.array(mask, dtype=np.float32) / 255.0
            if direction == 'h':                          # left → right
                t = np.tile(np.linspace(0, 1, W), (H, 1))
            else:                                         # diagonal (x60% + y40%)
                tx = np.tile(np.linspace(0, 1, W), (H, 1))
                ty = np.tile(np.linspace(0, 1, H).reshape(-1, 1), (1, W))
                t = np.clip(tx * 0.6 + ty * 0.4, 0, 1)
            r = np.clip(c1[0]*(1-t) + c2[0]*t, 0, 255)
            g = np.clip(c1[1]*(1-t) + c2[1]*t, 0, 255)
            b = np.clip(c1[2]*(1-t) + c2[2]*t, 0, 255)
            a = m * 230
            return Image.fromarray(
                np.stack([r, g, b, a], axis=-1).astype(np.uint8), 'RGBA'
            )

        # ── Drop shadow (offset + blur) ───────────────────────────────────────
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        for p in [
            [(42,304),(79,322),(194,82),(157,64)],
            [(157,64),(194,82),(282,246),(246,228)],
            [(246,228),(282,246),(375,82),(337,64)],
            [(337,64),(375,82),(445,222),(407,204)],
            [(407,204),(445,222),(489,98),(450,84)],
            [(450,84),(489,98),(523,310),(482,304)],
        ]:
            sdraw.polygon(p, fill=(0, 0, 0, 55))
        base = Image.alpha_composite(base, shadow.filter(ImageFilter.GaussianBlur(5)))

        # ── Six polygon legs ─────────────────────────────────────────────────
        # (points, c1, c2, direction)  — matches SVG gradient definitions
        legs = [
            ([(40,300),(77,318),(192,78),(155,60)],  (255,107,53),(255,45,120), 'd'),  # Leg1 gL
            ([(155,60),(192,78),(280,242),(244,224)], (255,45,120),(0,207,255), 'h'),  # Leg2 gM
            ([(244,224),(280,242),(373,78),(335,60)], (0,207,255),(91,47,221),  'd'),  # Leg3 gR
            ([(335,60),(373,78),(443,218),(405,200)], (0,207,255),(91,47,221),  'd'),  # Leg4 gR
            ([(405,200),(443,218),(487,94),(448,80)], (0,207,255),(91,47,221),  'd'),  # Leg5 gR
            ([(448,80),(487,94),(521,306),(480,300)], (0,207,255),(91,47,221),  'd'),  # Leg6 gR
        ]
        for pts, c1, c2, d in legs:
            base = Image.alpha_composite(base, poly_layer(pts, c1, c2, d))

        draw = ImageDraw.Draw(base)

        # ── Valley fill ellipses ─────────────────────────────────────────────
        draw.ellipse([242, 219, 282, 247], fill=(180, 100, 185, 220))
        draw.ellipse([406, 197, 442, 221], fill=(0, 207, 255, 220))

        # ── A crossbar (horizontal gold → orange gradient) ───────────────────
        t = np.tile(np.linspace(0, 1, W), (H, 1))
        bar_mask = Image.new('L', (W, H), 0)
        ImageDraw.Draw(bar_mask).rounded_rectangle([114, 178, 234, 206], radius=7, fill=255)
        bm = np.array(bar_mask, dtype=np.float32) / 255.0
        cross = np.stack([
            np.clip(255*(1-t) + 255*t, 0, 255),   # R: stays 255
            np.clip(229*(1-t) + 107*t, 0, 255),   # G: 229→107
            np.clip(102*(1-t) + 53*t,  0, 255),   # B: 102→53
            bm * 230,
        ], axis=-1).astype(np.uint8)
        base = Image.alpha_composite(base, Image.fromarray(cross, 'RGBA'))

        draw = ImageDraw.Draw(base)

        # ── Base feet ────────────────────────────────────────────────────────
        draw.rounded_rectangle([32, 294, 90,  310], radius=5, fill=(255, 107,  53, 230))
        draw.rounded_rectangle([468,294, 526, 310], radius=5, fill=(0,  207, 255, 230))

        # ── Peak accent dots ─────────────────────────────────────────────────
        draw.ellipse([145, 48, 165, 68], fill=(255, 229, 102, 255))   # A apex  — yellow
        draw.ellipse([325, 48, 345, 68], fill=(0,  255, 204, 255))    # M left  — teal
        draw.ellipse([440, 70, 456, 86], fill=(0,  229, 255, 255))    # M right — cyan

        base.save(png_path, "PNG")
        print("[OK] Logo PNG generated via Pillow (AM vector render)")
        return True

    except Exception as exc:
        print(f"[WARN] Pillow AM logo render failed: {exc}")
        return False


def _logo_as_png() -> Optional[str]:
    """
    Resolve logo as PNG for FFmpeg overlay.

    Backends tried in order:
      0. logo.png already in assets/       — zero deps (drop a PNG here to override)
      1. cairosvg                           — pixel-perfect, needs Cairo native lib
      2. svglib + reportlab                 — needs _renderPM C extension
      3. inkscape CLI                       — if Inkscape is installed
      4. magick CLI (ImageMagick)           — if ImageMagick is installed
      5. Pillow + numpy                     — pure Python, draws AM geometry

    Returns the PNG path, or None to skip the logo overlay.
    """
    # 0. Pre-rendered PNG (user-supplied or previously cached)
    if os.path.exists(_LOGO_PNG):
        print("✅ Using pre-rendered logo.png")
        return _LOGO_PNG

    if not os.path.exists(_LOGO_SVG):
        print(f"⚠️  No logo found in {_ASSETS_DIR} — skipping logo overlay")
        return None

    png_path = tempfile.mktemp(suffix='.png')

    # 1. cairosvg
    try:
        import cairosvg
        cairosvg.svg2png(url=_LOGO_SVG, write_to=png_path, output_width=520, output_height=340)
        print("✅ Logo PNG via cairosvg")
        return png_path
    except ImportError:
        pass
    except Exception:
        pass

    # 2. svglib + reportlab
    try:
        from svglib.svglib import svg2rlg       # type: ignore
        from reportlab.graphics import renderPM  # type: ignore
        drawing = svg2rlg(_LOGO_SVG)
        if drawing:
            renderPM.drawToFile(drawing, png_path, fmt="PNG")
            print("✅ Logo PNG via svglib")
            return png_path
    except ImportError:
        pass
    except Exception:
        pass

    # 3. Inkscape CLI
    try:
        r = subprocess.run(
            ['inkscape', '--export-type=png', f'--export-filename={png_path}', _LOGO_SVG],
            capture_output=True, check=False, timeout=15
        )
        if r.returncode == 0 and os.path.exists(png_path):
            print("✅ Logo PNG via Inkscape")
            return png_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 4. ImageMagick CLI
    try:
        r = subprocess.run(
            ['magick', 'convert', '-background', 'none', _LOGO_SVG, png_path],
            capture_output=True, check=False, timeout=15
        )
        if r.returncode == 0 and os.path.exists(png_path):
            print("✅ Logo PNG via ImageMagick")
            return png_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 5. Pillow + numpy (draws the actual AM polygon/gradient geometry)
    if _pillow_am_logo(png_path):
        return png_path

    print("⚠️  All logo backends exhausted — skipping logo overlay")
    print("     Quickest fix: place a logo.png in utils/assets/")
    return None


async def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Get video width and height using ffprobe."""
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        video_path
    ]

    def run_ffprobe():
        return subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_ffprobe)

    if result.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {result.stderr.decode()}")

    dims = result.stdout.decode().strip().split(',')
    return int(dims[0]), int(dims[1])


async def render_video(
    video_url: Optional[str] = None,
    video_path: Optional[str] = None,
    center_x: Optional[int] = None,
    start: float = 0.0,
    end: float = 0.0,
    subtitle_path: Optional[str] = None,
) -> Dict:
    """
    Render a clip with the branded layout, keeping the original video resolution:

      ┌──────────────────────────┐
      │ [logo]    [title text]   │  ← top gap  (~9 % of source height)
      ├──────────────────────────┤
      │                          │
      │  video content (original resolution, no resize)
      │  1. bullet               │
      │  …                       │
      │      [word captions]     │
      ├──────────────────────────┤
      │                          │  ← bottom gap (~5.5 % of source height)
      └──────────────────────────┘

    Output width  = source width  (unchanged)
    Output height = source height + top_gap + bottom_gap

    The title + bullet points + word captions are burned via the ASS file.
    The logo is overlaid by FFmpeg using a second input (cairosvg or svglib).

    Args:
        video_url:     URL to download the source video from
        video_path:    Local path to source video (alternative to URL)
        center_x:      Optional horizontal crop centre; defaults to video centre
        start:         Clip start timestamp in seconds
        end:           Clip end timestamp in seconds
        subtitle_path: Local path to the ASS subtitle file

    Returns:
        {'output_path': str, 'duration': float}
    """
    temp_video_path = None
    logo_png_path = None
    output_path = None

    try:
        # ── 1. Resolve input ──────────────────────────────────────────────
        if video_url:
            temp_video_path = await download_video(video_url)
            input_path = temp_video_path
        elif video_path:
            input_path = video_path
        else:
            raise ValueError("Either video_url or video_path must be provided")

        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Video file not found: {input_path}")

        duration = end - start
        output_path = tempfile.mktemp(suffix=".mp4")

        # ── 2. Detect source dimensions ───────────────────────────────────
        orig_w, orig_h = await get_video_dimensions(input_path)
        print(f"📐 Source dimensions: {orig_w}×{orig_h}")

        # Compute gap sizes from source height — keeps original video untouched
        top_gap    = max(40, int(orig_h * TOP_GAP_RATIO))
        bottom_gap = max(25, int(orig_h * BOTTOM_GAP_RATIO))
        out_h      = orig_h + top_gap + bottom_gap   # canvas = original + gaps
        print(f"📐 Layout: top_gap={top_gap}px  bottom_gap={bottom_gap}px  output={orig_w}×{out_h}")

        # ── 3. Build FFmpeg filter chain ──────────────────────────────────
        #
        # Just add black bars above and below — the video itself is NOT resized.
        # pad=width:height:x_offset:y_offset  →  shifts content down by top_gap.
        video_chain = (
            f"[0:v]"
            f"pad={orig_w}:{out_h}:0:{top_gap}:black"
            f"[padded]"
        )

        fc_parts = [video_chain]
        extra_inputs: list = []
        current_label = "[padded]"
        next_input_idx = 1

        # Step B: logo overlay (optional — requires cairosvg or svglib)
        logo_png_path = _logo_as_png()
        if logo_png_path and os.path.exists(logo_png_path):
            logo_display_h = max(30, top_gap - 20)               # fills ~80% of top gap
            logo_y = (top_gap - logo_display_h) // 2             # vertically centred in gap
            logo_x = max(10, int(orig_w * 0.015))                # ~1.5% from left edge
            fc_parts.append(f"[{next_input_idx}:v]scale=-1:{logo_display_h}[logo]")
            fc_parts.append(f"{current_label}[logo]overlay={logo_x}:{logo_y}[with_logo]")
            current_label = "[with_logo]"
            extra_inputs += ["-i", logo_png_path]
            next_input_idx += 1

        # Step C: burn ASS subtitles (title + bullets + word captions)
        if subtitle_path and os.path.exists(subtitle_path):
            print(f"🔍 Subtitle path: {subtitle_path}")
            # Windows: forward slashes + escape colon in drive letter
            escaped = subtitle_path.replace('\\', '/').replace(':', '\\\\:')
            print(f"🔍 Escaped subtitle path: {escaped}")
            fc_parts.append(f"{current_label}subtitles={escaped}[out]")
            output_label = "[out]"
        else:
            output_label = current_label

        filter_complex = ";".join(fc_parts)
        print(f"🔧 filter_complex:\n{filter_complex}")

        # ── 5. Assemble FFmpeg command ────────────────────────────────────
        # IMPORTANT: -t must come AFTER all -i flags.
        # If placed between two -i flags, FFmpeg treats it as an input option
        # for the next input (the logo PNG), not as an output duration limit —
        # causing the output to run to the end of the source file.
        ffmpeg_cmd = [
            "ffmpeg",
            "-ss", str(start),       # fast seek (input option for video)
            "-i", input_path,
            *extra_inputs,           # logo PNG input (if any) — must come before -t
            "-t", str(duration),     # OUTPUT duration limit (after all -i flags)
            "-filter_complex", filter_complex,
            "-map", output_label,    # video track from filter
            "-map", "0:a",           # audio from original input
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-y",
            output_path
        ]

        print(f"🔧 FFmpeg command: {' '.join(ffmpeg_cmd)}")

        # ── 6. Run FFmpeg ─────────────────────────────────────────────────
        def run_ffmpeg():
            return subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_ffmpeg)

        stderr_output = result.stderr.decode()
        if subtitle_path and stderr_output:
            if '[Parsed_subtitles_' in stderr_output:
                print("✅ Subtitle filter loaded by FFmpeg")
            else:
                print("❌ WARNING: Subtitle filter was NOT loaded by FFmpeg!")
                print(stderr_output[:3000])

        if result.returncode != 0:
            print(f"❌ FFmpeg FULL error:\n{stderr_output}")
            raise RuntimeError(f"FFmpeg failed: {stderr_output[-1000:]}")

        if not os.path.exists(output_path):
            raise RuntimeError("Output file was not created")

        return {"output_path": output_path, "duration": duration}

    finally:
        if temp_video_path:
            await cleanup_file(temp_video_path)
        if logo_png_path and os.path.exists(logo_png_path):
            try:
                os.remove(logo_png_path)
            except Exception:
                pass
        # output_path is intentionally NOT cleaned up — it's the result
