# Python Video Generator - Beginner's Guide

Welcome to Python! This guide explains all the key concepts used in this video processing backend.

---

## 📋 Table of Contents

1. [Project Structure](#project-structure)
2. [Python Basics Used](#python-basics-used)
3. [Key Concepts Explained](#key-concepts-explained)
4. [File-by-File Breakdown](#file-by-file-breakdown)

---

## 🗂️ Project Structure

```
video-generator-be/
├── main.py                    # FastAPI app entry point (like Express.js server)
├── run.py                     # Startup script (ensures correct setup)
├── requirements.txt           # Dependencies (like package.json)
├── .env                       # Environment variables
│
├── workflow/                  # LangGraph workflow (state machine)
│   ├── state.py              # Type definitions for workflow state
│   ├── nodes.py              # Individual processing steps
│   └── graph.py              # Workflow orchestration
│
├── tasks/                     # Core processing functions
│   ├── transcribe.py         # Whisper AI transcription
│   └── render.py             # FFmpeg video rendering
│
└── utils/                     # Helper utilities
    ├── supabase_client.py    # File upload/download
    ├── caption_generator.py  # ASS subtitle generation
    └── file_utils.py         # File operations
```

---

## 🐍 Python Basics Used

### 1. **Type Hints** (Python's TypeScript)

```python
# TypeScript:
function transcribe(url: string): Promise<Transcript>

# Python equivalent:
async def transcribe_video(video_url: str) -> Dict:
    pass
```

**Common Types:**
- `str` = string
- `int` = integer (number without decimals)
- `float` = decimal number
- `bool` = boolean
- `List[str]` = array of strings (like string[])
- `Dict` = object/dictionary (like {})
- `Optional[str]` = string | None (nullable)
- `Any` = any type

### 2. **async/await** (Same as JavaScript!)

```python
# JavaScript:
const result = await fetch(url);

# Python:
result = await fetch_url(url)
```

**Key Points:**
- `async def` = async function
- `await` = wait for async operation
- `asyncio` = Python's event loop library (like Node.js event loop)

### 3. **Decorators** (Like TypeScript decorators)

```python
@app.post("/transcribe")  # Route decorator (like app.post() in Express)
async def transcribe_endpoint(request: TranscribeRequest):
    pass
```

**Common decorators:**
- `@app.post("/path")` = POST endpoint
- `@app.get("/path")` = GET endpoint
- `@asynccontextmanager` = Creates a context manager

### 4. **Context Managers** (`with` statement)

```python
# Automatically handles cleanup (like try/finally)
with open("file.txt", "r") as f:
    content = f.read()
    # File is automatically closed after this block
```

Similar to JavaScript:
```javascript
try {
  const f = open("file.txt");
  const content = f.read();
} finally {
  f.close();  // Python does this automatically with "with"
}
```

### 5. **f-strings** (Template literals)

```python
# JavaScript:
const message = `Hello ${name}!`;

# Python:
message = f"Hello {name}!"
```

### 6. **Dictionaries** (Objects)

```python
# JavaScript:
const user = { name: "Alice", age: 30 };
console.log(user.name);

# Python:
user = {"name": "Alice", "age": 30}
print(user["name"])  # Access with brackets
```

### 7. **Lists** (Arrays)

```python
# JavaScript:
const numbers = [1, 2, 3];
numbers.push(4);

# Python:
numbers = [1, 2, 3]
numbers.append(4)  # append instead of push
```

### 8. **List Comprehensions** (Array.map in one line)

```python
# JavaScript:
const doubled = numbers.map(n => n * 2);

# Python:
doubled = [n * 2 for n in numbers]
```

### 9. **Triple-Quoted Strings** (Multi-line strings)

```python
prompt = """
This is a multi-line string.
You can write multiple lines.
No need for \n or template literals!
"""
```

---

## 🔑 Key Concepts Explained

### **1. FastAPI** (Like Express.js for Python)

FastAPI is a modern web framework for building APIs:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}
```

**Key Features:**
- Automatic API documentation (Swagger UI at `/docs`)
- Built-in request/response validation with Pydantic
- Native async/await support
- Type hints for automatic validation

### **2. Pydantic** (Runtime Type Validation)

Pydantic validates data at runtime (like Zod in JavaScript):

```python
from pydantic import BaseModel

class TranscribeRequest(BaseModel):
    video_url: Optional[str] = None
    video_path: Optional[str] = None

# FastAPI automatically validates:
@app.post("/transcribe")
async def transcribe(request: TranscribeRequest):
    # request.video_url is guaranteed to be str or None
    pass
```

### **3. TypedDict** (Type Hints for Dictionaries)

Used to define the shape of dictionaries (like TypeScript interfaces):

```python
from typing import TypedDict

class User(TypedDict):
    name: str
    age: int

# Usage:
user: User = {"name": "Alice", "age": 30}
```

### **4. LangGraph** (State Machine for AI Workflows)

LangGraph orchestrates multi-step AI workflows:

```python
# Define a workflow graph
workflow = StateGraph(VideoProcessingState)

# Add nodes (processing steps)
workflow.add_node("transcribe", transcribe_node)
workflow.add_node("identifyClips", identify_clips_node)

# Add edges (flow between steps)
workflow.add_edge("transcribe", "identifyClips")
```

**Key Concepts:**
- **State**: Data that flows through the workflow
- **Nodes**: Processing functions that update state
- **Edges**: Define the flow between nodes
- **Checkpointer**: Saves state to database (for resume/debugging)

### **5. asyncio Event Loop** (JavaScript Event Loop)

Python's async runtime (similar to Node.js):

```python
import asyncio

# Run async function
result = await some_async_function()

# Run in thread pool (for blocking code)
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, blocking_function)
```

**Windows Issue:**
- Windows has 2 event loop policies:
  - `ProactorEventLoop` (default) - supports subprocess
  - `SelectorEventLoop` - supports psycopg (PostgreSQL)
- We use `SelectorEventLoop` + thread pool for subprocess

### **6. Server-Sent Events (SSE)**

Real-time streaming to frontend:

```python
async def event_generator():
    yield {"event": "status", "data": json.dumps({"stage": "processing"})}

return EventSourceResponse(event_generator())
```

---

## 📄 File-by-File Breakdown

### **main.py** - FastAPI Server

This is the entry point, like `server.js` in Express:

```python
# 1. Set event loop policy (Windows fix)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 2. Create FastAPI app
app = FastAPI()

# 3. Define API endpoints
@app.post("/transcribe")
async def transcribe_endpoint(request: TranscribeRequest):
    # Call transcription task
    result = await transcribe_video(video_url=request.video_url)
    return result
```

**Key endpoints:**
- `POST /transcribe` - Transcribe video with Whisper
- `POST /render` - Render video clip with FFmpeg
- `POST /process-video` - Start LangGraph workflow
- `GET /process-video/stream` - Stream workflow progress (SSE)

### **workflow/state.py** - State Type Definitions

Defines the data structure that flows through the workflow:

```python
class VideoProcessingState(TypedDict):
    # Input
    videoUrl: str
    sessionId: Optional[str]

    # Processing results
    transcript: Optional[Transcript]
    clips: Optional[List[Clip]]
    renderedVideos: Optional[List[RenderedVideo]]

    # Metadata
    currentStage: Optional[str]
    errors: Optional[List[str]]
```

### **workflow/nodes.py** - Processing Steps

Each node is a function that processes the state:

```python
async def transcribe_node(state: VideoProcessingState) -> Dict[str, Any]:
    # 1. Get input from state
    video_url = state.get("videoUrl")

    # 2. Process (transcribe video)
    result = await transcribe_video(video_url=video_url)

    # 3. Return updates to merge into state
    return {
        "transcript": result,
        "currentStage": "identifyClips"  # Move to next stage
    }
```

**Workflow stages:**
1. `transcribe` - Extract audio + generate transcript
2. `identifyClips` - AI finds best clips (GPT-4)
3. `generateCaptions` - Create word-by-word subtitles
4. `render` - Render videos with burned-in captions

### **workflow/graph.py** - Workflow Orchestration

Builds the LangGraph workflow:

```python
# 1. Create state graph
workflow = StateGraph(VideoProcessingState)

# 2. Add nodes
workflow.add_node("transcribe", transcribe_node)
workflow.add_node("identifyClips", identify_clips_node)

# 3. Define flow
workflow.add_edge(START, "transcribe")
workflow.add_edge("transcribe", "identifyClips")

# 4. Add PostgreSQL checkpointer (saves state)
checkpointer = AsyncPostgresSaver(pool)

# 5. Compile workflow
app = workflow.compile(checkpointer=checkpointer)
```

### **tasks/transcribe.py** - Whisper Transcription

Uses OpenAI Whisper for speech-to-text:

```python
async def transcribe_video(video_url: str) -> Dict:
    # 1. Download video
    temp_video_path = await download_video(video_url)

    # 2. Extract audio with FFmpeg
    # (Run in thread pool for Windows compatibility)
    ffmpeg_result = await loop.run_in_executor(None, run_ffmpeg)

    # 3. Transcribe with Whisper
    model = get_whisper_model()
    result = await loop.run_in_executor(
        None,
        lambda: model.transcribe(audio_path, word_timestamps=True)
    )

    # 4. Return transcript with word-level timestamps
    return {
        "text": result["text"],
        "words": all_words,  # [{word, start, end}, ...]
        "language": result.get("language")
    }
```

### **tasks/render.py** - FFmpeg Video Rendering

Renders video clips with subtitles:

```python
async def render_video(
    video_url: str,
    start: float,
    end: float,
    subtitle_path: Optional[str] = None
) -> Dict:
    # 1. Download video if URL provided
    input_path = await download_video(video_url)

    # 2. Build FFmpeg command
    ffmpeg_cmd = [
        "ffmpeg",
        "-ss", str(start),      # Start time
        "-i", input_path,       # Input file
        "-t", str(duration),    # Duration
        "-vf", f"subtitles={subtitle_path}",  # Burn subtitles
        "-c:v", "libx264",      # H.264 codec
        output_path
    ]

    # 3. Run FFmpeg (in thread pool for Windows)
    result = await loop.run_in_executor(None, run_ffmpeg)

    # 4. Return output path
    return {"output_path": output_path, "duration": duration}
```

---

## 🎯 Common Python Patterns

### **1. Error Handling**

```python
try:
    result = await some_function()
except ValueError as e:
    print(f"Value error: {e}")
except Exception as e:
    print(f"Unknown error: {e}")
finally:
    # Always runs (cleanup)
    cleanup()
```

### **2. None Checks** (like null checks)

```python
# JavaScript:
if (value !== null && value !== undefined)

# Python:
if value is not None:
    pass

# With default value:
name = user.get("name", "Unknown")  # Returns "Unknown" if key missing
```

### **3. String Methods**

```python
text = "hello world"
text.upper()           # "HELLO WORLD"
text.split(" ")        # ["hello", "world"]
text.strip()           # Remove whitespace
text.replace("h", "H") # "Hello world"
```

### **4. File Operations**

```python
# Read file
with open("file.txt", "r") as f:
    content = f.read()

# Write file
with open("file.txt", "w") as f:
    f.write("Hello")

# Check if file exists
import os
if os.path.exists("file.txt"):
    pass
```

### **5. Environment Variables**

```python
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Access variables
api_key = os.getenv("API_KEY")  # Returns None if not found
api_key = os.getenv("API_KEY", "default")  # With default value
```

---

## 🔧 Common Operations

### **Running the Server**

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
python run.py

# Or with uvicorn directly
uvicorn main:app --reload --port 8000
```

### **Installing Packages**

```bash
# Install one package
pip install fastapi

# Install all from requirements.txt
pip install -r requirements.txt

# Freeze current packages (like npm list)
pip freeze > requirements.txt
```

### **Python Virtual Environment** (like node_modules)

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Deactivate
deactivate
```

---

## 🎓 Key Differences from JavaScript

| Feature | JavaScript | Python |
|---------|-----------|--------|
| **Variables** | `const x = 1` | `x = 1` |
| **Functions** | `function foo() {}` | `def foo():` |
| **Async** | `async function` | `async def` |
| **Arrays** | `[1, 2, 3]` | `[1, 2, 3]` (same!) |
| **Objects** | `{key: value}` | `{"key": value}` |
| **Access props** | `obj.key` or `obj['key']` | `obj["key"]` |
| **Null** | `null` | `None` |
| **True/False** | `true`/`false` | `True`/`False` |
| **Comments** | `// comment` | `# comment` |
| **Multiline** | `` ` ` `` | `""" """` |
| **String format** | `` `${var}` `` | `f"{var}"` |
| **Export** | `export function` | N/A (use imports) |
| **Import** | `import {x} from` | `from module import x` |

---

## 📚 Learn More

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Python Asyncio**: https://docs.python.org/3/library/asyncio.html
- **LangGraph**: https://langchain-ai.github.io/langgraph/
- **Pydantic**: https://docs.pydantic.dev/

---

## 🐞 Debugging Tips

### **Print Debugging**

```python
print("Debug:", variable)
print(f"Value is: {value}")

# Pretty print dictionaries
import json
print(json.dumps(data, indent=2))
```

### **FastAPI Interactive Docs**

Visit `http://localhost:8000/docs` for automatic Swagger UI!

### **Check Types**

```python
print(type(variable))  # <class 'str'>
isinstance(variable, str)  # True/False
```

---

## ✅ Next Steps

Now that you understand the basics, you can:

1. Read through `main.py` with these concepts in mind
2. Look at `workflow/nodes.py` to see how each processing step works
3. Experiment by adding print statements to understand the flow
4. Try modifying the LLM prompt in `identify_clips_node`

Happy coding! 🎉
