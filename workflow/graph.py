"""
LangGraph Workflow Definition

Defines the video processing workflow as a state graph with PostgreSQL checkpointing.
"""

import os
from typing import Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from workflow.state import VideoProcessingState
from utils.model_selector import ensure_tables
from workflow.nodes import (
    transcribe_node,
    identify_clips_node,
    generate_captions_node,
    render_node
)


# Singleton instances for pool and checkpointer
_pool_instance: Optional[AsyncConnectionPool] = None
_checkpointer_instance: Optional[AsyncPostgresSaver] = None


async def get_checkpointer() -> AsyncPostgresSaver:
    """
    Create async PostgreSQL checkpointer for workflow persistence (singleton pattern).

    This allows the workflow to resume from any point if it fails or is interrupted.
    """
    global _pool_instance, _checkpointer_instance

    if _checkpointer_instance is not None:
        return _checkpointer_instance

    connection_string = os.getenv("DATABASE_URL")

    if not connection_string:
        raise ValueError("DATABASE_URL environment variable not set")

    # Create async connection pool (singleton)
    _pool_instance = AsyncConnectionPool(
        conninfo=connection_string,
        max_size=3,
        min_size=1,
        open=False,  # Don't open in constructor (avoid deprecation warning)
        timeout=60,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "connect_timeout": 30,
        },
    )

    # Open the pool explicitly
    await _pool_instance.open()

    # Create async checkpointer
    _checkpointer_instance = AsyncPostgresSaver(_pool_instance)

    # Setup LangGraph checkpoint tables
    await _checkpointer_instance.setup()

    # Setup model_usage and sessions tables
    await ensure_tables(_pool_instance)

    return _checkpointer_instance


async def get_pool() -> AsyncConnectionPool:
    """Return the shared connection pool (initializes it if needed)."""
    await get_checkpointer()
    return _pool_instance


async def create_workflow() -> StateGraph:
    """
    Create the video processing workflow graph.

    Workflow stages:
    1. Transcribe: Extract audio and generate word-level transcription
    2. IdentifyClips: Use LLM to identify best short-form clips
    3. GenerateCaptions: Create ASS subtitle files for each clip
    4. Render: Render final videos with burned-in captions

    Returns:
        Compiled LangGraph workflow with checkpointing
    """

    # Define the workflow
    workflow = StateGraph(VideoProcessingState)

    # Add nodes
    workflow.add_node("transcribe", transcribe_node)
    workflow.add_node("identifyClips", identify_clips_node)
    workflow.add_node("generateCaptions", generate_captions_node)
    workflow.add_node("render", render_node)

    # Define edges (workflow path)
    workflow.set_entry_point("transcribe")
    workflow.add_edge("transcribe", "identifyClips")
    workflow.add_edge("identifyClips", "generateCaptions")
    workflow.add_edge("generateCaptions", "render")
    workflow.add_edge("render", END)

    # Compile with async checkpointing
    checkpointer = await get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)


# Singleton instance (lazy initialization)
_graph_instance: Optional[StateGraph] = None


async def get_workflow() -> StateGraph:
    """
    Get or create the workflow instance (singleton pattern).

    Returns:
        The compiled LangGraph workflow
    """
    global _graph_instance

    if _graph_instance is None:
        print("Initializing video processing workflow...")
        _graph_instance = await create_workflow()
        print("Workflow initialized successfully")

    return _graph_instance


async def cleanup_connections():
    """
    Cleanup database connections and pools.

    Should be called on application shutdown.
    """
    global _pool_instance, _checkpointer_instance, _graph_instance

    if _pool_instance is not None:
        try:
            await _pool_instance.close()
            print("Database connection pool closed")
        except Exception as e:
            print(f"Error closing connection pool: {e}")

    _pool_instance = None
    _checkpointer_instance = None
    _graph_instance = None
