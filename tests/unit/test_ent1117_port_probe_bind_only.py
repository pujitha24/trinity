"""`is_port_available` is a bind-only probe: it never listens, and it closes.

`services.docker_service.is_port_available(port)` opens a TCP socket, binds it
to `0.0.0.0:port`, and closes it when its `with` block exits; when the host has
IPv6 it then does the same on `[::]:port` with IPV6_V6ONLY set, because an IPv4
wildcard bind does not collide with an IPv6-only listener. It never calls
`listen()` or `accept()`, so nothing can ever connect to that socket; the bind
only asks the kernel whether the port is taken. (It is a weak extra filter for
SSH-port allocation; `test_2215_port_allocation.py` covers the allocator and
always stubs this function out.)

The wildcard address is deliberate: a bind on `0.0.0.0` collides with an
existing bind on ANY local address, which a `127.0.0.1` probe would miss.

Pinned here, on the function's source:

* it constructs exactly two sockets, an AF_INET and an AF_INET6 stream socket,
  each used as a context manager, and names no `listen`,
  `accept`, `create_server`, `create_connection` or low-level `_socket`;

and on the real function and real sockets:

* the exact socket calls are `settimeout`, `bind(("0.0.0.0", port))`, `close`
  on an AF_INET socket, then (IPv6 hosts) `setsockopt(V6ONLY)`, `settimeout`,
  `bind(("::", port))`, `close` on an AF_INET6 socket;
* after it returns, the socket is closed and nothing accepts a connection;
* a bind held on 127.0.0.1, and one held on another local address, both make it
  report the port busy, while a 127.0.0.1 probe would miss the second.

abilityai/trinity-enterprise#1117
"""
from __future__ import annotations

import ast
import errno
import importlib
import socket
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "src" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = pytest.mark.unit

_RealSocket = socket.socket


@pytest.fixture
def is_port_available():
    """The real function, imported at test time: other files in the suite stub
    `services.docker_service`, so a collection-time import could bind a stub."""
    module = importlib.import_module("services.docker_service")
    assert Path(getattr(module, "__file__", "")).resolve() == (
        _BACKEND / "services" / "docker_service.py"
    ).resolve(), f"services.docker_service is not the real module: {module!r}"
    return module.is_port_available
_TRACKED = {
    "accept",
    "bind",
    "close",
    "connect",
    "connect_ex",
    "detach",
    "listen",
    "recv",
    "send",
    "sendall",
    "setblocking",
    "setsockopt",
    "settimeout",
}


@pytest.fixture
def recorded(monkeypatch):
    """Replace `socket.socket` (the probe imports `socket` at call time) with a
    subclass that records each socket it creates and every tracked call."""
    sockets: list = []

    class Recorder(_RealSocket):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            object.__setattr__(self, "_calls", [])
            sockets.append(self)

        def __getattribute__(self, name):
            if name in _TRACKED:
                calls = object.__getattribute__(self, "_calls")
                method = super().__getattribute__(name)

                def traced(*args, **kwargs):
                    calls.append((name, args))
                    return method(*args, **kwargs)

                return traced
            return super().__getattribute__(name)

    monkeypatch.setattr(socket, "socket", Recorder)
    return sockets


_SOURCE = _BACKEND / "services" / "docker_service.py"
_FORBIDDEN_NAMES = {"listen", "accept", "create_server", "create_connection", "fromfd", "socketpair", "_socket"}


def _probe_source() -> ast.FunctionDef:
    tree = ast.parse(_SOURCE.read_text())
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "is_port_available"]
    assert len(found) == 1, f"is_port_available not found exactly once in {_SOURCE}"
    return found[0]


def test_probe_source_builds_one_stream_socket_and_names_no_listener():
    fn = _probe_source()
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
    assert not names & _FORBIDDEN_NAMES, sorted(names & _FORBIDDEN_NAMES)
    assert "__import__" not in names and "importlib" not in names, sorted(names)
    constructors = [
        ast.unparse(n)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] == "socket"
    ]
    assert constructors == [
        "socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
        "socket.socket(socket.AF_INET6, socket.SOCK_STREAM)",
    ], constructors
    withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    assert [ast.unparse(item.context_expr) for w in withs for item in w.items] == constructors


def _free_port() -> int:
    with _RealSocket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_V6 = [
    ("setsockopt", (socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)),
    ("settimeout", (1,)),
    ("bind", (("::", 0),)),
    ("close", ()),
]


def _probe_calls(sockets, port, *, v6):
    """Per-socket call lists; every probe socket must be closed."""
    assert len(sockets) == (2 if v6 else 1), f"unexpected probe sockets: {len(sockets)}"
    assert all(sk.fileno() == -1 for sk in sockets), "a probe socket was left open"
    families = [(sk.family, sk.type) for sk in sockets]
    expected = [(socket.AF_INET, socket.SOCK_STREAM)]
    if v6:
        expected.append((socket.AF_INET6, socket.SOCK_STREAM))
    assert families == expected
    return [sk._calls for sk in sockets]


_V4_FREE = lambda port: [("settimeout", (1,)), ("bind", (("0.0.0.0", port),)), ("close", ())]  # noqa: E731


def test_free_port_is_probed_by_bind_then_close_only(recorded, is_port_available):
    port = _free_port()
    assert is_port_available(port) is True
    v6 = socket.has_ipv6
    calls = _probe_calls(recorded, port, v6=v6)
    assert calls[0] == _V4_FREE(port)
    if v6:
        assert calls[1] == [(n, (("::", port),) if n == "bind" else a) for n, a in _V6]


def test_busy_port_is_probed_the_same_way_and_still_closed(recorded, is_port_available):
    with _RealSocket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        port = held.getsockname()[1]
        assert is_port_available(port) is False
    # The IPv4 bind fails first, so the IPv6 probe is never opened.
    assert _probe_calls(recorded, port, v6=False) == [_V4_FREE(port)]


@pytest.mark.skipif(not socket.has_ipv6, reason="host has no IPv6")
@pytest.mark.parametrize("host", ["::1", "::"])
def test_ipv6_only_listener_makes_port_busy(host, is_port_available):
    try:
        held = _RealSocket(socket.AF_INET6, socket.SOCK_STREAM)
        held.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        held.bind((host, 0))
    except OSError as exc:
        pytest.skip(f"cannot bind [{host}] here: {exc}")
    with held:
        held.listen(1)
        assert is_port_available(held.getsockname()[1]) is False


def test_host_without_ipv6_is_decided_by_ipv4_alone(monkeypatch, recorded, is_port_available):
    monkeypatch.setattr(socket, "has_ipv6", False)
    assert is_port_available(_free_port()) is True
    assert len(recorded) == 1


@pytest.mark.parametrize("code", [errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL])
def test_unsupported_ipv6_is_skipped_not_busy(monkeypatch, code, is_port_available):
    monkeypatch.setattr(socket, "has_ipv6", True)

    class NoV6(_RealSocket):
        def __init__(self, family=-1, *args, **kwargs):
            if family == socket.AF_INET6:
                raise OSError(code, "no ipv6")
            super().__init__(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", NoV6)
    assert is_port_available(_free_port()) is True


def test_nothing_accepts_connections_after_the_probe(is_port_available):
    port = _free_port()
    assert is_port_available(port) is True
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def _other_local_ipv4() -> str:
    """A local IPv4 address other than 127.0.0.1 that a socket can bind.

    Linux routes all of 127.0.0.0/8 to loopback, so 127.0.0.2 always works
    there; elsewhere use the address of the default route. No address is a
    failure, not a skip: the wildcard property must be shown, not assumed.
    """
    with _RealSocket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.2", 0))
            return "127.0.0.2"
        except OSError:
            pass
    with _RealSocket(socket.AF_INET, socket.SOCK_DGRAM) as u:
        try:
            u.connect(("192.0.2.1", 9))  # TEST-NET-1; a UDP connect sends nothing
            ip = u.getsockname()[0]
        except OSError as exc:
            pytest.fail(f"no second local IPv4 address to bind on this host: {exc}")
    if ip.startswith("127.") or ip == "0.0.0.0":
        pytest.fail(f"no second local IPv4 address to bind on this host (got {ip})")
    return ip


def test_wildcard_probe_sees_a_bind_on_another_local_address(is_port_available):
    other = _other_local_ipv4()
    with _RealSocket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind((other, 0))
        port = held.getsockname()[1]
        assert is_port_available(port) is False
        # The reason the probe binds the wildcard: a loopback-only probe would
        # have called this port free.
        with _RealSocket(socket.AF_INET, socket.SOCK_STREAM) as loopback:
            loopback.bind(("127.0.0.1", port))
