# Troubleshooting Installation

## Common Issues with `pip install -r requirements.txt`

### Issue 1: faster-whisper Installation Fails

**Symptoms:** Error installing `faster-whisper` or `ctranslate2`

**Solutions:**

#### Windows
```bash
# Install Visual C++ Build Tools first
# Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/

# Or try installing faster-whisper separately with pip upgrade
pip install --upgrade pip setuptools wheel
pip install faster-whisper
```

#### macOS
```bash
# Ensure Xcode command line tools are installed
xcode-select --install

# Install dependencies
pip install --upgrade pip setuptools wheel
pip install faster-whisper
```

#### Linux (Ubuntu/Debian)
```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-dev build-essential

# Install Python packages
pip install --upgrade pip setuptools wheel
pip install faster-whisper
```

### Issue 2: Version Conflicts

**Solution:** Install packages one by one
```bash
pip install fastapi
pip install "uvicorn[standard]"
pip install pydantic
pip install aiohttp
pip install faster-whisper
```

### Issue 3: Python Version Issues

**Requirements:** Python 3.9 or higher

Check your Python version:
```bash
python --version
```

If too old, install a newer Python version.

### Issue 4: Network/Proxy Issues

**Solution:** Use a different index or retry
```bash
pip install --index-url https://pypi.org/simple -r requirements.txt
```

## Alternative: Minimal Installation

If you still have issues, start with a minimal setup:

```bash
# Create minimal requirements
cat > requirements-minimal.txt << EOF
fastapi
uvicorn
pydantic
aiohttp
EOF

pip install -r requirements-minimal.txt

# Install faster-whisper later when needed
pip install faster-whisper
```

## Verify Installation

After successful installation, verify:

```bash
python -c "import fastapi; print('FastAPI:', fastapi.__version__)"
python -c "import faster_whisper; print('faster-whisper: OK')"
python -c "import aiohttp; print('aiohttp: OK')"
```

## Still Having Issues?

1. **Share the error message** - Copy the full error output
2. **Check your environment:**
   ```bash
   python --version
   pip --version
   which python
   which pip
   ```
3. **Try a fresh virtual environment:**
   ```bash
   deactivate  # if already in venv
   rm -rf venv
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
