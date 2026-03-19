"""
Model Selector — Tiered model selection with PostgreSQL usage tracking.

Selection order: low -> high -> special
Both RPM (per minute) and RPD (per day) windows are enforced.
Windows reset lazily on each read.
"""

from datetime import datetime, timezone
from psycopg_pool import AsyncConnectionPool

from utils.model_registry import MODEL_REGISTRY, TIER_ORDER


class ModelQuotaExhaustedError(Exception):
    """Raised when all model quotas across all tiers are exhausted."""
    pass


async def ensure_tables(pool: AsyncConnectionPool) -> None:
    """Create model_usage and sessions tables, upsert registry rows."""
    async with pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS model_usage (
                model_name      TEXT PRIMARY KEY,
                tier            TEXT NOT NULL,
                rpm_limit       INT  NOT NULL,
                rpd_limit       INT  NOT NULL,
                rpm_used        INT  NOT NULL DEFAULT 0,
                rpd_used        INT  NOT NULL DEFAULT 0,
                rpm_window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                rpd_window_start TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Upsert registry rows — update limits if changed, preserve usage counters
        for model in MODEL_REGISTRY:
            await conn.execute("""
                INSERT INTO model_usage
                    (model_name, tier, rpm_limit, rpd_limit, rpm_window_start, rpd_window_start)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (model_name) DO UPDATE SET
                    tier      = EXCLUDED.tier,
                    rpm_limit = EXCLUDED.rpm_limit,
                    rpd_limit = EXCLUDED.rpd_limit
            """, (model["name"], model["tier"], model["rpm_limit"], model["rpd_limit"]))

        # Remove any models that are no longer in the registry
        active_names = [m["name"] for m in MODEL_REGISTRY]
        await conn.execute(
            "DELETE FROM model_usage WHERE model_name <> ALL(%s)",
            (active_names,)
        )

    print("✅ model_usage table ready")


async def select_model(pool: AsyncConnectionPool, excluded: set[str] | None = None) -> str:
    """
    Select an available model following tier priority: low -> high -> special.

    Lazily resets expired RPM / RPD windows, then increments usage atomically
    using SELECT FOR UPDATE to prevent race conditions under concurrent requests.

    Args:
        excluded: Optional set of model names to skip (used for retry-with-next logic).

    Returns:
        The model name to use for the LLM call.

    Raises:
        ModelQuotaExhaustedError: If all models across all tiers are exhausted.
    """
    excluded = excluded or set()

    async with pool.connection() as conn:
        async with conn.transaction():
            now = datetime.now(timezone.utc)

            for tier in TIER_ORDER:
                rows = await conn.execute("""
                    SELECT model_name, rpm_limit, rpd_limit,
                           rpm_used, rpd_used,
                           rpm_window_start, rpd_window_start
                    FROM model_usage
                    WHERE tier = %s
                    ORDER BY rpd_used ASC, rpm_used ASC
                    FOR UPDATE
                """, (tier,))
                models = await rows.fetchall()

                for row in models:
                    (model_name, rpm_limit, rpd_limit,
                     rpm_used, rpd_used,
                     rpm_window_start, rpd_window_start) = row

                    if model_name in excluded:
                        continue

                    # Lazily reset RPM window if > 60 seconds have passed
                    if (now - rpm_window_start).total_seconds() >= 60:
                        rpm_used = 0
                        rpm_window_start = now

                    # Lazily reset RPD window if UTC day has rolled over
                    if rpd_window_start.date() < now.date():
                        rpd_used = 0
                        rpd_window_start = now

                    if rpm_used < rpm_limit and rpd_used < rpd_limit:
                        await conn.execute("""
                            UPDATE model_usage SET
                                rpm_used         = %s,
                                rpd_used         = %s,
                                rpm_window_start = %s,
                                rpd_window_start = %s
                            WHERE model_name = %s
                        """, (rpm_used + 1, rpd_used + 1,
                              rpm_window_start, rpd_window_start,
                              model_name))

                        print(f"🤖 Selected model: {model_name} (tier={tier}, "
                              f"rpm={rpm_used + 1}/{rpm_limit}, rpd={rpd_used + 1}/{rpd_limit})")
                        return model_name

                print(f"⚠️ {tier.capitalize()} tier exhausted, trying next tier...")

    raise ModelQuotaExhaustedError(
        "All model quotas exhausted across low, high, and special tiers. "
        "Please wait for rate limit windows to reset."
    )


async def exhaust_model(pool: AsyncConnectionPool, model_name: str) -> None:
    """Mark a model as fully exhausted for the day (e.g. after an unknown_model API error)."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE model_usage SET rpd_used = rpd_limit WHERE model_name = %s",
            (model_name,)
        )
    print(f"🚫 Model '{model_name}' marked as exhausted (will not be selected again today)")


