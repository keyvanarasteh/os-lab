"""PENT-03 — Headless Android Analysis Pipeline & Objection SSL Pinning Bypass.

Importable, standard-library-only helpers for the containerized Android lab.
Every module exposes pure, testable helpers (argv/URL/name builders) kept
separate from the side-effecting ``run``/``deploy`` functions, so the whole
suite can be unit-tested offline with no device, no network and no root.

Authorization only: these tools target emulators/apps you own or are
authorized in writing to assess, inside an isolated lab. See ``scope.py``.
"""

__all__ = [
    "scope",
    "adb",
    "deploy_frida",
    "install_ca",
    "sslpinning_bypass",
    "pipeline",
    "report",
    "mitm_addon",
]
