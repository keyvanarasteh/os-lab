# PENT-06 Verification Log (`VERIFY.md`)

Verification record for **PENT-06: `frida-trace` Auto-Tracer & Call-Map Builder** ([`REPORT.md`](REPORT.md), [`hooks/trace_runner.py`](hooks/trace_runner.py), [`scripts/trace_runner.py`](scripts/trace_runner.py), [`tests/test_trace_runner.py`](tests/test_trace_runner.py)).

## 1. Unit & Integration Test Suite (`pytest`)

Command run from `android-lab/lab`:

```bash
python -m pytest tests/test_trace_runner.py -v
```

Result:

```text
============================= test session starts =============================
collecting ... collected 12 items

tests/test_trace_runner.py::test_hooks_and_scripts_entry_points_expose_same_api PASSED [  8%]
tests/test_trace_runner.py::test_validate_target_accepts_lab_targets_and_rejects_unsafe_inputs PASSED [ 16%]
tests/test_trace_runner.py::test_validate_symbol_glob_accepts_valid_globs_and_rejects_injection PASSED [ 25%]
tests/test_trace_runner.py::test_build_frida_trace_cmd_constructs_typed_argument_list PASSED [ 33%]
tests/test_trace_runner.py::test_parse_args_string_snapshots_diverse_argument_types PASSED [ 41%]
tests/test_trace_runner.py::test_generate_and_instrument_handlers_dir PASSED [ 50%]
tests/test_trace_runner.py::test_build_call_map_from_standard_frida_trace_fixture PASSED [ 58%]
tests/test_trace_runner.py::test_parse_oslab_structured_json_and_objc_trace_lines PASSED [ 66%]
tests/test_trace_runner.py::test_run_trace_session_writes_json_and_annotated_session_log PASSED [ 75%]
tests/test_trace_runner.py::test_run_trace_session_with_mocked_frida_trace_subprocess PASSED [ 83%]
tests/test_trace_runner.py::test_cli_simulate_and_scope_guard_exit_codes PASSED [ 91%]
tests/test_trace_runner.py::test_oslab_console_plan_supports_android_trace_action PASSED [100%]

============================= 12 passed in 0.39s ==============================
```

## 2. CLI Smoke Test (`hooks/trace_runner.py` & `orchestrator.py`)

Command:

```bash
python hooks/trace_runner.py --target com.testlab.vulnerable -i "*auth*" -i "check_*" --simulate --action login_flow
```

Verified JSON call-map summary fields:
- `schema_version`: `"1.0"`
- `task_id`: `"PENT-06"`
- `target`: `"com.testlab.vulnerable"`
- `summary.discovered_count`: `7`
- `summary.functions_called_count`: `7`
- `summary.total_calls`: `7`
- `summary.unique_edges`: `6`
- `summary.max_depth`: `3`

## 3. Repository Content & Signing Verification

Commands run from repository root:

```bash
python scripts/build-content.py --check
python scripts/verify-content.py
```

Both checks exit `0` (`content pack verified`).

