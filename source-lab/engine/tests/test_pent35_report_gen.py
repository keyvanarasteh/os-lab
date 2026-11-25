"""PENT-35 — Tests for the Red-Team Report & MITRE ATT&CK Mapping Generator.

Covers:
  - MITRE ATT&CK technique extraction from valid lab sessions
  - Scope Guard enforcement (rejection of public IPs and unauthorized domains)
  - Markdown and PDF output generation and structural validity
  - CLI end-to-end parameter handling
  - Risk score calculation
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ── Import the module under test ───────────────────────────────────────

# Insert the engine directory so the module is importable.
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from pent35_report_gen import (
    Finding,
    MitreRule,
    ReportData,
    ScopeViolationError,
    _PDFWriter,
    _is_hostname_safe,
    _is_ip_safe,
    analyze_events,
    calculate_risk_score,
    generate_markdown,
    load_rules,
    load_session,
    main,
    redact_secrets,
    run_pipeline,
    validate_scope,
)

FIXTURES = ENGINE_DIR / "fixtures"
SAMPLE_SESSION = FIXTURES / "sample_lab_session.json"
OOS_SESSION = FIXTURES / "out_of_scope_session.json"


# ── Helpers ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_out(tmp_path: Path) -> Path:
    """Provide a fresh output directory."""
    d = tmp_path / "reports"
    d.mkdir()
    return d


@pytest.fixture
def sample_events() -> list[dict]:
    """Load events from the sample lab session fixture."""
    with open(SAMPLE_SESSION, encoding="utf-8") as f:
        data = json.load(f)
    return data["events"]


@pytest.fixture
def rules() -> list[MitreRule]:
    """Load the bundled MITRE rules."""
    return load_rules()


# ── Scope Guard tests ──────────────────────────────────────────────────

class TestScopeGuard:
    """Scope Guard must accept lab targets and reject public ones."""

    def test_private_ips_accepted(self) -> None:
        assert _is_ip_safe("10.0.0.1")
        assert _is_ip_safe("10.255.255.255")
        assert _is_ip_safe("172.16.0.1")
        assert _is_ip_safe("172.31.255.255")
        assert _is_ip_safe("192.168.0.1")
        assert _is_ip_safe("192.168.255.255")

    def test_loopback_accepted(self) -> None:
        assert _is_ip_safe("127.0.0.1")
        assert _is_ip_safe("127.255.255.255")

    def test_cidr_private_accepted(self) -> None:
        assert _is_ip_safe("192.168.10.0/24")
        assert _is_ip_safe("10.0.0.0/8")

    def test_public_ip_rejected(self) -> None:
        assert not _is_ip_safe("8.8.8.8")
        assert not _is_ip_safe("1.1.1.1")
        assert not _is_ip_safe("142.250.185.206")

    def test_safe_hostnames(self) -> None:
        assert _is_hostname_safe("localhost")
        assert _is_hostname_safe("server.local")
        assert _is_hostname_safe("dc01.lab")
        assert _is_hostname_safe("web-server.lab")
        assert _is_hostname_safe("my.host.local")

    def test_unsafe_hostnames(self) -> None:
        assert not _is_hostname_safe("google.com")
        assert not _is_hostname_safe("example.com")
        assert not _is_hostname_safe("evil.org")

    def test_validate_scope_accepts_sample(self, sample_events: list[dict]) -> None:
        targets = validate_scope(sample_events)
        assert len(targets) > 0
        # All should be private or .lab
        for t in targets:
            assert _is_ip_safe(t) or _is_hostname_safe(t), f"unexpected: {t}"

    def test_validate_scope_rejects_oos(self) -> None:
        with open(OOS_SESSION, encoding="utf-8") as f:
            data = json.load(f)
        with pytest.raises(ScopeViolationError):
            validate_scope(data["events"])

    def test_validate_scope_rejects_public_ip_in_text(self) -> None:
        events = [{"command": "nmap 8.8.8.8", "target": "8.8.8.8"}]
        with pytest.raises(ScopeViolationError):
            validate_scope(events)

    def test_validate_scope_rejects_public_domain(self) -> None:
        events = [{"target": "example.com"}]
        with pytest.raises(ScopeViolationError):
            validate_scope(events)


# ── MITRE ATT&CK Matching tests ───────────────────────────────────────

class TestMitreMatching:
    """MITRE ATT&CK engine must correctly identify techniques."""

    def test_rules_load(self, rules: list[MitreRule]) -> None:
        assert len(rules) > 0
        ids = {r.id for r in rules}
        assert "T1046" in ids
        assert "T1059.001" in ids
        assert "T1003" in ids
        assert "T1071" in ids

    def test_nmap_maps_to_t1046(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "nmap", "command": "nmap -sV 192.168.10.0/24"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1046" in technique_ids

    def test_powershell_maps_to_t1059_001(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "powershell", "command": "powershell -ep bypass"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1059.001" in technique_ids

    def test_mimikatz_maps_to_credential_techniques(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "mimikatz", "command": "sekurlsa::logonpasswords", "output": "lsass"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1003" in technique_ids or "T1003.001" in technique_ids

    def test_schtasks_maps_to_t1053(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "schtasks", "command": "schtasks /create /tn task1"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1053.005" in technique_ids

    def test_reg_maps_to_t1547(self, rules: list[MitreRule]) -> None:
        events = [{"command": "reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1547.001" in technique_ids

    def test_whoami_maps_to_t1033(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "whoami", "command": "whoami /all"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1033" in technique_ids

    def test_curl_beacon_maps_to_t1071(self, rules: list[MitreRule]) -> None:
        events = [{"tool": "curl", "command": "curl http://192.168.10.1/beacon"}]
        findings = analyze_events(events, rules)
        technique_ids = {f.technique_id for f in findings}
        assert "T1071" in technique_ids or "T1105" in technique_ids

    def test_sample_session_has_multiple_techniques(
        self, sample_events: list[dict], rules: list[MitreRule]
    ) -> None:
        findings = analyze_events(sample_events, rules)
        technique_ids = {f.technique_id for f in findings}
        # Must match at least 5 distinct techniques from the rich sample
        assert len(technique_ids) >= 5, f"only matched {technique_ids}"

    def test_sample_session_has_multiple_tactics(
        self, sample_events: list[dict], rules: list[MitreRule]
    ) -> None:
        findings = analyze_events(sample_events, rules)
        tactics = {f.tactic for f in findings}
        assert len(tactics) >= 3, f"only matched tactics: {tactics}"

    def test_no_match_on_benign_event(self, rules: list[MitreRule]) -> None:
        events = [{"action": "read file", "target": "readme.txt"}]
        findings = analyze_events(events, rules)
        assert len(findings) == 0


# ── Risk Score tests ───────────────────────────────────────────────────

class TestRiskScore:
    """Risk score must be in [0, 10] and reflect severity."""

    def test_empty_findings(self) -> None:
        assert calculate_risk_score([]) == 0.0

    def test_high_severity_produces_high_score(self) -> None:
        findings = [
            Finding("T1003", "Cred Dump", "Credential Access", 10, "mimikatz", {}, ""),
            Finding("T1059.001", "PS", "Execution", 7, "powershell", {}, ""),
            Finding("T1046", "Scan", "Discovery", 4, "nmap", {}, ""),
        ]
        score = calculate_risk_score(findings)
        assert 0 <= score <= 10
        assert score >= 5  # high severity should yield non-trivial score

    def test_low_severity_produces_low_score(self) -> None:
        findings = [
            Finding("T1082", "SysInfo", "Discovery", 3, "systeminfo", {}, ""),
        ]
        score = calculate_risk_score(findings)
        assert 0 <= score <= 10
        assert score <= 5

    def test_score_never_exceeds_10(self) -> None:
        findings = [
            Finding(f"T{i}", f"Tech{i}", f"Tactic{i}", 10, f"kw{i}", {}, "")
            for i in range(20)
        ]
        score = calculate_risk_score(findings)
        assert score <= 10.0


# ── Input Parsing tests ───────────────────────────────────────────────

class TestInputParsing:
    """Session loader must handle .json and .jsonl formats."""

    def test_load_json(self) -> None:
        meta, events = load_session(SAMPLE_SESSION)
        assert meta["source_file"] == "sample_lab_session.json"
        assert len(events) > 0

    def test_load_jsonl(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "test.jsonl"
        lines = [
            json.dumps({"tool": "nmap", "target": "192.168.1.1"}),
            json.dumps({"tool": "whoami", "target": "localhost"}),
        ]
        jsonl.write_text("\n".join(lines), encoding="utf-8")
        meta, events = load_session(jsonl)
        assert meta["format"] == "jsonl"
        assert len(events) == 2

    def test_load_json_array(self, tmp_path: Path) -> None:
        jf = tmp_path / "array.json"
        data = [
            {"tool": "nmap", "target": "10.0.0.1"},
            {"tool": "whoami", "target": "localhost"},
        ]
        jf.write_text(json.dumps(data), encoding="utf-8")
        meta, events = load_session(jf)
        assert meta["format"] == "json-array"
        assert len(events) == 2


# ── Report Generation tests ───────────────────────────────────────────

class TestReportGeneration:
    """Markdown and PDF outputs must be valid and complete."""

    def test_markdown_has_required_sections(self, sample_events: list[dict], rules: list[MitreRule]) -> None:
        findings = analyze_events(sample_events, rules)
        report = ReportData(
            session_meta={"source_file": "test.json"},
            findings=findings,
            risk_score=calculate_risk_score(findings),
            targets=["192.168.10.0/24"],
            event_count=len(sample_events),
        )
        md = generate_markdown(report)
        assert "# Red-Team Engagement Report" in md
        assert "## Executive Summary" in md
        assert "## MITRE ATT&CK Mapping" in md
        assert "## Detailed Findings" in md
        assert "## Remediation Summary" in md
        assert "T1046" in md or "T1059" in md  # at least one technique

    def test_markdown_contains_risk_score(self) -> None:
        report = ReportData(
            session_meta={"source_file": "x.json"},
            findings=[],
            risk_score=5.5,
            targets=[],
            event_count=0,
        )
        md = generate_markdown(report)
        assert "5.5/10" in md

    def test_pdf_has_valid_header(self) -> None:
        writer = _PDFWriter()
        pdf = writer.generate("# Test\nHello World")
        assert pdf[:5] == b"%PDF-"

    def test_pdf_has_valid_structure(self) -> None:
        writer = _PDFWriter()
        pdf = writer.generate("# Test Report\n\nSome content here.\nAnother line.")
        # Must contain essential PDF structures
        assert b"xref" in pdf
        assert b"trailer" in pdf
        assert b"startxref" in pdf
        assert b"%%EOF" in pdf
        assert b"/Type /Catalog" in pdf
        assert b"/Type /Pages" in pdf
        assert b"/Type /Page" in pdf
        assert b"/Type /Font" in pdf

    def test_pdf_non_empty(self) -> None:
        writer = _PDFWriter()
        pdf = writer.generate("# Report\n\n- Finding 1\n- Finding 2")
        assert len(pdf) > 100  # a valid PDF is at least a few hundred bytes


# ── Pipeline E2E tests ─────────────────────────────────────────────────

class TestPipeline:
    """End-to-end pipeline tests."""

    def test_full_pipeline_produces_files(self, tmp_out: Path) -> None:
        report = run_pipeline(SAMPLE_SESSION, tmp_out)
        md_file = tmp_out / "redteam_report.md"
        pdf_file = tmp_out / "redteam_report.pdf"
        assert md_file.exists()
        assert pdf_file.exists()
        assert md_file.stat().st_size > 0
        assert pdf_file.stat().st_size > 0

    def test_pipeline_md_content(self, tmp_out: Path) -> None:
        run_pipeline(SAMPLE_SESSION, tmp_out)
        md_text = (tmp_out / "redteam_report.md").read_text(encoding="utf-8")
        assert "# Red-Team Engagement Report" in md_text
        assert "MITRE ATT&CK" in md_text

    def test_pipeline_pdf_valid(self, tmp_out: Path) -> None:
        run_pipeline(SAMPLE_SESSION, tmp_out)
        pdf_bytes = (tmp_out / "redteam_report.pdf").read_bytes()
        assert pdf_bytes[:5] == b"%PDF-"
        assert b"%%EOF" in pdf_bytes

    def test_pipeline_risk_score_positive(self, tmp_out: Path) -> None:
        report = run_pipeline(SAMPLE_SESSION, tmp_out)
        assert report.risk_score > 0

    def test_pipeline_has_findings(self, tmp_out: Path) -> None:
        report = run_pipeline(SAMPLE_SESSION, tmp_out)
        assert len(report.findings) > 0

    def test_pipeline_rejects_oos(self, tmp_out: Path) -> None:
        with pytest.raises(ScopeViolationError):
            run_pipeline(OOS_SESSION, tmp_out)


# ── CLI tests ──────────────────────────────────────────────────────────

class TestCLI:
    """CLI argument handling and exit codes."""

    def test_cli_success(self, tmp_out: Path) -> None:
        rc = main(["--input", str(SAMPLE_SESSION), "--out-dir", str(tmp_out)])
        assert rc == 0
        assert (tmp_out / "redteam_report.md").exists()
        assert (tmp_out / "redteam_report.pdf").exists()

    def test_cli_scope_violation_exit_code(self, tmp_out: Path) -> None:
        rc = main(["--input", str(OOS_SESSION), "--out-dir", str(tmp_out)])
        assert rc == 2  # ScopeViolationError => exit 2

    def test_cli_missing_input(self, tmp_out: Path) -> None:
        rc = main(["--input", "/nonexistent/file.json", "--out-dir", str(tmp_out)])
        assert rc == 1

    def test_cli_creates_output_dir(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "brand_new_dir"
        rc = main(["--input", str(SAMPLE_SESSION), "--out-dir", str(new_dir)])
        assert rc == 0
        assert new_dir.exists()
        assert (new_dir / "redteam_report.md").exists()

    def test_cli_subprocess(self, tmp_out: Path) -> None:
        """Run the CLI as a subprocess to test real-world invocation."""
        result = subprocess.run(
            [sys.executable, str(ENGINE_DIR / "pent35_report_gen.py"),
             "--input", str(SAMPLE_SESSION),
             "--out-dir", str(tmp_out)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Report generated successfully" in result.stdout

    def test_cli_subprocess_oos_fails(self, tmp_out: Path) -> None:
        """Scope violation must produce non-zero exit in subprocess."""
        result = subprocess.run(
            [sys.executable, str(ENGINE_DIR / "pent35_report_gen.py"),
             "--input", str(OOS_SESSION),
             "--out-dir", str(tmp_out)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "SCOPE VIOLATION" in result.stderr


# ── Hardened Security & Quality Tests ─────────────────────────────────

def _extract_pdf_streams(pdf_bytes: bytes) -> str:
    """Decompress all FlateDecode streams from a PDF byte buffer."""
    import re
    import zlib

    chunks: list[str] = []
    for match in re.finditer(rb"stream\n(.*?)\nendstream", pdf_bytes, re.DOTALL):
        chunks.append(zlib.decompress(match.group(1)).decode("latin-1"))
    return "\n".join(chunks)


class TestHardenedScopeGuard:
    """Scope Guard must catch metadata, IPv6, IPv4-mapped, and .sh ccTLD targets."""

    def test_ipv6_loopback_and_ula_accepted(self) -> None:
        assert _is_ip_safe("::1")
        assert _is_ip_safe("fc00::1")
        assert _is_ip_safe("fd00::1/64")
        assert _is_ip_safe("::ffff:192.168.1.10")

    def test_ipv6_public_and_mapped_public_rejected(self) -> None:
        assert not _is_ip_safe("2001:4860:4860::8888")
        assert not _is_ip_safe("2606:4700:4700::1111")
        assert not _is_ip_safe("::ffff:8.8.8.8")

    def test_bracketed_ipv6_and_url_rejected_in_events(self) -> None:
        for payload in (
            {"endpoint": "[2001:4860:4860::8888]:443"},
            {"url": "https://[2001:4860:4860::8888]:443/api"},
            {"host": "::ffff:8.8.8.8"},
        ):
            with pytest.raises(ScopeViolationError):
                validate_scope([payload])

    def test_bracketed_ipv6_private_accepted(self) -> None:
        targets = validate_scope([
            {"endpoint": "[::1]:8080"},
            {"url": "http://[fd00::10]:8443/beacon"},
        ])
        assert "::1" in targets
        assert "fd00::10" in targets

    def test_public_sh_cctld_rejected(self) -> None:
        assert not _is_hostname_safe("evil.sh")
        assert not _is_hostname_safe("target.sh")
        for payload in (
            {"target": "evil.sh"},
            {"host": "target.sh"},
            {"url": "https://deploy.sh/api"},
        ):
            with pytest.raises(ScopeViolationError):
                validate_scope([payload])

    def test_extended_lab_domains_accepted(self) -> None:
        for host in ("api.internal", "app.test", "svc.localhost", "db01.lab", "printer.local"):
            assert _is_hostname_safe(host)

    @pytest.mark.parametrize("meta_key", [
        "metadata", "session", "target", "targets", "scope",
        "environment", "assets", "host", "ip", "url", "endpoint",
    ])
    def test_metadata_oos_target_rejected_end_to_end(
        self, tmp_path: Path, tmp_out: Path, meta_key: str
    ) -> None:
        session_file = tmp_path / f"meta_{meta_key}.json"
        session_data = {
            meta_key: {"nested": ["https://evil.sh/exfil"]} if meta_key in ("metadata", "session", "environment", "assets") else "8.8.8.8",
            "events": [{"tool": "nmap", "command": "nmap -sV 192.168.10.10"}],
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
        assert main(["--input", str(session_file), "--out-dir", str(tmp_out)]) == 2


class TestSecretRedaction:
    """Secrets must never leak into Markdown or PDF reports."""

    def test_redact_secrets_patterns(self) -> None:
        raw = (
            "curl -H '" 'Authorization: ' 'Bearer tok_secret_123456' "' "
            "-H 'Cookie: sessionid=abc123xyz' "
            "https://admin:MyS3cr3tPass@web-server.lab/api?api_key=AKIAIOSFODNN7EXAMPLE "
            "--password SuperPassword123 -p ShortSecret "
            "token=ghp_1234567890abcdef123456 "
            "sk-proj1234567890abcdef "
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
        )
        redacted = redact_secrets(raw)
        for leaked in (
            "tok_secret_123456",
            "abc123xyz",
            "MyS3cr3tPass",
            "AKIAIOSFODNN7EXAMPLE",
            "SuperPassword123",
            "ShortSecret",
            "ghp_1234567890abcdef123456",
            "sk-proj1234567890abcdef",
            "MIIEpAIBAAKCAQEA",
        ):
            assert leaked not in redacted, f"Secret leaked: {leaked}"
        assert "[REDACTED]" in redacted
        assert "[REDACTED PRIVATE KEY]" in redacted

    def test_nmap_port_flag_preserved(self) -> None:
        cmd = "nmap -p 1-65535 -T4 192.168.10.10"
        assert redact_secrets(cmd) == cmd

    def test_pipeline_redacts_secrets_from_md_and_pdf(
        self, tmp_path: Path, tmp_out: Path
    ) -> None:
        session_file = tmp_path / "secrets_session.json"
        session_data = {
            "meta": {"operator": "tester", "api_key": "sk-secretkey9876543210"},
            "events": [
                {
                    "tool": "curl",
                    "command": "curl -H '" 'Authorization: ' 'Bearer my_jwt_secret_token_999' "' https://svc:TopSecret99@web-server.lab/beacon",
                    "output": "C2 beacon callback, Cookie: PHPSESSID=deadbeef123456; password=Hunter2Secret!",
                }
            ],
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
        run_pipeline(session_file, tmp_out)

        md_text = (tmp_out / "redteam_report.md").read_text(encoding="utf-8")
        pdf_stream = _extract_pdf_streams((tmp_out / "redteam_report.pdf").read_bytes())

        for secret in (
            "sk-secretkey9876543210",
            "my_jwt_secret_token_999",
            "TopSecret99",
            "deadbeef123456",
            "Hunter2Secret!",
        ):
            assert secret not in md_text, f"Secret leaked in MD: {secret}"
            assert secret not in pdf_stream, f"Secret leaked in PDF: {secret}"


class TestPdfAndFalsePositives:
    """PDF must preserve all wrapped/multi-page/Turkish text; benign text yields 0 findings."""

    def test_pdf_multipage_and_turkish_normalization(self) -> None:
        long_line = "Güvenlik açığı tespiti ve ağ taraması raporu: " + ("veri " * 30)
        many_lines = [f"- Bulgu {i}: {long_line}" for i in range(60)]
        md = "# Türkçe Başlık: ğüşıöç ĞÜŞİÖÇ (test) \\path\n\n" + "\n".join(many_lines)

        pdf = _PDFWriter().generate(md)
        stream = _extract_pdf_streams(pdf)
        assert b"/Count 1 " not in pdf  # must span multiple pages
        assert "?" not in stream  # no lost glyphs replaced with '?'
        assert "Turkce Baslik: gusioc GUSIOC" in stream
        assert "Bulgu 59" in stream  # last line not dropped

    def test_benign_ordinary_text_produces_zero_findings(self, rules: list[MitreRule]) -> None:
        benign_events = [
            {"message": "User alice logged in via ssh on port 22 over http"},
            {"level": "info", "status": "ok", "message": "SSH service started, HTTP server version 2.4 verified"},
            {"log": "Normal user login completed without errors; server id 42"},
        ]
        findings = analyze_events(benign_events, rules)
        assert findings == []

class TestInstructorReviewScopeCases:
    """Explicit regression tests requested in 25.11 instructor review."""

    def test_public_ipv6_event_target_raises_and_exits_2(
        self, tmp_path: Path, tmp_out: Path
    ) -> None:
        event = {"tool": "nmap", "target": "2001:4860:4860::8888"}
        with pytest.raises(ScopeViolationError):
            validate_scope([event])

        session_file = tmp_path / "ipv6_oos.json"
        session_file.write_text(
            json.dumps({"events": [event]}),
            encoding="utf-8",
        )
        assert main(["--input", str(session_file), "--out-dir", str(tmp_out)]) == 2

    @pytest.mark.parametrize(
        "target_value",
        [
            "evil.example.sh",
            "evil.example.py",
            "evil.example.md",
            "evil.example.go",
        ],
    )
    def test_public_cctld_extensions_in_target_field_raise_and_exit_2(
        self, tmp_path: Path, tmp_out: Path, target_value: str
    ) -> None:
        event = {"tool": "curl", "target": target_value}
        with pytest.raises(ScopeViolationError):
            validate_scope([event])

        session_file = tmp_path / f"cctld_{target_value.replace('.', '_')}.json"
        session_file.write_text(
            json.dumps({"events": [event]}),
            encoding="utf-8",
        )
        assert main(["--input", str(session_file), "--out-dir", str(tmp_out)]) == 2
