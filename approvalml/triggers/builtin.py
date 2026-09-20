"""Built-in trigger adapters: cron, one_time, webhook.

Validation rules ported from TriggerConfig.validate_trigger_type_requirements
in parser.py so the parser can delegate per-type checks instead of
hardcoding them.
"""

from .base import TriggerAdapter, TriggerValidationIssue, default_registry

# Config fields any tenant may override per subscription (schedule computation
# itself is caller-side; the adapter only declares the field as tunable).
_COMMON_TUNABLES = frozenset({
    "max_runs",
    "allow_concurrent",
    "requestor_email",
    "requestor_company_role",
    "preset_form_data",
    "data_condition",
})

# Config keys recognized per trigger type. Validators warn on any other key.
# Mirrors the historical allowlist of the SaaS yaml validator (which was a
# single global set, so e.g. `requestor_email` is deliberately NOT listed and
# keeps producing an "unrecognized field" warning there).
_COMMON_KNOWN_FIELDS = frozenset({
    "type",
    "max_runs",
    "allow_concurrent",
    "preset_form_data",
    "requestor_id",
    "requestor_company_role",
    "data_condition",
})


def _check_max_runs(config: dict, issues: list[TriggerValidationIssue]) -> list[TriggerValidationIssue]:
    max_runs = config.get("max_runs")
    if max_runs is not None and max_runs < 1:
        issues.append(TriggerValidationIssue(
            severity="error",
            message="max_runs must be at least 1",
            field="max_runs",
        ))
    return issues


class CronAdapter(TriggerAdapter):
    """Recurring cron schedule (requires 'schedule')."""
    trigger_type = "cron"
    tunable_fields = _COMMON_TUNABLES | frozenset({"schedule"})
    known_fields = _COMMON_KNOWN_FIELDS | frozenset({"schedule"})
    is_schedulable = True

    @classmethod
    def validate(cls, config: dict) -> list[TriggerValidationIssue]:
        issues: list[TriggerValidationIssue] = []
        if not config.get("schedule"):
            issues.append(TriggerValidationIssue(
                severity="error",
                message="Cron triggers must have a 'schedule' field with a valid cron expression",
                field="schedule",
            ))
        return _check_max_runs(config, issues)


class OneTimeAdapter(TriggerAdapter):
    """Single execution at a scheduled time (requires 'schedule')."""
    trigger_type = "one_time"
    tunable_fields = _COMMON_TUNABLES | frozenset({"schedule"})
    known_fields = _COMMON_KNOWN_FIELDS | frozenset({"schedule"})
    is_schedulable = True

    @classmethod
    def validate(cls, config: dict) -> list[TriggerValidationIssue]:
        issues: list[TriggerValidationIssue] = []
        if not config.get("schedule"):
            issues.append(TriggerValidationIssue(
                severity="error",
                message="One-time triggers must have a 'schedule' field with a datetime or cron expression",
                field="schedule",
            ))
        return _check_max_runs(config, issues)


class WebhookAdapter(TriggerAdapter):
    """External HTTP POST trigger (app generates the webhook token)."""
    trigger_type = "webhook"
    tunable_fields = frozenset(_COMMON_TUNABLES)
    # `schedule` is listed so a webhook carrying one gets the dedicated
    # "should not have a schedule" issue rather than a spurious unknown-field
    # warning on top of it.
    known_fields = _COMMON_KNOWN_FIELDS | frozenset({"schedule"})
    is_schedulable = False
    generates_webhook_token = True

    @classmethod
    def validate(cls, config: dict) -> list[TriggerValidationIssue]:
        issues: list[TriggerValidationIssue] = []
        if config.get("schedule"):
            issues.append(TriggerValidationIssue(
                severity="error",
                message="Webhook triggers should not have a 'schedule' field",
                field="schedule",
            ))
        return _check_max_runs(config, issues)


def register_builtin_adapters(registry=default_registry) -> None:
    """Register the three built-in adapters into a registry (idempotent)."""
    registry.register(CronAdapter, override=True)
    registry.register(OneTimeAdapter, override=True)
    registry.register(WebhookAdapter, override=True)


register_builtin_adapters()
