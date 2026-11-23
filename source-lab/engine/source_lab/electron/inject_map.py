#!/usr/bin/env python3
"""PENT-10 - Electron app unpacker and injection-point mapper (static, offline).

Given an Electron application - either an app directory or an ``app.asar``
archive - this maps the *injection surface*: the configuration flags and code
patterns that let a renderer-side problem (an XSS, a malicious remote page, a
tampered local resource) reach the main process or Node, which is the lab
Electron injection case this reproduces.

What it looks at
----------------
* **Unpack.** ``app.asar`` is read with the repo's own pickle parser
  (:mod:`source_lab.sourcemap.archives.asar`); loose files and an
  ``app.asar.unpacked`` overlay are read from disk. Only text source files
  (``.js/.mjs/.cjs/.ts/.html/.htm/.json``) are scanned; binaries, ``node_modules``
  and ``.git`` are skipped.
* **Entry points.** ``package.json`` ``main`` (and the fixture's ``preload``),
  every ``webPreferences.preload`` seen in main code, files named ``preload*`` and
  the renderer HTML pages.
* **BrowserWindow / webPreferences.** ``nodeIntegration``, ``contextIsolation``,
  ``sandbox``, ``webSecurity``, ``allowRunningInsecureContent``,
  ``enableRemoteModule``, ``nodeIntegrationInWorker/InSubFrames``,
  ``experimentalFeatures``, ``webviewTag`` - each weakened flag is a finding; a
  window whose ``webPreferences`` never sets ``contextIsolation`` is noted
  (the secure default is version-dependent).
* **Navigation / remote content.** ``loadURL('http(s)://...')`` to a non-local
  origin, and remote content loaded without a ``setWindowOpenHandler`` /
  ``will-navigate`` guard.
* **Preload bridge.** ``contextBridge.exposeInMainWorld`` that hands the renderer
  ``ipcRenderer``/``require``/``child_process``/``fs`` directly, and
  ``window.X = require(...)`` in a preload.
* **IPC -> shell.** a file with ``ipcMain`` handlers and a concatenated
  ``child_process`` ``exec/spawn`` (command-injection bridge).
* **Dynamic code & CSP.** ``eval`` / ``new Function``, ``shell.openExternal`` with a
  non-literal argument, and renderer HTML with no CSP or a ``unsafe-eval`` /
  ``unsafe-inline`` CSP.

Safety envelope
---------------
Strictly static and offline: application code is read as text, never executed;
hosts are classified lexically, never resolved; nothing is contacted. The tool
never writes inside the analyzed tree, never follows symlinks, caps the number
and size of files it reads, scans file contents in linear time, and escapes
control/bidi characters in every app-supplied string it prints. Standard library
only; Python 3.11+.

Usage::

    python3 -m source_lab.electron <app_dir | app.asar> [--format text|md|json]
        [-o OUT] [--max-files N]

Exit codes: ``0`` = complete scan, no high/medium findings, ``1`` = high/medium
findings or an incomplete scan, ``2`` = usage/input error. Use only on applications you own or are authorized
to assess.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # normal package import
    from source_lab.sourcemap.archives.asar import load_asar, AsarError
except Exception:  # pragma: no cover - allow running the file directly
    _HERE = Path(__file__).resolve()
    sys.path.insert(0, str(_HERE.parents[2]))  # source-lab/engine
    from source_lab.sourcemap.archives.asar import load_asar, AsarError

TOOL = "electron_inject"
VERSION = "1.0.1"
MIN_PYTHON = (3, 11)

SOURCE_EXTS = {".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".html", ".htm", ".json"}
HTML_EXTS = (".html", ".htm")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".next", "coverage"}
DEFAULT_MAX_FILES = 4000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_WEBPREFS_SPAN = 4000  # chars scanned inside a single webPreferences object
SNIPPET_MAX = 200

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
FAILING_SEVERITIES = {"high", "medium"}

DISCLAIMER = (
    "Static, offline analysis: no application code was executed, no host name was "
    "resolved and no host was contacted. Findings are potential injection points "
    "derived from configuration and source text, not observed behaviour. "
    "Use only on applications you own or are authorized to assess."
)

# Local / non-network hosts that make a loadURL benign.
_LOCAL_HOST_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?:[:/]|$)", re.I)

# A webPreferences boolean flag -> (severity, title, rationale, remediation).
# Calibration: "high" = the flag alone hands page JS a path to Node/main.
# sandbox:false, allowRunningInsecureContent and webviewTag widen the blast
# radius of *another* bug, so they are "medium" here (windows_rules rates them
# high). Both levels fail the run (exit 1), so CI behaviour is identical.
# `expected_bad` is the value that is the weakening one.
_WEBPREF_FLAGS: Tuple[Tuple[str, bool, str, str, str, str], ...] = (
    ("nodeIntegration", True, "high",
     "nodeIntegration enabled",
     "The renderer gets full Node.js; any XSS or malicious page becomes main-host code execution.",
     "Set nodeIntegration:false and expose only a vetted API through a contextBridge preload."),
    ("contextIsolation", False, "high",
     "contextIsolation disabled",
     "Preload and page share one JS world, so a page can reach privileged preload internals.",
     "Set contextIsolation:true (the modern default) and bridge with contextBridge."),
    ("webSecurity", False, "high",
     "webSecurity disabled",
     "Same-origin policy is off, allowing cross-origin fetches and resource loads from the renderer.",
     "Remove webSecurity:false; load only trusted local content."),
    ("enableRemoteModule", True, "high",
     "remote module enabled",
     "The deprecated remote module exposes main-process objects to the renderer.",
     "Remove enableRemoteModule; use ipcRenderer/ipcMain with explicit, validated channels."),
    ("nodeIntegrationInSubFrames", True, "high",
     "nodeIntegrationInSubFrames enabled",
     "Sub-frames (including remote iframes) gain Node integration.",
     "Set nodeIntegrationInSubFrames:false."),
    ("sandbox", False, "medium",
     "sandbox disabled",
     "The renderer process is not sandboxed, widening the impact of a renderer compromise.",
     "Prefer sandbox:true unless a preload genuinely needs Node (then keep contextIsolation:true)."),
    ("allowRunningInsecureContent", True, "medium",
     "insecure content allowed",
     "HTTPS pages may load and run HTTP sub-resources, enabling downgrade/MITM injection.",
     "Remove allowRunningInsecureContent:true."),
    ("nodeIntegrationInWorker", True, "medium",
     "nodeIntegrationInWorker enabled",
     "Web workers gain Node integration, another path to Node from page-controlled code.",
     "Set nodeIntegrationInWorker:false."),
    ("webviewTag", True, "medium",
     "<webview> tag enabled",
     "The <webview> tag lets page content embed arbitrary guests; its own webPreferences must be locked down.",
     "Disable webviewTag unless required; if used, set a will-attach-webview guard."),
    ("experimentalFeatures", True, "low",
     "experimental features enabled",
     "Experimental Chromium features broaden the attack surface.",
     "Disable experimentalFeatures in shipping builds."),
)


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    surface: str  # main | preload | renderer | navigation | ipc | csp
    file: str
    line: int
    snippet: str
    rationale: str
    remediation: str

    def sort_key(self) -> Tuple[int, str, int]:
        return (SEVERITY_ORDER.get(self.severity, 9), self.file, self.line)


@dataclass
class SourceFile:
    path: str
    text: str
    origin: str  # "asar" | "disk"
    role: str = "other"  # main | preload | renderer | other


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u2028\u2029\u202a-\u202e]")


def _clean(s: str) -> str:
    """Escape control/bidi/invisible chars so app text can't corrupt output."""
    return _CTRL_RE.sub(lambda m: "\\u%04x" % ord(m.group(0)), s)


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


def _lineno(starts: List[int], idx: int) -> int:
    # binary search without importing bisect semantics subtly wrong: use bisect
    import bisect
    return bisect.bisect_right(starts, idx)


def _snippet(text: str, starts: List[int], idx: int) -> str:
    line = _lineno(starts, idx)
    begin = starts[line - 1]
    end = text.find("\n", begin)
    if end == -1:
        end = len(text)
    frag = text[begin:end].strip()
    if len(frag) > SNIPPET_MAX:
        frag = frag[:SNIPPET_MAX] + "..."
    return _clean(frag)


def _is_probably_text(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    return True


def _within(base_real: str, full: str) -> bool:
    """True only if ``full`` resolves to a path inside ``base_real`` (no symlink escape)."""
    try:
        fr = os.path.realpath(full)
    except OSError:
        return False
    return fr == base_real or fr.startswith(base_real + os.sep)


# --------------------------------------------------------------------------- #
# Loading / unpacking
# --------------------------------------------------------------------------- #

def _in_skipped_dir(member: str) -> bool:
    return any(part in SKIP_DIRS for part in member.split("/")[:-1])


def _read_asar_sources(data: bytes, limitations: List[str], max_entries: int,
                       unpacked_dir: Optional[Path] = None) -> Dict[str, str]:
    header, data_base, packed, unpacked, notes = load_asar(data, max_entries=max_entries)
    for note in notes:
        # entry/byte caps mean members were never mounted -> the scan is partial
        if "cap" in note and "reached" in note:
            limitations.append("INCOMPLETE: " + note)
        else:
            limitations.append(note)
    out: Dict[str, str] = {}
    for member, (offset, size) in packed.items():
        ext = os.path.splitext(member)[1].lower()
        if ext not in SOURCE_EXTS or _in_skipped_dir(member):
            continue  # node_modules/.git etc. are excluded inside archives too
        if size > MAX_FILE_BYTES:
            limitations.append(f"INCOMPLETE: asar member too large, skipped: {member}")
            continue
        start = data_base + offset
        if start < 0 or start + size > len(data):
            # declared range runs past the bytes we have (truncated/capped archive)
            limitations.append(f"INCOMPLETE: asar member truncated, not scanned: {member}")
            continue
        chunk = data[start:start + size]
        if not _is_probably_text(chunk):
            continue
        out[member] = chunk.decode("utf-8", "replace")
    wanted = sorted(m for m in unpacked
                    if os.path.splitext(m)[1].lower() in SOURCE_EXTS and not _in_skipped_dir(m))
    if wanted:
        if unpacked_dir is not None and unpacked_dir.is_dir() and not unpacked_dir.is_symlink():
            base_real = os.path.realpath(unpacked_dir)
            missing = 0
            for member in wanted:
                full = os.path.join(unpacked_dir, *member.split("/"))
                if os.path.islink(full) or not _within(base_real, full) or not os.path.isfile(full):
                    missing += 1
                    continue
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    limitations.append(f"INCOMPLETE: unpacked member too large, skipped: {member}")
                    continue
                with open(full, "rb") as fh:
                    blob = fh.read(MAX_FILE_BYTES + 1)
                if _is_probably_text(blob):
                    out.setdefault(member, blob.decode("utf-8", "replace"))
            if missing:
                limitations.append(f"INCOMPLETE: {missing} unpacked member(s) missing from .asar.unpacked")
        else:
            limitations.append(
                f"INCOMPLETE: {len(wanted)} source member(s) live in .asar.unpacked, which was not found")
    return out


def _walk_disk_sources(root: Path, limitations: List[str],
                       max_files: int) -> Dict[str, str]:
    out: Dict[str, str] = {}
    total = 0
    count = 0
    root_real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):  # followlinks=False (default)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            ext = os.path.splitext(name)[1].lower()
            if ext not in SOURCE_EXTS:
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not _within(root_real, full) or not os.path.isfile(full):
                continue  # isfile(): regular files only - a FIFO would block on open()
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if count >= max_files:
                limitations.append(f"INCOMPLETE: disk file cap {max_files} reached, remaining files not scanned")
                return out
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                limitations.append(f"INCOMPLETE: disk file too large, skipped: {rel}")
                continue
            total += size
            if total > MAX_TOTAL_BYTES:
                limitations.append("INCOMPLETE: disk total-bytes cap reached, remaining files not scanned")
                return out
            try:
                with open(full, "rb") as fh:
                    data = fh.read(MAX_FILE_BYTES + 1)
            except OSError:
                continue
            if not _is_probably_text(data):
                continue
            out[rel] = data.decode("utf-8", "replace")
            count += 1
    return out


def _load_sources(root: Path, limitations: List[str],
                  max_files: int) -> Tuple[Dict[str, str], List[str], bool]:
    """Return (member->text, asar paths found, is_electron_evidence)."""
    sources: Dict[str, str] = {}
    asar_paths: List[str] = []
    if root.is_symlink():
        # never follow a symlinked target out of the requested tree
        raise ValueError(f"refusing to analyze a symlinked target: {root}")
    if root.is_file() and root.suffix.lower() == ".asar":
        try:
            with open(root, "rb") as fh:
                data = fh.read(MAX_TOTAL_BYTES + 1)
        except OSError as exc:
            raise ValueError(f"cannot read archive {root}: {exc}") from exc
        if len(data) > MAX_TOTAL_BYTES:
            limitations.append("INCOMPLETE: archive larger than the total-bytes cap; tail not scanned")
            data = data[:MAX_TOTAL_BYTES]
        overlay = root.with_name(root.name + ".unpacked")
        sources.update(_read_asar_sources(data, limitations, max_files, overlay))
        asar_paths.append(root.name)
        return sources, asar_paths, True
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory or .asar file: {root}")
    # loose files first
    sources.update(_walk_disk_sources(root, limitations, max_files))
    # any app.asar under the tree (resources/app.asar is the usual spot).
    # Archives share ONE file budget and ONE byte budget with the loose files.
    root_real = os.path.realpath(root)
    bytes_used = sum(len(t) for t in sources.values())
    stop = False
    for dirpath, dirnames, filenames in os.walk(root):  # followlinks=False (default)
        if stop:
            break
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            if not name.endswith(".asar"):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not _within(root_real, full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            files_left = max_files - len(sources)
            bytes_left = MAX_TOTAL_BYTES - bytes_used
            if files_left <= 0 or bytes_left <= 0:
                limitations.append(f"INCOMPLETE: scan budget exhausted before archive {rel}")
                stop = True
                break
            try:
                with open(full, "rb") as fh:
                    data = fh.read(bytes_left + 1)
            except OSError as exc:
                limitations.append(f"INCOMPLETE: archive {rel} could not be read: {exc}")
                continue
            if len(data) > bytes_left:
                limitations.append(f"INCOMPLETE: archive {rel} exceeds the remaining byte budget; tail not scanned")
                data = data[:bytes_left]
            bytes_used += len(data)
            try:
                members = _read_asar_sources(data, limitations, files_left,
                                             Path(full + ".unpacked"))
            except AsarError as exc:
                limitations.append(f"INCOMPLETE: asar {rel} could not be parsed: {exc}")
                continue
            asar_paths.append(rel)
            for mname, text in members.items():
                key = mname if mname not in sources else f"{rel}!/{mname}"
                sources.setdefault(key, text)
    is_electron = bool(asar_paths)
    # package.json electron evidence
    pkg = sources.get("package.json")
    if pkg:
        if re.search(r'"electron"', pkg) or re.search(r'"main"\s*:', pkg):
            is_electron = True
    if any(re.search(r"require\(\s*['\"]electron['\"]\s*\)", t) for t in sources.values()):
        is_electron = True
    return sources, asar_paths, is_electron


# --------------------------------------------------------------------------- #
# Entry-point resolution
# --------------------------------------------------------------------------- #

def _resolve_entrypoints(sources: Dict[str, str]) -> Dict[str, List[str]]:
    main: List[str] = []
    preload: List[str] = []
    renderer: List[str] = []
    # the app's packaged manifest (inside app.asar) wins over a loose root one
    packaged = sorted(k for k in sources if k.endswith("!/package.json"))
    pkg_text = sources[packaged[0]] if packaged else sources.get("package.json")
    main_hint = None
    preload_hint = None
    if pkg_text:
        try:
            pkg = json.loads(pkg_text)
        except (ValueError, TypeError):
            pkg = None
        if isinstance(pkg, dict):
            # package.json fields can be any JSON type; only strings are usable hints.
            mh = pkg.get("main")
            ph = pkg.get("preload")
            main_hint = mh if isinstance(mh, str) else None
            preload_hint = ph if isinstance(ph, str) else None

    def _match(hint: Optional[str]) -> Optional[str]:
        if not isinstance(hint, str) or not hint.strip():
            return None
        h = hint.strip().replace("\\", "/")
        h = re.sub(r"^\.?/+", "", h)  # drop leading ./ or / (prefix, not char-set)
        candidates = [h]
        if not os.path.splitext(h)[1]:
            # Node resolves an extensionless or directory "main" to <h>.js / <h>/index.js
            base = h.rstrip("/")
            candidates += [base + ".js", base + ".cjs", base + ".mjs", base + "/index.js"]
        for cand in candidates:
            if not cand:
                continue
            for key in sources:
                if key == cand or key.endswith("/" + cand) or key.endswith("!/" + cand):
                    return key
        return None

    m = _match(main_hint) or _match("index.js") or _match("main.js")
    if m:
        main.append(m)
    p = _match(preload_hint)
    if p:
        preload.append(p)
    # preload referenced inside any webPreferences (.js / .cjs / .mjs)
    for key, text in sources.items():
        for pm in re.finditer(r"preload\s*:\s*[^,}\n]*?['\"]([^'\"]+?\.(?:js|cjs|mjs))['\"]", text):
            cand = _match(os.path.basename(pm.group(1)))
            if cand and cand not in preload:
                preload.append(cand)
    # files named preload* (any JS extension)
    for key in sources:
        base = key.rsplit("/", 1)[-1].lower()
        if base.startswith("preload") and base.endswith((".js", ".cjs", ".mjs")) and key not in preload:
            preload.append(key)
    for key in sources:
        if key.lower().endswith(HTML_EXTS):
            renderer.append(key)
    return {"main": sorted(set(main)), "preload": sorted(set(preload)),
            "renderer_html": sorted(set(renderer))}


def _assign_roles(sources: Dict[str, str], entry: Dict[str, List[str]]) -> Dict[str, str]:
    roles: Dict[str, str] = {}
    for k in entry["main"]:
        roles[k] = "main"
    for k in entry["preload"]:
        roles[k] = "preload"
    for k in entry["renderer_html"]:
        roles.setdefault(k, "renderer")
    for k in sources:
        roles.setdefault(k, "other")
    return roles


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

def _scan_webpreferences(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    for wp in re.finditer(r"webPreferences\s*:", text):
        brace = text.find("{", wp.end())
        if brace == -1 or brace - wp.end() > 40:
            continue
        # bounded brace matching
        depth = 0
        end = brace
        for i in range(brace, min(len(text), brace + MAX_WEBPREFS_SPAN)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        block = text[brace:end + 1]
        base = brace
        saw_context_isolation = False
        for flag, bad_value, sev, title, rationale, remediation in _WEBPREF_FLAGS:
            fm = re.search(rf"\b{flag}\s*:\s*(true|false)\b", block)
            if flag == "contextIsolation" and fm:
                saw_context_isolation = True
            if not fm:
                continue
            value = fm.group(1) == "true"
            if value is bad_value:
                idx = base + fm.start()
                out.append(Finding(
                    id=f"electron.webpref.{flag}",
                    severity=sev, title=title, surface="main",
                    file=sf.path, line=_lineno(starts, idx),
                    snippet=_snippet(text, starts, idx),
                    rationale=rationale, remediation=remediation))
        if not saw_context_isolation:
            idx = base
            out.append(Finding(
                id="electron.webpref.contextIsolation-unset",
                severity="info", title="contextIsolation not set explicitly",
                surface="main", file=sf.path, line=_lineno(starts, idx),
                snippet=_snippet(text, starts, idx),
                rationale="The secure default depends on the Electron version; set it explicitly.",
                remediation="Set contextIsolation:true explicitly on every BrowserWindow."))


def _scan_navigation(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    remote_hits = []
    for nm in re.finditer(r"\.loadURL\(\s*([`'\"])(https?://[^`'\"]+)\1", text):
        url = nm.group(2)
        if _LOCAL_HOST_RE.match(url):
            continue
        remote_hits.append(nm.start())
        out.append(Finding(
            id="electron.nav.remote-loadurl",
            severity="medium", title="remote content loaded via loadURL",
            surface="navigation", file=sf.path, line=_lineno(starts, nm.start()),
            snippet=_snippet(text, starts, nm.start()),
            rationale="Remote pages run inside the app window; combined with a weak webPreferences they lead to injection.",
            remediation="Prefer loadFile with local content; if remote is required, pin the origin and lock webPreferences."))
    if remote_hits:
        has_guard = ("setWindowOpenHandler" in text) or re.search(r"on\(\s*['\"]will-navigate['\"]", text)
        if not has_guard:
            idx = remote_hits[0]
            out.append(Finding(
                id="electron.nav.unguarded",
                severity="low", title="remote navigation without a navigation guard",
                surface="navigation", file=sf.path, line=_lineno(starts, idx),
                snippet=_snippet(text, starts, idx),
                rationale="No setWindowOpenHandler or will-navigate handler was found to constrain where the app can navigate.",
                remediation="Add setWindowOpenHandler and a will-navigate allowlist."))


def _scan_preload(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    for em in re.finditer(r"exposeInMainWorld\s*\(", text):
        window = text[em.end():em.end() + 400]
        if re.search(r"\bipcRenderer\b(?!\.(?:on|once|invoke|send)\s*\()", window) or \
           re.search(r"\bipcRenderer\s*(?:,|})", window) or \
           re.search(r":\s*ipcRenderer\b", window):
            sev, why = "high", "the raw ipcRenderer object"
        elif re.search(r"\(\s*(\w+)\s*(?:,[^)]*)?\)\s*=>\s*ipcRenderer\.(?:send|sendSync|invoke)\s*\(\s*\1\b", window) or \
                re.search(r"\(\s*\.\.\.(\w+)\s*\)\s*=>\s*ipcRenderer\.(?:send|sendSync|invoke)\s*\(\s*\.\.\.\1\b", window):
            sev, why = "high", "a generic IPC forwarder (renderer chooses the channel)"
        elif re.search(r"require\s*\(", window) or re.search(r"child_process|\bfs\b", window):
            sev, why = "high", "require/child_process/fs"
        else:
            sev, why = "info", "a scoped API (review the exposed surface)"
        out.append(Finding(
            id="electron.preload.expose",
            severity=sev, title=f"contextBridge exposes {why}",
            surface="preload", file=sf.path, line=_lineno(starts, em.start()),
            snippet=_snippet(text, starts, em.start()),
            rationale="Everything exposed in the main world is reachable by page JS; broad objects defeat context isolation.",
            remediation="Expose only narrow, validated functions - never ipcRenderer, require, fs or child_process directly."))
    for wm in re.finditer(r"window\.\w+\s*=\s*require\s*\(", text):
        out.append(Finding(
            id="electron.preload.window-require",
            severity="high", title="require() attached to window in preload",
            surface="preload", file=sf.path, line=_lineno(starts, wm.start()),
            snippet=_snippet(text, starts, wm.start()),
            rationale="Assigning require()'d modules onto window hands Node straight to page JS.",
            remediation="Remove the assignment; bridge a minimal API with contextBridge."))


def _scan_ipc_shell(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    if not re.search(r"\bipcMain\.(?:handle|on)\s*\(", text):
        return
    for cm in re.finditer(r"\b(?:exec|execSync|spawn|spawnSync)\s*\(\s*[`'\"][^`'\"]*(?:\$\{|\"\s*\+|'\s*\+|`\s*\+|\+\s*\w)", text):
        out.append(Finding(
            id="electron.ipc.command-injection",
            severity="high", title="IPC handler shells out with a concatenated command",
            surface="ipc", file=sf.path, line=_lineno(starts, cm.start()),
            snippet=_snippet(text, starts, cm.start()),
            rationale="A renderer-supplied IPC argument reaching child_process with string concatenation is a command-injection bridge.",
            remediation="Use execFile/spawn with an argument array, validate inputs, and never interpolate IPC data into a shell string."))


def _scan_dynamic_and_shell(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    for dm in re.finditer(r"(?<![\w.])(?:eval|new\s+Function)\s*\(", text):
        out.append(Finding(
            id="electron.code.dynamic-eval",
            severity="medium", title="dynamic code execution (eval/new Function)",
            surface="renderer" if sf.role != "main" else "main",
            file=sf.path, line=_lineno(starts, dm.start()),
            snippet=_snippet(text, starts, dm.start()),
            rationale="eval / new Function on any attacker-influenced string is direct code execution.",
            remediation="Remove eval/new Function; parse data instead of executing it."))
    for om in re.finditer(r"shell\.openExternal\s*\(\s*(?:[^)\s'\"`]|(['\"])[^'\"]*\1\s*\+|`[^`]*\$\{)", text):
        out.append(Finding(
            id="electron.shell.open-external",
            severity="medium", title="shell.openExternal with a non-literal argument",
            surface="main", file=sf.path, line=_lineno(starts, om.start()),
            snippet=_snippet(text, starts, om.start()),
            rationale="A variable URL reaching openExternal can launch attacker-chosen schemes/handlers.",
            remediation="Validate the URL against an https allowlist before calling openExternal."))


def _scan_csp(sf: SourceFile, starts: List[int], out: List[Finding]) -> None:
    text = sf.text
    # Find the CSP meta tag regardless of attribute order, then read the WHOLE
    # content value (delimited by its own quote) - a CSP value legitimately
    # contains single quotes ('self', 'unsafe-inline'), so a [^"']* capture
    # would stop early and miss a weak policy.
    csp = None
    value = ""
    for mtag in re.finditer(r"<meta\b[^>]*>", text, re.I):
        tag = mtag.group(0)
        if not re.search(r"http-equiv\s*=\s*(['\"])\s*Content-Security-Policy\s*\1", tag, re.I):
            continue
        csp = mtag
        cm = re.search(r"content\s*=\s*(['\"])(.*?)\1", tag, re.I | re.S)
        value = cm.group(2) if cm else ""
        break
    if not csp:
        out.append(Finding(
            id="electron.csp.missing",
            severity="low", title="renderer HTML has no Content-Security-Policy",
            surface="csp", file=sf.path, line=1, snippet="",
            rationale="Without a CSP a renderer bug has no second line of defence against injected scripts.",
            remediation="Add a restrictive CSP meta tag (no unsafe-inline / unsafe-eval; default-src 'self')."))
        return
    weak = [tok for tok in ("unsafe-eval", "unsafe-inline") if tok in value]
    if weak:
        out.append(Finding(
            id="electron.csp.weak",
            severity="medium", title="CSP allows " + " / ".join(weak),
            surface="csp", file=sf.path, line=_lineno(starts, csp.start()),
            snippet=_snippet(text, starts, csp.start()),
            rationale="unsafe-inline/unsafe-eval let injected markup execute, defeating the CSP.",
            remediation="Drop unsafe-inline/unsafe-eval; use nonces/hashes for any needed inline code."))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def analyze_app(root, *, max_files: int = DEFAULT_MAX_FILES) -> dict:
    """Analyze an Electron app directory or ``.asar`` and return a report dict."""
    root = Path(root)
    limitations: List[str] = []
    sources, asar_paths, is_electron = _load_sources(root, limitations, max_files)
    entry = _resolve_entrypoints(sources)
    roles = _assign_roles(sources, entry)

    findings: List[Finding] = []
    for path in sorted(sources):
        text = sources[path]
        sf = SourceFile(path=path, text=text, origin="asar", role=roles.get(path, "other"))
        starts = _line_starts(text)
        ext = os.path.splitext(path)[1].lower()
        if ext in HTML_EXTS:
            _scan_csp(sf, starts, findings)
            continue
        if ext not in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
            continue
        _scan_webpreferences(sf, starts, findings)
        _scan_navigation(sf, starts, findings)
        _scan_dynamic_and_shell(sf, starts, findings)
        _scan_ipc_shell(sf, starts, findings)
        if sf.role == "preload" or re.search(r"contextBridge|exposeInMainWorld", text) \
                or path.rsplit("/", 1)[-1].lower().startswith("preload"):
            _scan_preload(sf, starts, findings)

    # dedupe (id, file, line)
    seen = set()
    unique: List[Finding] = []
    for f in findings:
        k = (f.id, f.file, f.line)
        if k in seen:
            continue
        seen.add(k)
        unique.append(f)
    unique.sort(key=lambda f: f.sort_key())

    counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for f in unique:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    # A scan that hit a cap or skipped/failed to read a member is not a clean
    # pass: callers (CI) must be able to tell an incomplete scan from a clean one.
    complete = not any(l.startswith("INCOMPLETE:") for l in limitations)

    return {
        "tool": TOOL,
        "version": VERSION,
        "target": {
            "root": str(root),
            "is_electron": is_electron,
            "asar": asar_paths,
            "source_files": len(sources),
        },
        "entrypoints": entry,
        "counts": counts,
        "complete": complete,
        "findings": [asdict(f) for f in unique],
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


def has_failing(report: dict) -> bool:
    c = report.get("counts", {})
    return bool(c.get("high", 0) or c.get("medium", 0))


def should_fail(report: dict) -> bool:
    """Exit-non-zero condition: a high/medium finding OR an incomplete scan."""
    return has_failing(report) or not report.get("complete", True)


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

_SEV_LABEL = {"high": "HIGH", "medium": "MED ", "low": "LOW ", "info": "INFO"}


def format_report(report: dict, fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(report, indent=2, ensure_ascii=True)
    if fmt == "md":
        return _format_md(report)
    return _format_text(report)


def _format_text(report: dict) -> str:
    t = report["target"]
    lines = [
        f"# {report['tool']} {report['version']} - Electron injection-point map",
        f"target: {_clean(t['root'])}",
        f"electron: {t['is_electron']}   asar: {_clean(', '.join(t['asar'])) or '-'}   source files: {t['source_files']}",
        "entrypoints:",
        f"  main:     {_clean(', '.join(report['entrypoints']['main'])) or '-'}",
        f"  preload:  {_clean(', '.join(report['entrypoints']['preload'])) or '-'}",
        f"  renderer: {_clean(', '.join(report['entrypoints']['renderer_html'])) or '-'}",
        "",
    ]
    c = report["counts"]
    lines.append(f"findings: {c['high']} high, {c['medium']} medium, {c['low']} low, {c['info']} info")
    if not report.get("complete", True):
        lines.append("scan: INCOMPLETE (a cap was hit or a member could not be read - see limitations)")
    lines.append("")
    for f in report["findings"]:
        lines.append(f"[{_SEV_LABEL.get(f['severity'], f['severity'])}] {_clean(f['title'])}  ({f['surface']})")
        lines.append(f"    {_clean(f['file'])}:{f['line']}")
        if f["snippet"]:
            lines.append(f"    > {f['snippet']}")
        lines.append(f"    why: {f['rationale']}")
        lines.append(f"    fix: {f['remediation']}")
        lines.append("")
    if report["limitations"]:
        lines.append("limitations:")
        for lim in report["limitations"]:
            lines.append(f"  - {_clean(lim)}")
        lines.append("")
    lines.append(report["disclaimer"])
    return "\n".join(lines)


def _md_cell(s: str) -> str:
    return _clean(s).replace("|", "\\|").replace("\n", " ")


def _format_md(report: dict) -> str:
    t = report["target"]
    c = report["counts"]
    out = [
        f"# Electron injection-point map - `{_md_cell(t['root'])}`",
        "",
        f"- electron: **{t['is_electron']}**",
        f"- asar: {', '.join('`%s`' % a for a in t['asar']) or '-'}",
        f"- source files scanned: {t['source_files']}",
        f"- entrypoints - main: {', '.join('`%s`' % m for m in report['entrypoints']['main']) or '-'}; "
        f"preload: {', '.join('`%s`' % m for m in report['entrypoints']['preload']) or '-'}; "
        f"renderer: {', '.join('`%s`' % m for m in report['entrypoints']['renderer_html']) or '-'}",
        f"- findings: **{c['high']} high**, {c['medium']} medium, {c['low']} low, {c['info']} info",
        "",
        "| Sev | Finding | Surface | Location |",
        "|-----|---------|---------|----------|",
    ]
    for f in report["findings"]:
        out.append(f"| {f['severity']} | {_md_cell(f['title'])} | {f['surface']} | `{_md_cell(f['file'])}:{f['line']}` |")
    out.append("")
    for f in report["findings"]:
        out.append(f"### [{f['severity']}] {_md_cell(f['title'])}")
        out.append(f"- **where:** `{_md_cell(f['file'])}:{f['line']}`")
        if f["snippet"]:
            out.append(f"- **code:** `{_md_cell(f['snippet'])}`")
        out.append(f"- **why:** {_md_cell(f['rationale'])}")
        out.append(f"- **fix:** {_md_cell(f['remediation'])}")
        out.append("")
    if report["limitations"]:
        out.append("## Limitations")
        for lim in report["limitations"]:
            out.append(f"- {_md_cell(lim)}")
        out.append("")
    out.append(f"> {report['disclaimer']}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    if sys.version_info < MIN_PYTHON:
        sys.stderr.write("electron_inject requires Python %d.%d+\n" % MIN_PYTHON)
        return 2
    parser = argparse.ArgumentParser(
        prog="source_lab.electron",
        description="Static Electron app unpacker and injection-point mapper (PENT-10).")
    parser.add_argument("target", help="Electron app directory or an app.asar file")
    parser.add_argument("--format", choices=["text", "md", "json"], default="text")
    parser.add_argument("-o", "--out", help="write the report to this file instead of stdout")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    args = parser.parse_args(argv)

    try:
        report = analyze_app(args.target, max_files=args.max_files)
    except (OSError, AsarError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    text = format_report(report, args.format)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"error: cannot write {args.out}: {exc}\n")
            return 2
    else:
        sys.stdout.write(text + "\n")
    return 1 if should_fail(report) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
