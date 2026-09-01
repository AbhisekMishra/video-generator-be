"""
Quota enforcement helpers — called from the /process-video endpoint.
Uses the service-role Supabase client so it can bypass RLS.

Quota itself (checking and incrementing attempts_used) is enforced entirely by the
frontend (it owns the atomic increment RPC and the user-facing upgrade flow). This
module only verifies session ownership before the backend does any work for it.
"""
from utils.supabase_client import supabase
from fastapi import HTTPException


def verify_session_owner(session_id: str, user_id: str) -> None:
    """Raise 403 if the session does not belong to user_id."""
    result = (
        supabase.table("sessions")
        .select("user_id")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Session not found")
    if result.data["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Session does not belong to user")
