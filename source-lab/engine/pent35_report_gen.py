#!/usr/bin/env python3
"""PENT-35 — Red-Team Report & MITRE ATT&CK Mapping Generator.

Reads red-team / pentest session logs (.json / .jsonl) produced in an
**isolated lab environment**, maps observed tools and commands to MITRE
ATT&CK techniques, calculates a composite risk score, and outputs a
professional report in both Markdown and PDF formats.

Safety: A mandatory **Scope Guard** verifies every target (IP, CIDR,
hostname) in the session log.  Only RFC 1918 private addresses,
loopback, and ``.local`` / ``.lab`` hostnames are accepted.  Any
public IP or unauthorized domain causes an immediate abort with a
non-zero exit code and a ``ScopeViolationError``.

Usage::

    python pent35_report_gen.py --input session.json --out-dir ./reports
    python pent35_report_gen.py --input session.jsonl --out-dir ./reports

Outputs::

    <out-dir>/redteam_report.md
    <out-dir>/redteam_report.pdf

Dependencies: **Python 3.11+ standard library only** — no external
packages.  The PDF writer is a minimal, self-contained ``%PDF-1.4``
generator that produces valid, openable PDF documents.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import struct
import sys
import textwrap
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


# ── Scope Guard ─────────────────────────────────────────────────────────

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]

_SAFE_HOSTNAME_RE = re.compile(
    r"^("
    r"localhost"
    r"|[\w.-]+\.local"
    r"|[\w.-]+\.lab"
    r")$",
    re.IGNORECASE,
)

_IP_RE = re.compile(
    r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?:/\d{1,2})?)\b"
)

_HOSTNAME_RE = re.compile(
    r"\b((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,})\b"
)


def _is_ip_safe(ip_str: str) -> bool:
    """Return True if *ip_str* (IP or CIDR) is within allowed ranges."""
    try:
        net = ipaddress.ip_network(ip_str, strict=False)
    except ValueError:
        return False
    return any(
        net.subnet_of(priv) for priv in _PRIVATE_NETWORKS
    )


def _is_hostname_safe(hostname: str) -> bool:
    """Return True if *hostname* is an allowed lab hostname."""
    return bool(_SAFE_HOSTNAME_RE.match(hostname))


def _extract_targets_from_value(value: Any) -> set[str]:
    """Recursively extract IP addresses and hostnames from a value."""
    targets: set[str] = set()
    if isinstance(value, str):
        targets.update(_IP_RE.findall(value))
        for m in _HOSTNAME_RE.finditer(value):
            h = m.group(1)
            # Skip common non-hostname patterns
            if not h.endswith((".exe", ".dll", ".py", ".js", ".json",
                               ".md", ".txt", ".log", ".cfg", ".conf",
                               ".yml", ".yaml", ".xml", ".html", ".css",
                               ".sh", ".bat", ".ps1", ".c", ".h",
                               ".cpp", ".java", ".rb", ".go")):
                targets.add(h)
    elif isinstance(value, dict):
        for v in value.values():
            targets.update(_extract_targets_from_value(v))
    elif isinstance(value, (list, tuple)):
        for item in value:
            targets.update(_extract_targets_from_value(item))
    return targets


def validate_scope(events: list[dict[str, Any]]) -> list[str]:
    """Validate all targets in *events* are within lab scope.

    Returns the list of unique targets found.
    Raises ``ScopeViolationError`` on the first out-of-scope target.
    """
    all_targets: set[str] = set()
    for event in events:
        all_targets.update(_extract_targets_from_value(event))

    validated: list[str] = []
    for target in sorted(all_targets):
        # Try as IP/CIDR first
        try:
            ipaddress.ip_network(target, strict=False)
            if _is_ip_safe(target):
                validated.append(target)
                continue
            raise ScopeViolationError(
                f"Public/out-of-scope IP detected: {target}. "
                f"Only RFC 1918 private, loopback, and .local/.lab "
                f"targets are allowed."
            )
        except ValueError:
            pass
        # Try as hostname
        if _is_hostname_safe(target):
            validated.append(target)
            continue
        raise ScopeViolationError(
            f"Unauthorized hostname detected: {target}. "
            f"Only .local and .lab domains are allowed."
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
        )
        for r in data["rules"]
    ]


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


def analyze_events(
    events: list[dict[str, Any]],
    rules: list[MitreRule],
) -> list[Finding]:
    """Match events against MITRE ATT&CK rules and return findings."""
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()  # (technique_id, event_index)

    for idx, event in enumerate(events):
        text = _event_text(event)
        for rule in rules:
            key = (rule.id, idx)
            if key in seen:
                continue
            for kw in rule.keywords:
                if kw.lower() in text:
                    findings.append(Finding(
                        technique_id=rule.id,
                        technique_name=rule.name,
                        tactic=rule.tactic,
                        severity=rule.severity,
                        matched_keyword=kw,
                        source_event=event,
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

    Returns (session_metadata, events_list).
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
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
    # Expect {"meta": {...}, "events": [...]}
    meta = data.get("meta", data.get("metadata", {}))
    if not isinstance(meta, dict):
        meta = {}
    meta["source_file"] = path.name
    events = data.get("events", data.get("findings", data.get("log", [])))
    if not isinstance(events, list):
        events = [data]
    meta["event_count"] = len(events)
    return meta, events


# ── Markdown Report ────────────────────────────────────────────────────

def generate_markdown(report: ReportData) -> str:
    """Generate a professional Markdown report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    w = lines.append

    w("# Red-Team Engagement Report")
    w("")
    w(f"> **Generated:** {now}  ")
    w(f"> **Tool:** PENT-35 Red-Team Report & MITRE ATT&CK Mapping Generator  ")
    w(f"> **Source:** `{report.session_meta.get('source_file', 'N/A')}`  ")
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
    w(f"- **MITRE ATT&CK Tactics Observed:** {len(tactics)} — {', '.join(tactics) if tactics else 'None'}")
    w(f"- **Unique Techniques Matched:** {len({f.technique_id for f in report.findings})}")
    w(f"- **Targets in Scope:** {len(report.targets)}")
    w("")

    # Targets
    w("## Scope & Targets")
    w("")
    w("All targets validated as in-scope (RFC 1918 / loopback / .local / .lab):")
    w("")
    for t in report.targets:
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
        w(f"### {i}. {f.technique_id} — {f.technique_name}")
        w("")
        w(f"- **Tactic:** {f.tactic}")
        w(f"- **Severity:** {f.severity}/10")
        w(f"- **Matched Keyword:** `{f.matched_keyword}`")
        w(f"- **Source Event:** `{json.dumps(f.source_event, ensure_ascii=False)[:200]}`")
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

    return "\n".join(lines)


# ── Pure-Python PDF Generator ──────────────────────────────────────────

class _PDFWriter:
    """Minimal PDF 1.4 writer using only the standard library.

    Produces a valid PDF with a proper cross-reference table, page tree,
    and embedded Type1 font (Helvetica).  Text is encoded to
    latin-1/WinAnsiEncoding with fallback replacement.
    """

    def __init__(self) -> None:
        self._objects: list[bytes] = []  # 1-indexed (obj 0 unused)
        self._objects.append(b"")  # placeholder for 0-index

    def _add_obj(self, content: bytes) -> int:
        obj_num = len(self._objects)
        self._objects.append(content)
        return obj_num

    def _encode_text(self, text: str) -> str:
        """Encode text for PDF string, escaping special chars."""
        safe = text.encode("latin-1", errors="replace").decode("latin-1")
        safe = safe.replace("\\", "\\\\")
        safe = safe.replace("(", "\\(")
        safe = safe.replace(")", "\\)")
        return safe

    def _wrap_lines(self, text: str, max_chars: int = 90) -> list[str]:
        """Wrap text to fit within PDF page width."""
        result: list[str] = []
        for line in text.split("\n"):
            if len(line) <= max_chars:
                result.append(line)
            else:
                wrapped = textwrap.wrap(line, width=max_chars,
                                        break_long_words=True,
                                        break_on_hyphens=False)
                result.extend(wrapped if wrapped else [""])
        return result

    def generate(self, markdown_text: str) -> bytes:
        """Generate a valid PDF document from markdown text."""
        self._objects = [b""]  # reset

        # Parse markdown into lines with basic formatting
        lines = self._wrap_lines(markdown_text, max_chars=95)

        # Page dimensions (A4: 595 x 842 points)
        page_w, page_h = 595, 842
        margin_left = 50
        margin_top = 50
        margin_bottom = 50
        line_height = 14
        title_line_height = 20
        usable_h = page_h - margin_top - margin_bottom

        # Build pages of content
        pages_content: list[list[tuple[str, int, bool]]] = []
        current_page: list[tuple[str, int, bool]] = []
        y_used = 0

        for line in lines:
            is_heading = line.startswith("#")
            lh = title_line_height if is_heading else line_height
            if y_used + lh > usable_h and current_page:
                pages_content.append(current_page)
                current_page = []
                y_used = 0
            # Clean markdown formatting for PDF
            clean = line.lstrip("#").strip()
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
            clean = re.sub(r"`(.+?)`", r"\1", clean)
            clean = re.sub(r"^>\s*", "", clean)
            clean = re.sub(r"^\|\s*", "", clean)
            font_size = 16 if line.startswith("# ") else (
                13 if line.startswith("## ") else (
                    11 if line.startswith("### ") else 10
                )
            )
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
            # Build content stream
            stream_parts: list[str] = ["BT"]
            y = page_h - margin_top
            for text, font_size, is_heading in page_lines:
                lh = title_line_height if is_heading else line_height
                font_ref = "/F2" if is_heading else "/F1"
                safe = self._encode_text(text)
                stream_parts.append(
                    f"{font_ref} {font_size} Tf "
                    f"{margin_left} {y} Td "
                    f"({safe}) Tj"
                )
                y -= lh
            stream_parts.append("ET")
            stream_text = "\n".join(stream_parts)
            stream_bytes = stream_text.encode("latin-1", errors="replace")

            # Compress stream
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

        # Fill in Pages object
        kids = b" ".join(
            str(n).encode() + b" 0 R" for n in page_obj_nums
        )
        self._objects[pages_num] = (
            b"<< /Type /Pages /Kids [" + kids + b"]"
            b" /Count " + str(len(page_obj_nums)).encode() + b" >>"
        )

        # Fill in Catalog
        self._objects[catalog_num] = (
            b"<< /Type /Catalog /Pages " +
            str(pages_num).encode() + b" 0 R >>"
        )

        # Build the PDF file
        buf = bytearray()
        buf.extend(b"%PDF-1.4\n")
        buf.extend(b"%\xe2\xe3\xcf\xd3\n")  # binary comment

        offsets: list[int] = [0]  # 0-index unused
        for i in range(1, len(self._objects)):
            offsets.append(len(buf))
            buf.extend(f"{i} 0 obj\n".encode())
            buf.extend(self._objects[i])
            buf.extend(b"\nendobj\n")

        # Cross-reference table
        xref_offset = len(buf)
        buf.extend(b"xref\n")
        buf.extend(f"0 {len(self._objects)}\n".encode())
        buf.extend(b"0000000000 65535 f \n")
        for i in range(1, len(self._objects)):
            buf.extend(f"{offsets[i]:010d} 00000 n \n".encode())

        # Trailer
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
    2. Validate scope (raises ScopeViolationError on violation)
    3. Run MITRE ATT&CK matching
    4. Calculate risk score
    5. Generate Markdown + PDF reports

    Returns the ReportData for programmatic use.
    """
    # Load
    meta, events = load_session(input_path)

    # Scope guard
    targets = validate_scope(events)

    # Analyze
    rules = load_rules(rules_path)
    findings = analyze_events(events, rules)

    # Sort findings by severity (highest first)
    findings.sort(key=lambda f: f.severity, reverse=True)

    # Risk score
    score = calculate_risk_score(findings)

    report = ReportData(
        session_meta=meta,
        findings=findings,
        risk_score=score,
        targets=targets,
        event_count=len(events),
    )

    # Output
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

    print(f"Report generated successfully!")
    print(f"  Risk Score : {report.risk_score}/10")
    print(f"  Findings   : {len(report.findings)}")
    print(f"  Markdown   : {args.out_dir / 'redteam_report.md'}")
    print(f"  PDF        : {args.out_dir / 'redteam_report.pdf'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
