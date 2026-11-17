"""Pytest integration wrapper for PENT-20 Session Scribe tests."""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.session_scribe.tests.test_session_scribe import (  # noqa: E402, F401
    AuditLoggerTests,
    CircuitBreakerTests,
    CliTests,
    ForensicExporterTests,
    HTMLDashboardTests,
    MitreMapperTests,
    PromptInjectionGuardTests,
    ReportSignerTests,
    ScopeGuardTests,
    SecretRedactorTests,
    SubagentTests,
)
