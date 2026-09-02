FROM python:3.11.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# yt-dlp ships fixes for YouTube's bot-detection/extractor changes to its nightly
# channel first, often days before they reach a stable release. Upgrade it alone via
# --pre (not a blanket --pre on the whole requirements.txt, which would also opt every
# other dependency into pre-releases) so every image build has the latest fixes.
RUN pip install --no-cache-dir --pre --upgrade yt-dlp

COPY . .

EXPOSE 8000

CMD ["python", "run.py"]
