#!/usr/bin/env python3
"""
Startup script for the Video Generator FastAPI backend.

This script ensures the correct event loop policy is set before uvicorn starts,
which is critical for Windows compatibility with psycopg async connections.
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE importing uvicorn or any async code
if sys.platform == 'win32':
    print("Windows detected - setting WindowsSelectorEventLoopPolicy")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
else:
    print(f"Platform: {sys.platform} - using default event loop policy")

# Now we can safely import and run uvicorn
import uvicorn

if __name__ == "__main__":
    print("Starting Video Generator Worker API...")
    print(f"Event loop policy: {asyncio.get_event_loop_policy().__class__.__name__}")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        loop="none",
        log_level="info"
    )
