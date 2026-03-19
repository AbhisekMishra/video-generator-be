# Python Video Generator - Quick Start for Beginners

Welcome! This guide will get you up and running quickly.

---

## 📚 Documentation

We've created 3 guides for you:

1. **PYTHON_GUIDE.md** - Learn Python basics (types, async, dictionaries, etc.)
2. **CODE_EXPLANATION.md** - Detailed explanation of how this project works
3. **SIMPLE_EXAMPLES.py** - Runnable Python examples (see code samples)

**Start here:** Read `PYTHON_GUIDE.md` first if you're new to Python!

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt
```

### 2. Set Up Environment Variables

Create a `.env` file in this directory:

```bash
# PostgreSQL (for workflow state)
DATABASE_URL=postgresql://user:pass@localhost:5432/video_gen

# Supabase (for file storage)
SUPABASE_URL=https://yourproject.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# AI Model (GitHub Models - free!)
GITHUB_TOKEN=your-github-token
```

### 3. Run the Server

```bash
# Start the server
python run.py
```

The server will start on `http://localhost:8000`

### 4. Test the API

Visit `http://localhost:8000/docs` for interactive API documentation (Swagger UI)!

---

## 🎯 What This App Does

```
1. User uploads video → Supabase Storage
2. Backend transcribes video → Whisper AI (speech-to-text)
3. AI finds best clips → GPT-4o-mini analyzes transcript
4. Generate subtitles → Word-by-word animated captions
5. Render videos → FFmpeg burns captions into clips
6. Upload results → Supabase Storage
7. Stream progress → Real-time updates to frontend (SSE)
```

---

## 📁 Project Structure

```
video-generator-be/
│
├── main.py              ⭐ MAIN FILE - FastAPI server entry point
├── run.py               🚀 Startup script (sets up event loop for Windows)
│
├── workflow/            🔄 LangGraph workflow (state machine)
│   ├── state.py         📊 State type definitions
│   ├── nodes.py         ⚙️ Processing steps (transcribe, identify, etc.)
│   └── graph.py         🔗 Workflow orchestration
│
├── tasks/               💼 Core processing functions
│   ├── transcribe.py    🎤 Whisper AI transcription
│   └── render.py        🎬 FFmpeg video rendering
│
├── utils/               🛠️ Helper utilities
│   ├── supabase_client.py  ☁️ File upload/download
│   ├── caption_generator.py 📝 Subtitle generation
│   └── file_utils.py    📂 File operations
│
└── requirements.txt     📦 Python dependencies
```

---

## 🔑 Key Files Explained

### **main.py** - FastAPI Server

This is the entry point. It creates HTTP endpoints for the frontend.

**Key endpoints:**
- `POST /transcribe` - Transcribe video with Whisper
- `POST /render` - Render video clip
- `POST /process-video` - Start workflow
- `GET /process-video/stream` - Stream progress (SSE)

### **workflow/graph.py** - Workflow Builder

Creates the LangGraph state machine:

```python
workflow.add_node("transcribe", transcribe_node)
workflow.add_node("identifyClips", identify_clips_node)
workflow.add_node("generateCaptions", generate_captions_node)
workflow.add_node("render", render_node)
```

### **workflow/nodes.py** - Processing Steps

Each node is a function that:
1. Reads from state
2. Processes data
3. Returns updates

```python
async def transcribe_node(state):
    video_url = state.get("videoUrl")
    result = await transcribe_video(video_url)
    return {
        "transcript": result,
        "currentStage": "identifyClips"
    }
```

### **tasks/transcribe.py** - Whisper AI

Downloads video, extracts audio, transcribes with Whisper.

### **tasks/render.py** - FFmpeg Rendering

Renders video clips with burned-in subtitles.

---

## 🐍 Python vs JavaScript Cheat Sheet

| Concept | JavaScript | Python |
|---------|-----------|--------|
| **Variables** | `const x = 1` | `x = 1` |
| **Functions** | `function foo()` | `def foo():` |
| **Async** | `async function` | `async def` |
| **Await** | `await fetch()` | `await fetch()` (same!) |
| **Arrays** | `[1, 2, 3]` | `[1, 2, 3]` (same!) |
| **Objects** | `{key: value}` | `{"key": value}` |
| **Access** | `obj.key` | `obj["key"]` |
| **Null** | `null` | `None` |
| **True/False** | `true`/`false` | `True`/`False` |
| **Comments** | `// comment` | `# comment` |
| **Template** | `` `${var}` `` | `f"{var}"` |
| **Import** | `import {x} from 'y'` | `from y import x` |

---

## 🎓 Key Python Concepts Used

### 1. Type Hints

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

### 2. Async/Await

```python
async def fetch_data(url: str):
    result = await some_async_function()
    return result
```

### 3. Dictionaries (Objects)

```python
user = {"name": "Alice", "age": 30}
print(user["name"])  # Access with brackets
```

### 4. Lists (Arrays)

```python
numbers = [1, 2, 3]
numbers.append(4)  # Like push
doubled = [n * 2 for n in numbers]  # Like map
```

### 5. F-Strings (Template Literals)

```python
name = "Alice"
message = f"Hello, {name}!"  # Like `Hello, ${name}!`
```

### 6. Context Managers

```python
with open("file.txt", "r") as f:
    content = f.read()
# File auto-closes here!
```

---

## 🔧 Common Commands

### Install Package

```bash
pip install package-name
```

### Install All Dependencies

```bash
pip install -r requirements.txt
```

### Run Server

```bash
python run.py
```

### Run with Auto-Reload

```bash
uvicorn main:app --reload --port 8000
```

### Test Endpoint

```bash
curl -X POST http://localhost:8000/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_url": "https://example.com/video.mp4"}'
```

---

## 🐛 Debugging

### 1. Print Debugging

```python
print("Debug:", variable)
print(f"Value: {variable}")

# Pretty print JSON
import json
print(json.dumps(data, indent=2))
```

### 2. Check API Docs

Visit `http://localhost:8000/docs` for interactive Swagger UI!

### 3. Check Logs

The server prints detailed logs to the console. Look for:
- Emoji indicators (🎤 = transcribing, 🔍 = identifying clips, etc.)
- Error messages with tracebacks
- Processing status updates

---

## 📖 Learning Resources

### Python Basics
- Official Tutorial: https://docs.python.org/3/tutorial/
- Real Python: https://realpython.com/

### FastAPI
- Official Docs: https://fastapi.tiangolo.com/
- Tutorial: https://fastapi.tiangolo.com/tutorial/

### Async Python
- AsyncIO Guide: https://docs.python.org/3/library/asyncio.html
- Real Python AsyncIO: https://realpython.com/async-io-python/

### LangGraph
- Official Docs: https://langchain-ai.github.io/langgraph/

---

## 🎯 Next Steps

1. ✅ Read `PYTHON_GUIDE.md` to learn Python basics
2. ✅ Read `CODE_EXPLANATION.md` for detailed architecture
3. ✅ Review `workflow/nodes.py` to understand processing steps
4. ✅ Experiment by modifying the AI prompt in `identify_clips_node`
5. ✅ Add print statements to see data flow
6. ✅ Test endpoints using `/docs` Swagger UI

---

## ❓ Common Questions

### Q: What's the difference between `main.py` and `run.py`?

- `main.py` - FastAPI application code
- `run.py` - Startup script that sets event loop policy for Windows

Always use `python run.py` to start the server!

### Q: Why do we need event loop policy on Windows?

Windows has 2 event loop types:
- `ProactorEventLoop` (default) - supports subprocess
- `SelectorEventLoop` - supports psycopg (PostgreSQL)

We use `SelectorEventLoop` + thread pool for subprocess compatibility.

### Q: What is LangGraph?

LangGraph is a state machine framework for AI workflows. It:
- Manages state across processing steps
- Saves state to database (checkpointing)
- Allows resuming workflows
- Makes complex AI pipelines easy to build

### Q: How do I modify the AI prompt?

Edit `workflow/nodes.py`, find the `identify_clips_node` function, and modify the `prompt` string!

### Q: How do I add a new endpoint?

Add a function in `main.py`:

```python
@app.post("/my-endpoint")
async def my_endpoint(request: MyRequest):
    # Your code here
    return {"status": "success"}
```

---

## 🎉 You're Ready!

You now have:
- ✅ A working Python video processing backend
- ✅ LangGraph workflow with AI
- ✅ Real-time progress streaming (SSE)
- ✅ Comprehensive documentation

**Next:** Start reading `PYTHON_GUIDE.md` to learn Python basics!

Happy coding! 🚀
