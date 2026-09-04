"""Unit tests for Telegram Bot Command Handler."""

from services.telegram_bot_handler import HELP_MESSAGE, EMERGENCY_CONTACTS, process_telegram_updates


def test_help_and_emergency_messages():
    assert "100" in EMERGENCY_CONTACTS
    assert "1114" in EMERGENCY_CONTACTS
    assert "1155" in EMERGENCY_CONTACTS
    assert "/status" in HELP_MESSAGE
    assert "/emergency" in HELP_MESSAGE


def test_process_telegram_updates_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    processed = process_telegram_updates()
    assert processed == 0
