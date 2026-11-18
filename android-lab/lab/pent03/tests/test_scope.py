"""Scope guard tests — the authorization gate that fronts every action."""
import pytest

import scope


def test_emulator_serials_in_scope():
    assert scope.serial_in_scope("emulator-5554")
    assert scope.serial_in_scope("emulator-9999")
    assert scope.serial_in_scope("127.0.0.1:5555")
    assert scope.serial_in_scope("10.0.2.15:5555")


def test_physical_and_lan_serials_out_of_scope():
    assert not scope.serial_in_scope("HT7A1B2C3D4E")       # USB device id
    assert not scope.serial_in_scope("192.168.1.50:5555")  # home LAN
    assert not scope.serial_in_scope("")


def test_lab_packages_in_scope():
    assert scope.package_in_scope("com.securebank.mobile")
    assert scope.package_in_scope("org.oslab.target")
    assert not scope.package_in_scope("com.whatsapp")
    assert not scope.package_in_scope("")


def test_proxy_hosts_in_scope():
    assert scope.proxy_host_in_scope("127.0.0.1")
    assert scope.proxy_host_in_scope("10.0.2.2")
    assert not scope.proxy_host_in_scope("8.8.8.8")
    assert not scope.proxy_host_in_scope("evil.example.com")


def test_assert_in_scope_passes_for_lab_targets():
    scope.assert_in_scope(
        serial="emulator-5554",
        package="com.securebank.mobile",
        proxy_host="10.0.2.2",
    )


def test_assert_in_scope_raises_and_names_each_problem():
    with pytest.raises(scope.ScopeError) as ei:
        scope.assert_in_scope(
            serial="192.168.1.50:5555",
            package="com.whatsapp",
            proxy_host="8.8.8.8",
        )
    msg = str(ei.value)
    assert "192.168.1.50:5555" in msg
    assert "com.whatsapp" in msg
    assert "8.8.8.8" in msg


def test_env_escape_hatch_widens_scope(monkeypatch):
    assert not scope.serial_in_scope("192.168.56.101:5555")
    monkeypatch.setenv("OSLAB_EXTRA_SERIALS", "192.168.56.101:5555")
    assert scope.serial_in_scope("192.168.56.101:5555")

    monkeypatch.setenv("OSLAB_EXTRA_PACKAGES", "com.myorg.app")
    assert scope.package_in_scope("com.myorg.app")


def test_cli_reports_out_of_scope_with_exit_2(capsys):
    rc = scope.main(["--serial", "192.168.1.50:5555"])
    assert rc == 2
    assert "OUT OF SCOPE" in capsys.readouterr().err


def test_invalid_package_with_path_control_is_rejected():
    # A package carrying a path separator / traversal is never valid or in scope.
    assert not scope.is_valid_package("com.securebank/../../etc")
    assert not scope.is_valid_package("../../etc/passwd")
    assert not scope.package_in_scope("com.securebank.mobile/../x")
    with pytest.raises(scope.ScopeError):
        scope.assert_in_scope(package="com.securebank.mobile/../x")


def test_compose_emulator_hostname_in_scope():
    assert scope.serial_in_scope("emulator:5555")
    assert scope.serial_in_scope("emulator-5554")


def test_proxy_host_is_exact_not_subnet():
    assert scope.proxy_host_in_scope("10.0.2.2")
    # a different host in the same /24 must NOT be trusted as a proxy
    assert not scope.proxy_host_in_scope("10.0.2.5")
    assert not scope.proxy_host_in_scope("10.0.2.200")


def test_com_example_prefix_no_longer_trusted():
    assert not scope.package_in_scope("com.example.anything")


def test_require_serial_rejects_empty_and_out_of_scope():
    with pytest.raises(scope.ScopeError):
        scope.require_serial(None)
    with pytest.raises(scope.ScopeError):
        scope.require_serial("")
    with pytest.raises(scope.ScopeError):
        scope.require_serial("192.168.1.50:5555")
    assert scope.require_serial("emulator-5554") == "emulator-5554"
