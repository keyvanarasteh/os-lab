#!/usr/bin/env python3
"""PENT-07 Policy-Driven Frida Interceptor Runner, Scope Guard & Golden Verifier.

Drives policy-based `onEnter` (argument observation/tampering) and `onLeave`
(`retval.replace`) experiments strictly against the isolated lab auth harness
(`android-lab/lab/tests/targets/hedef.c`).

Supports two execution modes:
- deterministic (default): reproduces the exact `hedef.c` + `tamper_policy.js`
  lifecycle offline with zero compiler or Frida runtime requirements (CI-safe).
- live: compiles `hedef.c` into an isolated temporary directory and attaches
  `android-lab/lab/hooks/tamper_policy.js` via Frida when available locally.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LAB_ROOT = REPO_ROOT / "android-lab" / "lab"
TARGETS_DIR = LAB_ROOT / "tests" / "targets"
CANONICAL_TARGET = TARGETS_DIR / "hedef.c"
CANONICAL_TARGET_REL = "android-lab/lab/tests/targets/hedef.c"
HOOK_SCRIPT_PATH = LAB_ROOT / "hooks" / "tamper_policy.js"
DEFAULT_FIXTURES_DIR = LAB_ROOT / "tests" / "fixtures" / "pent07"

ALLOWED_FUNCTIONS = frozenset({"parola_kontrol", "check_password"})
ALLOWED_ARG_TYPES = frozenset({"utf8", "int32", "uint32", "pointer"})
ALLOWED_RET_TYPES = frozenset({"int32", "uint32"})
POLICY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

TOP_LEVEL_KEYS = frozenset(
    {"version", "policy_id", "description", "target", "schedule", "inputs", "rules"}
)
TARGET_KEYS = frozenset({"source", "function", "module"})
SCHEDULE_KEYS = frozenset({"iterations", "interval_ms"})
INPUTS_KEYS = frozenset({"parola", "yetki_seviyesi"})
RULE_KEYS = frozenset({"function", "onEnter", "onLeave"})
ON_ENTER_KEYS = frozenset({"observe_args", "tamper_args"})
OBSERVE_ARG_KEYS = frozenset({"index", "name", "type"})
TAMPER_ARG_KEYS = frozenset({"index", "name", "type", "value", "when_equals"})
ON_LEAVE_KEYS = frozenset({"observe_retval", "retval_replace"})
RETVAL_REPLACE_KEYS = frozenset({"enabled", "when_equals", "value", "type"})

DEFAULT_EXPECTED_PASS = "gizli123"
DEFAULT_MIN_LEVEL = 1


class ScopeViolationError(PermissionError):
    """Raised when a target, file path, or hook function violates lab scope."""


class PolicyValidationError(ValueError):
    """Raised when a policy file cannot be parsed or fails schema validation."""


@dataclass(frozen=True)
class HarnessSpec:
    """Authoritative auth constants extracted from `hedef.c`."""

    expected_pass: str
    min_required_level: int


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and (attrs & reparse_flag))


def _assert_no_link_escape(candidate: Path, stop_at: Path) -> None:
    current = candidate
    stop_norm = os.path.normcase(str(stop_at.resolve()))
    while True:
        if _is_reparse_or_symlink(current):
            raise ScopeViolationError(
                f"Scope violation: symlink or reparse point is not permitted: {current}"
            )
        if os.path.normcase(os.path.abspath(str(current))) == stop_norm:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def _validate_raw_target_string(raw: str) -> None:
    if not raw:
        raise ScopeViolationError("Scope violation: empty target path.")
    if raw != raw.strip():
        raise ScopeViolationError("Scope violation: target path has leading or trailing whitespace.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise ScopeViolationError("Scope violation: target path contains control characters.")
    lower = raw.lower()
    if "://" in raw or lower.startswith("file:"):
        raise ScopeViolationError(f"Scope violation: remote/URL targets are forbidden: {raw}")
    if raw.isdigit():
        raise ScopeViolationError(f"Scope violation: arbitrary process PID targets are forbidden: {raw}")
    if re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){2,}", raw) and not lower.endswith(".c"):
        raise ScopeViolationError(f"Scope violation: package/app targets are outside PENT-07 scope: {raw}")


def _resolve_candidate_path(raw: str) -> Path:
    raw_path = Path(raw)
    if raw_path.is_absolute():
        return raw_path
    repo_candidate = REPO_ROOT / raw_path
    if repo_candidate.exists() or os.path.lexists(repo_candidate):
        return repo_candidate
    return Path.cwd() / raw_path


def _extract_harness_spec(target_path: Path) -> HarnessSpec:
    text = target_path.read_text(encoding="utf-8")
    if "int parola_kontrol(" not in text:
        raise ScopeViolationError(
            "Scope violation: target file does not define the canonical parola_kontrol harness."
        )
    pass_match = re.search(r'#define\s+EXPECTED_PASS\s+"([^"]+)"', text)
    level_match = re.search(r"#define\s+MIN_REQUIRED_LEVEL\s+(-?\d+)", text)
    if not pass_match or not level_match:
        raise ScopeViolationError(
            "Scope violation: target file is missing EXPECTED_PASS or MIN_REQUIRED_LEVEL definitions."
        )
    return HarnessSpec(
        expected_pass=pass_match.group(1),
        min_required_level=int(level_match.group(1)),
    )


def verify_target_scope(target_path: str | Path, policy: dict[str, Any] | None = None) -> Path:
    """Enforce fail-closed lab scope: allow only the canonical `hedef.c` target and functions."""
    if not isinstance(target_path, (str, Path)):
        raise ScopeViolationError("Scope violation: target path must be a string or Path.")

    raw = str(target_path)
    _validate_raw_target_string(raw)

    canonical_dir = TARGETS_DIR.resolve(strict=True)
    canonical_file = CANONICAL_TARGET.resolve(strict=True)
    candidate = _resolve_candidate_path(raw)

    if not candidate.exists() and not os.path.lexists(candidate):
        raise ScopeViolationError(f"Scope violation: target does not exist: {raw}")

    _assert_no_link_escape(candidate, REPO_ROOT)
    resolved = candidate.resolve(strict=True)

    if os.path.commonpath([str(canonical_dir), str(resolved)]) != str(canonical_dir):
        raise ScopeViolationError(
            f"Scope violation: target escapes authorized targets directory: {raw}"
        )
    if os.path.normcase(str(resolved)) != os.path.normcase(str(canonical_file)):
        raise ScopeViolationError(
            f"Scope violation: only {CANONICAL_TARGET_REL} is authorized, got: {raw}"
        )
    if not resolved.is_file():
        raise ScopeViolationError(f"Scope violation: target is not a regular file: {raw}")

    _extract_harness_spec(resolved)

    if policy is not None:
        _verify_policy_scope(policy)

    return resolved


def _verify_policy_scope(policy: dict[str, Any]) -> None:
    target_cfg = policy.get("target")
    if not isinstance(target_cfg, dict):
        raise ScopeViolationError("Scope violation: policy target block is missing.")
    source = target_cfg.get("source")
    if not isinstance(source, str):
        raise ScopeViolationError("Scope violation: policy target.source must be a string.")
    verify_target_scope(source)

    fn = target_cfg.get("function")
    if fn not in ALLOWED_FUNCTIONS:
        raise ScopeViolationError(f"Scope violation: unauthorized target function: {fn!r}")

    for idx, rule in enumerate(policy.get("rules", [])):
        rule_fn = rule.get("function")
        if rule_fn not in ALLOWED_FUNCTIONS:
            raise ScopeViolationError(
                f"Scope violation: rule[{idx}] attempts to hook unauthorized function: {rule_fn!r}"
            )


def _check_keys(obj: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise PolicyValidationError(
            f"Unknown key(s) in {context}: {', '.join(sorted(unknown))}"
        )


def _parse_yaml_scalar(raw_val: str) -> Any:
    val = raw_val.strip()
    if val in ("true", "True"):
        return True
    if val in ("false", "False"):
        return False
    if val in ("null", "None", "~"):
        return None
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:idx]
    return line


def _parse_basic_yaml(text: str) -> dict[str, Any]:
    """Parse JSON-compatible YAML or simple key/list YAML without third-party dependencies."""
    try:
        ruamel_yaml = importlib.import_module("ruamel.yaml")
        loader = ruamel_yaml.YAML(typ="safe")
        loaded = loader.load(text)
        if not isinstance(loaded, dict):
            raise PolicyValidationError("Policy root must be a mapping/object.")
        return loaded
    except ImportError:
        pass
    except Exception as exc:
        raise PolicyValidationError(f"Invalid YAML policy: {exc}") from exc

    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        cleaned = _strip_yaml_comment(raw_line).rstrip()
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        lines.append((indent, cleaned.strip()))

    if not lines:
        raise PolicyValidationError("Empty YAML policy file.")

    def parse_block(idx: int, min_indent: int) -> tuple[Any, int]:
        indent, content = lines[idx]
        if content.startswith("- "):
            items: list[Any] = []
            while idx < len(lines) and lines[idx][0] == indent and lines[idx][1].startswith("- "):
                item_text = lines[idx][1][2:].strip()
                if ":" in item_text and not item_text.startswith(("'", '"')):
                    k, _, v = item_text.partition(":")
                    entry: dict[str, Any] = {k.strip(): _parse_yaml_scalar(v) if v.strip() else None}
                    idx += 1
                    if not v.strip() and idx < len(lines) and lines[idx][0] > indent:
                        nested, idx = parse_block(idx, indent + 1)
                        entry[k.strip()] = nested
                    if idx < len(lines) and lines[idx][0] > indent and not lines[idx][1].startswith("- "):
                        extra, idx = parse_block(idx, indent + 1)
                        if isinstance(extra, dict):
                            entry.update(extra)
                    items.append(entry)
                else:
                    items.append(_parse_yaml_scalar(item_text))
                    idx += 1
            return items, idx

        mapping: dict[str, Any] = {}
        while idx < len(lines) and lines[idx][0] >= min_indent:
            cur_indent, cur_text = lines[idx]
            if cur_indent != indent or cur_text.startswith("- "):
                break
            if ":" not in cur_text:
                raise PolicyValidationError(f"Malformed YAML line: {cur_text}")
            key, _, val = cur_text.partition(":")
            key_clean = key.strip()
            val_clean = val.strip()
            idx += 1
            if val_clean in ("[]", "{}"):
                mapping[key_clean] = [] if val_clean == "[]" else {}
            elif val_clean:
                mapping[key_clean] = _parse_yaml_scalar(val_clean)
            elif idx < len(lines) and lines[idx][0] > cur_indent:
                nested_val, idx = parse_block(idx, cur_indent + 1)
                mapping[key_clean] = nested_val
            else:
                mapping[key_clean] = None
        return mapping, idx

    parsed, _ = parse_block(0, 0)
    if not isinstance(parsed, dict):
        raise PolicyValidationError("Policy root must be a mapping/object.")
    return parsed


def _validate_arg_spec(spec: Any, ctx: str, require_value: bool) -> None:
    if not isinstance(spec, dict):
        raise PolicyValidationError(f"{ctx} must be an object.")
    allowed = TAMPER_ARG_KEYS if require_value else OBSERVE_ARG_KEYS
    _check_keys(spec, allowed, ctx)

    idx = spec.get("index")
    if not _is_strict_int(idx) or idx not in (0, 1):
        raise PolicyValidationError(f"{ctx}.index must be 0 or 1.")

    arg_type = spec.get("type")
    if arg_type not in ALLOWED_ARG_TYPES:
        raise PolicyValidationError(f"{ctx}.type must be one of {sorted(ALLOWED_ARG_TYPES)}.")

    if "name" in spec and (not isinstance(spec["name"], str) or not spec["name"].strip()):
        raise PolicyValidationError(f"{ctx}.name must be a non-empty string.")

    if not require_value:
        return

    if "value" not in spec:
        raise PolicyValidationError(f"{ctx}.value is required.")
    val = spec["value"]
    if arg_type == "utf8" and not isinstance(val, str):
        raise PolicyValidationError(f"{ctx}.value must be a string when type is 'utf8'.")
    if arg_type in ("int32", "uint32") and not _is_strict_int(val):
        raise PolicyValidationError(f"{ctx}.value must be an integer when type is {arg_type!r}.")


def _validate_on_enter(on_enter: Any, ctx: str) -> None:
    if not isinstance(on_enter, dict):
        raise PolicyValidationError(f"{ctx} must be an object.")
    _check_keys(on_enter, ON_ENTER_KEYS, ctx)

    observe_args = on_enter.get("observe_args", [])
    if not isinstance(observe_args, list):
        raise PolicyValidationError(f"{ctx}.observe_args must be a list.")
    for i, item in enumerate(observe_args):
        _validate_arg_spec(item, f"{ctx}.observe_args[{i}]", require_value=False)

    tamper_args = on_enter.get("tamper_args", [])
    if not isinstance(tamper_args, list):
        raise PolicyValidationError(f"{ctx}.tamper_args must be a list.")
    for i, item in enumerate(tamper_args):
        _validate_arg_spec(item, f"{ctx}.tamper_args[{i}]", require_value=True)


def _validate_on_leave(on_leave: Any, ctx: str) -> None:
    if not isinstance(on_leave, dict):
        raise PolicyValidationError(f"{ctx} must be an object.")
    _check_keys(on_leave, ON_LEAVE_KEYS, ctx)

    if "observe_retval" in on_leave and not isinstance(on_leave["observe_retval"], bool):
        raise PolicyValidationError(f"{ctx}.observe_retval must be a boolean.")

    rep = on_leave.get("retval_replace")
    if rep is None:
        return
    if not isinstance(rep, dict):
        raise PolicyValidationError(f"{ctx}.retval_replace must be an object.")
    _check_keys(rep, RETVAL_REPLACE_KEYS, f"{ctx}.retval_replace")
    if not isinstance(rep.get("enabled"), bool):
        raise PolicyValidationError(f"{ctx}.retval_replace.enabled must be a boolean.")
    if "type" in rep and rep["type"] not in ALLOWED_RET_TYPES:
        raise PolicyValidationError(
            f"{ctx}.retval_replace.type must be one of {sorted(ALLOWED_RET_TYPES)}."
        )
    if "when_equals" in rep and not _is_strict_int(rep["when_equals"]):
        raise PolicyValidationError(f"{ctx}.retval_replace.when_equals must be an integer.")
    if rep["enabled"] and not _is_strict_int(rep.get("value")):
        raise PolicyValidationError(f"{ctx}.retval_replace.value must be an integer.")


def validate_policy(data: Any) -> None:
    """Validate structure, types, and bounds of a loaded PENT-07 policy dictionary."""
    if not isinstance(data, dict):
        raise PolicyValidationError("Policy root must be a JSON/YAML object.")
    _check_keys(data, TOP_LEVEL_KEYS, "policy")

    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise PolicyValidationError("policy.version must be integer 1.")

    policy_id = data.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id or not POLICY_ID_RE.match(policy_id):
        raise PolicyValidationError("policy.policy_id must match ^[A-Za-z0-9_.-]+$.")

    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        raise PolicyValidationError("policy.description must be a non-empty string.")

    target = data.get("target")
    if not isinstance(target, dict):
        raise PolicyValidationError("policy.target must be an object.")
    _check_keys(target, TARGET_KEYS, "policy.target")
    if not isinstance(target.get("source"), str) or not target["source"].strip():
        raise PolicyValidationError("policy.target.source must be a non-empty string.")
    if not isinstance(target.get("function"), str) or not target["function"].strip():
        raise PolicyValidationError("policy.target.function must be a non-empty string.")

    schedule = data.get("schedule")
    if not isinstance(schedule, dict):
        raise PolicyValidationError("policy.schedule must be an object.")
    _check_keys(schedule, SCHEDULE_KEYS, "policy.schedule")
    iters = schedule.get("iterations")
    interval = schedule.get("interval_ms")
    if not _is_strict_int(iters) or not 1 <= iters <= 20:
        raise PolicyValidationError("policy.schedule.iterations must be an integer in 1..20.")
    if not _is_strict_int(interval) or not 0 <= interval <= 10000:
        raise PolicyValidationError("policy.schedule.interval_ms must be an integer in 0..10000.")

    inputs = data.get("inputs")
    if not isinstance(inputs, dict):
        raise PolicyValidationError("policy.inputs must be an object.")
    _check_keys(inputs, INPUTS_KEYS, "policy.inputs")
    if not isinstance(inputs.get("parola"), str):
        raise PolicyValidationError("policy.inputs.parola must be a string.")
    if not _is_strict_int(inputs.get("yetki_seviyesi")):
        raise PolicyValidationError("policy.inputs.yetki_seviyesi must be an integer.")

    rules = data.get("rules")
    if not isinstance(rules, list):
        raise PolicyValidationError("policy.rules must be a list.")
    for idx, rule in enumerate(rules):
        ctx = f"policy.rules[{idx}]"
        if not isinstance(rule, dict):
            raise PolicyValidationError(f"{ctx} must be an object.")
        _check_keys(rule, RULE_KEYS, ctx)
        if not isinstance(rule.get("function"), str) or not rule["function"].strip():
            raise PolicyValidationError(f"{ctx}.function must be a non-empty string.")
        if "onEnter" in rule:
            _validate_on_enter(rule["onEnter"], f"{ctx}.onEnter")
        if "onLeave" in rule:
            _validate_on_leave(rule["onLeave"], f"{ctx}.onLeave")


def load_policy(path: str | Path) -> dict[str, Any]:
    """Read, parse (JSON or YAML), and validate a PENT-07 policy file."""
    policy_path = Path(path)
    if not policy_path.is_file():
        raise PolicyValidationError(f"Policy file not found: {policy_path}")

    try:
        text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyValidationError(f"Cannot read policy file {policy_path}: {exc}") from exc

    suffix = policy_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = _parse_basic_yaml(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PolicyValidationError(f"Invalid JSON in {policy_path}: {exc}") from exc

    validate_policy(data)
    return data


def _read_arg_value(args: list[Any], spec: dict[str, Any]) -> Any:
    val = args[spec["index"]]
    if spec["type"] == "utf8":
        return str(val)
    if spec["type"] in ("int32", "uint32"):
        return int(val)
    return str(val)


def _apply_on_enter(
    rules: list[dict[str, Any]], args: list[Any]
) -> tuple[dict[str, Any], list[Any]]:
    if not rules:
        return {"hooked": False, "observed_args": {}, "tampered_args": []}, list(args)

    observed: dict[str, Any] = {}
    tampered: list[dict[str, Any]] = []
    effective = list(args)

    for rule in rules:
        on_enter = rule.get("onEnter", {})
        for spec in on_enter.get("observe_args", []):
            key = spec.get("name") or f"arg{spec['index']}"
            observed[key] = _read_arg_value(effective, spec)

        for tamper in on_enter.get("tamper_args", []):
            idx = tamper["index"]
            current = _read_arg_value(effective, tamper)
            if "when_equals" in tamper and current != tamper["when_equals"]:
                continue
            new_val = str(tamper["value"]) if tamper["type"] == "utf8" else int(tamper["value"])
            effective[idx] = new_val
            tampered.append(
                {
                    "index": idx,
                    "name": tamper.get("name") or f"arg{idx}",
                    "type": tamper["type"],
                    "before": current,
                    "after": new_val,
                }
            )

    return {
        "hooked": True,
        "observed_args": observed,
        "tampered_args": tampered,
    }, effective


def _apply_on_leave(
    rules: list[dict[str, Any]], native_retval: int
) -> dict[str, Any]:
    if not rules:
        return {
            "hooked": False,
            "observed_retval": None,
            "retval_replaced": False,
            "final_retval": native_retval,
        }

    observe_ret = any(rule.get("onLeave", {}).get("observe_retval", True) for rule in rules)
    observed_val: int | None = native_retval if observe_ret else None
    current_ret = native_retval
    replaced = False

    for rule in rules:
        rep = rule.get("onLeave", {}).get("retval_replace")
        if not rep or not rep.get("enabled"):
            continue
        if "when_equals" in rep and current_ret != rep["when_equals"]:
            continue
        current_ret = int(rep["value"])
        replaced = True

    return {
        "hooked": True,
        "observed_retval": observed_val,
        "retval_replaced": replaced,
        "final_retval": current_ret,
    }


def _evaluate_native_parola_kontrol(
    girilen_parola: str, yetki_seviyesi: int, spec: HarnessSpec
) -> int:
    if girilen_parola == spec.expected_pass and yetki_seviyesi >= spec.min_required_level:
        return 1
    return 0


def run_policy(policy: dict[str, Any], target_path: str | Path = CANONICAL_TARGET) -> dict[str, Any]:
    """Verify scope and deterministically execute a policy against the lab `hedef.c` harness."""
    validate_policy(policy)
    resolved_target = verify_target_scope(target_path, policy)
    spec = _extract_harness_spec(resolved_target)

    target_fn = policy["target"]["function"]
    matching_rules = [r for r in policy["rules"] if r["function"] == target_fn]
    iterations = policy["schedule"]["iterations"]
    interval_ms = policy["schedule"]["interval_ms"]
    base_pass = policy["inputs"]["parola"]
    base_level = policy["inputs"]["yetki_seviyesi"]

    records: list[dict[str, Any]] = []
    approved_calls = 0
    arg_tampers_total = 0
    retval_replacements_total = 0

    for idx in range(1, iterations + 1):
        elapsed_ms = (idx - 1) * interval_ms
        initial_args: list[Any] = [base_pass, base_level]
        on_enter_res, effective_args = _apply_on_enter(matching_rules, initial_args)
        native_retval = _evaluate_native_parola_kontrol(
            str(effective_args[0]), int(effective_args[1]), spec
        )
        on_leave_res = _apply_on_leave(matching_rules, native_retval)

        final_retval = on_leave_res["final_retval"]
        durum = "ONAYLANDI" if final_retval == 1 else "REDDEDILDI"
        approved_calls += int(final_retval == 1)
        arg_tampers_total += len(on_enter_res["tampered_args"])
        retval_replacements_total += int(on_leave_res["retval_replaced"])

        records.append(
            {
                "iteration": idx,
                "total_iterations": iterations,
                "elapsed_ms": elapsed_ms,
                "caller_inputs": {
                    "parola": base_pass,
                    "yetki_seviyesi": base_level,
                },
                "onEnter": on_enter_res,
                "effective_args": {
                    "girilen_parola": str(effective_args[0]),
                    "yetki_seviyesi": int(effective_args[1]),
                },
                "native_retval": native_retval,
                "onLeave": on_leave_res,
                "durum": durum,
            }
        )

    rejected_calls = iterations - approved_calls
    final_status = "ONAYLANDI" if approved_calls == iterations else "REDDEDILDI"

    return {
        "schema_version": 1,
        "task_id": "PENT-07",
        "policy_id": policy["policy_id"],
        "target": {
            "source": CANONICAL_TARGET_REL,
            "function": target_fn,
            "scope_verified": True,
        },
        "schedule": {
            "iterations": iterations,
            "interval_ms": interval_ms,
        },
        "inputs": {
            "parola": base_pass,
            "yetki_seviyesi": base_level,
        },
        "summary": {
            "total_calls": iterations,
            "approved_calls": approved_calls,
            "rejected_calls": rejected_calls,
            "arg_tampers_applied": arg_tampers_total,
            "retval_replacements_applied": retval_replacements_total,
            "final_status": final_status,
        },
        "iterations": records,
    }


def _has_trusted_tool(name: str) -> bool:
    """Return True if `name` resolves outside the repo and current working directory."""
    resolved = shutil.which(name)
    if not resolved:
        return False
    folder = os.path.normcase(os.path.dirname(os.path.abspath(resolved)))
    untrusted = {
        os.path.normcase(os.path.abspath(d))
        for d in (os.getcwd(), str(REPO_ROOT), str(LAB_ROOT))
    }
    return folder not in untrusted


def _compile_harness(resolved_target: Path, binary_path: Path) -> None:
    """Compile the scope-verified `hedef.c` harness with a static compiler argv."""
    flags = ("-O0", "-g", "-fno-inline", str(resolved_target), "-o", str(binary_path))
    if _has_trusted_tool("gcc"):
        # Audited: static compiler literal, shell=False, and scope-verified CANONICAL_TARGET only.
        subprocess.run(  # nosec B603,B607  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit, python.lang.security.audit.dangerous-subprocess-use
            ["gcc", *flags],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        return
    if _has_trusted_tool("clang"):
        # Audited: static compiler literal, shell=False, and scope-verified CANONICAL_TARGET only.
        subprocess.run(  # nosec B603,B607  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit, python.lang.security.audit.dangerous-subprocess-use
            ["clang", *flags],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        return
    raise RuntimeError("No C compiler (gcc/clang) found on PATH for live Frida mode.")


def run_live_frida(policy: dict[str, Any], target_path: str | Path = CANONICAL_TARGET) -> dict[str, Any]:
    """Compile `hedef.c` into a temporary directory and attach `tamper_policy.js` via Frida."""
    validate_policy(policy)
    resolved_target = verify_target_scope(target_path, policy)
    if not HOOK_SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"Hook script missing: {HOOK_SCRIPT_PATH}")

    if not (_has_trusted_tool("gcc") or _has_trusted_tool("clang")):
        raise RuntimeError("No C compiler (gcc/clang) found on PATH for live Frida mode.")

    try:
        frida_mod = importlib.import_module("frida")
    except ImportError as exc:
        raise RuntimeError("Python 'frida' package is not installed for live Frida mode.") from exc

    hook_source = HOOK_SCRIPT_PATH.read_text(encoding="utf-8")
    events: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="pent07-live-") as tmp_dir:
        exe_name = "hedef.exe" if os.name == "nt" else "hedef"
        binary_path = Path(tmp_dir) / exe_name
        _compile_harness(resolved_target, binary_path)

        argv = [
            str(binary_path),
            "--pass",
            policy["inputs"]["parola"],
            "--level",
            str(policy["inputs"]["yetki_seviyesi"]),
            "--iterations",
            str(policy["schedule"]["iterations"]),
            "--interval-ms",
            str(policy["schedule"]["interval_ms"]),
        ]
        pid = frida_mod.spawn(argv)
        session = frida_mod.attach(pid)
        try:
            script = session.create_script(hook_source)

            def _on_message(message: dict[str, Any], _data: Any) -> None:
                if message.get("type") == "send":
                    payload = message.get("payload", {})
                    if isinstance(payload, dict) and payload.get("type") == "pent07:event":
                        events.append(payload.get("payload", {}))

            script.on("message", _on_message)
            script.load()
            script.exports_sync.apply_policy(policy)
            frida_mod.resume(pid)
            # Wait briefly for spawned iterations to finish before detaching cleanly.
            deadline_sec = (
                max(1, policy["schedule"]["iterations"] - 1)
                * policy["schedule"]["interval_ms"]
                / 1000.0
            ) + 2.0
            import time

            time.sleep(deadline_sec)
        finally:
            session.detach()

    return {
        "schema_version": 1,
        "task_id": "PENT-07",
        "mode": "live-frida",
        "policy_id": policy["policy_id"],
        "events": events,
    }


def format_trace_text(result: dict[str, Any]) -> str:
    """Format a deterministic execution result into canonical trace lines."""
    target = result["target"]
    schedule = result["schedule"]
    inputs = result["inputs"]
    summary = result["summary"]
    fn_name = target["function"]
    hook_active = any(it["onEnter"]["hooked"] or it["onLeave"]["hooked"] for it in result["iterations"])

    lines = [
        f"[PENT-07] policy={result['policy_id']} | target={target['source']} "
        f"| fn={fn_name} | scope={'VERIFIED' if target['scope_verified'] else 'FAILED'}",
        f"[PENT-07] schedule={schedule['iterations']}x{schedule['interval_ms']}ms "
        f"| inputs=parola:{json.dumps(inputs['parola'])},yetki_seviyesi:{inputs['yetki_seviyesi']} "
        f"| hook_active={'true' if hook_active else 'false'}",
    ]

    for it in result["iterations"]:
        t_ms = it["elapsed_ms"]
        on_enter = it["onEnter"]
        on_leave = it["onLeave"]
        eff = it["effective_args"]
        caller = it["caller_inputs"]

        if on_enter["hooked"]:
            obs_json = json.dumps(on_enter["observed_args"], sort_keys=True)
            tamp_json = json.dumps(on_enter["tampered_args"], sort_keys=True)
            lines.append(
                f"[t={t_ms}ms] [INTERCEPTOR] onEnter {fn_name} | observed={obs_json} | tampered={tamp_json}"
            )

        lines.append(
            f"[t={t_ms}ms] [HEDEF] native {fn_name}("
            f"{json.dumps(eff['girilen_parola'])}, {eff['yetki_seviyesi']}) -> {it['native_retval']}"
        )

        if on_leave["hooked"]:
            obs_ret = "null" if on_leave["observed_retval"] is None else str(on_leave["observed_retval"])
            rep_flag = "true" if on_leave["retval_replaced"] else "false"
            lines.append(
                f"[t={t_ms}ms] [INTERCEPTOR] onLeave {fn_name} "
                f"| observed_retval={obs_ret} | final_retval={on_leave['final_retval']} "
                f"| retval_replaced={rep_flag}"
            )

        lines.append(
            f"[t={t_ms}ms] [HEDEF] iter={it['iteration']}/{it['total_iterations']} "
            f"| girilen={json.dumps(caller['parola'])} | seviye={caller['yetki_seviyesi']} "
            f"| sonuc={on_leave['final_retval']} | durum={it['durum']}"
        )

    lines.append(
        f"[SUMMARY] calls={summary['total_calls']} | approved={summary['approved_calls']} "
        f"| rejected={summary['rejected_calls']} | arg_tampers={summary['arg_tampers_applied']} "
        f"| retval_replacements={summary['retval_replacements_applied']} "
        f"| final={summary['final_status']}"
    )
    return "\n".join(lines) + "\n"


def verify_golden_suite(
    fixtures_dir: Path | None = None, target_path: Path = CANONICAL_TARGET
) -> tuple[bool, list[str]]:
    """Run every policy fixture and compare text + JSON outputs against golden files."""
    base = fixtures_dir or DEFAULT_FIXTURES_DIR
    policies_dir = base / "policies"
    golden_dir = base / "golden"

    if not policies_dir.is_dir():
        return False, [f"[FAIL] missing policies directory: {policies_dir}"]

    policy_files = sorted(policies_dir.glob("*.json"))
    if not policy_files:
        return False, [f"[FAIL] no policy fixtures found in: {policies_dir}"]

    messages: list[str] = []
    all_ok = True

    for policy_file in policy_files:
        stem = policy_file.stem
        golden_txt_path = golden_dir / f"{stem}.golden.txt"
        golden_json_path = golden_dir / f"{stem}.golden.json"

        try:
            policy = load_policy(policy_file)
            result = run_policy(policy, target_path=target_path)
        except (PolicyValidationError, ScopeViolationError, OSError) as exc:
            all_ok = False
            messages.append(f"[FAIL] {stem}: execution error: {exc}")
            continue

        actual_txt = format_trace_text(result)
        actual_json = json.dumps(result, indent=2) + "\n"

        if not golden_txt_path.is_file() or not golden_json_path.is_file():
            all_ok = False
            messages.append(f"[FAIL] {stem}: missing golden file(s) in {golden_dir}")
            continue

        expected_txt = golden_txt_path.read_text(encoding="utf-8")
        expected_json = golden_json_path.read_text(encoding="utf-8")

        if actual_txt != expected_txt:
            all_ok = False
            messages.append(f"[FAIL] {stem}: text trace mismatch against {golden_txt_path.name}")
            continue
        if actual_json != expected_json:
            all_ok = False
            messages.append(f"[FAIL] {stem}: JSON output mismatch against {golden_json_path.name}")
            continue

        messages.append(
            f"[OK]   {stem} (calls={result['summary']['total_calls']}, "
            f"final={result['summary']['final_status']})"
        )

    return all_ok, messages


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PENT-07 Policy-Driven Frida Interceptor Runner & Golden Verifier"
    )
    parser.add_argument("--policy", help="Path to a JSON/YAML interceptor policy file.")
    parser.add_argument(
        "--target",
        default=str(CANONICAL_TARGET),
        help="Path to the authorized lab C target (default: android-lab/lab/tests/targets/hedef.c).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format when running a policy.",
    )
    parser.add_argument(
        "--mode",
        choices=("deterministic", "live"),
        default="deterministic",
        help="Execution backend: deterministic CI runner or live Frida injection.",
    )
    parser.add_argument("--output", help="Optional path to write rendered output.")
    parser.add_argument(
        "--verify-golden",
        action="store_true",
        help="Run all fixture policies and assert exact match against golden files.",
    )
    parser.add_argument(
        "--check-scope",
        help="Check whether a target path is allowed by the PENT-07 Scope Guard.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.check_scope is not None:
        try:
            resolved = verify_target_scope(args.check_scope)
            print(f"[ALLOW] {resolved}")
            return 0
        except ScopeViolationError as exc:
            print(f"[DENY] {exc}", file=sys.stderr)
            return 1

    if args.verify_golden:
        try:
            target = verify_target_scope(args.target)
        except ScopeViolationError as exc:
            print(f"[DENY] {exc}", file=sys.stderr)
            return 1
        ok, msgs = verify_golden_suite(target_path=target)
        for msg in msgs:
            print(msg)
        return 0 if ok else 1

    if not args.policy:
        parser.print_usage(sys.stderr)
        print("Error: specify --policy, --verify-golden, or --check-scope.", file=sys.stderr)
        return 2

    try:
        policy = load_policy(args.policy)
    except PolicyValidationError as exc:
        print(f"[POLICY-ERROR] {exc}", file=sys.stderr)
        return 2

    try:
        if args.mode == "live":
            result = run_live_frida(policy, target_path=args.target)
            rendered = json.dumps(result, indent=2) + "\n"
        else:
            result = run_policy(policy, target_path=args.target)
            rendered = (
                json.dumps(result, indent=2) + "\n"
                if args.format == "json"
                else format_trace_text(result)
            )
    except ScopeViolationError as exc:
        print(f"[DENY] {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[LIVE-ERROR] {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
