import json
import pytest
import hmac
import hashlib
from approvalml.runtime.chat_adapters import (
    SlackAdapter,
    TeamsAdapter,
    LarkAdapter,
    TelegramAdapter,
    WhatsAppAdapter,
    GoogleChatAdapter
)

# ── SlackAdapter Tests ───────────────────────────────────────────────────────

def test_slack_adapter_build_payload():
    adapter = SlackAdapter()
    step_id = "step_123"
    desc = "Approve invoice #456"
    context = {"form_data": {"Amount": "$1,000", "Department": "Finance"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    assert payload["text"] == desc
    assert len(payload["blocks"]) >= 3
    
    # Verify header and description section
    assert payload["blocks"][0]["type"] == "header"
    assert payload["blocks"][1]["text"]["text"] == f"*{desc}*"
    
    # Verify fields section (context)
    fields = payload["blocks"][2]["fields"]
    assert any("Amount" in f["text"] for f in fields)
    assert any("Finance" in f["text"] for f in fields)
    
    # Verify actions element
    actions = payload["blocks"][-1]
    assert actions["type"] == "actions"
    elements = actions["elements"]
    assert len(elements) == 2
    
    # Check values and action_ids
    approve_btn = elements[0]
    assert approve_btn["action_id"] == "slack_approve"
    assert json.loads(approve_btn["value"]) == {"step_id": step_id, "decision": "approve"}
    
    reject_btn = elements[1]
    assert reject_btn["action_id"] == "slack_reject"
    assert json.loads(reject_btn["value"]) == {"step_id": step_id, "decision": "reject"}


def test_slack_adapter_verify_request():
    adapter = SlackAdapter()
    secret = "slack_signing_secret_key"
    body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"
    timestamp = "1531420618"
    
    # Valid signature generation
    sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body
    valid_hash = hmac.new(secret.encode("utf-8"), sig_basestring, hashlib.sha256).hexdigest()
    valid_sig = f"v0={valid_hash}"
    
    headers = {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": valid_sig
    }
    
    assert adapter.verify_request(headers, body, secret) is True
    
    # Invalid signature check
    headers["X-Slack-Signature"] = "v0=invalidhash"
    assert adapter.verify_request(headers, body, secret) is False


def test_slack_adapter_parse_callback():
    adapter = SlackAdapter()
    
    # Raw action payload
    actions_payload = {
        "actions": [
            {
                "value": json.dumps({"step_id": "step_123", "decision": "approve"}),
                "action_id": "slack_approve"
            }
        ],
        "submission": {
            "comment": "Looks good!"
        }
    }
    
    # Parse dict directly
    step_id, decision, comment = adapter.parse_callback(actions_payload)
    assert step_id == "step_123"
    assert decision == "approve"
    assert comment == "Looks good!"

    # Parse wrapped payload string
    wrapped = {
        "payload": json.dumps(actions_payload)
    }
    step_id, decision, comment = adapter.parse_callback(wrapped)
    assert step_id == "step_123"
    assert decision == "approve"
    assert comment == "Looks good!"


# ── TeamsAdapter Tests ───────────────────────────────────────────────────────

def test_teams_adapter_build_payload():
    adapter = TeamsAdapter()
    step_id = "step_teams"
    desc = "Teams approval check"
    context = {"form_data": {"Project": "Alpha"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    assert payload["type"] == "message"
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    
    # Verify widgets
    assert card["body"][0]["text"] == desc
    assert card["body"][1]["facts"][0]["title"] == "Project"
    assert card["body"][1]["facts"][0]["value"] == "Alpha"
    
    # Verify action verb/data
    actions = card["actions"]
    assert len(actions) == 2
    assert actions[0]["title"] == "Approve"
    assert actions[0]["verb"] == "approve"
    assert actions[0]["data"] == {"step_id": step_id, "decision": "approve"}


def test_teams_adapter_verify_request():
    adapter = TeamsAdapter()
    secret = "teams_secret"
    body = b"teams_request_body"
    
    valid_hash = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    
    headers_bearer = {"Authorization": f"Bearer {valid_hash}"}
    headers_signature = {"X-Teams-Signature": valid_hash}
    
    assert adapter.verify_request(headers_bearer, body, secret) is True
    assert adapter.verify_request(headers_signature, body, secret) is True
    assert adapter.verify_request({"Authorization": "Bearer badtoken"}, body, secret) is False


def test_teams_adapter_parse_callback():
    adapter = TeamsAdapter()
    callback_payload = {
        "action": {
            "verb": "reject",
            "data": {
                "step_id": "step_456",
                "decision": "reject",
                "comment": "Too expensive"
            }
        }
    }
    
    step_id, decision, comment = adapter.parse_callback(callback_payload)
    assert step_id == "step_456"
    assert decision == "reject"
    assert comment == "Too expensive"


# ── LarkAdapter Tests ────────────────────────────────────────────────────────

def test_lark_adapter_build_payload():
    adapter = LarkAdapter()
    step_id = "step_lark"
    desc = "Lark request description"
    context = {"form_data": {"User": "Alice"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    assert payload["header"]["title"]["content"] == "Approval Required"
    assert payload["elements"][0]["text"]["content"] == f"**{desc}**"
    assert "User" in payload["elements"][1]["fields"][0]["text"]["content"]
    
    actions = payload["elements"][2]["actions"]
    assert actions[0]["text"]["content"] == "Approve"
    assert actions[0]["value"] == {"step_id": step_id, "decision": "approve"}


def test_lark_adapter_verify_request():
    adapter = LarkAdapter()
    secret = "lark_secret"
    body = b"lark_body_contents"
    timestamp = "1620000000"
    nonce = "abcd1234"
    
    sig_bytes = timestamp.encode("utf-8") + nonce.encode("utf-8") + secret.encode("utf-8") + body
    valid_sig = hashlib.sha256(sig_bytes).hexdigest()
    
    headers = {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": valid_sig
    }
    
    assert adapter.verify_request(headers, body, secret) is True
    headers["X-Lark-Signature"] = "invalidsig"
    assert adapter.verify_request(headers, body, secret) is False


def test_lark_adapter_parse_callback():
    adapter = LarkAdapter()
    
    # Handle challenge verification
    challenge_payload = {
        "type": "url_verification",
        "challenge": "challenge_12345"
    }
    step_id, decision, challenge = adapter.parse_callback(challenge_payload)
    assert decision == "challenge"
    assert challenge == "challenge_12345"
    
    # Handle button action
    action_payload = {
        "action": {
            "value": {
                "step_id": "step_789",
                "decision": "approve"
            }
        },
        "comment": "Approved on Lark"
    }
    step_id, decision, comment = adapter.parse_callback(action_payload)
    assert step_id == "step_789"
    assert decision == "approve"
    assert comment == "Approved on Lark"


# ── TelegramAdapter Tests ────────────────────────────────────────────────────

def test_telegram_adapter_build_payload():
    adapter = TelegramAdapter()
    step_id = "step_tg"
    desc = "Telegram card"
    context = {"form_data": {"Due": "Tomorrow"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    assert "Telegram card" in payload["text"]
    assert "Due" in payload["text"]
    assert "Tomorrow" in payload["text"]
    
    keyboard = payload["reply_markup"]["inline_keyboard"][0]
    assert keyboard[0]["text"] == "Approve ✅"
    assert json.loads(keyboard[0]["callback_data"]) == {"step_id": step_id, "decision": "approve"}


def test_telegram_adapter_verify_request():
    adapter = TelegramAdapter()
    secret = "tg_bot_token"
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
    
    assert adapter.verify_request(headers, b"", secret) is True
    assert adapter.verify_request({"X-Telegram-Bot-Api-Secret-Token": "badtoken"}, b"", secret) is False


def test_telegram_adapter_parse_callback():
    adapter = TelegramAdapter()
    callback_payload = {
        "callback_query": {
            "data": json.dumps({"step_id": "step_tg_99", "decision": "reject"})
        }
    }
    step_id, decision, comment = adapter.parse_callback(callback_payload)
    assert step_id == "step_tg_99"
    assert decision == "reject"
    assert comment is None


# ── WhatsAppAdapter Tests ────────────────────────────────────────────────────

def test_whatsapp_adapter_build_payload():
    adapter = WhatsAppAdapter()
    step_id = "step_wa"
    desc = "WhatsApp approve request"
    context = {"form_data": {"User": "Dave"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    assert payload["messaging_product"] == "whatsapp"
    assert payload["type"] == "interactive"
    
    interactive = payload["interactive"]
    assert "WhatsApp approve request" in interactive["body"]["text"]
    assert "User: Dave" in interactive["body"]["text"]
    
    buttons = interactive["action"]["buttons"]
    assert buttons[0]["reply"]["id"] == f"approve:{step_id}"
    assert buttons[0]["reply"]["title"] == "Approve"


def test_whatsapp_adapter_verify_request():
    adapter = WhatsAppAdapter()
    secret = "wa_verify_secret"
    body = b"whatsapp_payload_body"
    
    valid_hash = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={valid_hash}"}
    
    assert adapter.verify_request(headers, body, secret) is True
    assert adapter.verify_request({"X-Hub-Signature-256": "sha256=badhash"}, body, secret) is False


def test_whatsapp_adapter_parse_callback():
    adapter = WhatsAppAdapter()
    
    # Challenge check helper
    challenge_payload = {
        "hub.mode": "subscribe",
        "hub.challenge": "challenge_wa_123"
    }
    step_id, decision, challenge = adapter.parse_callback(challenge_payload)
    assert challenge == "challenge_wa_123"
    
    # Message callback check
    message_payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "interactive": {
                                        "button_reply": {
                                            "id": "reject:step_wa_55"
                                        }
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    step_id, decision, comment = adapter.parse_callback(message_payload)
    assert step_id == "step_wa_55"
    assert decision == "reject"


# ── GoogleChatAdapter Tests ──────────────────────────────────────────────────

def test_google_chat_adapter_build_payload():
    adapter = GoogleChatAdapter()
    step_id = "step_gchat"
    desc = "Google Chat card description"
    context = {"form_data": {"Host": "Local"}}
    
    payload = adapter.build_approval_payload(step_id, desc, "http://callback", context)
    
    card = payload["cardsV2"][0]["card"]
    assert card["header"]["title"] == "Approval System"
    
    widgets = card["sections"][0]["widgets"]
    assert "Google Chat card description" in widgets[0]["textParagraph"]["text"]
    assert "Host" in widgets[1]["textParagraph"]["text"]
    assert "Local" in widgets[1]["textParagraph"]["text"]
    
    buttons = widgets[2]["buttonList"]["buttons"]
    assert buttons[0]["text"] == "Approve"
    assert buttons[0]["onClick"]["action"]["actionMethodName"] == "approve"
    assert buttons[0]["onClick"]["action"]["parameters"][0] == {"key": "step_id", "value": step_id}


def test_google_chat_adapter_verify_request():
    adapter = GoogleChatAdapter()
    secret = "gchat_token"
    
    assert adapter.verify_request({"Authorization": f"Bearer {secret}"}, b"", secret) is True
    assert adapter.verify_request({"X-Google-Chat-Token": secret}, b"", secret) is True
    assert adapter.verify_request({"X-Google-Chat-Token": "badtoken"}, b"", secret) is False


def test_google_chat_adapter_parse_callback():
    adapter = GoogleChatAdapter()
    callback_payload = {
        "action": {
            "actionMethodName": "approve",
            "parameters": [
                {"key": "step_id", "value": "step_gc_77"},
                {"key": "decision", "value": "approve"}
            ]
        }
    }
    step_id, decision, comment = adapter.parse_callback(callback_payload)
    assert step_id == "step_gc_77"
    assert decision == "approve"
    assert comment is None
