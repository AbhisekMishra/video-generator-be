# Video Generator Backend

Python FastAPI worker for video transcription and rendering.

## Features

- **Transcription**: Uses OpenAI's `whisper` for accurate video transcription with word-level timestamps
- **Rendering**: Uses FFmpeg for vertical crop (9:16 aspect ratio) video processing
- **File Management**: Automatic cleanup of temporary files
- **Windows Compatible**: No compilation required - uses pre-built packages

## Prerequisites

1. **Python 3.9+**
2. **FFmpeg** - Must be installed and available in PATH
   - Ubuntu/Debian: `sudo apt-get install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Windows: Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)

## Setup

### 1. Create Virtual Environment

```bash
cd video-generator-be
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify FFmpeg Installation

```bash
ffmpeg -version
```

### 4. Start the Server

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Documentation

### POST `/process`

Process video based on task type.

#### Task: `transcribe`

Transcribe video using faster-whisper.

**Request:**
```json
{
  "task": "transcribe",
  "video_url": "https://example.com/video.mp4"
}
```

Or with local file:
```json
{
  "task": "transcribe",
  "video_path": "/path/to/video.mp4"
}
```

**Response:**
```json
{
  "text": "Full transcription text here...",
  "words": [
    {
      "word": "Hello",
      "start": 0.5,
      "end": 0.8
    }
  ],
  "language": "en"
}
```

#### Task: `render`

Crop video to 9:16 aspect ratio using FFmpeg.

**Request:**
```json
{
  "task": "render",
  "video_url": "https://example.com/video.mp4",
  "center_x": 960,
  "start": 10.5,
  "end": 45.2
}
```

**Parameters:**
- `center_x`: X coordinate for center of the crop
- `start`: Start timestamp in seconds
- `end`: End timestamp in seconds

**Response:**
```json
{
  "output_path": "/tmp/tmpXXXXXX.mp4",
  "duration": 34.7
}
```

## Example Usage

### Using cURL

**Transcribe:**
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{
    "task": "transcribe",
    "video_path": "/path/to/video.mp4"
  }'
```

**Render:**
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{
    "task": "render",
    "video_path": "/path/to/video.mp4",
    "center_x": 960,
    "start": 0,
    "end": 30
  }'
```

### Using Python

```python
import requests

# Transcribe
response = requests.post(
    "http://localhost:8000/process",
    json={
        "task": "transcribe",
        "video_path": "/path/to/video.mp4"
    }
)
result = response.json()
print(result["text"])

# Render
response = requests.post(
    "http://localhost:8000/process",
    json={
        "task": "render",
        "video_path": "/path/to/video.mp4",
        "center_x": 960,
        "start": 0,
        "end": 30
    }
)
result = response.json()
print(f"Output: {result['output_path']}")
```

## Project Structure

```
video-generator-be/
├── main.py                 # FastAPI application
├── tasks/
│   ├── __init__.py
│   ├── transcribe.py      # Whisper transcription logic
│   └── render.py          # FFmpeg rendering logic
├── utils/
│   ├── __init__.py
│   └── file_utils.py      # File download and cleanup utilities
├── requirements.txt       # Python dependencies
└── README.md
```

## Configuration

The Whisper model is configured in `tasks/transcribe.py`. Default is `base` model.

Available models (in order of speed/accuracy trade-off):
- `tiny` - Fastest, least accurate
- `base` - Good balance (default)
- `small` - Better accuracy
- `medium` - High accuracy
- `large` - Best accuracy
- `large-v2` - Enhanced accuracy
- `large-v3` - Latest, best accuracy

To change the model, edit line 22 in `tasks/transcribe.py`:
```python
_whisper_model = whisper.load_model("base", device=device)
```

GPU acceleration is automatic if CUDA is available (PyTorch detects it automatically).

## Notes

- Temporary files are automatically cleaned up after processing
- Rendered videos are saved to temporary files - move them to permanent storage before they're deleted
- The first transcription may take longer as the Whisper model is downloaded
- Audio is extracted at 16kHz mono for optimal Whisper performance
