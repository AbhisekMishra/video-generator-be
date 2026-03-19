"""Test workflow initialization with async connection pool."""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE any async operations on Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(f"Event loop policy set to: {asyncio.get_event_loop_policy().__class__.__name__}")

from dotenv import load_dotenv

load_dotenv()

async def test_workflow():
    from workflow.graph import get_workflow

    print("Testing workflow initialization...")
    workflow = await get_workflow()
    print("SUCCESS: Workflow initialized successfully!")
    print(f"Event loop policy: {asyncio.get_event_loop_policy().__class__.__name__}")

    # Test creating a config (this will trigger pool connection)
    config = {"configurable": {"thread_id": "test-123"}}
    print("SUCCESS: Config created successfully!")

    return workflow

if __name__ == "__main__":
    asyncio.run(test_workflow())
