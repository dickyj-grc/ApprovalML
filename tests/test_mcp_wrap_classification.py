"""
Unit tests for tool classification in the per-server MCP wrapper (mcp_wrap.py).

Pure logic, no DB, no subprocess — mirrors the offline style of test_runtime.py.
"""

from approvalml.mcp_wrap import classify_tool, classify_tool_zero_config, _normalize_guards_config

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Zero-config classification]]
def test_zero_config_agreement_passes_read_only():
    """A read-only-annotated tool with a matching safe name prefix auto-passes."""
    tool = {"name": "get_status", "annotations": {"readOnlyHint": True}}
    assert classify_tool_zero_config(tool) == "auto"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Zero-config classification]]
def test_zero_config_ambiguity_pends_no_signals():
    """A tool with no annotations and an unrecognized name prefix defaults to gate."""
    tool = {"name": "frobnicate"}
    assert classify_tool_zero_config(tool) == "gate"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Zero-config classification]]
def test_zero_config_ambiguity_pends_conflicting_signals():
    """Conflicting signals (safe name, unsafe annotation) default to gate, not auto."""
    tool = {"name": "get_status", "annotations": {"readOnlyHint": False, "destructiveHint": True}}
    assert classify_tool_zero_config(tool) == "gate"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Zero-config classification]]
def test_zero_config_sensitive_name_gates_even_without_annotations():
    """A sensitive-prefixed tool name gates even with no annotation signal at all."""
    tool = {"name": "delete_repository"}
    assert classify_tool_zero_config(tool) == "gate"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Zero-config classification]]
def test_zero_config_name_only_safe_prefix_passes():
    """A safe-prefixed name with no annotations at all (common case) still auto-passes."""
    tool = {"name": "list_files"}
    assert classify_tool_zero_config(tool) == "auto"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Classification config]]
def test_classify_tool_uses_config_rules_first_match_wins():
    """rules: are evaluated in order; the first fnmatch hit determines the action."""
    config = {
        "rules": [
            {"match": "get_*", "action": "auto"},
            {"match": "merge_pull_request", "action": "workflow", "workflow": "github_merge_guard"},
        ],
        "default_action": "gate",
    }
    assert classify_tool({"name": "get_status"}, config) == ("auto", None)
    assert classify_tool({"name": "merge_pull_request"}, config) == ("workflow", "github_merge_guard")


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Classification config]]
def test_classify_tool_falls_back_to_default_action():
    """A tool matching no rule falls back to default_action."""
    config = {"rules": [{"match": "get_*", "action": "auto"}], "default_action": "deny"}
    assert classify_tool({"name": "delete_file"}, config) == ("deny", None)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Classification config]]
def test_classify_tool_no_config_uses_zero_config_heuristic():
    """With no config at all, classification falls back entirely to the zero-config heuristic."""
    assert classify_tool({"name": "get_status"}, None) == ("auto", None)
    assert classify_tool({"name": "delete_file"}, None) == ("gate", None)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_normalize_guards_config_maps_tools_to_rules():
    """guards.tools entries become synthetic rules, first-match-wins like rules:."""
    raw = {
        "name": "GitHub MCP Guard",
        "guards": {"tools": {"get_*": "auto", "list_*": "auto"}},
        "workflow": {"done": {"name": "done", "type": "end"}},
    }
    normalized = _normalize_guards_config(raw)
    assert classify_tool({"name": "get_status"}, normalized) == ("auto", None)
    assert classify_tool({"name": "list_files"}, normalized) == ("auto", None)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_normalize_guards_config_falls_through_to_own_workflow():
    """A tool matching no guards.tools pattern escalates into the file's own workflow, by its own name."""
    raw = {
        "name": "GitHub MCP Guard",
        "guards": {"tools": {"get_*": "auto"}},
        "workflow": {"done": {"name": "done", "type": "end"}},
    }
    normalized = _normalize_guards_config(raw)
    assert classify_tool({"name": "merge_pull_request"}, normalized) == ("workflow", "GitHub MCP Guard")


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_normalize_guards_config_no_workflow_falls_back_to_default_action():
    """A guards-only file with no workflow: section falls back to default_action/gate, not 'workflow'."""
    raw = {
        "name": "Read-Only Guard",
        "guards": {"tools": {"get_*": "auto"}},
    }
    normalized = _normalize_guards_config(raw)
    assert classify_tool({"name": "delete_repo"}, normalized) == ("gate", None)
