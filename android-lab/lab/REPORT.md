# PENT-06: `frida-trace` Auto-Tracer & Call-Map Builder — Technical Report

## Overview

Task **PENT-06** (`frida-trace Auto-Tracer & Call-Map Builder`, Teached `05.10`) provides an automated function discovery, runtime argument-snapshot tracer, and structured JSON call-map builder around `frida-trace` for authorized lab targets.

### Deliverables

1. **Hook & Script Entry Points**:
   - [`hooks/trace_runner.py`](hooks/trace_runner.py) — Primary entry point under `android-lab/lab/hooks/` matching the PENT-06 deliverable path.
   - [`scripts/trace_runner.py`](scripts/trace_runner.py) — Core standard-library implementation under `android-lab/lab/scripts/` alongside the other Android Lab analysis modules.
2. **CLI & Console Action Integration**:
   - [`../../labctl`](../../labctl) — `labctl android trace` (and `labctl trace`) command saving both `call-map.json` and an annotated Markdown session log (`trace-session.md`) under `artifacts/traces/`.
   - [`../../console/oslab.py`](../../console/oslab.py) — `trace` action registered in `LABCTL_ACTIONS` and `ACTION_INFO` with target and symbol-glob validation in `oslab.plan()`.
   - [`orchestrator.py`](orchestrator.py) & [`Makefile`](Makefile) — `python3 orchestrator.py trace` subcommand and `make trace` target.
3. **Deterministic Unit & Integration Test Suite**:
   - [`tests/test_trace_runner.py`](tests/test_trace_runner.py) — 12 deterministic `pytest` tests exercising target/glob scope guards, command construction, handler generation, `__handlers__` instrumentation, argument snapshot parsing, call-hierarchy construction, and `oslab.plan()` integration without requiring a live rooted device in CI.
4. **Knowledge Graph & Documentation**:
   - [`../../lat.md/android-lab.md`](../../lat.md/android-lab.md), [`../../lat.md/labctl.md`](../../lat.md/labctl.md), [`../../lat.md/tooling.md`](../../lat.md/tooling.md), and [`README.md`](README.md).
   - [`VERIFY.md`](VERIFY.md) — Reproducible verification log and output transcripts.

---

## Architecture & Key Capabilities

### 1. Authorization & Target Scope Guardrails
- `validate_target()` rejects empty targets, CLI flag injection (`-`), shell metacharacters, path traversal, and critical host/system processes (`FORBIDDEN_TARGETS`, including `init`, `systemd`, `sshd`, `launchd`, `lsass.exe`, PIDs `0` and `1`).
- `validate_symbol_glob()` validates C/native (`*auth*`, `libnative.so!check_*`), Java (`com.testlab.*!verify*`), and Objective-C (`-[NSURLSession *]`) globs while rejecting option injection and shell metacharacters.

### 2. Handler Auto-Instrumentation (`defineHandler`)
- `generate_handler_script()` and `instrument_handlers_dir()` upgrade `frida-trace` `__handlers__/<module>/<symbol>.js` files so `onEnter` snapshots up to `N` arguments (dereferencing UTF-8 C strings when readable) and `onLeave` captures the return value, emitting structured `[OSLAB_TRACE]` JSON telemetry lines.

### 3. Multi-Format Trace Parser & Call-Map Builder
`parse_trace_output()` and `build_call_map()` parse:
- `frida-trace` handler discovery lines (`symbol: Auto-generated handler at "..."`)
- Standard `frida-trace` call trees with pipe (`|`) indentation, thread headers (`/* TID 0x... */`), and return arrows (`<=`, `<-`, `=>`, `->`)
- Structured `[OSLAB_TRACE]` `enter` / `leave` JSON events emitted by instrumented handlers
- Objective-C method traces (`-[Class selector:arg] => retval`)

The resulting JSON call map (`schema_version: "1.0"`, `task_id: "PENT-06"`) contains:
- `summary`: `discovered_count`, `functions_called_count`, `total_calls`, `unique_edges`, `threads_observed`, `max_depth`
- `discovered_functions`: per-symbol metadata (`symbol`, `module`, `qualified_name`, `handler_path`, `status`, `call_count`)
- `functions`: per-function aggregated statistics, observed `arg_Snapshots`, `return_values`, `callers`, and `callees`
- `call_sequence`: chronological call list with `call_id`, `parent_call_id`, `caller`, `children_call_ids`, `depth`, `thread_id`, `args` snapshots (`index`, `name`, `value`, `type`, `raw`, optional `annotation`), `retval`, and `duration_ms`
- `call_graph`: directed `caller -> callee` edges with call counts

