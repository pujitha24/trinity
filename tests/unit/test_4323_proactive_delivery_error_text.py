"""#4323 — an unexpected delivery exception must not reach the caller's 404
detail or the audit row; only its class name does, the text goes to the log."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

SENTINEL = "SENTINEL-/data/internal/path db-host:5432"


@pytest.fixture
def pms(monkeypatch):
    import services.proactive_message_service as mod
    monkeypatch.setattr(mod, "db", MagicMock())
    return mod


def _service(mod, monkeypatch):
    svc = mod.ProactiveMessageService()
    monkeypatch.setattr(svc, "check_rate_limit", lambda *a, **k: True)
    audits = []

    async def audit(*args, **kwargs):
        audits.append((args, kwargs))

    monkeypatch.setattr(svc, "audit_send", audit)
    return svc, audits


def test_unexpected_exception_text_stays_out_of_error_and_audit(pms, monkeypatch, caplog):
    svc, audits = _service(pms, monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(svc, "_deliver_via_channel", boom)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(pms.RecipientNotFoundError) as ei:
            asyncio.run(svc._rate_limit_and_deliver(
                "a", "user@example.com", "hi", "slack", False, "hi"))
    assert SENTINEL not in str(ei.value)
    assert "RuntimeError" in str(ei.value)
    assert SENTINEL not in repr(audits)
    assert "RuntimeError" in repr(audits)
    assert "db-host:5432" in caplog.text  # full text is kept in the log


@pytest.mark.parametrize("channel", ["telegram", "whatsapp"])
def test_helper_error_is_class_name_only(pms, monkeypatch, channel):
    from adapters.telegram_adapter import TelegramAdapter
    from adapters.whatsapp_adapter import WhatsAppAdapter

    def fail(self, text):
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(TelegramAdapter, "format_response", fail)
    monkeypatch.setattr(WhatsAppAdapter, "format_response", fail)
    # MagicMock lookups are truthy, so the helper reaches its guarded send block.
    svc = pms.ProactiveMessageService()
    r = asyncio.run(getattr(svc, f"_deliver_{channel}")("a", "user@example.com", "hi"))
    assert not r.success
    assert SENTINEL not in r.error
    assert "RuntimeError" in r.error
