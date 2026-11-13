"""Hermes registration. Import and registration do not access health data."""

from .client import HealthTools


def register(ctx):
    tools = HealthTools(ctx)
    ctx.register_tool(
        name="apple_health_analyzer_status",
        toolset="apple_health_analyzer",
        schema={
            "name": "apple_health_analyzer_status",
            "description": (
                "Check Health Data AI Analyzer readiness on this Mac after user opt-in. "
                "Returns app identity/version and dataset readiness only. Never enables the "
                "app API, imports files, or reads credentials from disk."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        handler=tools.status,
    )
    ctx.register_tool(
        name="apple_health_analyzer_daily_metrics",
        toolset="apple_health_analyzer",
        schema={
            "name": "apple_health_analyzer_daily_metrics",
            "description": (
                "Read selected numeric daily metrics for one explicit date from the user's "
                "selected Mac integration dataset. Use only when the user requests these "
                "metrics and understands results may reach their model provider. Ask for "
                "the date or metric selection if unclear. Missing values are unknown, not zero. "
                "Show the returned date and units; these are recorded summaries, not live "
                "HealthKit readings or medical advice. Never diagnose or recommend treatment. "
                "A mismatched date is withheld. Do not ask for or put tokens in tool arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Exact dataset calendar date, YYYY-MM-DD"},
                    "metrics": {
                        "type": "array", "minItems": 1, "maxItems": 5, "uniqueItems": True,
                        "items": {"type": "string", "enum": ["steps", "sleep", "workouts", "heart_rate", "hrv"]},
                        "description": "Only the metric groups the user requested; no default full-health export.",
                    },
                },
                "required": ["date", "metrics"],
                "additionalProperties": False,
            },
        },
        handler=tools.daily_metrics,
    )
