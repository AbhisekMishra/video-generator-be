"""
Model Selector — Tiered model selection with in-memory usage tracking.

Selection order: low -> high -> special
Both RPM (per minute) and RPD (per day) windows are enforced.
Windows reset lazily on each read.
"""

import asyncio
from datetime import datetime, timezone
from utils.model_registry import MODEL_REGISTRY, TIER_ORDER


class ModelQuotaExhaustedError(Exception):
    """Raised when all model quotas across all tiers are exhausted."""
    pass


# In-memory usage store: model_name -> usage dict
_usage: dict = {}
_lock = asyncio.Lock()


def _init_usage():
    """Populate _usage from MODEL_REGISTRY if not already done."""
    for model in MODEL_REGISTRY:
        name = model["name"]
        if name not in _usage:
            now = datetime.now(timezone.utc)
            _usage[name] = {
                "tier": model["tier"],
                "rpm_limit": model["rpm_limit"],
                "rpd_limit": model["rpd_limit"],
                "rpm_used": 0,
                "rpd_used": 0,
                "rpm_window_start": now,
                "rpd_window_start": now,
            }
    # Remove models no longer in registry
    active = {m["name"] for m in MODEL_REGISTRY}
    for name in list(_usage.keys()):
        if name not in active:
            del _usage[name]


async def ensure_tables(pool=None) -> None:
    """No-op: in-memory store needs no setup."""
    _init_usage()
    print("✅ model_usage ready (in-memory)")


async def select_model(pool=None, excluded: set[str] | None = None) -> str:
    """
    Select an available model following tier priority: low -> high -> special.
    Lazily resets expired RPM / RPD windows, then increments usage atomically.
    """
    excluded = excluded or set()

    async with _lock:
        _init_usage()
        now = datetime.now(timezone.utc)

        for tier in TIER_ORDER:
            tier_models = [
                (name, data) for name, data in _usage.items()
                if data["tier"] == tier and name not in excluded
            ]
            # Prefer least-used models
            tier_models.sort(key=lambda x: (x[1]["rpd_used"], x[1]["rpm_used"]))

            for name, data in tier_models:
                # Lazily reset RPM window
                if (now - data["rpm_window_start"]).total_seconds() >= 60:
                    data["rpm_used"] = 0
                    data["rpm_window_start"] = now

                # Lazily reset RPD window
                if data["rpd_window_start"].date() < now.date():
                    data["rpd_used"] = 0
                    data["rpd_window_start"] = now

                if data["rpm_used"] < data["rpm_limit"] and data["rpd_used"] < data["rpd_limit"]:
                    data["rpm_used"] += 1
                    data["rpd_used"] += 1
                    print(f"🤖 Selected model: {name} (tier={tier}, "
                          f"rpm={data['rpm_used']}/{data['rpm_limit']}, "
                          f"rpd={data['rpd_used']}/{data['rpd_limit']})")
                    return name

            print(f"⚠️ {tier.capitalize()} tier exhausted, trying next tier...")

    raise ModelQuotaExhaustedError(
        "All model quotas exhausted across low, high, and special tiers. "
        "Please wait for rate limit windows to reset."
    )


async def exhaust_model(pool=None, model_name: str = "") -> None:
    """Mark a model as fully exhausted for the day."""
    async with _lock:
        _init_usage()
        if model_name in _usage:
            _usage[model_name]["rpd_used"] = _usage[model_name]["rpd_limit"]
    print(f"🚫 Model '{model_name}' marked as exhausted (will not be selected again today)")
