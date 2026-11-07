"""Name checks must refuse a trailing newline (#4331).

`re.match` with a pattern ending in `$` accepts `"w\\n"`, because `$` also
matches just before a final newline. The patterns end in `\\Z` instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_STR = str(Path(__file__).resolve().parents[2] / "src" / "backend")
while _BACKEND_STR in sys.path:
    sys.path.remove(_BACKEND_STR)
sys.path.insert(0, _BACKEND_STR)


def _svc():
    try:
        from services import system_service
    except ImportError:  # pragma: no cover - backend venv required
        pytest.skip("backend venv required")
    return system_service


def _validate(doc: str):
    svc = _svc()
    svc.validate_manifest(svc.parse_manifest(doc))


def test_valid_manifest_still_passes():
    _validate('name: demo\nagents:\n  w:\n    template: local:x\n')


def test_member_key_with_trailing_newline_is_refused():
    with pytest.raises(ValueError, match="Invalid agent name"):
        _validate('name: demo\nagents:\n  "w\\n":\n    template: local:x\n')


def test_system_name_with_trailing_newline_is_refused():
    with pytest.raises(ValueError, match="Invalid system name"):
        _validate('name: "ab\\n"\nagents:\n  w:\n    template: local:x\n')


@pytest.mark.parametrize("module", ["services.template_service", "services.agent_service.crud"])
def test_local_template_name_with_trailing_newline_is_refused(module):
    try:
        mod = __import__(module, fromlist=["_LOCAL_TEMPLATE_NAME_RE"])
    except ImportError:  # pragma: no cover - backend venv required
        pytest.skip("backend venv required")
    assert mod._LOCAL_TEMPLATE_NAME_RE.match("tmpl-1.0")
    assert not mod._LOCAL_TEMPLATE_NAME_RE.match("tmpl\n")
