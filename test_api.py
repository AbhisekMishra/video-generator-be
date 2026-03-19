#!/usr/bin/env python3
"""
Quick test script for the Video Generator API
"""
import requests
import sys
import json


API_URL = "http://localhost:8000"


def test_health():
    """Test API health endpoint"""
    print("Testing API health...")
    response = requests.get(f"{API_URL}/")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()


def test_transcribe(video_path):
    """Test transcription endpoint"""
    print(f"Testing transcription with: {video_path}")
    response = requests.post(
        f"{API_URL}/process",
        json={
            "task": "transcribe",
            "video_path": video_path
        }
    )

    if response.status_code == 200:
        result = response.json()
        print(f"✓ Transcription successful!")
        print(f"Text: {result['text'][:100]}...")
        print(f"Words: {len(result['words'])} words detected")
        print(f"Language: {result.get('language', 'N/A')}")
    else:
        print(f"✗ Transcription failed: {response.status_code}")
        print(response.text)
    print()


def test_render(video_path):
    """Test rendering endpoint"""
    print(f"Testing rendering with: {video_path}")
    response = requests.post(
        f"{API_URL}/process",
        json={
            "task": "render",
            "video_path": video_path,
            "center_x": 960,
            "start": 0,
            "end": 5  # Just 5 seconds for quick test
        }
    )

    if response.status_code == 200:
        result = response.json()
        print(f"✓ Rendering successful!")
        print(f"Output: {result['output_path']}")
        print(f"Duration: {result['duration']}s")
    else:
        print(f"✗ Rendering failed: {response.status_code}")
        print(response.text)
    print()


if __name__ == "__main__":
    print("=" * 50)
    print("Video Generator API Test")
    print("=" * 50)
    print()

    # Test health endpoint
    try:
        test_health()
    except Exception as e:
        print(f"✗ API not reachable: {e}")
        print("Make sure the server is running: python main.py")
        sys.exit(1)

    # Test with video file if provided
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        print(f"Using video: {video_path}")
        print()

        test_transcribe(video_path)
        test_render(video_path)
    else:
        print("Usage: python test_api.py <video_path>")
        print("Example: python test_api.py /path/to/video.mp4")
