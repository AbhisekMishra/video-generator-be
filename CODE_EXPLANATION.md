# Video Generator Backend - Code Explanation

A beginner-friendly guide to understanding how this Python backend works.

---

## Quick Start Guide

### What This Application Does

1. **Upload Video** → Frontend sends video to Supabase
2. **Transcribe** → Backend extracts audio and converts speech to text (Whisper AI)
3. **Identify Clips** → AI analyzes transcript and finds 3 best short-form clips (GPT-4)
4. **Generate Captions** → Creates word-by-word animated subtitles (ASS format)
5. **Render Videos** → Burns subtitles into video clips (FFmpeg)
6. **Upload Results** → Saves final videos to Supabase
7. **Stream Progress** → Real-time updates to frontend via Server-Sent Events (SSE)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                        │
│  - User uploads video                                            │
│  - Triggers workflow                                             │
│  - Displays progress via SSE stream                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/SSE
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (main.py)                    │
│  - Receives requests                                             │
│  - Starts LangGraph workflow                                     │
│  - Streams progress via SSE                                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LangGraph Workflow (workflow/)                 │
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐        │
│  │ Transcribe  │ → │ Identify    │ → │ Generate    │ →      │
│  │   (Whisper) │    │ Clips (AI)  │    │ Captions    │        │
│  └─────────────┘    └─────────────┘    └─────────────┘        │
│                                                │                │
│                                                ▼                │
│                                        ┌─────────────┐          │
│                                        │   Render    │          │
│                                        │  (FFmpeg)   │          │
│                                        └─────────────┘          │
│                                                                  │
│  State saved to PostgreSQL after each step                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     External Services                            │
│  - PostgreSQL (State persistence)                                │
│  - Supabase Storage (Video files)                                │
│  - GitHub Models (AI - GPT-4o-mini)                              │
│  - FFmpeg (Video processing)                                     │
│  - Whisper AI (Transcription)                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure Explained

### Core Files

#### 1. `main.py` - FastAPI Server (Entry Point)

**What it does:**
- Creates HTTP API endpoints for the frontend to call
- Starts the LangGraph workflow
- Streams real-time progress to frontend via SSE

**Key endpoints:**
```python
POST /transcribe          # Transcribe video with Whisper
POST /render              # Render video clip with FFmpeg
POST /generate-captions   # Create subtitle file
POST /process-video       # Start full workflow
GET  /process-video/stream # Stream workflow progress (SSE)
```

**Code breakdown:**
```python
# 1. CRITICAL: Set event loop policy for Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Why? psycopg (PostgreSQL) needs SelectorEventLoop on Windows

# 2. Create FastAPI application
app = FastAPI(title="Video Generator Worker")

# 3. Define API endpoint (decorator pattern)
@app.post("/transcribe")
async def transcribe_endpoint(request: TranscribeRequest):
    # Pydantic automatically validates the request
    result = await transcribe_video(video_url=request.video_url)
    return result
```

**Important Python concepts:**
- `@app.post("/path")` - Decorator that registers HTTP endpoint
- `async def` - Async function (like JavaScript async/await)
- `TranscribeRequest` - Pydantic model that validates input
- `await` - Wait for async operation to complete

---

#### 2. `workflow/state.py` - State Type Definitions

**What it does:**
- Defines the data structure that flows through the workflow
- Like TypeScript interfaces, but for runtime validation

**Code breakdown:**
```python
class VideoProcessingState(TypedDict):
    """
    The complete state that flows through the workflow.
    Each node can read from and update this state.
    """
    # Input
    videoUrl: str                              # Video URL from Supabase
    sessionId: Optional[str]                   # Unique session ID

    # Processing results
    transcript: Optional[Transcript]           # Whisper transcription
    clips: Optional[List[Clip]]                # AI-identified clips
    captions: Optional[List[CaptionData]]      # Generated subtitle files
    renderedVideos: Optional[List[RenderedVideo]]  # Final videos

    # Metadata
    currentStage: Optional[str]                # Current workflow stage
    errors: Optional[List[str]]                # Error messages
```

**Important Python concepts:**
- `TypedDict` - Defines structure of a dictionary (like TS interface)
- `Optional[T]` - Value can be T or None (nullable)
- `List[T]` - Array of type T (like T[] in TypeScript)

---

#### 3. `workflow/graph.py` - Workflow Orchestration

**What it does:**
- Builds the LangGraph state machine
- Connects nodes in a specific order
- Saves state to PostgreSQL after each step

**Code breakdown:**
```python
async def get_workflow():
    """Build and return the compiled workflow."""

    # 1. Create state graph (state machine)
    workflow = StateGraph(VideoProcessingState)

    # 2. Add nodes (processing steps)
    workflow.add_node("transcribe", transcribe_node)
    workflow.add_node("identifyClips", identify_clips_node)
    workflow.add_node("generateCaptions", generate_captions_node)
    workflow.add_node("render", render_node)

    # 3. Define flow (order of execution)
    workflow.add_edge(START, "transcribe")           # Start → transcribe
    workflow.add_edge("transcribe", "identifyClips") # transcribe → identifyClips
    workflow.add_edge("identifyClips", "generateCaptions")
    workflow.add_edge("generateCaptions", "render")
    workflow.add_edge("render", END)                 # render → End

    # 4. Add PostgreSQL checkpointer (saves state after each step)
    pool = await get_postgres_pool()
    checkpointer = AsyncPostgresSaver(pool)

    # 5. Compile workflow
    app = workflow.compile(checkpointer=checkpointer)
    return app
```

**Important concepts:**
- **StateGraph** - LangGraph's state machine builder
- **Nodes** - Individual processing functions
- **Edges** - Define the flow between nodes
- **Checkpointer** - Saves state to database for resume/debugging

---

#### 4. `workflow/nodes.py` - Processing Steps

**What it does:**
- Implements each step in the workflow
- Each node receives state, processes it, returns updates

**Code breakdown:**

```python
async def transcribe_node(state: VideoProcessingState) -> Dict[str, Any]:
    """
    Step 1: Transcribe video using Whisper AI.

    Args:
        state: Current workflow state (contains videoUrl)

    Returns:
        Dictionary of updates to merge into state
    """
    # 1. Get input from state
    video_url = state.get("videoUrl")

    # 2. Process (call the actual transcription function)
    result = await transcribe_video(video_url=video_url)

    # 3. Return updates to merge into state
    return {
        "transcript": result,              # Save transcript in state
        "currentStage": "identifyClips"    # Move to next stage
    }
```

**The 4 workflow nodes:**

1. **transcribe_node** - Extract audio + generate transcript (Whisper)
2. **identify_clips_node** - AI finds best clips (GPT-4o-mini)
3. **generate_captions_node** - Create subtitle files (ASS format)
4. **render_node** - Render videos with burned-in subtitles (FFmpeg)

**Important pattern:**
```python
# Each node follows this pattern:
async def some_node(state: VideoProcessingState) -> Dict[str, Any]:
    # 1. Get data from state
    input_data = state.get("someField")

    # 2. Do processing
    result = await process(input_data)

    # 3. Return updates (LangGraph merges this into state)
    return {
        "someField": result,
        "currentStage": "nextStage"
    }
```

---

#### 5. `tasks/transcribe.py` - Whisper Transcription

**What it does:**
- Downloads video
- Extracts audio with FFmpeg
- Transcribes with Whisper AI
- Returns word-level timestamps

**Code breakdown:**
```python
async def transcribe_video(video_url: str) -> Dict:
    """Transcribe video using Whisper."""

    # 1. Download video
    temp_video_path = await download_video(video_url)

    # 2. Extract audio with FFmpeg (in thread pool for Windows)
    def run_ffmpeg():
        return subprocess.run([
            "ffmpeg", "-i", temp_video_path,
            "-vn", "-ar", "16000", temp_audio_path
        ])

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_ffmpeg)
    # Why executor? subprocess needs different event loop on Windows

    # 3. Transcribe with Whisper
    model = get_whisper_model()
    result = await loop.run_in_executor(
        None,
        lambda: model.transcribe(temp_audio_path, word_timestamps=True)
    )

    # 4. Extract word-level timestamps
    all_words = []
    for segment in result["segments"]:
        for word_data in segment["words"]:
            all_words.append({
                "word": word_data["word"].strip(),
                "start": float(word_data["start"]),  # Convert numpy to Python
                "end": float(word_data["end"])
            })

    return {
        "text": result["text"],
        "words": all_words,
        "language": result.get("language")
    }
```

**Important concepts:**
- **Thread pool executor** - Run blocking code without blocking async loop
- **Type conversion** - Convert numpy.float64 to Python float for serialization
- **Cleanup** - Always delete temporary files in `finally` block

---

#### 6. `tasks/render.py` - FFmpeg Video Rendering

**What it does:**
- Downloads video and subtitle files
- Renders clips with FFmpeg
- Burns subtitles into video
- Uploads to Supabase

**Code breakdown:**
```python
async def render_video(
    video_url: str,
    start: float,
    end: float,
    subtitle_path: Optional[str] = None
) -> Dict:
    """Render video clip with optional subtitles."""

    # 1. Download video
    input_path = await download_video(video_url)

    # 2. Build FFmpeg command
    duration = end - start
    ffmpeg_cmd = [
        "ffmpeg",
        "-ss", str(start),              # Start time
        "-i", input_path,               # Input file
        "-t", str(duration),            # Duration
    ]

    # 3. Add subtitle filter if provided
    if subtitle_path:
        # Escape path for FFmpeg on Windows
        escaped_path = subtitle_path.replace('\\', '/').replace(':', '\\\\:')
        ffmpeg_cmd.extend(["-vf", f"subtitles={escaped_path}"])

    # 4. Add encoding options
    ffmpeg_cmd.extend([
        "-c:v", "libx264",  # H.264 codec
        "-c:a", "aac",      # AAC audio
        output_path
    ])

    # 5. Run FFmpeg (in thread pool for Windows)
    def run_ffmpeg():
        return subprocess.run(ffmpeg_cmd, capture_output=True)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_ffmpeg)

    # 6. Check for errors
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()}")

    return {"output_path": output_path, "duration": duration}
```

**Important concepts:**
- **Path escaping** - Windows paths need special handling for FFmpeg
- **Subprocess in executor** - Blocking subprocess calls run in thread pool
- **Error handling** - Check return code and raise on failure

---

## Key Python Concepts Explained

### 1. Async/Await (Same as JavaScript!)

```python
# JavaScript:
async function fetchData(url) {
    const response = await fetch(url);
    return await response.json();
}

# Python (identical concept!):
async def fetch_data(url):
    response = await fetch(url)
    return await response.json()
```

**When to use:**
- Use `async def` for functions that do I/O (network, files, database)
- Use `await` when calling other async functions
- Never block the event loop with long-running CPU tasks

### 2. Type Hints (Python's TypeScript)

```python
# Basic types
def greet(name: str) -> str:
    return f"Hello, {name}!"

# Optional (nullable)
def find_user(id: int) -> Optional[str]:
    return users.get(id)  # Returns None if not found

# Lists and Dicts
def get_tags() -> List[str]:
    return ["python", "ai", "video"]

def get_user() -> Dict[str, Any]:
    return {"name": "Alice", "age": 30}
```

**Common types:**
- `str` - string
- `int` - integer
- `float` - decimal number
- `bool` - True/False
- `List[T]` - array of type T
- `Dict[K, V]` - object/map
- `Optional[T]` - T or None
- `Any` - any type

### 3. Dictionaries (JavaScript Objects)

```python
# Create
user = {
    "name": "Alice",
    "age": 30,
    "email": "alice@example.com"
}

# Access (always use brackets, not dot!)
print(user["name"])  # "Alice"

# Get with default
email = user.get("phone", "N/A")  # "N/A" if key missing

# Add/update
user["city"] = "New York"

# Check if key exists
if "age" in user:
    print("Age exists")

# Loop through
for key, value in user.items():
    print(f"{key}: {value}")
```

### 4. Lists (JavaScript Arrays)

```python
# Create
numbers = [1, 2, 3, 4, 5]

# Append (like push)
numbers.append(6)

# Access
first = numbers[0]
last = numbers[-1]  # Negative index = from end!

# Length
length = len(numbers)

# Map (list comprehension)
doubled = [n * 2 for n in numbers]

# Filter
evens = [n for n in numbers if n % 2 == 0]

# Slice
first_three = numbers[0:3]  # [1, 2, 3]
```

### 5. F-Strings (Template Literals)

```python
# JavaScript:
const message = `Hello, ${name}!`;

# Python:
message = f"Hello, {name}!"

# Can include expressions
message = f"Next year you'll be {age + 1}"

# Multi-line
text = """
This is a
multi-line string
"""
```

### 6. Error Handling

```python
try:
    result = risky_operation()
except ValueError as e:
    # Catch specific error
    print(f"Value error: {e}")
except Exception as e:
    # Catch any error
    print(f"Error: {e}")
finally:
    # Always runs (cleanup)
    cleanup()
```

### 7. Context Managers (`with` statement)

```python
# Auto-cleanup pattern
with open("file.txt", "r") as f:
    content = f.read()
# File is automatically closed here!

# Equivalent to:
try:
    f = open("file.txt", "r")
    content = f.read()
finally:
    f.close()
```

### 8. Decorators

```python
# Decorators modify functions
@app.post("/transcribe")  # Registers HTTP endpoint
async def transcribe_endpoint():
    pass

# @app.post is a decorator that:
# 1. Takes the function
# 2. Wraps it with routing logic
# 3. Returns the wrapped function
```

---

## Common Patterns in This Codebase

### Pattern 1: Async Function with Cleanup

```python
async def some_function():
    temp_file = None
    try:
        # Do work
        temp_file = create_temp_file()
        result = await process(temp_file)
        return result
    except Exception as e:
        # Handle error
        print(f"Error: {e}")
        raise
    finally:
        # Always cleanup
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
```

### Pattern 2: Thread Pool for Blocking Code

```python
# Don't do this (blocks event loop):
result = subprocess.run(["ffmpeg", "-i", "video.mp4"])

# Do this instead (runs in thread pool):
def run_ffmpeg():
    return subprocess.run(["ffmpeg", "-i", "video.mp4"])

loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, run_ffmpeg)
```

**Why?**
- On Windows with SelectorEventLoop, subprocess doesn't work in async
- Thread pool runs blocking code without blocking event loop

### Pattern 3: Pydantic Validation

```python
from pydantic import BaseModel

class Request(BaseModel):
    video_url: str
    start: float
    end: float

@app.post("/endpoint")
async def endpoint(request: Request):
    # FastAPI auto-validates:
    # - video_url is a string
    # - start and end are floats
    # - Raises 422 error if validation fails
    pass
```

### Pattern 4: Dictionary Return (Node Pattern)

```python
async def some_node(state: Dict) -> Dict[str, Any]:
    # Get input
    input_value = state.get("inputField")

    # Process
    result = await process(input_value)

    # Return updates (merged into state by LangGraph)
    return {
        "outputField": result,
        "currentStage": "nextStage",
        "errors": None
    }
```

---

## Debugging Tips

### 1. Print Debugging

```python
# Simple print
print("Debug:", variable)

# F-string
print(f"Value: {value}")

# Pretty-print JSON
import json
print(json.dumps(data, indent=2))
```

### 2. Check Types

```python
print(type(variable))        # <class 'str'>
print(isinstance(variable, str))  # True/False
```

### 3. Interactive API Docs

Visit `http://localhost:8000/docs` for automatic Swagger UI!

### 4. Error Tracebacks

```python
try:
    something()
except Exception as e:
    import traceback
    print(traceback.format_exc())  # Full error trace
```

---

## Environment Setup

### 1. Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt

# Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux
```

### 2. Environment Variables (.env)

```bash
# PostgreSQL (for LangGraph state)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-key

# AI Model
GITHUB_TOKEN=your-github-token
```

### 3. Run Server

```bash
# Method 1: Using run.py (recommended)
python run.py

# Method 2: Using uvicorn directly
uvicorn main:app --reload --port 8000
```

---

## Common Issues & Solutions

### Issue 1: Event Loop Error

**Error:** `Psycopg cannot use ProactorEventLoop`

**Solution:** Make sure event loop policy is set BEFORE imports:
```python
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### Issue 2: Subprocess NotImplementedError

**Error:** `NotImplementedError` when using `asyncio.create_subprocess_exec`

**Solution:** Use thread pool executor:
```python
# Don't use: await asyncio.create_subprocess_exec()
# Instead use:
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, subprocess.run, cmd)
```

### Issue 3: NumPy Serialization Error

**Error:** `Type is not msgpack serializable: numpy.float64`

**Solution:** Convert numpy types to Python types:
```python
# Don't return: numpy.float64(123.45)
# Instead: float(123.45)

value = float(word_data["start"])  # Convert to Python float
```

---

## Next Steps

Now that you understand the architecture:

1. ✅ Read `PYTHON_GUIDE.md` for Python basics
2. ✅ Review `main.py` to see how endpoints work
3. ✅ Study `workflow/nodes.py` to understand each processing step
4. ✅ Experiment by adding print statements
5. ✅ Try modifying the AI prompt in `identify_clips_node`
6. ✅ Check out `/docs` endpoint for interactive API testing

Happy coding! 🎉
