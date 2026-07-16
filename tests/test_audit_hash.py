"""
Unit tests for the shared audit-hash primitive (approvalml.audit_hash).

Pure logic, no DB — mirrors the offline style of test_runtime.py. These
tests cover the generalized fields-dict API used by both the SaaS
audit_hash.py wrapper and the standalone runtime's PostgresStore.
"""

from datetime import datetime, timezone

from approvalml.audit_hash import compute_entry_hash, verify_chain

_CREATED_AT = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def _fields(**overrides):
    base = {
        "entity_type": "gate",
        "entity_id": "11111111-1111-1111-1111-111111111111",
        "event_type": "created",
        "event_data": {"description": "test gate"},
        "actor": None,
        "created_at": _CREATED_AT.isoformat(),
    }
    base.update(overrides)
    return base


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Deterministic hashing]]
def test_compute_entry_hash_is_deterministic():
    """Calling compute_entry_hash twice with identical fields yields identical hashes."""
    h1 = compute_entry_hash(_fields(), None)
    h2 = compute_entry_hash(_fields(), None)
    assert h1 == h2
    assert len(h1) == 64


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Deterministic hashing]]
def test_compute_entry_hash_sensitive_to_field_changes():
    """Changing any single field value must change the resulting hash."""
    base_hash = compute_entry_hash(_fields(), None)
    for override in [
        {"event_type": "approved"},
        {"event_data": {"description": "different"}},
        {"actor": "alice@example.com"},
        {"entity_id": "22222222-2222-2222-2222-222222222222"},
    ]:
        assert compute_entry_hash(_fields(**override), None) != base_hash


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Deterministic hashing]]
def test_compute_entry_hash_prev_hash_none_is_literal_null():
    """prev_hash=None is treated as the literal string 'null', matching the documented first-entry convention."""
    h_none = compute_entry_hash(_fields(), None)
    h_literal = compute_entry_hash(_fields(), "null")
    assert h_none == h_literal
    # ...but a real prior hash still produces a different digest than the sentinel.
    h_chained = compute_entry_hash(_fields(), "a" * 64)
    assert h_chained != h_none


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Deterministic hashing]]
def test_compute_entry_hash_key_order_independent():
    """Dict insertion order must not affect the hash — sort_keys makes this safe to refactor around."""
    fields_a = {"a": 1, "b": 2, "c": 3}
    fields_b = {"c": 3, "a": 1, "b": 2}
    assert compute_entry_hash(fields_a, "prev") == compute_entry_hash(fields_b, "prev")


def _field_names():
    return ["entity_type", "entity_id", "event_type", "event_data", "actor", "created_at"]


def _build_chain():
    f1 = _fields()
    h1 = compute_entry_hash(f1, None)
    f2 = _fields(entity_type="step", event_type="approved", event_data={"decision": "approve"})
    h2 = compute_entry_hash(f2, h1)
    entries = [
        {**f1, "id": 1, "prev_hash": None, "entry_hash": h1},
        {**f2, "id": 2, "prev_hash": h1, "entry_hash": h2},
    ]
    return entries


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Chain verification]]
def test_verify_chain_valid():
    """A correctly chained sequence of entries verifies as valid with no errors."""
    is_valid, messages = verify_chain(_build_chain(), _field_names())
    assert is_valid is True
    assert messages == []


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Chain verification]]
def test_verify_chain_detects_tampered_entry():
    """Mutating a stored field after the fact must break its recomputed hash."""
    entries = _build_chain()
    entries[1]["event_data"] = {"decision": "reject"}
    is_valid, messages = verify_chain(entries, _field_names())
    assert is_valid is False
    assert any("id=2" in m and "mismatch" in m for m in messages)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Chain verification]]
def test_verify_chain_detects_broken_link():
    """A prev_hash that doesn't match the previous entry's stored hash is a chain break."""
    entries = _build_chain()
    entries[1]["prev_hash"] = "0" * 64
    is_valid, messages = verify_chain(entries, _field_names())
    assert is_valid is False
    assert any("chain break" in m for m in messages)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Chain verification]]
def test_verify_chain_empty_list_is_valid():
    """An empty entry list is trivially valid with no errors."""
    is_valid, messages = verify_chain([], _field_names())
    assert is_valid is True
    assert messages == []
