"""An admin cannot grant a collaboration permission to a nonexistent agent (#3550)."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "backend"))

from models import User  # noqa: E402
from services.agent_service import permissions  # noqa: E402


class _FakeDb:
    def __init__(self):
        self.stored = []

    def can_user_share_agent(self, username, agent):
        return True

    def can_user_access_agent(self, username, agent):
        return True  # the admin shortcut: True before any lookup

    def get_agent_owner(self, agent):
        return {"owner_username": "admin"} if agent in ("src-agent", "real-agent") else None

    def set_agent_permissions(self, agent, targets, who):
        self.stored = list(targets)

    def add_agent_permission(self, agent, target, who):
        self.stored.append(target)
        return True


@pytest.fixture
def fake(monkeypatch):
    f = _FakeDb()
    monkeypatch.setattr(permissions, "db", f)
    monkeypatch.setattr(permissions, "get_agent_container", lambda name: object())
    monkeypatch.setattr(permissions, "agent_may_reach", lambda *a, **k: True)
    return f


def _admin():
    return User(id=1, username="admin", email="a@example.com", role="admin")


def test_put_rejects_nonexistent_target_for_admin(fake):
    with pytest.raises(HTTPException) as e:
        asyncio.run(permissions.set_agent_permissions_logic(
            "src-agent", {"permitted_agents": ["real-agent", "no-such-agent"]}, _admin(), None))
    assert e.value.status_code == 400
    assert fake.stored == []


def test_post_rejects_nonexistent_target_for_admin(fake):
    with pytest.raises(HTTPException) as e:
        asyncio.run(permissions.add_agent_permission_logic(
            "src-agent", "no-such-agent", _admin(), None))
    assert e.value.status_code == 400
    assert fake.stored == []


def test_existing_target_still_granted(fake):
    r = asyncio.run(permissions.set_agent_permissions_logic(
        "src-agent", {"permitted_agents": ["real-agent"]}, _admin(), None))
    assert r["permitted_count"] == 1 and fake.stored == ["real-agent"]
