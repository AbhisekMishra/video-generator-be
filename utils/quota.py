"""
Quota enforcement helpers — called from the /process-video endpoint.
Uses the service-role Supabase client so it can bypass RLS.
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


def check_and_increment_quota(user_id: str) -> None:
    """
    Atomically check and increment the user's quota.
    Raises 402 if the quota is exceeded.
    """
    try:
        supabase.rpc("increment_user_attempts", {"p_user_id": user_id}).execute()
    except Exception as e:
        msg = str(e).lower()
        if "quota exceeded" in msg:
            # Fetch current limits for a helpful error message
            quota_result = (
                supabase.table("user_quotas")
                .select("attempts_limit, plan_tier")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            limit = quota_result.data.get("attempts_limit", 3) if quota_result.data else 3
            raise HTTPException(
                status_code=402,
                detail=f"You have used all {limit} attempts. Upgrade your plan to continue.",
            )
        raise HTTPException(status_code=500, detail=f"Quota check failed: {e}")
