"""Unit, scope-guard, contract, and golden-file tests for PENT-07."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from scripts import tamper_runner as tr


FIXTURES_DIR = tr.DEFAULT_FIXTURES_DIR
POLICIES_DIR = FIXTURES_DIR / "policies"
GOLDEN_DIR = FIXTURES_DIR / "golden"

POLICY_NAMES = [
    "01_baseline_unhooked",
    "02_observe_gozlem",
    "03_onenter_arg_tamper",
    "04_onleave_retval_replace",
    "05_combined_policy",
]


def _load_fixture_policy(name: str) -> dict:
    return tr.load_policy(POLICIES_DIR / f"{name}.json")


@pytest.mark.parametrize("policy_name", POLICY_NAMES)
def test_policy_matches_golden_files(policy_name: str) -> None:
    policy = _load_fixture_policy(policy_name)
    result = tr.run_policy(policy)

    actual_txt = tr.format_trace_text(result)
    actual_json = json.dumps(result, indent=2) + "\n"

    expected_txt = (GOLDEN_DIR / f"{policy_name}.golden.txt").read_text(encoding="utf-8")
    expected_json = (GOLDEN_DIR / f"{policy_name}.golden.json").read_text(encoding="utf-8")

    assert actual_txt == expected_txt
    assert actual_json == expected_json


def test_verify_golden_suite_passes() -> None:
    ok, messages = tr.verify_golden_suite(FIXTURES_DIR)
    assert ok is True
    assert len(messages) == len(POLICY_NAMES)
    assert all(msg.startswith("[OK]") for msg in messages)


def test_verify_golden_suite_detects_mismatch(tmp_path: Path) -> None:
    copied = tmp_path / "pent07"
    shutil.copytree(FIXTURES_DIR, copied)

    tampered_golden = copied / "golden" / "04_onleave_retval_replace.golden.txt"
    tampered_golden.write_text("CORRUPTED OUTPUT\n", encoding="utf-8")

    ok, messages = tr.verify_golden_suite(copied)
    assert ok is False
    assert any("04_onleave_retval_replace" in m and "[FAIL]" in m for m in messages)


def test_baseline_and_observe_fail_authentication_deterministically() -> None:
    baseline = tr.run_policy(_load_fixture_policy("01_baseline_unhooked"))
    assert baseline["summary"]["approved_calls"] == 0
    assert baseline["summary"]["rejected_calls"] == 3
    assert baseline["summary"]["final_status"] == "REDDEDILDI"
    assert baseline["schedule"] == {"iterations": 3, "interval_ms": 2000}

    observed = tr.run_policy(_load_fixture_policy("02_observe_gozlem"))
    assert observed["summary"]["approved_calls"] == 0
    assert observed["summary"]["arg_tampers_applied"] == 0
    assert observed["summary"]["retval_replacements_applied"] == 0
    for item in observed["iterations"]:
        assert item["onEnter"]["observed_args"] == {
            "girilen_parola": "deneme123",
            "yetki_seviyesi": 1,
        }
        assert item["onLeave"]["observed_retval"] == 0
        assert item["onLeave"]["final_retval"] == 0


def test_onenter_argument_tampering_overrides_password() -> None:
    result = tr.run_policy(_load_fixture_policy("03_onenter_arg_tamper"))
    assert result["summary"]["approved_calls"] == 3
    assert result["summary"]["arg_tampers_applied"] == 3
    assert result["summary"]["retval_replacements_applied"] == 0
    assert result["summary"]["final_status"] == "ONAYLANDI"

    for item in result["iterations"]:
        assert item["caller_inputs"]["parola"] == "deneme123"
        assert item["effective_args"]["girilen_parola"] == "gizli123"
        assert item["native_retval"] == 1
        assert item["onLeave"]["retval_replaced"] is False
        assert item["durum"] == "ONAYLANDI"


def test_onleave_retval_replace_overrides_return_value() -> None:
    result = tr.run_policy(_load_fixture_policy("04_onleave_retval_replace"))
    assert result["summary"]["approved_calls"] == 3
    assert result["summary"]["arg_tampers_applied"] == 0
    assert result["summary"]["retval_replacements_applied"] == 3
    assert result["summary"]["final_status"] == "ONAYLANDI"

    for item in result["iterations"]:
        assert item["effective_args"]["girilen_parola"] == "deneme123"
        assert item["native_retval"] == 0
        assert item["onLeave"]["observed_retval"] == 0
        assert item["onLeave"]["retval_replaced"] is True
        assert item["onLeave"]["final_retval"] == 1
        assert item["durum"] == "ONAYLANDI"


def test_combined_onenter_and_onleave_policy() -> None:
    result = tr.run_policy(_load_fixture_policy("05_combined_policy"))
    assert result["summary"]["approved_calls"] == 3
    assert result["summary"]["arg_tampers_applied"] == 3
    assert result["summary"]["retval_replacements_applied"] == 3
    assert result["summary"]["final_status"] == "ONAYLANDI"

    first = result["iterations"][0]
    assert first["caller_inputs"]["yetki_seviyesi"] == 0
    assert first["effective_args"]["yetki_seviyesi"] == 5
    assert first["native_retval"] == 0
    assert first["onLeave"]["final_retval"] == 1


def test_yaml_policy_is_supported(tmp_path: Path) -> None:
    yaml_policy = tmp_path / "custom.yaml"
    yaml_policy.write_text(
        "\n".join(
            [
                "version: 1",
                "policy_id: yaml_retval_test",
                'description: "YAML policy smoke test"',
                "target:",
                '  source: "android-lab/lab/tests/targets/hedef.c"',
                '  function: "parola_kontrol"',
                "schedule:",
                "  iterations: 2",
                "  interval_ms: 2000",
                "inputs:",
                '  parola: "deneme123"',
                "  yetki_seviyesi: 1",
                "rules:",
                '  - function: "parola_kontrol"',
                "    onLeave:",
                "      observe_retval: true",
                "      retval_replace:",
                "        enabled: true",
                "        when_equals: 0",
                "        value: 1",
                '        type: "int32"',
            ]
        ),
        encoding="utf-8",
    )
    loaded = tr.load_policy(yaml_policy)
    result = tr.run_policy(loaded)
    assert result["policy_id"] == "yaml_retval_test"
    assert result["summary"]["approved_calls"] == 2
    assert result["summary"]["retval_replacements_applied"] == 2


def test_scope_guard_allows_canonical_hedef_c() -> None:
    resolved = tr.verify_target_scope("android-lab/lab/tests/targets/hedef.c")
    assert resolved == tr.CANONICAL_TARGET.resolve()


@pytest.mark.parametrize(
    "bad_target",
    [
        "",
        "   ",
        " android-lab/lab/tests/targets/hedef.c",
        "android-lab/lab/tests/targets/hedef.c ",
        "android-lab/lab/tests/targets/hedef.c\n",
        "/bin/ls",
        "/usr/bin/passwd",
        r"C:\Windows\System32\cmd.exe",
        "../../etc/passwd",
        "https://example.com/hedef.c",
        "file:///etc/passwd",
        "12345",
        "com.example.banking",
        "android-lab/lab/tests/targets/nonexistent.c",
    ],
)
def test_scope_guard_refuses_non_lab_and_malformed_targets(bad_target: str) -> None:
    with pytest.raises(tr.ScopeViolationError):
        tr.verify_target_scope(bad_target)


def test_scope_guard_refuses_spoofed_hedef_in_temp_dir(tmp_path: Path) -> None:
    spoof = tmp_path / "hedef.c"
    spoof.write_text(
        '#define EXPECTED_PASS "gizli123"\n'
        "#define MIN_REQUIRED_LEVEL 1\n"
        "int parola_kontrol(const char *p, int l) { return 1; }\n",
        encoding="utf-8",
    )
    with pytest.raises(tr.ScopeViolationError):
        tr.verify_target_scope(spoof)


def test_scope_guard_refuses_unauthorized_hook_functions() -> None:
    policy = _load_fixture_policy("04_onleave_retval_replace")
    policy["rules"][0]["function"] = "system"
    with pytest.raises(tr.ScopeViolationError, match="hook unauthorized function"):
        tr.run_policy(policy)

    bad_target_fn = _load_fixture_policy("04_onleave_retval_replace")
    bad_target_fn["target"]["function"] = "execve"
    with pytest.raises(tr.ScopeViolationError, match="unauthorized target function"):
        tr.run_policy(bad_target_fn)


def test_scope_guard_refuses_symlink_and_reparse_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_rel = tr.CANONICAL_TARGET_REL
    monkeypatch.setattr(
        tr,
        "_is_reparse_or_symlink",
        lambda path: path.name == "hedef.c",
    )
    with pytest.raises(tr.ScopeViolationError, match="symlink or reparse point"):
        tr.verify_target_scope(target_rel)

    link_path = tmp_path / "hedef_link.c"
    try:
        os.symlink(tr.CANONICAL_TARGET, link_path)
    except (OSError, NotImplementedError):
        return
    monkeypatch.undo()
    with pytest.raises(tr.ScopeViolationError):
        tr.verify_target_scope(link_path)


def test_policy_validation_rejects_invalid_shapes(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(tr.PolicyValidationError):
        tr.load_policy(bad_json)

    base = _load_fixture_policy("02_observe_gozlem")

    # Unknown top-level key
    unknown = dict(base, extra_key="nope")
    with pytest.raises(tr.PolicyValidationError):
        tr.validate_policy(unknown)

    # Unsupported version
    bad_ver = dict(base, version=2)
    with pytest.raises(tr.PolicyValidationError):
        tr.validate_policy(bad_ver)

    # Out-of-bounds arg index
    bad_idx = _load_fixture_policy("03_onenter_arg_tamper")
    bad_idx["rules"][0]["onEnter"]["tamper_args"][0]["index"] = 5
    with pytest.raises(tr.PolicyValidationError):
        tr.validate_policy(bad_idx)


def test_frida_hook_and_c_harness_contracts() -> None:
    js_text = tr.HOOK_SCRIPT_PATH.read_text(encoding="utf-8")
    for required_token in (
        "Interceptor.attach",
        "onEnter",
        "onLeave",
        "retval.replace",
        "Memory.allocUtf8String",
        "rpc.exports",
        "ALLOWED_FUNCTIONS",
    ):
        assert required_token in js_text

    c_text = tr.CANONICAL_TARGET.read_text(encoding="utf-8")
    for required_c in (
        "parola_kontrol",
        "DEFAULT_INTERVAL_MS 2000",
        'EXPECTED_PASS "gizli123"',
    ):
        assert required_c in c_text

    # No compiled binary artifacts should remain in targets/
    entries = {p.name for p in tr.TARGETS_DIR.iterdir()}
    assert entries == {"hedef.c"}


def test_cli_exit_codes(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert tr.main(["--verify-golden"]) == 0
    captured = capsys.readouterr()
    assert "[OK]" in captured.out

    assert tr.main(["--check-scope", tr.CANONICAL_TARGET_REL]) == 0
    assert tr.main(["--check-scope", "/bin/sh"]) == 1

    out_file = tmp_path / "trace.json"
    code = tr.main(
        [
            "--policy",
            str(POLICIES_DIR / "04_onleave_retval_replace.json"),
            "--format",
            "json",
            "--output",
            str(out_file),
        ]
    )
    assert code == 0
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["summary"]["final_status"] == "ONAYLANDI"

    bad_policy = tmp_path / "invalid.json"
    bad_policy.write_text("{}", encoding="utf-8")
    assert tr.main(["--policy", str(bad_policy)]) == 2
