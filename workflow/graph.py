from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from workflow.state import VideoProcessingState
from utils.logger import get_logger
logger = get_logger(__name__)
from workflow.nodes import (
    transcribe_node,
    identify_clips_node,
    generate_captions_node,
    render_node
)


async def get_pool():
    return None


_graph_instance = None
_checkpointer = MemorySaver()


async def create_workflow() -> StateGraph:
    workflow = StateGraph(VideoProcessingState)

    workflow.add_node("transcribe", transcribe_node)
    workflow.add_node("identifyClips", identify_clips_node)
    workflow.add_node("generateCaptions", generate_captions_node)
    workflow.add_node("render", render_node)

    workflow.set_entry_point("transcribe")
    workflow.add_edge("transcribe", "identifyClips")
    workflow.add_edge("identifyClips", "generateCaptions")
    workflow.add_edge("generateCaptions", "render")
    workflow.add_edge("render", END)

    return workflow.compile(checkpointer=_checkpointer)


async def get_workflow() -> StateGraph:
    global _graph_instance
    if _graph_instance is None:
        logger.info("Initializing video processing workflow...")
        _graph_instance = await create_workflow()
        logger.info("Workflow initialized successfully")
    return _graph_instance


def reset_thread(session_id: str) -> None:
    """Delete the in-memory checkpoint for a session so the next ainvoke starts clean."""
    thread_id = session_id
    storage = _checkpointer.storage
    keys_to_delete = [k for k in storage if (k[0] if isinstance(k, tuple) else k) == thread_id]
    for k in keys_to_delete:
        del storage[k]
    logger.info(f"🗑️  Cleared checkpoint for thread {thread_id}")


async def cleanup_connections():
    global _graph_instance
    _graph_instance = None
