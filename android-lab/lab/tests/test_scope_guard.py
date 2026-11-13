"""Unit tests for PENT-21 Authorization & Scope-Guard Library."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scope_guard import (
    ScopeViolationError,
    assert_in_scope,
    filter_in_scope_hosts,
    is_device_in_scope,
    is_host_in_scope,
    is_package_in_scope,
    main,
)


@pytest.mark.parametrize(
    "target",
    [
        "localhost",
        "127.0.0.1",
        "http://127.0.0.1:5050/api/status",
        "10.25.130.15",
        "172.16.0.5",
        "192.168.1.50",
        "target.lab",
        "device.local",
    ],
)
def test_allowed_lab_hosts(target: str) -> None:
    assert is_host_in_scope(target) is True
    res = assert_in_scope(host=target)
    assert res["host"] == target


@pytest.mark.parametrize(
    "target",
    [
        "",
        "8.8.8.8",
        "1.1.1.1",
        "https://example.com",
        "https://google.com/search?q=test",
        "93.184.216.34",
    ],
)
def test_blocked_external_hosts(target: str) -> None:
    assert is_host_in_scope(target) is False
    with pytest.raises(ScopeViolationError):
        assert_in_scope(host=target)


def test_package_scope_enforcement() -> None:
    assert is_package_in_scope("com.oslab.vulnapp") is True
    assert is_package_in_scope("jakhar.aseem.diva") is True
    assert assert_in_scope(package="com.example.labtarget") == {"package": "com.example.labtarget"}

    assert is_package_in_scope("com.whatsapp") is False
    with pytest.raises(ScopeViolationError):
        assert_in_scope(package="com.whatsapp")


def test_device_scope_enforcement() -> None:
    assert is_device_in_scope("emulator-5554") is True
    assert is_device_in_scope("192.168.56.101:5555") is True
    assert is_device_in_scope("127.0.0.1:27042") is True

    assert is_device_in_scope("8.8.8.8:5555") is False
    with pytest.raises(ScopeViolationError):
        assert_in_scope(device="8.8.8.8:5555")


def test_filter_and_cli_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    mixed = ["http://127.0.0.1:5050", "https://prod.example.org", "192.168.1.10"]
    assert filter_in_scope_hosts(mixed) == ["http://127.0.0.1:5050", "192.168.1.10"]

    assert main(["--host", "192.168.1.10", "--package", "com.oslab.demo", "--json"]) == 0
    out_ok = capsys.readouterr().out
    assert '"in_scope": true' in out_ok

    assert main(["--host", "8.8.8.8"]) == 1
