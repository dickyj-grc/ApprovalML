"""
Unit tests for APPROVALML_NOTIFY parsing and webhook delivery in mcp_wrap.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from approvalml.mcp_wrap import parse_notify_env, send_env_notify


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#APPROVALML_NOTIFY]]
def test_parse_notify_env_splits_on_first_colon_only():
    """Target itself may contain ':' (e.g. a URL) — only the channel prefix is split off."""
    channel, target = parse_notify_env("slack:https://hooks.slack.com/services/XXX")
    assert channel == "slack"
    assert target == "https://hooks.slack.com/services/XXX"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#APPROVALML_NOTIFY]]
def test_parse_notify_env_requires_a_colon():
    """A value with no ':' at all is a configuration error, not a channel with an empty target."""
    with pytest.raises(ValueError):
        parse_notify_env("slack-only-no-target")


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#APPROVALML_NOTIFY]]
@pytest.mark.asyncio
async def test_send_env_notify_posts_slack_payload_to_target():
    """send_env_notify builds the Slack payload and POSTs it directly to the webhook target."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await send_env_notify(
            "slack:https://hooks.slack.com/services/XXX",
            subject="Approval needed",
            body="merge_pull_request",
        )

    mock_client.post.assert_awaited_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://hooks.slack.com/services/XXX"
    assert "blocks" in kwargs["json"]


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#APPROVALML_NOTIFY]]
@pytest.mark.asyncio
async def test_send_env_notify_rejects_unsupported_channel():
    """An unrecognized channel raises a clear error rather than silently failing to notify."""
    with pytest.raises(ValueError, match="Unsupported APPROVALML_NOTIFY channel"):
        await send_env_notify("telegram:12345", subject="x", body="y")
