from langgraph.graph import StateGraph, END

from workflow.state import VideoProcessingState
from workflow.nodes import (
    transcribe_node,
    identify_clips_node,
    generate_captions_node,
    render_node
)


async def get_pool():
    return None


_graph_instance = None


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

    return workflow.compile()


async def get_workflow() -> StateGraph:
    global _graph_instance
    if _graph_instance is None:
        print("Initializing video processing workflow...")
        _graph_instance = await create_workflow()
        print("Workflow initialized successfully")
    return _graph_instance


async def cleanup_connections():
    global _graph_instance
    _graph_instance = None
