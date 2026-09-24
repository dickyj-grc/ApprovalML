"""
Trigger adapter protocol and registry.

A trigger adapter decouples the ApprovalML parser from specific input
mechanisms (cron tick, HTTP webhook, external sweeps, ...). Each adapter
declares its trigger type key, which config fields a tenant may tune per
subscription, per-type validation rules, and how to build the initial
runtime-state entry. Everything here is synchronous and stdlib-only.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Optional


@dataclass
class TriggerValidationIssue:
    """A single validation finding from a trigger adapter.

    Dependency-free counterpart of the app's ValidationIssue — the app
    layer adapts these into its own type.
    """
    severity: str          # "error" or "warning"
    message: str
    field: Optional[str] = None
    suggestion: Optional[str] = None


class UnknownTriggerTypeError(Exception):
    """Raised when no adapter is registered for a trigger type."""

    def __init__(self, trigger_type: str):
        self.trigger_type = trigger_type
        super().__init__(f"No trigger adapter registered for type '{trigger_type}'")


class TriggerAdapter:
    """Base class for trigger adapters.

    Subclasses set the class attributes and override validate() /
    initialize() as needed. All behavior is class-level; adapters are
    never instantiated.
    """

    trigger_type: ClassVar[str] = ""                                    # registry key (YAML `type:`)
    tunable_fields: ClassVar[frozenset[str]] = frozenset()              # per-subscription tenant overrides
    known_fields: ClassVar[frozenset[str]] = frozenset()                # config keys recognized for this type (unknown → warning)
    is_schedulable: ClassVar[bool] = False                              # ticked via next_run_at (cron/one_time)
    is_external_engine: ClassVar[bool] = False                          # fired by an outside engine (sweep), not the tick loop
    generates_webhook_token: ClassVar[bool] = False                     # app fills webhook_token after initialize()
    supports_subscriptions: ClassVar[bool] = False                      # per-tenant workflow_trigger_subscriptions allowed

    @classmethod
    def validate(cls, config: dict) -> list[TriggerValidationIssue]:
        """Validate a trigger config dict. Returns issues (empty = valid)."""
        return []

    @classmethod
    def initialize(cls, config: dict, requestor_default: Any = None) -> dict[str, Any]:
        """Build the initial runtime-state entry for this trigger.

        Produces the same field shape SchedulerService.initialize_triggers
        builds for each trigger. The caller sets trigger_index and computes
        next_run_at (schedule computation is caller/app-side — this package
        stays free of croniter and token generation).
        """
        return {
            "trigger_type": cls.trigger_type,
            "schedule": config.get("schedule"),
            "webhook_token": None,
            "next_run_at": None,
            "last_run_at": None,
            "is_paused": False,
            "run_count": 0,
            "max_runs": config.get("max_runs"),
            "preset_form_data": config.get("preset_form_data"),
            "requestor_email": config.get("requestor_email"),
            "requestor_company_role": config.get("requestor_company_role"),
            # Only store the fallback requestor_id when the YAML doesn't specify
            # a named requestor — otherwise it takes priority in _resolve_requestor
            # and the explicit requestor_company_role / requestor_email is ignored.
            "requestor_id": None if (config.get("requestor_company_role") or config.get("requestor_email")) else requestor_default,
            "data_condition": config.get("data_condition"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class TriggerRegistry:
    """Registry mapping trigger type keys to adapter classes."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[TriggerAdapter]] = {}

    def register(self, adapter_class: type[TriggerAdapter], *, override: bool = False) -> None:
        """Register an adapter class under its trigger_type key."""
        key = adapter_class.trigger_type
        if not key:
            raise ValueError("TriggerAdapter subclass must define a non-empty trigger_type")
        if key in self._adapters and not override:
            raise ValueError(f"Trigger adapter already registered for type '{key}'")
        self._adapters[key] = adapter_class

    def get(self, trigger_type: str) -> type[TriggerAdapter]:
        """Look up the adapter for a trigger type.

        Raises UnknownTriggerTypeError for unregistered types — unknown
        types must fail loudly, never be silently accepted.
        """
        try:
            return self._adapters[trigger_type]
        except KeyError:
            raise UnknownTriggerTypeError(trigger_type) from None

    def list_types(self) -> list[str]:
        """Return the registered trigger type keys, sorted."""
        return sorted(self._adapters)

    def is_registered(self, trigger_type: str) -> bool:
        """Return True if an adapter is registered for the type."""
        return trigger_type in self._adapters

    def unregister(self, trigger_type: str) -> bool:
        """Remove an adapter from the registry. Returns True if one was removed."""
        return self._adapters.pop(trigger_type, None) is not None


default_registry = TriggerRegistry()
