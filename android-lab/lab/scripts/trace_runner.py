#!/usr/bin/env python3
"""
frida-trace Auto-Tracer & Call-Map Builder (PENT-06)

Discovers and traces exported/native/Java/ObjC functions of a lab target process
via `frida-trace`, parses per-call argument snapshots, return values, and call
nesting hierarchy, and emits a structured JSON call map alongside an annotated
session log. (Teached 05.10: frida-trace, süreç -> fonksiyon -> hook)
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Lab scope guard: never allow tracing critical host system daemons or PIDs 0/1
FORBIDDEN_TARGETS = frozenset({
    "init",
    "systemd",
    "sshd",
    "launchd",
    "kernel_task",
    "csrss.exe",
    "lsass.exe",
    "wininit.exe",
    "services.exe",
    "smss.exe",
    "0",
    "1",
})

SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
SAFE_GLOB_RE = re.compile(r"^[A-Za-z0-9_.*?!:\[\]+\-/ ]{1,160}$")
SHELL_META_CHARS = frozenset(";|&$`\n\r\0><")

MAX_RAW_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PARSED_CALLS = 5000
MAX_SNAPSHOTS_PER_FUNCTION = 250

SENSITIVE_SYMBOL_RE = re.compile(
    r"(?i)(?:auth|pass|pwd|pin|token|secret|key|cred|login|crypt|sign|verify|strcmp|memcmp|hmac)"
)
SENSITIVE_ARG_NAME_RE = re.compile(
    r"(?i)(?:pass|pwd|pin|token|secret|key|cred|auth|bearer|cookie|session|hash|cipher|priv|sig)"
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(?:^bearer\s+\S+|^tok_[A-Za-z0-9_-]+|^eyJ[A-Za-z0-9_-]{5,}|^AES[0-9]*:|password|secret|parola)"
)

_PROCESS_LOCK = threading.RLock()
_DEFAULT_LOCK_FILE = Path(tempfile.gettempdir()) / "oslab-android-trace-artifacts.lock"

# Built-in deterministic lab trace fixture (Teached 05.10 auth/crypto flow)
SAMPLE_LAB_TRACE_LOG = """Instrumenting...
Java_com_testlab_AuthBridge_verifyCredentials: Auto-generated handler at "/tmp/__handlers__/libauth.so/Java_com_testlab_AuthBridge_verifyCredentials.js"
check_password: Auto-generated handler at "/tmp/__handlers__/libauth.so/check_password.js"
strcmp: Loaded handler at "/tmp/__handlers__/libc.so/strcmp.js"
derive_session_token: Auto-generated handler at "/tmp/__handlers__/libcrypto.so/derive_session_token.js"
Started tracing 4 functions. Press Ctrl+C to stop.
           /* TID 0x1a2b */
   12 ms  libauth.so!Java_com_testlab_AuthBridge_verifyCredentials(env=0x7ff80010, thiz=0x7ff80020, user="student_lab", pass="deneme123")
   15 ms     | libauth.so!check_password(input="deneme123", expected_len=0x9)
   17 ms     |    | libc.so!strcmp("deneme123", "gizli_parola")
   18 ms     |    | <- libc.so!strcmp = 0xffffffff (-1)
   20 ms     | <= libauth.so!check_password = 0x0 (0)
   22 ms  <= libauth.so!Java_com_testlab_AuthBridge_verifyCredentials = 0x0 (0)
   45 ms  libauth.so!Java_com_testlab_AuthBridge_verifyCredentials(env=0x7ff80010, thiz=0x7ff80020, user="student_lab", pass="gizli_parola")
   47 ms     | libauth.so!check_password(input="gizli_parola", expected_len=0xc)
   49 ms     |    | libc.so!strcmp("gizli_parola", "gizli_parola")
   50 ms     |    | <- libc.so!strcmp = 0x0 (0)
   52 ms     | <= libauth.so!check_password = 0x1 (1)
   54 ms     | libcrypto.so!derive_session_token(0x7ff90100 ("student_lab"), 0x10)
   58 ms     | <= libcrypto.so!derive_session_token = 0x7ff90200 ("tok_9f8a7b6c")
   60 ms  <= libauth.so!Java_com_testlab_AuthBridge_verifyCredentials = 0x1 (1)
"""


class TraceScopeError(ValueError):
    """Raised when a trace target or symbol glob violates lab safety boundaries."""


@contextlib.contextmanager
def artifact_lock(lock_path: Path | str | None = None) -> Iterator[None]:
    """Serialize trace artifact publication and clean operations across threads and processes."""
    lpath = Path(lock_path) if lock_path else _DEFAULT_LOCK_FILE
    lpath.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        with open(lpath, "a+b") as lock_fh:
            if os.name == "nt":
                import msvcrt

                lock_fh.seek(0)
                if lock_fh.tell() == 0:
                    lock_fh.write(b"\0")
                    lock_fh.flush()
                lock_fh.seek(0)
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    try:
                        lock_fh.seek(0)
                        msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            else:
                import fcntl

                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    try:
                        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass


def validate_target(target: str) -> str:
    """Validate that a target process name, package ID, or PID is safe and in lab scope."""
    if not isinstance(target, str):
        raise TraceScopeError("Target must be a non-empty string")
    cleaned = target.strip()
    if not cleaned:
        raise TraceScopeError("Target process or package cannot be empty")
    if cleaned.startswith("-"):
        raise TraceScopeError(f"Invalid target {cleaned!r}: cannot start with '-'")
    if any(ch in SHELL_META_CHARS for ch in cleaned):
        raise TraceScopeError(f"Invalid target {cleaned!r}: contains forbidden metacharacters")
    if ".." in cleaned or "\\" in cleaned:
        raise TraceScopeError(f"Invalid target {cleaned!r}: path traversal is not allowed")
    base_name = cleaned.rsplit("/", 1)[-1].lower()
    if cleaned.lower() in FORBIDDEN_TARGETS or base_name in FORBIDDEN_TARGETS:
        raise TraceScopeError(f"Target {cleaned!r} is a protected system process outside lab scope")
    if cleaned.isdigit() and int(cleaned) <= 1:
        raise TraceScopeError(f"PID {cleaned} is reserved and outside lab scope")
    if not SAFE_TARGET_RE.match(cleaned):
        raise TraceScopeError(f"Invalid target format: {cleaned!r}")
    return cleaned


def validate_symbol_glob(pattern: str) -> str:
    """Validate a function or method glob pattern for frida-trace."""
    if not isinstance(pattern, str):
        raise TraceScopeError("Symbol glob must be a non-empty string")
    cleaned = pattern.strip()
    if not cleaned:
        raise TraceScopeError("Symbol glob cannot be empty")
    if any(ch in SHELL_META_CHARS for ch in cleaned):
        raise TraceScopeError(f"Invalid symbol glob {cleaned!r}: contains shell metacharacters")
    # Allow Objective-C method globs like "-[NSURLSession *]" or "+[Class *]"
    if cleaned.startswith("-") and not cleaned.startswith("-["):
        raise TraceScopeError(f"Invalid symbol glob {cleaned!r}: cannot start with option flag '-'")
    if ".." in cleaned or "\\" in cleaned:
        raise TraceScopeError(f"Invalid symbol glob {cleaned!r}: path traversal is not allowed")
    if not SAFE_GLOB_RE.match(cleaned):
        raise TraceScopeError(f"Invalid symbol glob characters in {cleaned!r}")
    return cleaned


def find_frida_trace() -> str:
    """Locate the frida-trace executable in the lab virtualenv or PATH."""
    script_dir = Path(__file__).resolve().parent
    lab_dir = script_dir.parent
    candidates = [
        lab_dir / ".venv" / "bin" / "frida-trace",
        lab_dir / ".venv" / "Scripts" / "frida-trace.exe",
        lab_dir.parent.parent / ".venv" / "bin" / "frida-trace",
        lab_dir.parent.parent / ".venv" / "Scripts" / "frida-trace.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    which_bin = shutil.which("frida-trace")
    return which_bin if which_bin else "frida-trace"


def build_frida_trace_cmd(
    target: str,
    include_globs: list[str] | tuple[str, ...] = (),
    *,
    exclude_globs: list[str] | tuple[str, ...] = (),
    module_globs: list[str] | tuple[str, ...] = (),
    java_globs: list[str] | tuple[str, ...] = (),
    objc_globs: list[str] | tuple[str, ...] = (),
    transport: str = "usb",
    device_id: str | None = None,
    host: str | None = None,
    spawn: bool = False,
    handlers_dir: str | None = None,
    frida_trace_bin: str | None = None,
) -> list[str]:
    """Build a validated, shell-free command list for invoking frida-trace."""
    safe_target = validate_target(target)
    effective_include_globs = (
        list(include_globs)
        if (include_globs or module_globs or java_globs or objc_globs)
        else ["*"]
    )

    cmd = [frida_trace_bin or find_frida_trace()]

    transport_norm = (transport or "usb").strip().lower()
    if transport_norm not in ("usb", "remote", "local"):
        raise TraceScopeError(f"Unsupported transport {transport!r} (choose usb, local, or remote)")

    if device_id and host:
        raise TraceScopeError("Cannot specify both device_id (-D) and remote host (-H)")

    if device_id:
        if transport_norm == "remote":
            raise TraceScopeError("Cannot combine explicit device_id (-D) with remote transport (-R/-H)")
        safe_dev = validate_target(device_id)
        cmd.extend(["-D", safe_dev])
    elif transport_norm == "usb":
        cmd.append("-U")
    elif transport_norm == "remote":
        if host:
            safe_host = validate_target(host)
            cmd.extend(["-H", safe_host])
        else:
            cmd.append("-R")
    elif transport_norm == "local":
        if host:
            raise TraceScopeError("Cannot specify remote host (-H) with local transport")

    if handlers_dir:
        cmd.extend(["-d", str(handlers_dir)])

    for pat in effective_include_globs:
        cmd.extend(["-i", validate_symbol_glob(pat)])
    for mod in module_globs:
        cmd.extend(["-I", validate_symbol_glob(mod)])
    for jpat in java_globs:
        cmd.extend(["-j", validate_symbol_glob(jpat)])
    for mpat in objc_globs:
        cmd.extend(["-m", validate_symbol_glob(mpat)])
    for xpat in exclude_globs:
        cmd.extend(["-x", validate_symbol_glob(xpat)])

    if spawn:
        cmd.extend(["-f", safe_target])
    elif safe_target.isdigit():
        cmd.extend(["-p", safe_target])
    else:
        cmd.extend(["-n", safe_target])

    return cmd


def generate_handler_script(
    symbol: str,
    module: str | None = None,
    arg_count: int = 4,
    arg_types: list[str] | tuple[str, ...] | None = None,
) -> str:
    """
    Generate a frida-trace handler script that captures per-call argument snapshots
    on onEnter and return values on onLeave, emitting both structured [OSLAB_TRACE]
    JSON telemetry and human-readable log lines.
    """
    safe_symbol = validate_symbol_glob(symbol)
    safe_module = validate_target(module) if module else None
    qualified = f"{safe_module}!{safe_symbol}" if safe_module else safe_symbol
    if not 0 <= arg_count <= 16:
        raise ValueError("arg_count must be between 0 and 16")

    module_json = json.dumps(safe_module)
    symbol_json = json.dumps(safe_symbol)
    qualified_json = json.dumps(qualified)
    sig_types_json = json.dumps(list(arg_types) if arg_types is not None else [])

    return f"""/*
 * Auto-generated by os-lab trace_runner.py (PENT-06)
 * Target symbol: {qualified}
 */
defineHandler({{
  onEnter(log, args, state) {{
    const tidKey = "0x" + this.threadId.toString(16);
    const depthMap = (globalThis.__oslabDepthByTid = globalThis.__oslabDepthByTid || {{}});
    const currentDepth = (typeof state.depth === "number") ? state.depth : (depthMap[tidKey] || 0);
    state.depth = currentDepth;
    depthMap[tidKey] = currentDepth + 1;
    const nowMs = Date.now();
    if (typeof globalThis.__oslabEpochMs !== "number") {{
      globalThis.__oslabEpochMs = nowMs;
    }}
    state.startMs = nowMs;
    const relStartMs = Math.max(0, nowMs - globalThis.__oslabEpochMs);
    const sigTypes = {sig_types_json};
    const snapshots = [];
    for (let i = 0; i < {arg_count}; i++) {{
      try {{
        const rawPtr = args[i];
        let valStr = rawPtr !== undefined ? rawPtr.toString() : "undefined";
        let argType = sigTypes[i] || "unknown";
        let annotation = null;
        try {{
          const cstr = rawPtr.readUtf8String();
          if (cstr !== null && cstr.length > 0 && cstr.length <= 256) {{
            annotation = cstr;
            if (argType === "unknown") {{
              argType = "string";
            }}
          }}
        }} catch (_) {{}}
        snapshots.push({{
          index: i,
          name: "arg" + i,
          value: annotation !== null ? annotation : valStr,
          type: argType,
          raw: valStr,
          annotation: annotation
        }});
      }} catch (_) {{
        break;
      }}
    }}
    const payload = {{
      event: "enter",
      module: {module_json},
      symbol: {symbol_json},
      qualified_name: {qualified_json},
      thread_id: tidKey,
      depth: state.depth,
      timestamp_ms: relStartMs,
      args: snapshots
    }};
    log("[OSLAB_TRACE] " + JSON.stringify(payload));
  }},

  onLeave(log, retval, state) {{
    const tidKey = "0x" + this.threadId.toString(16);
    const depthMap = (globalThis.__oslabDepthByTid = globalThis.__oslabDepthByTid || {{}});
    const leaveDepth = (typeof state.depth === "number")
      ? state.depth
      : Math.max(0, (depthMap[tidKey] || 1) - 1);
    depthMap[tidKey] = leaveDepth;
    const nowMs = Date.now();
    const epochMs = typeof globalThis.__oslabEpochMs === "number" ? globalThis.__oslabEpochMs : nowMs;
    const relEndMs = Math.max(0, nowMs - epochMs);
    const durMs = typeof state.startMs === "number" ? Math.max(0, nowMs - state.startMs) : null;
    const retStr = retval !== undefined ? retval.toString() : null;
    const payload = {{
      event: "leave",
      module: {module_json},
      symbol: {symbol_json},
      qualified_name: {qualified_json},
      thread_id: tidKey,
      depth: leaveDepth,
      timestamp_ms: relEndMs,
      duration_ms: durMs,
      retval: retStr
    }};
    log("[OSLAB_TRACE] " + JSON.stringify(payload));
  }}
}});
"""


_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\r\n]*")
_CUSTOM_JS_INDICATORS_RE = re.compile(
    r"\b(?:Interceptor|Memory|NativeFunction|NativeCallback|Java|ObjC|Module|Process|Thread|Socket|File| SqliteDatabase|send|recv|console\.\w+|retval\.replace|const\s+|let\s+|var\s+|function\s+|while\s*\(|for\s*\(|if\s*\(|switch\s*\(|try\s*\{)\b"
)
_FRIDA_STUB_BODY_RE = re.compile(
    r"^\s*defineHandler\s*\(\s*\{\s*"
    r"(?:onEnter\s*\([^)]*\)\s*\{\s*(?:log\s*\([^;{}]*\)\s*;?\s*)?\}\s*,?\s*)?"
    r"(?:onLeave\s*\([^)]*\)\s*\{\s*(?:log\s*\([^;{}]*\)\s*;?\s*)?\}\s*,?\s*)?"
    r"\}\s*\)\s*;?\s*$",
    re.DOTALL,
)


def _is_frida_stub_handler(text: str) -> bool:
    """
    Return True only if `text` is an unmodified Frida-generated handler stub or empty
    placeholder stub, and False if it contains custom user-authored handler code.
    """
    if "[OSLAB_TRACE]" in text or "Auto-generated by os-lab trace_runner.py" in text:
        return False
    stripped = _BLOCK_COMMENT_RE.sub("", text)
    stripped = _LINE_COMMENT_RE.sub("", stripped).strip()
    if not stripped:
        return True
    if _CUSTOM_JS_INDICATORS_RE.search(stripped):
        return False
    return bool(_FRIDA_STUB_BODY_RE.match(stripped))


def instrument_handlers_dir(handlers_dir: str | Path, arg_count: int = 4) -> list[str]:
    """
    Walk a frida-trace `__handlers__` directory and upgrade Frida-generated `.js` stub
    files with argument-snapshot and return-value instrumentation, preserving any
    user-customized handler files.
    """
    base = Path(handlers_dir)
    if not base.is_dir():
        return []
    updated: list[str] = []
    for js_file in sorted(base.rglob("*.js")):
        if not js_file.is_file() or js_file.is_symlink():
            continue
        try:
            existing = js_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _is_frida_stub_handler(existing):
            continue
        rel_parts = js_file.relative_to(base).parts
        symbol = js_file.stem
        module = rel_parts[0] if len(rel_parts) > 1 else None
        try:
            script = generate_handler_script(symbol=symbol, module=module, arg_count=arg_count)
        except TraceScopeError:
            continue
        js_file.write_text(script, encoding="utf-8")
        updated.append(str(js_file))
    return updated


def _split_top_level_args(arg_str: str) -> list[str]:
    """Split a comma-separated argument string while respecting quotes and nested brackets."""
    text = arg_str.strip()
    if not text:
        return []
    items: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_bracket = 0
    depth_brace = 0
    in_quote: str | None = None
    escape = False

    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\":
            current.append(ch)
            escape = True
            continue
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
            continue
        if ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        elif ch == "{":
            depth_brace += 1
        elif ch == "}" and depth_brace > 0:
            depth_brace -= 1
        elif ch == "," and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
            token = "".join(current).strip()
            if token:
                items.append(token)
            current = []
            continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


PTR_ANNOTATED_RE = re.compile(r"^(0x[0-9a-fA-F]+)\s*\(\s*([\"'].*[\"']|[^)]+)\s*\)$")
HEX_WITH_DEC_RE = re.compile(r"^(-?0x[0-9a-fA-F]+)\s*\((-?[0-9]+)\)$")
HEX_INT_RE = re.compile(r"^-?0x[0-9a-fA-F]+(?:\s*\(-?[0-9]+\))?$")
DEC_INT_RE = re.compile(r"^-?[0-9]+$")
NAMED_ARG_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")
POINTER_NAME_RE = re.compile(r"(?i)^(?:ptr|.*_ptr|env|thiz|self|cls|ctx|handle|addr|buf|dst|src)$")
INT_NAME_RE = re.compile(
    r"(?i)^(?:len|.*_len|count|.*_count|size|.*_size|flags|mode|fd|port|id|.*_id|status|code|num|retries|index|offset)$"
)


def parse_arg_value(raw_token: str, index: int, expected_type: str | None = None) -> dict[str, Any]:
    """Parse a single argument token into a normalized snapshot dictionary."""
    token = raw_token.strip()
    name = f"arg{index}"
    val_part = token

    named_match = NAMED_ARG_RE.match(token)
    if named_match:
        name = named_match.group(1)
        val_part = named_match.group(2).strip()

    annotation: str | None = None

    # Hex value with explicit signed decimal interpretation: 0xffffffff (-1)
    hex_dec_match = HEX_WITH_DEC_RE.match(val_part)
    if hex_dec_match:
        return {
            "index": index,
            "name": name,
            "value": hex_dec_match.group(1),
            "type": expected_type or "int",
            "raw": token,
        }

    # Pointer with inline string/symbol annotation: 0x7ff90100 ("student_lab")
    ptr_match = PTR_ANNOTATED_RE.match(val_part)
    if ptr_match:
        ptr_hex = ptr_match.group(1)
        inner = ptr_match.group(2).strip()
        if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
            inner = inner[1:-1]
        annotation = inner
        return {
            "index": index,
            "name": name,
            "value": ptr_hex,
            "type": expected_type or "pointer",
            "raw": token,
            "annotation": annotation,
        }

    # Quoted string literal
    if (val_part.startswith('"') and val_part.endswith('"')) or (
        val_part.startswith("'") and val_part.endswith("'")
    ):
        unquoted = val_part[1:-1]
        return {
            "index": index,
            "name": name,
            "value": unquoted,
            "type": expected_type or "string",
            "raw": token,
        }

    # JSON object or array
    if (val_part.startswith("{") and val_part.endswith("}")) or (
        val_part.startswith("[") and val_part.endswith("]")
    ):
        try:
            parsed_json = json.loads(val_part)
            return {
                "index": index,
                "name": name,
                "value": parsed_json,
                "type": expected_type or "json",
                "raw": token,
            }
        except ValueError:
            pass

    # Boolean / Null
    lower_val = val_part.lower()
    if lower_val in ("true", "false"):
        return {
            "index": index,
            "name": name,
            "value": lower_val == "true",
            "type": expected_type or "bool",
            "raw": token,
        }
    if lower_val in ("null", "nil", "none", "nullptr"):
        return {
            "index": index,
            "name": name,
            "value": None,
            "type": expected_type or "null",
            "raw": token,
        }

    # Hex scalar or pointer
    if HEX_INT_RE.match(val_part):
        hex_head = val_part.split()[0]
        clean_hex = hex_head.lstrip("-")[2:]
        if expected_type:
            arg_type = expected_type
        elif INT_NAME_RE.match(name) or len(clean_hex) <= 4 or hex_head.startswith("-"):
            arg_type = "int"
        elif POINTER_NAME_RE.match(name):
            arg_type = "pointer"
        else:
            # Ambiguous multi-byte hex value without signature metadata or dereference annotation
            arg_type = "unknown"
        return {
            "index": index,
            "name": name,
            "value": hex_head,
            "type": arg_type,
            "raw": token,
        }

    # Decimal integer
    if DEC_INT_RE.match(val_part):
        return {
            "index": index,
            "name": name,
            "value": int(val_part),
            "type": expected_type or "int",
            "raw": token,
        }

    return {
        "index": index,
        "name": name,
        "value": val_part,
        "type": expected_type or "unknown",
        "raw": token,
    }


def parse_args_string(
    arg_str: str,
    arg_types: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Parse a full function call argument list into per-argument snapshot dicts."""
    tokens = _split_top_level_args(arg_str)
    sig = list(arg_types) if arg_types is not None else []
    return [
        parse_arg_value(tok, idx, expected_type=sig[idx] if idx < len(sig) else None)
        for idx, tok in enumerate(tokens)
    ]


def _split_qualified_symbol(qualified: str) -> tuple[str | None, str, str]:
    """Split `module!symbol` into `(module, symbol, qualified_name)`."""
    cleaned = qualified.strip()
    if "!" in cleaned and not cleaned.startswith(("-[", "+[")):
        mod, sym = cleaned.split("!", 1)
        return mod.strip() or None, sym.strip(), f"{mod.strip()}!{sym.strip()}"
    return None, cleaned, cleaned


DISCOVERY_RE = re.compile(
    r"^\s*(?P<symbol>[^\s:]+)\s*:\s*(?P<kind>Auto-generated|Loaded)\s+handler\s+at\s+\"(?P<path>[^\"]+)\""
)
TID_HEADER_RE = re.compile(r"/\*\s*TID\s+(?P<tid>0x[0-9a-fA-F]+|[0-9]+)\s*\*/")
TRACE_LINE_PREFIX_RE = re.compile(
    r"^\s*(?P<ts>[0-9]+(?:\.[0-9]+)?)\s*ms(?:\s+\[(?!OSLAB_TRACE\])(?P<tid>[^\]]+)\])?(?P<rest>.*)$"
)
OSLAB_JSON_RE = re.compile(r"\[OSLAB_TRACE\]\s*(\{.*\})\s*$")
RETURN_LINE_RE = re.compile(
    r"^(?P<indent>[\s|]*)(?:<-|<=|->|=>)\s*(?:(?P<fn>[A-Za-z0-9_.$!+-]+)\s*=\s*)?(?P<ret>.+?)\s*$"
)
CALL_LINE_RE = re.compile(
    r"^(?P<indent>[\s|]*)(?P<fn>(?:[A-Za-z0-9_.$+-]+!)?[A-Za-z0-9_.$+-]+)\((?P<args>.*)\)(?:\s*(?:=>|->|=)\s*(?P<inline_ret>.+))?\s*$"
)
OBJC_CALL_RE = re.compile(
    r"^(?P<indent>[\s|]*)(?P<objc>[+-]\[[^\]]+\])(?:\s*(?:=>|->|=)\s*(?P<inline_ret>.+))?\s*$"
)


def _compute_indent_depth(indent_str: str) -> int:
    """Compute call nesting depth from frida-trace pipe (`|`) or whitespace indentation."""
    pipes = indent_str.count("|")
    if pipes > 0:
        return pipes
    spaces = len(indent_str.strip("\t"))
    # Standard frida-trace uses 2 spaces before top-level calls; deeper indent in 3-4 space steps
    if spaces <= 2:
        return 0
    return max(0, (spaces - 2) // 3)


def _normalize_timestamp(val: Any) -> int | float | None:
    if isinstance(val, bool) or val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val) if int(val) == val else round(float(val), 3)
    return None


def parse_trace_output(
    raw_text: str,
    *,
    max_calls: int = MAX_PARSED_CALLS,
) -> dict[str, Any]:
    """
    Parse raw `frida-trace` output (both standard CLI output and `[OSLAB_TRACE]`
    structured handler lines) into discovered functions and an ordered call sequence
    with hierarchy and argument snapshots.
    """
    discovered: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []
    # Per-thread active call stack: list of call dicts
    active_stacks: dict[str, list[dict[str, Any]]] = {}
    current_tid = "main"
    truncated = False
    omitted_calls = 0

    for raw_line in raw_text.splitlines():
        line = ANSI_RE.sub("", raw_line).rstrip("\r\n")
        if not line.strip():
            continue

        # 1. Check thread header comment: /* TID 0x1a2b */
        tid_match = TID_HEADER_RE.search(line)
        if tid_match:
            current_tid = tid_match.group("tid")
            continue

        # 2. Check handler discovery line
        disc_match = DISCOVERY_RE.match(line)
        if disc_match:
            sym_raw = disc_match.group("symbol")
            kind = disc_match.group("kind").lower()
            hpath = disc_match.group("path").replace("\\", "/")
            mod, sym, qualified = _split_qualified_symbol(sym_raw)
            if mod is None:
                parts = [p for p in hpath.split("/") if p]
                if len(parts) >= 2 and parts[-1].endswith(".js"):
                    parent_dir = parts[-2]
                    if parent_dir != "__handlers__":
                        mod = parent_dir
                        qualified = f"{mod}!{sym}"
            discovered[qualified] = {
                "symbol": sym,
                "module": mod,
                "qualified_name": qualified,
                "handler_path": hpath,
                "status": kind,
            }
            continue

        # 3. Extract timestamp & optional [tid] prefix if present
        ts_ms: float | int | None = None
        tid = current_tid
        rest = line
        prefix_match = TRACE_LINE_PREFIX_RE.match(line)
        if prefix_match:
            ts_val = float(prefix_match.group("ts"))
            ts_ms = int(ts_val) if int(ts_val) == ts_val else ts_val
            if prefix_match.group("tid"):
                tid = prefix_match.group("tid").strip()
                current_tid = tid
            rest = prefix_match.group("rest")

        # 4. Check structured [OSLAB_TRACE] JSON line
        oslab_match = OSLAB_JSON_RE.search(rest)
        if oslab_match:
            try:
                ev = json.loads(oslab_match.group(1))
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            ev_type = ev.get("event")
            ev_tid = str(ev.get("thread_id") or tid)
            stack = active_stacks.setdefault(ev_tid, [])
            mod = ev.get("module")
            sym = str(ev.get("symbol") or "unknown")
            qualified = str(ev.get("qualified_name") or (f"{mod}!{sym}" if mod else sym))
            if qualified not in discovered:
                discovered[qualified] = {
                    "symbol": sym,
                    "module": mod,
                    "qualified_name": qualified,
                    "handler_path": None,
                    "status": "observed",
                }

            if ev_type == "enter":
                if len(calls) >= max_calls:
                    truncated = True
                    omitted_calls += 1
                    continue
                raw_depth = ev.get("depth")
                if isinstance(raw_depth, int) and not isinstance(raw_depth, bool) and raw_depth >= 0:
                    if raw_depth == 0 and stack and all(c.get("_raw_depth") == 0 for c in stack):
                        depth = len(stack)
                    else:
                        depth = raw_depth
                        while len(stack) > depth:
                            stack.pop()
                else:
                    depth = len(stack)
                parent = stack[-1] if stack else None
                call_id = len(calls) + 1
                raw_args = ev.get("args") if isinstance(ev.get("args"), list) else []
                norm_args = []
                for idx, a in enumerate(raw_args):
                    if isinstance(a, dict):
                        norm_args.append({
                            "index": int(a.get("index", idx)),
                            "name": str(a.get("name", f"arg{idx}")),
                            "value": a.get("value"),
                            "type": str(a.get("type", "unknown")),
                            "raw": str(a.get("raw", a.get("value", ""))),
                            **(
                                {"annotation": a["annotation"]}
                                if a.get("annotation") is not None
                                else {}
                            ),
                        })
                    else:
                        norm_args.append(parse_arg_value(str(a), idx))
                ev_ts = _normalize_timestamp(ev.get("timestamp_ms"))
                effective_ts = ev_ts if ev_ts is not None else ts_ms
                call_rec: dict[str, Any] = {
                    "call_id": call_id,
                    "timestamp_ms": effective_ts if effective_ts is not None else 0,
                    "_has_measured_ts": effective_ts is not None,
                    "_raw_depth": raw_depth,
                    "thread_id": ev_tid,
                    "depth": depth,
                    "parent_call_id": parent["call_id"] if parent else None,
                    "caller": parent["qualified_name"] if parent else None,
                    "children_call_ids": [],
                    "module": mod,
                    "symbol": sym,
                    "qualified_name": qualified,
                    "args": norm_args,
                    "retval": ev.get("retval"),
                    "duration_ms": None,
                }
                if parent:
                    parent["children_call_ids"].append(call_id)
                calls.append(call_rec)
                stack.append(call_rec)
            elif ev_type == "leave":
                ret_val = ev.get("retval")
                matched_call = None
                for idx in range(len(stack) - 1, -1, -1):
                    if stack[idx]["qualified_name"] == qualified or stack[idx]["symbol"] == sym:
                        matched_call = stack[idx]
                        del stack[idx:]
                        break
                if matched_call is None and stack:
                    matched_call = stack.pop()
                if matched_call is not None:
                    matched_call["retval"] = str(ret_val) if ret_val is not None else None
                    ev_dur = _normalize_timestamp(ev.get("duration_ms"))
                    ev_leave_ts = _normalize_timestamp(ev.get("timestamp_ms"))
                    leave_ts = ev_leave_ts if ev_leave_ts is not None else ts_ms
                    if ev_dur is not None:
                        matched_call["duration_ms"] = ev_dur
                    elif leave_ts is not None and matched_call.get("_has_measured_ts"):
                        dur = round(float(leave_ts) - float(matched_call["timestamp_ms"]), 3)
                        matched_call["duration_ms"] = int(dur) if int(dur) == dur else dur
            continue

        # 5. Check standard return line (`<- fn = 0x0`, `<= fn = 0x1`, `-> 0x1`)
        ret_match = RETURN_LINE_RE.match(rest)
        if ret_match:
            indent_str = ret_match.group("indent") or ""
            depth = _compute_indent_depth(indent_str)
            fn_raw = ret_match.group("fn")
            ret_raw = ret_match.group("ret").strip()
            stack = active_stacks.setdefault(tid, [])
            matched_call = None
            if fn_raw:
                _, ret_sym, ret_qual = _split_qualified_symbol(fn_raw)
                for idx in range(len(stack) - 1, -1, -1):
                    cand = stack[idx]
                    if cand["qualified_name"] == ret_qual or cand["symbol"] == ret_sym:
                        matched_call = cand
                        del stack[idx:]
                        break
            if matched_call is None:
                for idx in range(len(stack) - 1, -1, -1):
                    if stack[idx]["depth"] == depth:
                        matched_call = stack[idx]
                        del stack[idx:]
                        break
            if matched_call is None and stack:
                matched_call = stack.pop()
            if matched_call is not None:
                matched_call["retval"] = ret_raw
                if ts_ms is not None and matched_call.get("_has_measured_ts"):
                    dur = round(float(ts_ms) - float(matched_call["timestamp_ms"]), 3)
                    matched_call["duration_ms"] = int(dur) if int(dur) == dur else dur
            continue

        # 6. Check standard function call line (`lib!fn(arg0, arg1)`)
        call_match = CALL_LINE_RE.match(rest)
        if call_match:
            if len(calls) >= max_calls:
                truncated = True
                omitted_calls += 1
                continue
            indent_str = call_match.group("indent") or ""
            depth = _compute_indent_depth(indent_str)
            fn_raw = call_match.group("fn")
            args_str = call_match.group("args") or ""
            inline_ret = call_match.group("inline_ret")
            mod, sym, qualified = _split_qualified_symbol(fn_raw)
            if mod is None:
                # Match against already-discovered module if unambiguous
                for d_qual, d_info in discovered.items():
                    if d_info["symbol"] == sym and d_info["module"]:
                        mod = d_info["module"]
                        qualified = d_qual
                        break
            if qualified not in discovered:
                discovered[qualified] = {
                    "symbol": sym,
                    "module": mod,
                    "qualified_name": qualified,
                    "handler_path": None,
                    "status": "observed",
                }

            stack = active_stacks.setdefault(tid, [])
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            parent = stack[-1] if stack else None
            call_id = len(calls) + 1
            parsed_args = parse_args_string(args_str)
            call_rec = {
                "call_id": call_id,
                "timestamp_ms": ts_ms if ts_ms is not None else 0,
                "_has_measured_ts": ts_ms is not None,
                "thread_id": tid,
                "depth": depth,
                "parent_call_id": parent["call_id"] if parent else None,
                "caller": parent["qualified_name"] if parent else None,
                "children_call_ids": [],
                "module": mod,
                "symbol": sym,
                "qualified_name": qualified,
                "args": parsed_args,
                "retval": inline_ret.strip() if inline_ret else None,
                "duration_ms": None,
            }
            if parent:
                parent["children_call_ids"].append(call_id)
            calls.append(call_rec)
            if not inline_ret:
                stack.append(call_rec)
            continue

        # 7. Check Objective-C style call line (`-[NSURLSession dataTaskWithRequest:0x1]`)
        objc_match = OBJC_CALL_RE.match(rest)
        if objc_match:
            if len(calls) >= max_calls:
                truncated = True
                omitted_calls += 1
                continue
            indent_str = objc_match.group("indent") or ""
            depth = _compute_indent_depth(indent_str)
            objc_expr = objc_match.group("objc").strip()
            inline_ret = objc_match.group("inline_ret")
            inner = objc_expr[2:-1].strip()
            parts = inner.split(None, 1)
            cls_name = parts[0] if parts else "ObjC"
            sel_rest = parts[1] if len(parts) > 1 else ""
            # Extract selector tokens and argument values
            objc_args: list[dict[str, Any]] = []
            sel_parts: list[str] = []
            if ":" in sel_rest:
                for idx, chunk in enumerate(re.findall(r"([A-Za-z0-9_]+:)\s*([^\s\]]+)", sel_rest)):
                    sel_parts.append(chunk[0])
                    snap = parse_arg_value(chunk[1], idx)
                    snap["name"] = chunk[0].rstrip(":")
                    objc_args.append(snap)
                selector = "".join(sel_parts)
            else:
                selector = sel_rest
            sym = f"{objc_expr[:2]}{cls_name} {selector}]"
            qualified = sym
            if qualified not in discovered:
                discovered[qualified] = {
                    "symbol": sym,
                    "module": cls_name,
                    "qualified_name": qualified,
                    "handler_path": None,
                    "status": "observed",
                }
            stack = active_stacks.setdefault(tid, [])
            while stack and stack[-1]["depth"] >= depth:
                stack.pop()
            parent = stack[-1] if stack else None
            call_id = len(calls) + 1
            call_rec = {
                "call_id": call_id,
                "timestamp_ms": ts_ms if ts_ms is not None else 0,
                "_has_measured_ts": ts_ms is not None,
                "thread_id": tid,
                "depth": depth,
                "parent_call_id": parent["call_id"] if parent else None,
                "caller": parent["qualified_name"] if parent else None,
                "children_call_ids": [],
                "module": cls_name,
                "symbol": sym,
                "qualified_name": qualified,
                "args": objc_args,
                "retval": inline_ret.strip() if inline_ret else None,
                "duration_ms": None,
            }
            if parent:
                parent["children_call_ids"].append(call_id)
            calls.append(call_rec)
            if not inline_ret:
                stack.append(call_rec)

    for c in calls:
        c.pop("_has_measured_ts", None)
        c.pop("_raw_depth", None)

    return {
        "discovered_functions": list(discovered.values()),
        "calls": calls,
        "truncated": truncated,
        "omitted_calls": omitted_calls,
    }


def _is_sensitive_arg(qualified_name: str, arg: dict[str, Any]) -> bool:
    arg_name = str(arg.get("name") or "")
    val = arg.get("value")
    annot = arg.get("annotation")
    if SENSITIVE_ARG_NAME_RE.search(arg_name):
        return True
    if isinstance(val, str) and SENSITIVE_VALUE_RE.search(val):
        return True
    if isinstance(annot, str) and SENSITIVE_VALUE_RE.search(annot):
        return True
    if SENSITIVE_SYMBOL_RE.search(qualified_name):
        if arg.get("type") == "string" and arg_name.lower() not in ("user", "username", "role", "action", "module"):
            return True
        if annot is not None and arg_name.lower() not in ("user", "username", "role"):
            return True
    return False


def _redact_arg_snapshot(qualified_name: str, arg: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(arg)
    if not _is_sensitive_arg(qualified_name, out):
        return out
    name = out.get("name", f"arg{out.get('index', 0)}")
    if "annotation" in out and out["annotation"] is not None:
        out["annotation"] = "[REDACTED]"
        out["raw"] = f'{name}={out.get("value")} ("[REDACTED]")'
    else:
        out["value"] = "[REDACTED]"
        out["raw"] = f'{name}="[REDACTED]"'
    out["redacted"] = True
    return out


def _redact_return_value(qualified_name: str, retval: str | None) -> str | None:
    if retval is None:
        return None
    if not SENSITIVE_SYMBOL_RE.search(qualified_name) and not SENSITIVE_VALUE_RE.search(retval):
        return retval
    ptr_match = PTR_ANNOTATED_RE.match(retval.strip())
    if ptr_match:
        return f'{ptr_match.group(1)} ("[REDACTED]")'
    if (retval.startswith('"') and retval.endswith('"')) or SENSITIVE_VALUE_RE.search(retval):
        return '"[REDACTED]"'
    return retval


_RAW_QUOTED_SECRET_RE = re.compile(
    r'(?i)(\b(?:pass|password|pwd|pin|token|secret|key|key_id|input|cipher)\s*=\s*)(?:0x[0-9a-fA-F]+\s*\(\s*"[^"]*"\s*\)|"[^"]*"|\'[^\']*\'|[^\s,)]+)'
)
_RAW_FUNC_STRING_RE = re.compile(
    r'(?i)(\b(?:strcmp|memcmp|check_password|derive_session_token|verify_token|decrypt_payload)\s*\([^)\n]*)'
)
_RAW_RET_ANNOT_RE = re.compile(r'(0x[0-9a-fA-F]+\s*\(\s*)"([^"]*)"(\s*\))')


def redact_trace_text(raw_text: str) -> str:
    """Redact credentials, tokens, and sensitive string literals from raw trace logs."""
    text = _RAW_QUOTED_SECRET_RE.sub(r'\1"[REDACTED]"', raw_text)

    def _mask_fn_call(match: re.Match[str]) -> str:
        segment = match.group(1)
        return re.sub(r'"[^"]*"', '"[REDACTED]"', segment)

    text = _RAW_FUNC_STRING_RE.sub(_mask_fn_call, text)
    text = _RAW_RET_ANNOT_RE.sub(r'\1"[REDACTED]"\3', text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._-]+', "Bearer [REDACTED]", text)
    text = re.sub(r'\btok_[A-Za-z0-9_-]+', "[REDACTED]", text)
    return text


def redact_call_map(call_map: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `call_map` with sensitive argument and return snapshots redacted."""
    redacted = copy.deepcopy(call_map)
    for call in redacted.get("call_sequence", []):
        qname = str(call.get("qualified_name") or "")
        call["args"] = [_redact_arg_snapshot(qname, a) for a in call.get("args", [])]
        call["retval"] = _redact_return_value(qname, call.get("retval"))
    if "calls" in redacted:
        redacted["calls"] = redacted["call_sequence"]

    for qname, fn_info in redacted.get("functions", {}).items():
        snaps = fn_info.get("arg_snapshots") or fn_info.get("argument_snapshots") or []
        redacted_snaps = []
        for snap in snaps:
            s_copy = copy.deepcopy(snap)
            s_copy["args"] = [_redact_arg_snapshot(qname, a) for a in s_copy.get("args", [])]
            s_copy["retval"] = _redact_return_value(qname, s_copy.get("retval"))
            redacted_snaps.append(s_copy)
        fn_info["arg_snapshots"] = redacted_snaps
        fn_info["argument_snapshots"] = redacted_snaps
        fn_info["return_values"] = [
            _redact_return_value(qname, rv) for rv in fn_info.get("return_values", [])
        ]
    redacted["redacted"] = True
    return redacted


def build_call_map(
    target: str,
    patterns: list[str] | tuple[str, ...],
    raw_output: str,
    *,
    action: str = "default",
    transport: str = "usb",
    timestamp: str | None = None,
    redact: bool = False,
    max_calls: int = MAX_PARSED_CALLS,
    max_snapshots_per_function: int = MAX_SNAPSHOTS_PER_FUNCTION,
    raw_truncated: bool = False,
) -> dict[str, Any]:
    """
    Build a structured, deterministic JSON call map from a `frida-trace` session,
    including discovered symbols, per-function argument snapshots, caller/callee
    relationships, and the full hierarchical call sequence.
    """
    safe_target = validate_target(target)
    safe_patterns = [validate_symbol_glob(p) for p in (patterns or ("*",))]
    parsed = parse_trace_output(raw_output, max_calls=max_calls)
    discovered_list = parsed["discovered_functions"]
    calls = parsed["calls"]
    snapshots_truncated = False

    functions_map: dict[str, dict[str, Any]] = {}
    for d in discovered_list:
        qname = d["qualified_name"]
        functions_map[qname] = {
            "symbol": d["symbol"],
            "module": d["module"],
            "qualified_name": qname,
            "handler_status": d["status"],
            "call_count": 0,
            "callers": set(),
            "callees": set(),
            "arg_snapshots": [],
            "return_values": [],
        }

    edge_counts: dict[tuple[str, str], int] = {}
    threads_seen: list[str] = []
    entry_points: list[str] = []
    max_depth = 0

    for call in calls:
        qname = call["qualified_name"]
        if qname not in functions_map:
            functions_map[qname] = {
                "symbol": call["symbol"],
                "module": call["module"],
                "qualified_name": qname,
                "handler_status": "observed",
                "call_count": 0,
                "callers": set(),
                "callees": set(),
                "arg_snapshots": [],
                "return_values": [],
            }
        fn_entry = functions_map[qname]
        fn_entry["call_count"] += 1
        if len(fn_entry["arg_snapshots"]) < max_snapshots_per_function:
            fn_entry["arg_snapshots"].append({
                "call_id": call["call_id"],
                "timestamp_ms": call["timestamp_ms"],
                "thread_id": call["thread_id"],
                "depth": call["depth"],
                "args": call["args"],
                "retval": call["retval"],
            })
        else:
            snapshots_truncated = True

        if call["retval"] is not None and len(fn_entry["return_values"]) < max_snapshots_per_function:
            fn_entry["return_values"].append(call["retval"])

        if call["thread_id"] not in threads_seen:
            threads_seen.append(call["thread_id"])
        if call["depth"] > max_depth:
            max_depth = call["depth"]
        if call["depth"] == 0 and qname not in entry_points:
            entry_points.append(qname)

        caller = call.get("caller")
        if caller:
            fn_entry["callers"].add(caller)
            if caller in functions_map:
                functions_map[caller]["callees"].add(qname)
            edge_key = (caller, qname)
            edge_counts[edge_key] = edge_counts.get(edge_key, 0) + 1

    # Enrich discovered_functions with call_count per documented schema
    enriched_discovered = []
    for d in discovered_list:
        qname = d["qualified_name"]
        d_copy = dict(d)
        d_copy["call_count"] = functions_map.get(qname, {}).get("call_count", 0)
        enriched_discovered.append(d_copy)

    # Convert sets to sorted lists for deterministic JSON output
    serialized_functions: dict[str, dict[str, Any]] = {}
    for qname in sorted(functions_map):
        info = functions_map[qname]
        serialized_functions[qname] = {
            "symbol": info["symbol"],
            "module": info["module"],
            "qualified_name": info["qualified_name"],
            "handler_status": info["handler_status"],
            "call_count": info["call_count"],
            "callers": sorted(info["callers"]),
            "callees": sorted(info["callees"]),
            "arg_snapshots": info["arg_snapshots"],
            "argument_snapshots": info["arg_snapshots"],
            "return_values": info["return_values"],
        }

    call_graph = [
        {"caller": caller, "callee": callee, "count": count}
        for (caller, callee), count in sorted(edge_counts.items())
    ]

    called_names = [q for q, f in serialized_functions.items() if f["call_count"] > 0]
    uncalled_names = [q for q, f in serialized_functions.items() if f["call_count"] == 0]
    is_truncated = bool(raw_truncated or parsed.get("truncated") or snapshots_truncated)

    result = {
        "schema_version": "1.0",
        "task_id": "PENT-06",
        "target": safe_target,
        "action": action,
        "patterns": safe_patterns,
        "transport": transport,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "truncated": is_truncated,
        "discovered_functions": enriched_discovered,
        "summary": {
            "discovered_count": len(enriched_discovered),
            "total_discovered": len(enriched_discovered),
            "functions_called_count": len(called_names),
            "unique_functions_called": len(called_names),
            "total_calls": len(calls),
            "unique_edges": len(call_graph),
            "uncalled_functions": uncalled_names,
            "max_depth": max_depth,
            "threads_observed": threads_seen,
            "entry_points": entry_points,
            "truncated": is_truncated,
        },
        "functions": serialized_functions,
        "call_graph": call_graph,
        "call_sequence": calls,
        "calls": calls,
    }
    if redact:
        return redact_call_map(result)
    return result


def render_annotated_session_log(
    call_map: dict[str, Any],
    raw_output: str,
    command: list[str] | None = None,
    *,
    redact: bool = True,
) -> str:
    """Render a human-readable, annotated session log from a call map and raw trace output."""
    effective_map = redact_call_map(call_map) if (redact and not call_map.get("redacted")) else call_map
    effective_raw = redact_trace_text(raw_output) if redact else raw_output
    summary = effective_map.get("summary", {})
    discovered_count = summary.get("discovered_count", summary.get("total_discovered", 0))
    called_count = summary.get("functions_called_count", summary.get("unique_functions_called", 0))

    lines = [
        "# os-lab frida-trace Annotated Session Log (PENT-06)",
        "",
        f"- **Target Process:** `{effective_map.get('target')}`",
        f"- **Traced Action:** `{effective_map.get('action')}`",
        f"- **Symbol Globs:** `{', '.join(effective_map.get('patterns', []))}`",
        f"- **Transport:** `{effective_map.get('transport')}`",
        f"- **Timestamp:** `{effective_map.get('timestamp')}`",
        f"- **Redaction:** `{'enabled' if redact else 'disabled (unsafe plaintext)'}`",
    ]
    if command:
        lines.append(f"- **Command:** `{' '.join(command)}`")
    if summary.get("truncated") or effective_map.get("truncated"):
        lines.append("- **Notice:** `Trace output or call sequence was truncated due to volume limits.`")

    lines.extend([
        "",
        "## Summary Metrics",
        "",
        f"- **Discovered Functions:** {discovered_count}",
        f"- **Total Function Calls:** {summary.get('total_calls', 0)}",
        f"- **Unique Functions Fired:** {called_count}",
        f"- **Unique Call Edges:** {summary.get('unique_edges', len(effective_map.get('call_graph', [])))}",
        f"- **Max Call Depth:** {summary.get('max_depth', 0)}",
        f"- **Threads Observed:** {', '.join(summary.get('threads_observed', [])) or 'none'}",
        f"- **Entry Points:** {', '.join(summary.get('entry_points', [])) or 'none'}",
        "",
        "## Discovered Functions",
        "",
        "| Qualified Name | Module | Symbol | Status | Calls |",
        "|:---|:---|:---|:---|---:|",
    ])

    funcs = effective_map.get("functions", {})
    for qname, finfo in funcs.items():
        mod = finfo.get("module") or "—"
        sym = finfo.get("symbol") or qname
        status = finfo.get("handler_status") or "observed"
        count = finfo.get("call_count", 0)
        lines.append(f"| `{qname}` | `{mod}` | `{sym}` | {status} | {count} |")

    lines.extend(["", "## Call Hierarchy & Per-Call Argument Snapshots", ""])
    calls = effective_map.get("call_sequence", effective_map.get("calls", []))
    if not calls:
        lines.append("_No function calls captured during the trace window._")
    else:
        for call in calls:
            indent = "  " * int(call.get("depth", 0))
            arg_parts = []
            for a in call.get("args", []):
                val = a.get("value")
                annot = a.get("annotation")
                disp = f"{val!r} ({annot})" if annot else repr(val)
                arg_parts.append(f"{a.get('name')}={disp}")
            args_formatted = ", ".join(arg_parts)
            ret = call.get("retval")
            ret_suffix = f" => {ret}" if ret is not None else ""
            dur = call.get("duration_ms")
            dur_suffix = f" [{dur} ms]" if dur is not None else ""
            lines.append(
                f"{indent}- **[#{call['call_id']}]** `{call['timestamp_ms']} ms` "
                f"(`{call['thread_id']}`) `{call['qualified_name']}({args_formatted})`{ret_suffix}{dur_suffix}"
            )

    lines.extend(["", "## Caller -> Callee Graph Edges", ""])
    edges = effective_map.get("call_graph", [])
    if not edges:
        lines.append("_No nested caller -> callee edges observed._")
    else:
        for edge in edges:
            lines.append(f"- `{edge['caller']}` -> `{edge['callee']}` ({edge['count']}x)")

    lines.extend([
        "",
        "## Raw frida-trace Output",
        "",
        "```text",
        effective_raw.strip(),
        "```",
        "",
    ])
    return "\n".join(lines)


def _read_bounded_file(path: Path, max_bytes: int) -> tuple[str, bool]:
    with open(path, "rb") as fh:
        raw_bytes = fh.read(max_bytes + 1)
    truncated = len(raw_bytes) > max_bytes
    if truncated:
        raw_bytes = raw_bytes[:max_bytes]
    return raw_bytes.decode("utf-8", errors="replace"), truncated


def _run_bounded_frida_trace(
    cmd: list[str],
    timeout_sec: float,
    max_output_bytes: int,
) -> tuple[str, bool]:
    """
    Execute `frida-trace` with bounded stdout buffering and return `(raw_output, truncated)`.
    Raises `RuntimeError` if `frida-trace` exits with a non-zero status before timeout.
    """
    if not cmd or not isinstance(cmd[0], str) or any(ch in SHELL_META_CHARS for arg in cmd for ch in arg):
        raise TraceScopeError("Refusing to execute command with invalid arguments")

    safe_cmd = [str(part) for part in cmd]
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit, python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
        with subprocess.Popen(
            safe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        ) as proc:
            stdout_pipe = getattr(proc, "stdout", None)
            if stdout_pipe is None:
                # Support lightweight test doubles that implement communicate() without a pipe
                try:
                    out_str, _ = proc.communicate(timeout=timeout_sec)
                    timed_out = False
                except subprocess.TimeoutExpired as exc:
                    proc.kill()
                    out_bytes = exc.stdout or ""
                    out_str = (
                        out_bytes.decode("utf-8", errors="replace")
                        if isinstance(out_bytes, bytes)
                        else str(out_bytes)
                    )
                    timed_out = True
                raw_output = out_str or ""
                encoded = raw_output.encode("utf-8", errors="replace")
                truncated = len(encoded) > max_output_bytes
                if truncated:
                    raw_output = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
                rc = getattr(proc, "returncode", 0)
                if not timed_out and not truncated and rc not in (0, None):
                    raise RuntimeError(
                        f"frida-trace exited with code {rc}: {raw_output.strip()[:300]}"
                    )
                return raw_output, truncated

            chunks: list[str] = []
            bytes_read = 0
            truncated = False

            def _reader() -> None:
                nonlocal bytes_read, truncated
                try:
                    while True:
                        piece = stdout_pipe.read(4096)
                        if not piece:
                            break
                        piece_bytes = len(piece.encode("utf-8", errors="replace"))
                        if bytes_read + piece_bytes > max_output_bytes:
                            allowed = max(0, max_output_bytes - bytes_read)
                            if allowed > 0:
                                chunks.append(
                                    piece.encode("utf-8", errors="replace")[:allowed].decode(
                                        "utf-8", errors="ignore"
                                    )
                                )
                            bytes_read = max_output_bytes
                            truncated = True
                            try:
                                proc.kill()
                            except OSError:
                                pass
                            break
                        chunks.append(piece)
                        bytes_read += piece_bytes
                except Exception:
                    pass

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()
            timed_out = False
            try:
                proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.wait()
            reader_thread.join(timeout=2.0)
            raw_output = "".join(chunks)
            rc = proc.returncode
            if not timed_out and not truncated and rc not in (0, None):
                raise RuntimeError(
                    f"frida-trace exited with code {rc}: {raw_output.strip()[:300]}"
                )
            return raw_output, truncated
    except FileNotFoundError as exc:
        raise RuntimeError(
            "frida-trace executable not found. Install frida-tools in .venv or pass --simulate / --input-log."
        ) from exc


def _publish_artifacts_atomically(
    out_json: str | Path | None,
    json_payload: str | None,
    session_log: str | Path | None,
    log_payload: str | None,
) -> None:
    """Stage and atomically publish the JSON call map and Markdown session log together."""
    if not out_json and not session_log:
        return

    with artifact_lock():
        staged: list[tuple[Path, Path, bytes | None]] = []
        token = f"{os.getpid()}.{uuid.uuid4().hex[:8]}"
        try:
            if out_json and json_payload is not None:
                out_path = Path(out_json)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                prev_bytes = out_path.read_bytes() if out_path.is_file() else None
                tmp_out = out_path.with_name(f".{out_path.name}.{token}.tmp")
                with open(tmp_out, "wb") as fh:
                    fh.write(json_payload.encode("utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
                staged.append((tmp_out, out_path, prev_bytes))

            if session_log and log_payload is not None:
                log_path = Path(session_log)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                prev_bytes = log_path.read_bytes() if log_path.is_file() else None
                tmp_log = log_path.with_name(f".{log_path.name}.{token}.tmp")
                with open(tmp_log, "wb") as fh:
                    fh.write(log_payload.encode("utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
                staged.append((tmp_log, log_path, prev_bytes))

            published: list[tuple[Path, bytes | None]] = []
            try:
                for tmp_file, dest_file, prev_bytes in staged:
                    os.replace(tmp_file, dest_file)
                    published.append((dest_file, prev_bytes))
            except Exception:
                for dest_file, prev_bytes in published:
                    try:
                        if prev_bytes is None:
                            dest_file.unlink(missing_ok=True)
                        else:
                            dest_file.write_bytes(prev_bytes)
                    except OSError:
                        pass
                raise
        finally:
            for tmp_file, _, _ in staged:
                try:
                    if tmp_file.exists():
                        tmp_file.unlink()
                except OSError:
                    pass


def run_trace_session(
    target: str,
    include_globs: list[str] | tuple[str, ...] = (),
    *,
    exclude_globs: list[str] | tuple[str, ...] = (),
    module_globs: list[str] | tuple[str, ...] = (),
    java_globs: list[str] | tuple[str, ...] = (),
    objc_globs: list[str] | tuple[str, ...] = (),
    transport: str = "usb",
    device_id: str | None = None,
    host: str | None = None,
    spawn: bool = False,
    action: str = "default",
    timeout_sec: float = 10.0,
    input_log: str | Path | None = None,
    simulate: bool = False,
    out_json: str | Path | None = None,
    session_log: str | Path | None = None,
    handlers_dir: str | Path | None = None,
    runner: Any = None,
    timestamp: str | None = None,
    redact: bool = True,
    max_output_bytes: int = MAX_RAW_OUTPUT_BYTES,
    max_calls: int = MAX_PARSED_CALLS,
    max_snapshots_per_function: int = MAX_SNAPSHOTS_PER_FUNCTION,
) -> dict[str, Any]:
    """
    Execute a `frida-trace` session (or replay an input log / built-in lab simulation),
    build the JSON call map, and optionally write both the call map and annotated session log.
    """
    effective_include_globs = (
        list(include_globs)
        if (include_globs or module_globs or java_globs or objc_globs)
        else ["*"]
    )
    cmd = build_frida_trace_cmd(
        target=target,
        include_globs=effective_include_globs,
        exclude_globs=exclude_globs,
        module_globs=module_globs,
        java_globs=java_globs,
        objc_globs=objc_globs,
        transport=transport,
        device_id=device_id,
        host=host,
        spawn=spawn,
        handlers_dir=str(handlers_dir) if handlers_dir else None,
    )

    # Instrument existing Frida handler stubs BEFORE starting the live trace session
    if handlers_dir:
        instrument_handlers_dir(handlers_dir)

    raw_truncated = False
    if input_log is not None:
        raw_output, raw_truncated = _read_bounded_file(Path(input_log), max_output_bytes)
    elif simulate:
        raw_output = SAMPLE_LAB_TRACE_LOG
    elif runner is not None:
        raw_output = runner(cmd, timeout_sec)
        encoded = raw_output.encode("utf-8", errors="replace")
        if len(encoded) > max_output_bytes:
            raw_output = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
            raw_truncated = True
    else:
        raw_output, raw_truncated = _run_bounded_frida_trace(cmd, timeout_sec, max_output_bytes)

    all_patterns = (
        list(effective_include_globs)
        + [f"module:{m}" for m in module_globs]
        + [f"java:{j}" for j in java_globs]
        + list(objc_globs)
    )
    call_map = build_call_map(
        target=target,
        patterns=all_patterns or ["*"],
        raw_output=raw_output,
        action=action,
        transport=transport,
        timestamp=timestamp,
        redact=redact,
        max_calls=max_calls,
        max_snapshots_per_function=max_snapshots_per_function,
        raw_truncated=raw_truncated,
    )
    call_map["command"] = cmd
    call_map["mode"] = "input_log" if input_log is not None else ("simulate" if simulate else "live")

    json_payload = (
        json.dumps(call_map, indent=2, ensure_ascii=False) + "\n"
        if out_json
        else None
    )
    log_payload = (
        render_annotated_session_log(call_map, raw_output, command=cmd, redact=redact)
        if session_log
        else None
    )
    _publish_artifacts_atomically(out_json, json_payload, session_log, log_payload)

    return call_map


_PATTERN_FLAGS = frozenset({
    "-i",
    "--include",
    "-x",
    "--exclude",
    "-I",
    "--include-module",
    "-j",
    "--java",
    "-m",
    "--objc",
    "--emit-handler",
    "-t",
    "--target",
})


def _normalize_cli_argv(argv: list[str]) -> list[str]:
    """
    Allow pattern/target options to receive leading-hyphen values (such as Objective-C
    globs `-[NSURLSession *]`) without `argparse` misinterpreting the value as a flag.
    """
    normalized: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            normalized.extend(argv[i:])
            break
        if tok in _PATTERN_FLAGS and i + 1 < len(argv):
            nxt = argv[i + 1]
            if nxt.startswith("-"):
                normalized.append(f"{tok}={nxt}")
                i += 2
                continue
        normalized.append(tok)
        i += 1
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trace_runner.py",
        description="frida-trace Auto-Tracer & Call-Map Builder (PENT-06)",
    )
    parser.add_argument(
        "-t",
        "--target",
        default=None,
        help="Target process name, package identifier, or PID (default: $PKG or com.testlab.vulnerable)",
    )
    parser.add_argument(
        "-i",
        "--include",
        action="append",
        dest="include_globs",
        help="Function symbol glob to include (repeatable, e.g. -i '*auth*' -i 'check_*')",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        dest="exclude_globs",
        default=[],
        help="Function symbol glob to exclude (repeatable)",
    )
    parser.add_argument(
        "-I",
        "--include-module",
        action="append",
        dest="module_globs",
        default=[],
        help="Module glob to include (repeatable, e.g. -I 'libnative.so')",
    )
    parser.add_argument(
        "-j",
        "--java",
        action="append",
        dest="java_globs",
        default=[],
        help="Java class!method glob to trace (repeatable, e.g. -j '*!*auth*')",
    )
    parser.add_argument(
        "-m",
        "--objc",
        action="append",
        dest="objc_globs",
        default=[],
        help="Objective-C method glob to trace (repeatable, e.g. -m '-[NSURLSession *]')",
    )
    parser.add_argument(
        "--transport",
        choices=["usb", "local", "remote"],
        default="usb",
        help="Frida transport mode (default: usb)",
    )
    parser.add_argument("-D", "--device", dest="device_id", help="Explicit Frida device ID")
    parser.add_argument("-H", "--host", help="Remote frida-server host:port (with --transport remote)")
    parser.add_argument("-f", "--spawn", action="store_true", help="Spawn the target process instead of attaching")
    parser.add_argument(
        "--action",
        default="default",
        help="Label for the user/app action being traced (e.g. login_attempt)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Trace capture window in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--input-log",
        help="Parse an existing frida-trace output log file instead of invoking frida-trace",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run offline against the deterministic 05.10 lab auth/crypto trace fixture",
    )
    parser.add_argument(
        "-o",
        "--out",
        help="Output path for the generated JSON call map",
    )
    parser.add_argument(
        "--session-log",
        help="Output path for the annotated markdown session log",
    )
    parser.add_argument(
        "--handlers-dir",
        help="Directory for frida-trace __handlers__ scripts",
    )
    parser.add_argument(
        "--emit-handler",
        metavar="SYMBOL",
        help="Print an instrumented defineHandler JS template for SYMBOL and exit",
    )
    parser.add_argument(
        "--unsafe-plaintext",
        action="store_true",
        help="Disable automatic credential/token redaction in generated artifacts",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the JSON call map to stdout",
    )

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_normalize_cli_argv(raw_argv))

    try:
        if args.emit_handler:
            mod, sym, _ = _split_qualified_symbol(args.emit_handler)
            print(generate_handler_script(symbol=sym, module=mod), end="")
            return 0

        target = args.target if args.target is not None else (os.environ.get("PKG") or "com.testlab.vulnerable")
        includes = list(args.include_globs or [])
        if not includes and not (args.module_globs or args.java_globs or args.objc_globs):
            env_glob = os.environ.get("GLOB")
            includes = [env_glob] if env_glob else ["*"]

        call_map = run_trace_session(
            target=target,
            include_globs=includes,
            exclude_globs=args.exclude_globs,
            module_globs=args.module_globs,
            java_globs=args.java_globs,
            objc_globs=args.objc_globs,
            transport=args.transport,
            device_id=args.device_id,
            host=args.host,
            spawn=args.spawn,
            action=args.action,
            timeout_sec=args.timeout,
            input_log=args.input_log,
            simulate=args.simulate,
            out_json=args.out,
            session_log=args.session_log,
            handlers_dir=args.handlers_dir,
            redact=not args.unsafe_plaintext,
        )
    except TraceScopeError as exc:
        print(f"error (scope): {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json or not (args.out or args.session_log):
        print(json.dumps(call_map, indent=2, ensure_ascii=False))
    else:
        summary = call_map["summary"]
        trunc_note = " [TRUNCATED]" if summary.get("truncated") else ""
        print(
            f"[+] Trace complete for {call_map['target']} ({summary['discovered_count']} discovered, "
            f"{summary['total_calls']} calls, max depth {summary['max_depth']}){trunc_note}"
        )
        if args.out:
            print(f"    Call map JSON : {args.out}")
        if args.session_log:
            print(f"    Session log   : {args.session_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
