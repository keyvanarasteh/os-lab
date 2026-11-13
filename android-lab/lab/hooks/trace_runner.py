#!/usr/bin/env python3
"""
frida-trace Auto-Tracer & Call-Map Builder entry point in `android-lab/lab/hooks/` (PENT-06).

Re-exports the full implementation from `android-lab/lab/scripts/trace_runner.py` so
both `hooks/trace_runner.py` and `scripts/trace_runner.py` expose the same CLI and
importable Python API.
"""

from __future__ import annotations

import os
import sys

_LAB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SCRIPTS_DIR = os.path.join(_LAB_DIR, "scripts")
if _LAB_DIR not in sys.path:
    sys.path.insert(0, _LAB_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import scripts.trace_runner as _impl  # noqa: E402
sys.modules.setdefault("trace_runner", _impl)

from scripts.trace_runner import (  # noqa: E402,F401
    FORBIDDEN_TARGETS,
    SAMPLE_LAB_TRACE_LOG,
    TraceScopeError,
    build_call_map,
    build_frida_trace_cmd,
    find_frida_trace,
    generate_handler_script,
    instrument_handlers_dir,
    main,
    parse_arg_value,
    parse_args_string,
    parse_trace_output,
    render_annotated_session_log,
    run_trace_session,
    validate_symbol_glob,
    validate_target,
)

__all__ = [
    "FORBIDDEN_TARGETS",
    "SAMPLE_LAB_TRACE_LOG",
    "TraceScopeError",
    "build_call_map",
    "build_frida_trace_cmd",
    "find_frida_trace",
    "generate_handler_script",
    "instrument_handlers_dir",
    "main",
    "parse_arg_value",
    "parse_args_string",
    "parse_trace_output",
    "render_annotated_session_log",
    "run_trace_session",
    "validate_symbol_glob",
    "validate_target",
]

if __name__ == "__main__":
    raise SystemExit(main())
