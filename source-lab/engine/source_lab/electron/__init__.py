"""PENT-10 - Electron app unpacker and injection-point mapper.

Static, offline mapping of an Electron application's *injection surface*: it
unpacks ``app.asar`` (reusing :mod:`source_lab.sourcemap.archives.asar`), finds
the main / preload / renderer entry points, and flags the configuration and
code patterns that turn a renderer-side bug (XSS, a malicious remote page, a
tampered resource) into main-process / Node code execution.

Nothing here executes application code, resolves a host or touches the network;
see :mod:`source_lab.electron.inject_map` for the analysis and the safety
envelope. Use only on applications you own or are authorized to assess.
"""

from .inject_map import analyze_app, format_report, Finding, SEVERITY_ORDER

__all__ = ["analyze_app", "format_report", "Finding", "SEVERITY_ORDER"]
