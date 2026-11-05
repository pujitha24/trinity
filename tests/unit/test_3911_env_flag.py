"""env_flag accepts 1/true/yes/on (any case) and warns on unknown values (#3911)."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "backend"))

from utils.helpers import env_flag  # noqa: E402


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on", " ON "])
def test_truthy_values_enable(monkeypatch, val):
    monkeypatch.setenv("X_FLAG", val)
    assert env_flag("X_FLAG", False) is True
    assert env_flag("X_FLAG", True) is True


@pytest.mark.parametrize("val", ["0", "false", "False", "no", "off"])
def test_falsy_values_disable_without_warning(monkeypatch, caplog, val):
    monkeypatch.setenv("X_FLAG", val)
    with caplog.at_level(logging.WARNING):
        assert env_flag("X_FLAG", True) is False
    assert not caplog.records


@pytest.mark.parametrize("default", [True, False])
def test_unset_and_empty_use_default_silently(monkeypatch, caplog, default):
    monkeypatch.delenv("X_FLAG", raising=False)
    with caplog.at_level(logging.WARNING):
        assert env_flag("X_FLAG", default) is default
        monkeypatch.setenv("X_FLAG", "")
        assert env_flag("X_FLAG", default) is default
    assert not caplog.records


def test_unknown_value_warns_with_name_and_value_and_keeps_default(monkeypatch, caplog):
    monkeypatch.setenv("X_FLAG", "enabled")
    with caplog.at_level(logging.WARNING):
        assert env_flag("X_FLAG", True) is True
    assert "X_FLAG" in caplog.text and "enabled" in caplog.text


def test_otel_enabled_true_no_longer_disables_ops_costs(monkeypatch):
    # Before: OTEL_ENABLED=true compared != "1" and silently turned OTel off.
    monkeypatch.setenv("OTEL_ENABLED", "true")
    assert env_flag("OTEL_ENABLED", True) is True
    monkeypatch.setenv("OTEL_ENABLED", "off")
    assert env_flag("OTEL_ENABLED", True) is False
