"""API 34+ (APEX tmpfs overlay) CA-install command builders — pure, offline."""
import install_ca as ic


def test_method_selection_by_sdk():
    assert ic.install_method_for_sdk(30) == "writable-system"
    assert ic.install_method_for_sdk(33) == "writable-system"
    assert ic.install_method_for_sdk(34) == "apex-tmpfs"
    assert ic.install_method_for_sdk(35) == "apex-tmpfs"


def test_apex_overlay_commands_cover_both_stores():
    cmds = ic.apex_overlay_commands("c8750f0d.0")
    flat = " ".join(" ".join(c) for c in cmds)
    # stages the cert
    assert "/data/local/tmp/c8750f0d.0" in flat
    assert ic.DEVICE_STAGING in flat
    # overlays BOTH the legacy and the APEX store
    assert ic.SYSTEM_CACERTS_DIR in flat
    assert ic.APEX_CACERTS_DIR in flat
    # mounts a tmpfs over each target
    tmpfs_mounts = [c for c in cmds if c[:3] == ["mount", "-t", "tmpfs"]]
    assert len(tmpfs_mounts) == 2
    # restores the SELinux label
    assert ic.SELINUX_CACERT_CONTEXT in flat


def test_apex_overlay_order_stage_before_mount():
    cmds = ic.apex_overlay_commands("abcd1234.0")
    first_mount = next(i for i, c in enumerate(cmds) if c[:1] == ["mount"])
    mkdir_idx = next(i for i, c in enumerate(cmds) if c[:1] == ["mkdir"])
    assert mkdir_idx < first_mount  # stage the certs before overlaying


def test_apex_nsenter_targets_zygote():
    cmds = ic.apex_nsenter_commands()
    flat = " ".join(" ".join(c) for c in cmds)
    assert "zygote" in flat
    assert "nsenter" in flat
    assert ic.APEX_CACERTS_DIR in flat


def test_system_cert_path_unchanged():
    assert ic.system_cert_path("c8750f0d") == (
        "/system/etc/security/cacerts/c8750f0d.0"
    )
