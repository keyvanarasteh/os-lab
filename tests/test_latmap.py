"""Unit and scenario tests for PENT-19 latmap.py brain-map generator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analysis import latmap

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "latmap"


def test_demo_session_generates_valid_graph_and_wiki_links() -> None:
    raw = latmap.build_demo_session()
    session = latmap.normalize_session(raw)
    report = latmap.validate_graph(session)
    md = latmap.render_lat_markdown(session, report)

    assert report["status"] == "OK"
    assert report["counts"]["targets"] == 2
    assert report["counts"]["scripts"] == 1
    assert report["counts"]["findings"] == 2
    assert report["dangling_links"] == []
    assert "[[lat.md/session-brain-map.md#Targets#avelium-lms-waf|avelium-lms-waf]]" in md
    assert "[[lat.md/session-brain-map.md#Scripts#waf-crs-probe|waf-crs-probe]]" in md
    assert "[[lat.md/session-brain-map.md#Findings#waf-sqli-blocked|waf-sqli-blocked]]" in md


def test_valid_fixture_cli_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = latmap.main(["--session", str(FIXTURES / "valid_session.json"), "--check"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "## Targets" in captured.out
    assert "### lms-waf-node" in captured.out


def test_orphan_fixture_warns_and_strict_mode_fails(capsys: pytest.CaptureFixture[str]) -> None:
    rc_normal = latmap.main(["--session", str(FIXTURES / "orphan_warning.json"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_normal == 0
    assert payload["validation"]["status"] == "WARN"
    assert "forgotten-host" in payload["validation"]["orphan_nodes"]

    rc_strict = latmap.main(["--session", str(FIXTURES / "orphan_warning.json"), "--strict"])
    assert rc_strict == 1


def test_broken_links_fixture_returns_fail(capsys: pytest.CaptureFixture[str]) -> None:
    rc = latmap.main(["--session", str(FIXTURES / "broken_links.json"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["validation"]["status"] == "FAIL"
    assert len(payload["validation"]["dangling_links"]) == 2


def test_sanitize_strips_ansi_and_control_chars() -> None:
    dirty = "Target\x1b[31m-Host\x07\x00"
    assert latmap.sanitize_text(dirty) == "Target-Host"
    assert latmap.slugify(dirty) == "target-host"


def test_atomic_output_writes_markdown_file(tmp_path: Path) -> None:
    out_file = tmp_path / "brain-map.md"
    rc = latmap.main(["--demo", "--output", str(out_file)])
    assert rc == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "# Avelium DMZ WAF & Android Lab Brain-Map" in content
