"""
Deterministic SHA-256 hash chaining for tamper-evident audit log entries.

Shared primitive: callers supply their own field dict and hash scope
(per-instance for the SaaS backend, a single global chain for the
standalone runtime — see runtime/postgres_store.py). The canonical input
is a UTF-8-encoded JSON object with sorted keys, followed by ':' and the
prev_hash value (or the literal string "null" for the first entry in a
chain).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def serialize_value(v: Any) -> Any:
    """Convert a field value to a JSON-serializable form."""
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def compute_entry_hash(fields: Dict[str, Any], prev_hash: Optional[str]) -> str:
    """
    Return the SHA-256 hex digest for one audit log entry.

    `fields` must contain exactly the values that will be stored in the DB
    for this entry (excluding the auto-assigned id and the hash columns
    themselves). Call this after all other field values are final but
    before the INSERT.
    """
    canonical_json = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    prev_part = prev_hash if prev_hash is not None else "null"
    raw = f"{canonical_json}:{prev_part}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_chain(entries: List[Any], field_names: List[str]) -> Tuple[bool, List[str]]:
    """
    Verify the hash chain for a list of audit log entries ordered by id ASC.

    `field_names` lists the keys (in any order — hashing sorts them) that
    were passed to `compute_entry_hash` for each entry, e.g.
    ["entity_type", "entity_id", "event_type", "event_data", "actor", "created_at"].
    Each entry may be a dict or an object with matching attributes.
    Entries with entry_hash=None are treated as pre-immutability rows:
    reported as INFO but do not fail validation.

    Returns (is_valid, list_of_messages).
    """
    errors: List[str] = []
    last_hash: Optional[str] = None
    skipped = 0

    for entry in entries:
        def g(attr):
            return entry[attr] if isinstance(entry, dict) else getattr(entry, attr)

        entry_hash = g("entry_hash")
        prev_hash = g("prev_hash")
        entry_id = g("id")

        if entry_hash is None:
            skipped += 1
            continue

        fields = {}
        for name in field_names:
            value = g(name)
            if name == "event_data" and isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    value = {}
            fields[name] = serialize_value(value)

        recomputed = compute_entry_hash(fields, prev_hash)

        if recomputed != entry_hash:
            errors.append(
                f"Row id={entry_id}: entry_hash mismatch "
                f"(stored={entry_hash!r}, recomputed={recomputed!r})"
            )

        if last_hash is not None and prev_hash != last_hash:
            errors.append(
                f"Row id={entry_id}: chain break "
                f"(expected prev_hash={last_hash!r}, stored={prev_hash!r})"
            )
        elif last_hash is None and prev_hash is not None:
            errors.append(
                f"Row id={entry_id}: first hashed entry has non-null "
                f"prev_hash={prev_hash!r}"
            )

        last_hash = entry_hash

    if skipped:
        errors.insert(
            0,
            f"INFO: {skipped} pre-immutability row(s) with NULL entry_hash skipped.",
        )

    is_valid = not any(e for e in errors if not e.startswith("INFO:"))
    return is_valid, errors
