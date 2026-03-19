#!/usr/bin/env python3
"""
Production startup script (no reload) for the Video Generator FastAPI backend.

This ensures the correct event loop policy is set on Windows.
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE any other imports
if sys.platform == 'win32':
    print("Windows detected - setting WindowsSelectorEventLoopPolicy")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(f"Event loop policy set to: {asyncio.get_event_loop_policy().__class__.__name__}")
else:
    print(f"Platform: {sys.platform} - using default event loop policy")

if __name__ == "__main__":
    # Import uvicorn AFTER setting the policy
    import uvicorn

    print("Starting Video Generator Worker API (no reload)...")

    # Start without reload to test basic functionality
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        loop="none",
        log_level="info"
    )
