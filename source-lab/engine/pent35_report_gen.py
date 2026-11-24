#!/usr/bin/env python3
"""PENT-35 — Red-Team Report & MITRE ATT&CK Mapping Generator.

Reads red-team / pentest session logs (.json / .jsonl) produced in an
**isolated lab environment**, maps observed tools and commands to MITRE
ATT&CK techniques, redacts any embedded secrets, calculates a composite
risk score, and outputs a professional report in both Markdown and PDF
formats.

Safety: A mandatory **Scope Guard** verifies every target (IPv4, IPv6,
CIDR, URL, hostname) across both root metadata and session events.
Only RFC 1918 private IPv4 addresses, IPv4/IPv6 loopback, IPv6 ULA
(``fc00::/7``), and explicit lab domains (``.lab``, ``.local``,
``.internal``, ``.test``, ``.localhost``) are accepted.  Any public IP
or unauthorized domain (including public ccTLDs such as ``.sh``) causes
an immediate abort with exit code 2 and a ``ScopeViolationError``.

Dependencies: **Python 3.11+ standard library only** — no external
packages.  The PDF writer is a minimal, self-contained ``%PDF-1.4``
generator that produces valid, openable, multi-page PDF documents.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import textwrap
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


# ── Exceptions ──────────────────────────────────────────────────────────

class ScopeViolationError(Exception):
    """Raised when a target falls outside the allowed lab scope."""


# ── Data classes ────────────────────────────────────────────────────────

@dataclass
class MitreRule:
    id: str
    name: str
    tactic: str
    keywords: list[str]
    severity: int
    remediation: str
    negative_keywords: list[str] = field(default_factory=list)


@dataclass
class Finding:
    technique_id: str
    technique_name: str
    tactic: str
    severity: int
    matched_keyword: str
    source_event: dict[str, Any]
    remediation: str


@dataclass
class ReportData:
    session_meta: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    risk_score: float = 0.0
    targets: list[str] = field(default_factory=list)
    event_count: int = 0


# ── Secret Redaction ───────────────────────────────────────────────────

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?"
    r"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)"
)
_URL_CREDS_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/\s:@]+:[^/\s@]+@)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)(Authorization\s*:\s*(?:Bearer|Basic|Token|ApiKey|Digest)?\s*)"
    r"([A-Za-z0-9\-._~+/=]{6,})"
)
_BEARER_RE = re.compile(
    r"(?i)(Bearer\s+)([A-Za-z0-9\-._~+/=]{6,})"
)
_COOKIE_HEADER_RE = re.compile(
    r"(?i)((?:Set-)?Cookie\s*:\s*)([^\r\n'\"]+)"
)
_KV_SECRET_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|"
    r"app[_-]?secret|secret|access[_-]?token|auth[_-]?token|"
    r"refresh[_-]?token|token|session[_-]?id|sessionid|"
    r"phpsessid|jsessionid)\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;\"'&]+)"
)
_CLI_PASSWORD_RE = re.compile(
    r"(?i)(--(?:password|passwd|token|api-key|secret)(?:=|\s+))"
    r"(\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_CLI_SHORT_P_RE = re.compile(
    r"(?<!\S)(-p\s+)(?!\d+(?:[-,]\d+)*\b)(\"[^\"]*\"|'[^']*'|[^\s-]+)"
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:"
    r"sk-[A-Za-z0-9_-]{10,}"
    r"|gh[pousr]_[A-Za-z0-9]{10,}"
    r"|github_pat_[A-Za-z0-9_]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ASIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]+"
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r")\b"
)
_CRED_PAIR_RE = re.compile(
    r"(?i)(credentials?[^:\n]*:\s*)([a-zA-Z0-9_.-]+):([^\s,;\"']+)"
)


def redact_secrets(text: str) -> str:
    """Mask passwords, API keys, tokens, cookies, and private keys."""
    if not text:
        return text
    result = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    result = _URL_CREDS_RE.sub(r"\1[REDACTED]@", result)
    result = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", result)
    result = _BEARER_RE.sub(r"\1[REDACTED]", result)
    result = _COOKIE_HEADER_RE.sub(r"\1[REDACTED]", result)
    result = _KV_SECRET_RE.sub(r"\1[REDACTED]", result)
    result = _CLI_PASSWORD_RE.sub(r"\1[REDACTED]", result)
    result = _CLI_SHORT_P_RE.sub(r"\1[REDACTED]", result)
    result = _KNOWN_TOKEN_RE.sub("[REDACTED]", result)
    result = _CRED_PAIR_RE.sub(r"\1\2:[REDACTED]", result)
    return result


def redact_obj(obj: Any) -> Any:
    """Recursively redact secrets from strings, lists, and dicts."""
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(item) for item in obj)
    return obj


# ── Scope Guard ─────────────────────────────────────────────────────────

_PRIVATE_IPV4_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]

_ALLOWED_IPV6_NETWORKS = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # Unique Local Addresses (includes fd00::/8)
]

_SAFE_HOSTNAME_RE = re.compile(
    r"^("
    r"localhost"
    r"|[\w.-]+\.local"
    r"|[\w.-]+\.lab"
    r"|[\w.-]+\.internal"
    r"|[\w.-]+\.test"
    r"|[\w.-]+\.localhost"
    r")$",
    re.IGNORECASE,
)

_URL_RE = re.compile(
    r"(?:https?|ftp|wss?|ssh|rdp|ldap|smb)://[^\s\"'<>]+",
    re.IGNORECASE,
)

_IPV4_RE = re.compile(
    r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b"
)

_BRACKETED_IPV6_RE = re.compile(
    r"\[([0-9a-fA-F:]+(?:%[a-zA-Z0-9_.-]+)?)\](?::\d+)?"
)

_IPV6_TOKEN_RE = re.compile(
    r"(?<![a-zA-Z0-9._-])"
    r"([0-9a-fA-F:]*:[0-9a-fA-F:]*:[0-9a-fA-F:.]*(?:/\d{1,3})?)"
    r"(?![a-zA-Z0-9._-])"
)

_HOSTNAME_RE = re.compile(
    r"\b((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,})\b"
)

# Strictly non-domain file extensions (note: .sh is intentionally NOT here
# because .sh is a public ccTLD and targets like evil.sh must be rejected).
_NON_DOMAIN_EXTENSIONS = (
    ".exe", ".dll", ".py", ".js", ".ts", ".json", ".jsonl",
    ".md", ".txt", ".log", ".cfg", ".conf", ".ini",
    ".yml", ".yaml", ".xml", ".html", ".css",
    ".bat", ".ps1", ".c", ".h", ".cpp", ".java", ".rb", ".go",
    ".dit", ".dmp", ".pdf",
)


def _strip_ipv6_zone(ip_str: str) -> str:
    """Remove optional IPv6 zone identifier (e.g. %eth0) before parsing."""
    if "%" in ip_str:
        addr_part, _, rest = ip_str.partition("%")
        if "/" in rest:
            _, _, prefix = rest.partition("/")
            return f"{addr_part}/{prefix}"
        return addr_part
    return ip_str


def _is_ip_safe(ip_str: str) -> bool:
    """Return True if *ip_str* (IPv4, IPv6, or CIDR) is within lab scope."""
    cleaned = _strip_ipv6_zone(ip_str.strip("[]"))
    try:
        net = ipaddress.ip_network(cleaned, strict=False)
    except ValueError:
        return False

    if net.version == 4:
        return any(net.subnet_of(priv) for priv in _PRIVATE_IPV4_NETWORKS)

    # IPv6: check IPv4-mapped IPv6 addresses (e.g. ::ffff:8.8.8.8)
    if net.prefixlen == 128 and net.network_address.ipv4_mapped is not None:
        mapped_v4 = ipaddress.ip_network(
            f"{net.network_address.ipv4_mapped}/32", strict=False
        )
        return any(mapped_v4.subnet_of(priv) for priv in _PRIVATE_IPV4_NETWORKS)

    return any(net.subnet_of(allowed) for allowed in _ALLOWED_IPV6_NETWORKS)


def _is_hostname_safe(hostname: str) -> bool:
    """Return True if *hostname* is an allowed lab hostname."""
    return bool(_SAFE_HOSTNAME_RE.match(hostname.rstrip(".")))


def _extract_targets_from_string(text: str) -> set[str]:
    """Extract IPv4, IPv6, URL hostnames, and domain targets from *text*."""
    targets: set[str] = set()

    # 1. URLs (handles user:pass@host, [ipv6]:port, domains, etc.)
    for url_match in _URL_RE.finditer(text):
        url_str = url_match.group(0).rstrip(".,;)")
        try:
            parsed = urlsplit(url_str)
            if parsed.hostname:
                targets.add(parsed.hostname)
        except ValueError:
            pass

    # 2. Bracketed IPv6 with optional port: [2001:4860:4860::8888]:443
    for m in _BRACKETED_IPV6_RE.finditer(text):
        candidate = _strip_ipv6_zone(m.group(1))
        try:
            ipaddress.ip_network(candidate, strict=False)
            targets.add(candidate)
        except ValueError:
            pass

    # 3. Bare IPv6 tokens (including ::1, fd00::/8, ::ffff:8.8.8.8)
    for m in _IPV6_TOKEN_RE.finditer(text):
        candidate = _strip_ipv6_zone(m.group(1))
        try:
            net = ipaddress.ip_network(candidate, strict=False)
            if net.version == 6:
                targets.add(candidate)
        except ValueError:
            pass

    # 4. IPv4 / CIDR
    for m in _IPV4_RE.finditer(text):
        targets.add(m.group(1))

    # 5. Hostnames / domains (including .sh public ccTLD)
    for m in _HOSTNAME_RE.finditer(text):
        h = m.group(1)
        lower_h = h.lower()
        # Skip if already parsed as IPv4
        try:
            ipaddress.ip_network(h, strict=False)
            continue
        except ValueError:
            pass
        if not lower_h.endswith(_NON_DOMAIN_EXTENSIONS):
            targets.add(h)

    return targets


def _extract_targets_from_value(value: Any) -> set[str]:
    """Recursively extract IP addresses and hostnames from any value."""
    targets: set[str] = set()
    if isinstance(value, str):
        targets.update(_extract_targets_from_string(value))
    elif isinstance(value, dict):
        for v in value.values():
            targets.update(_extract_targets_from_value(v))
    elif isinstance(value, (list, tuple)):
        for item in value:
            targets.update(_extract_targets_from_value(item))
    return targets


def validate_scope(
    events: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> list[str]:
    """Validate all targets in *meta* and *events* are within lab scope.

    Returns the sorted list of unique targets found.
    Raises ``ScopeViolationError`` on the first out-of-scope target.
    """
    all_targets: set[str] = set()
    if meta:
        all_targets.update(_extract_targets_from_value(meta))
    for event in events:
        all_targets.update(_extract_targets_from_value(event))

    validated: list[str] = []
    for target in sorted(all_targets):
        cleaned = _strip_ipv6_zone(target.strip("[]"))
        # Try as IP/CIDR first
        try:
            ipaddress.ip_network(cleaned, strict=False)
            if _is_ip_safe(cleaned):
                validated.append(target)
                continue
            raise ScopeViolationError(
                f"Public/out-of-scope IP detected: {target}. "
                f"Only RFC 1918 private IPv4, loopback (127.0.0.0/8, ::1), "
                f"IPv6 ULA (fc00::/7), and lab domains are allowed."
            )
        except ValueError:
            pass
        # Try as hostname
        if _is_hostname_safe(target):
            validated.append(target)
            continue
        raise ScopeViolationError(
            f"Unauthorized hostname detected: {target}. "
            f"Only .lab, .local, .internal, .test, and .localhost "
            f"domains are allowed."
        )

    return validated


# ── MITRE ATT&CK Engine ────────────────────────────────────────────────

def load_rules(rules_path: Path | None = None) -> list[MitreRule]:
    """Load MITRE ATT&CK mapping rules from JSON."""
    if rules_path is None:
        rules_path = Path(__file__).parent / "mitre_rules.json"
    with open(rules_path, encoding="utf-8") as f:
        data = json.load(f)
    return [
        MitreRule(
            id=r["id"],
            name=r["name"],
            tactic=r["tactic"],
            keywords=r["keywords"],
            severity=r["severity"],
            remediation=r["remediation"],
            negative_keywords=r.get("negative_keywords", []),
        )
        for r in data["rules"]
    ]


def _compile_keyword_pattern(kw: str) -> re.Pattern[str]:
    """Build a boundary-aware regex for *kw* to avoid substring false hits."""
    escaped = re.escape(kw.lower())
    prefix = r"(?<![a-z0-9_])" if kw and (kw[0].isalnum() or kw[0] == "_") else ""
    suffix = r"(?![a-z0-9_])" if kw and (kw[-1].isalnum() or kw[-1] == "_") else ""
    return re.compile(f"{prefix}{escaped}{suffix}")


def _event_text(event: dict[str, Any]) -> str:
    """Flatten an event dict into a single lowercase string for matching."""
    parts: list[str] = []

    def _collect(v: Any) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for val in v.values():
                _collect(val)
        elif isinstance(v, (list, tuple)):
            for item in v:
                _collect(item)

    _collect(event)
    return " ".join(parts).lower()


def _is_benign_informational(event: dict[str, Any]) -> bool:
    """Return True if *event* is clearly an ordinary benign status log."""
    level = str(event.get("level", "")).lower()
    status = str(event.get("status", "")).lower()
    ev_type = str(event.get("type", "")).lower()
    if level in {"info", "debug", "notice"} and status in {"ok", "healthy", "success"}:
        return True
    if ev_type in {"healthcheck", "heartbeat", "keepalive"}:
        return True
    return False


def analyze_events(
    events: list[dict[str, Any]],
    rules: list[MitreRule],
) -> list[Finding]:
    """Match events against MITRE ATT&CK rules and return findings."""
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()  # (technique_id, event_index)

    compiled_rules = [
        (
            rule,
            [(kw, _compile_keyword_pattern(kw)) for kw in rule.keywords],
            [_compile_keyword_pattern(nkw) for nkw in rule.negative_keywords],
        )
        for rule in rules
    ]

    for idx, event in enumerate(events):
        if _is_benign_informational(event):
            continue
        text = _event_text(event)
        for rule, kw_patterns, neg_patterns in compiled_rules:
            key = (rule.id, idx)
            if key in seen:
                continue
            if any(np.search(text) for np in neg_patterns):
                continue
            for kw, pat in kw_patterns:
                if pat.search(text):
                    findings.append(Finding(
                        technique_id=rule.id,
                        technique_name=rule.name,
                        tactic=rule.tactic,
                        severity=rule.severity,
                        matched_keyword=kw,
                        source_event=redact_obj(event),
                        remediation=rule.remediation,
                    ))
                    seen.add(key)
                    break

    return findings


def calculate_risk_score(findings: list[Finding]) -> float:
    """Calculate overall risk score (0–10) from findings."""
    if not findings:
        return 0.0
    max_sev = max(f.severity for f in findings)
    avg_sev = sum(f.severity for f in findings) / len(findings)
    unique_tactics = len({f.tactic for f in findings})
    # Weighted formula: 40% max severity, 30% average, 30% tactic breadth
    tactic_factor = min(unique_tactics / 5.0, 1.0) * 10
    score = 0.4 * max_sev + 0.3 * avg_sev + 0.3 * tactic_factor
    return round(min(score, 10.0), 1)


# ── Input parsing ──────────────────────────────────────────────────────

def load_session(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a session file (.json or .jsonl).

    Returns (session_metadata, events_list).  All root-level metadata
    and target fields are preserved in *session_metadata* so the Scope
    Guard validates them as well.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        events = [json.loads(line) for line in lines]
        meta = {
            "format": "jsonl",
            "source_file": path.name,
            "event_count": len(events),
        }
        return meta, events

    data = json.loads(text)
    if isinstance(data, list):
        return {
            "format": "json-array",
            "source_file": path.name,
            "event_count": len(data),
        }, data

    if not isinstance(data, dict):
        raise ValueError("Session JSON root must be an object or array")

    # Preserve all root-level keys except the event list itself so
    # Scope Guard inspects metadata, session, target, targets, scope,
    # environment, assets, host, ip, url, endpoint, etc.
    event_key = next(
        (k for k in ("events", "findings", "log") if k in data),
        None,
    )
    raw_events = data.get(event_key, []) if event_key else []
    if not isinstance(raw_events, list):
        raw_events = [data]

    meta: dict[str, Any] = {}
    for k, v in data.items():
        if k != event_key:
            meta[k] = v
    # Flatten common nested meta dict keys at top for display convenience
    nested_meta = data.get("meta") or data.get("metadata")
    if isinstance(nested_meta, dict):
        for k, v in nested_meta.items():
            meta.setdefault(k, v)

    meta["source_file"] = path.name
    meta["event_count"] = len(raw_events)
    return meta, raw_events


# ── Markdown Report ────────────────────────────────────────────────────

def generate_markdown(report: ReportData) -> str:
    """Generate a professional Markdown report with all secrets redacted."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    w = lines.append

    safe_meta = redact_obj(report.session_meta)
    safe_targets = [redact_secrets(t) for t in report.targets]

    w("# Red-Team Engagement Report")
    w("")
    w(f"> **Generated:** {now}  ")
    w(f"> **Tool:** PENT-35 Red-Team Report & MITRE ATT&CK Mapping Generator  ")
    w(f"> **Source:** `{safe_meta.get('source_file', 'N/A')}`  ")
    w(f"> **Events Analyzed:** {report.event_count}")
    w("")

    # Risk summary
    w("## Executive Summary")
    w("")
    score = report.risk_score
    if score >= 8:
        level = "CRITICAL"
    elif score >= 6:
        level = "HIGH"
    elif score >= 4:
        level = "MEDIUM"
    elif score >= 2:
        level = "LOW"
    else:
        level = "INFORMATIONAL"
    w(f"**Overall Risk Score: {score}/10 ({level})**")
    w("")
    w(f"- **Total Findings:** {len(report.findings)}")
    tactics = sorted({f.tactic for f in report.findings})
    w(f"- **MITRE ATT&CK Tactics Observed:** {len(tactics)} - {', '.join(tactics) if tactics else 'None'}")
    w(f"- **Unique Techniques Matched:** {len({f.technique_id for f in report.findings})}")
    w(f"- **Targets in Scope:** {len(safe_targets)}")
    w("")

    # Targets
    w("## Scope & Targets")
    w("")
    w("All targets validated as in-scope (RFC 1918 / loopback / ULA / lab domains):")
    w("")
    for t in safe_targets:
        w(f"- `{t}`")
    w("")

    # MITRE ATT&CK mapping table
    w("## MITRE ATT&CK Mapping")
    w("")
    w("| # | Technique ID | Technique Name | Tactic | Severity | Matched Keyword |")
    w("|---|---|---|---|---|---|")
    for i, f in enumerate(report.findings, 1):
        w(f"| {i} | {f.technique_id} | {f.technique_name} | {f.tactic} | {f.severity}/10 | `{f.matched_keyword}` |")
    w("")

    # Detailed findings
    w("## Detailed Findings")
    w("")
    for i, f in enumerate(report.findings, 1):
        safe_event = redact_obj(f.source_event)
        event_preview = json.dumps(safe_event, ensure_ascii=False)[:220]
        w(f"### {i}. {f.technique_id} - {f.technique_name}")
        w("")
        w(f"- **Tactic:** {f.tactic}")
        w(f"- **Severity:** {f.severity}/10")
        w(f"- **Matched Keyword:** `{f.matched_keyword}`")
        w(f"- **Source Event:** `{event_preview}`")
        w("")
        w(f"**Remediation:** {f.remediation}")
        w("")

    # Remediation summary
    w("## Remediation Summary")
    w("")
    seen_remediations: set[str] = set()
    idx = 1
    for f in report.findings:
        if f.remediation not in seen_remediations:
            w(f"{idx}. **[{f.technique_id}]** {f.remediation}")
            seen_remediations.add(f.remediation)
            idx += 1
    w("")

    # Footer
    w("---")
    w("")
    w("*This report was generated by PENT-35 Red-Team Report & MITRE ATT&CK "
      "Mapping Generator. All testing was conducted in an authorized, isolated "
      "lab environment.*")
    w("")

    return redact_secrets("\n".join(lines))


# ── Pure-Python PDF Generator ──────────────────────────────────────────

_CHAR_NORMALIZE_MAP = str.maketrans({
    "ğ": "g", "Ğ": "G",
    "ş": "s", "Ş": "S",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ü": "u", "Ü": "U",
    "ç": "c", "Ç": "C",
    "—": "-", "–": "-",
    "’": "'", "‘": "'",
    "“": '"', "”": '"',
    "•": "*", "·": "-",
    "✓": "[OK]", "✗": "[X]",
})


class _PDFWriter:
    """Minimal PDF 1.4 writer using only the standard library.

    Produces a valid, multi-page PDF with a proper cross-reference table,
    page tree, and embedded Type1 fonts (Helvetica / Helvetica-Bold).
    Turkish characters and punctuation are normalized cleanly so no glyphs
    are lost in standard WinAnsiEncoding, and lines are wrapped strictly
    according to font size and page width before pagination.
    """

    def __init__(self) -> None:
        self._objects: list[bytes] = []  # 1-indexed (obj 0 unused)
        self._objects.append(b"")

    def _add_obj(self, content: bytes) -> int:
        obj_num = len(self._objects)
        self._objects.append(content)
        return obj_num

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize non-WinAnsi characters (including Turkish) losslessly."""
        normalized = text.translate(_CHAR_NORMALIZE_MAP)
        return normalized.encode("latin-1", errors="replace").decode("latin-1")

    def _encode_text(self, text: str) -> str:
        """Normalize and escape PDF literal string special characters."""
        safe = self._normalize_text(text)
        safe = safe.replace("\\", "\\\\")
        safe = safe.replace("(", "\\(")
        safe = safe.replace(")", "\\)")
        return safe

    @staticmethod
    def _max_chars_for_font(font_size: int) -> int:
        """Return safe character width for A4 (495pt usable width)."""
        if font_size >= 16:
            return 50
        if font_size >= 13:
            return 62
        if font_size >= 11:
            return 74
        return 84

    def _parse_and_wrap(self, markdown_text: str) -> list[tuple[str, int, bool]]:
        """Clean markdown formatting and wrap each line to fit page width."""
        wrapped_entries: list[tuple[str, int, bool]] = []
        for raw_line in markdown_text.split("\n"):
            is_heading = raw_line.startswith("#")
            if raw_line.startswith("# "):
                font_size = 16
            elif raw_line.startswith("## "):
                font_size = 13
            elif raw_line.startswith("### "):
                font_size = 11
            else:
                font_size = 10

            clean = raw_line.lstrip("#").strip() if is_heading else raw_line
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
            clean = re.sub(r"`(.+?)`", r"\1", clean)
            clean = re.sub(r"^>\s*", "", clean)
            clean = re.sub(r"^\|\s*", "", clean)
            clean = self._normalize_text(clean)

            max_chars = self._max_chars_for_font(font_size)
            if len(clean) <= max_chars:
                wrapped_entries.append((clean, font_size, is_heading))
            else:
                parts = textwrap.wrap(
                    clean,
                    width=max_chars,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
                for part in (parts or [""]):
                    wrapped_entries.append((part, font_size, is_heading))
        return wrapped_entries

    def generate(self, markdown_text: str) -> bytes:
        """Generate a valid PDF document from markdown text."""
        self._objects = [b""]  # reset

        entries = self._parse_and_wrap(markdown_text)

        # Page dimensions (A4: 595 x 842 points)
        page_w, page_h = 595, 842
        margin_left = 50
        margin_top = 50
        margin_bottom = 50
        line_height = 14
        title_line_height = 20
        usable_h = page_h - margin_top - margin_bottom

        # Paginate strictly so bottom lines never overflow
        pages_content: list[list[tuple[str, int, bool]]] = []
        current_page: list[tuple[str, int, bool]] = []
        y_used = 0

        for clean, font_size, is_heading in entries:
            lh = title_line_height if is_heading else line_height
            if y_used + lh > usable_h and current_page:
                pages_content.append(current_page)
                current_page = []
                y_used = 0
            current_page.append((clean, font_size, is_heading))
            y_used += lh

        if current_page:
            pages_content.append(current_page)

        if not pages_content:
            pages_content = [[("Empty Report", 16, True)]]

        # Object 1: Catalog
        catalog_num = self._add_obj(b"")  # placeholder
        # Object 2: Pages (parent)
        pages_num = self._add_obj(b"")  # placeholder
        # Object 3: Font
        font_num = self._add_obj(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        )
        # Object 4: Bold font
        font_bold_num = self._add_obj(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )

        page_obj_nums: list[int] = []
        for page_lines in pages_content:
            stream_parts: list[str] = ["BT"]
            y = page_h - margin_top
            for text, font_size, is_heading in page_lines:
                lh = title_line_height if is_heading else line_height
                font_ref = "/F2" if is_heading else "/F1"
                safe = self._encode_text(text)
                stream_parts.append(
                    f"{font_ref} {font_size} Tf "
                    f"1 0 0 1 {margin_left} {y} Tm "
                    f"({safe}) Tj"
                )
                y -= lh
            stream_parts.append("ET")
            stream_text = "\n".join(stream_parts)
            stream_bytes = stream_text.encode("latin-1", errors="replace")

            compressed = zlib.compress(stream_bytes)

            content_num = self._add_obj(
                b"<< /Length " + str(len(compressed)).encode() +
                b" /Filter /FlateDecode >>\nstream\n" +
                compressed + b"\nendstream"
            )

            page_num = self._add_obj(
                b"<< /Type /Page /Parent " +
                str(pages_num).encode() + b" 0 R" +
                b" /MediaBox [0 0 " +
                str(page_w).encode() + b" " +
                str(page_h).encode() + b"]" +
                b" /Contents " + str(content_num).encode() + b" 0 R" +
                b" /Resources << /Font << /F1 " +
                str(font_num).encode() + b" 0 R" +
                b" /F2 " + str(font_bold_num).encode() + b" 0 R >> >> >>"
            )
            page_obj_nums.append(page_num)

        kids = b" ".join(
            str(n).encode() + b" 0 R" for n in page_obj_nums
        )
        self._objects[pages_num] = (
            b"<< /Type /Pages /Kids [" + kids + b"]"
            b" /Count " + str(len(page_obj_nums)).encode() + b" >>"
        )

        self._objects[catalog_num] = (
            b"<< /Type /Catalog /Pages " +
            str(pages_num).encode() + b" 0 R >>"
        )

        buf = bytearray()
        buf.extend(b"%PDF-1.4\n")
        buf.extend(b"%\xe2\xe3\xcf\xd3\n")

        offsets: list[int] = [0]
        for i in range(1, len(self._objects)):
            offsets.append(len(buf))
            buf.extend(f"{i} 0 obj\n".encode())
            buf.extend(self._objects[i])
            buf.extend(b"\nendobj\n")

        xref_offset = len(buf)
        buf.extend(b"xref\n")
        buf.extend(f"0 {len(self._objects)}\n".encode())
        buf.extend(b"0000000000 65535 f \n")
        for i in range(1, len(self._objects)):
            buf.extend(f"{offsets[i]:010d} 00000 n \n".encode())

        buf.extend(b"trailer\n")
        buf.extend(
            f"<< /Size {len(self._objects)}"
            f" /Root {catalog_num} 0 R >>\n".encode()
        )
        buf.extend(b"startxref\n")
        buf.extend(f"{xref_offset}\n".encode())
        buf.extend(b"%%EOF\n")

        return bytes(buf)


# ── Main pipeline ──────────────────────────────────────────────────────

def run_pipeline(
    input_path: Path,
    out_dir: Path,
    rules_path: Path | None = None,
) -> ReportData:
    """Execute the full analysis pipeline.

    1. Load session log
    2. Validate scope across metadata and events
    3. Run MITRE ATT&CK matching (with secret redaction)
    4. Calculate risk score
    5. Generate Markdown + PDF reports
    """
    meta, events = load_session(input_path)

    # Scope guard across BOTH metadata and events
    targets = validate_scope(events, meta=meta)

    rules = load_rules(rules_path)
    findings = analyze_events(events, rules)
    findings.sort(key=lambda f: f.severity, reverse=True)

    score = calculate_risk_score(findings)

    report = ReportData(
        session_meta=redact_obj(meta),
        findings=findings,
        risk_score=score,
        targets=[redact_secrets(t) for t in targets],
        event_count=len(events),
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    md_text = generate_markdown(report)
    md_path = out_dir / "redteam_report.md"
    md_path.write_text(md_text, encoding="utf-8")

    pdf_writer = _PDFWriter()
    pdf_bytes = pdf_writer.generate(md_text)
    pdf_path = out_dir / "redteam_report.pdf"
    pdf_path.write_bytes(pdf_bytes)

    return report


# ── CLI ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="pent35_report_gen",
        description="Red-Team Report & MITRE ATT&CK Mapping Generator (PENT-35)",
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        type=Path,
        help="Path to session log file (.json or .jsonl)",
    )
    parser.add_argument(
        "--out-dir", "-o",
        required=True,
        type=Path,
        help="Output directory for reports",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help="Path to custom MITRE rules JSON (default: bundled mitre_rules.json)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        report = run_pipeline(args.input, args.out_dir, args.rules)
    except ScopeViolationError as exc:
        print(f"SCOPE VIOLATION: {exc}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"Error processing session log: {exc}", file=sys.stderr)
        return 3

    print("Report generated successfully!")
    print(f"  Risk Score : {report.risk_score}/10")
    print(f"  Findings   : {len(report.findings)}")
    print(f"  Markdown   : {args.out_dir / 'redteam_report.md'}")
    print(f"  PDF        : {args.out_dir / 'redteam_report.pdf'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
