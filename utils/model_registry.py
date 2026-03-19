"""
Model Registry — Curated list of GitHub Models API models by tier.

Tier priority for selection: low -> high -> special
"""

MODEL_REGISTRY = [
    # LOW TIER — 15 rpm / 150 rpd
    {"name": "gpt-4o-mini",                     "tier": "low",     "rpm_limit": 15, "rpd_limit": 150},
    {"name": "Phi-4-mini-instruct",              "tier": "low",     "rpm_limit": 15, "rpd_limit": 150},
    {"name": "Phi-4",                            "tier": "low",     "rpm_limit": 15, "rpd_limit": 150},
    {"name": "Meta-Llama-3.1-8B-Instruct",       "tier": "low",     "rpm_limit": 15, "rpd_limit": 150},
    {"name": "open-mistral-nemo",                "tier": "low",     "rpm_limit": 15, "rpd_limit": 150},

    # HIGH TIER — 10 rpm / 50 rpd
    {"name": "gpt-4o",                           "tier": "high",    "rpm_limit": 10, "rpd_limit": 50},
    {"name": "Llama-4-Scout-17B-16E-Instruct",   "tier": "high",    "rpm_limit": 10, "rpd_limit": 50},
    {"name": "Meta-Llama-3.1-70B-Instruct",      "tier": "high",    "rpm_limit": 10, "rpd_limit": 50},
    {"name": "Mistral-Large-2411",               "tier": "high",    "rpm_limit": 10, "rpd_limit": 50},

    # SPECIAL TIER — lower limits
    {"name": "DeepSeek-R1",                      "tier": "special", "rpm_limit": 1,  "rpd_limit": 8},
    {"name": "grok-3-mini",                      "tier": "special", "rpm_limit": 2,  "rpd_limit": 30},
]

TIER_ORDER = ["low", "high", "special"]
