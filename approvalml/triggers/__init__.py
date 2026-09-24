"""Pluggable trigger adapter registry.

The parser delegates per-trigger-type validation and runtime-state
initialization to registered adapters, so new input mechanisms can be
added without touching the parser. The built-in adapters (cron,
one_time, webhook) are registered into default_registry at import time;
the SaaS app registers its own adapters (e.g. asset_expiry) additionally.
"""

from .base import (
    TriggerAdapter,
    TriggerRegistry,
    TriggerValidationIssue,
    UnknownTriggerTypeError,
    default_registry,
)
from .builtin import (
    CronAdapter,
    OneTimeAdapter,
    WebhookAdapter,
    register_builtin_adapters,
)

__all__ = [
    "TriggerAdapter",
    "TriggerRegistry",
    "TriggerValidationIssue",
    "UnknownTriggerTypeError",
    "default_registry",
    "CronAdapter",
    "OneTimeAdapter",
    "WebhookAdapter",
    "register_builtin_adapters",
]
