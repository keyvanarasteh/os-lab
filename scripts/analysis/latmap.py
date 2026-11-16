#!/usr/bin/env python3
"""PENT-19 · Analysis Session Brain-Map (lat.md) Generator.

Generates a lat.md-compatible knowledge graph from a penetration testing or
security analysis session's targets, findings, and scripts with [[wiki-links]]
between nodes so a long investigation stays navigable.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

VALID_SEVERITIES = ("critical", "high", "medium", "low", "info")
SLUG_RE = re.compile(r"[^a-z0-9]+")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\x1b\[[0-9;]*[a-zA-Z]")


def sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(value))
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
    return " ".join(cleaned.split()).strip()


def slugify(value: str) -> str:
    """Convert an arbitrary identifier or title into a stable lat.md section slug."""
    cleaned = sanitize_text(value).lower()
    slug = SLUG_RE.sub("-", cleaned).strip("-")
    return slug or "unnamed-node"


def normalize_session(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize raw session dictionary into canonical nodes and links."""
    if not isinstance(raw, dict):
        raise ValueError("Session payload must be a JSON object.")

    session_id = sanitize_text(raw.get("session_id") or "analysis-session")
    title = sanitize_text(raw.get("title") or f"Analysis Session: {session_id}")
    doc_ref = sanitize_text(raw.get("doc_path") or "lat.md/session-brain-map.md")

    targets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for item in raw.get("targets", []):
        if not isinstance(item, dict):
            continue
        tid = slugify(item.get("id") or item.get("name") or item.get("host") or "")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        targets.append({
            "id": tid,
            "kind": "target",
            "name": sanitize_text(item.get("name") or tid),
            "host": sanitize_text(item.get("host") or "unknown-host"),
            "scope": sanitize_text(item.get("scope") or "in-scope"),
            "tags": [slugify(t) for t in item.get("tags", []) if sanitize_text(t)],
            "notes": sanitize_text(item.get("notes") or "Authorized analysis target."),
        })

    scripts: list[dict[str, Any]] = []
    for item in raw.get("scripts", []):
        if not isinstance(item, dict):
            continue
        sid = slugify(item.get("id") or item.get("name") or item.get("path") or "")
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        scripts.append({
            "id": sid,
            "kind": "script",
            "name": sanitize_text(item.get("name") or sid),
            "path": sanitize_text(item.get("path") or f"scripts/analysis/{sid}.py"),
            "targets": [slugify(t) for t in item.get("targets", []) if sanitize_text(t)],
            "purpose": sanitize_text(item.get("purpose") or "Automated inspection script."),
        })

    findings: list[dict[str, Any]] = []
    for item in raw.get("findings", []):
        if not isinstance(item, dict):
            continue
        fid = slugify(item.get("id") or item.get("title") or "")
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)
        sev = sanitize_text(item.get("severity") or "info").lower()
        if sev not in VALID_SEVERITIES:
            sev = "info"
        findings.append({
            "id": fid,
            "kind": "finding",
            "title": sanitize_text(item.get("title") or fid),
            "severity": sev,
            "target": slugify(item.get("target")) if item.get("target") else "",
            "script": slugify(item.get("script")) if item.get("script") else "",
            "evidence": sanitize_text(item.get("evidence") or "Verified during session."),
            "remediation": sanitize_text(item.get("remediation") or "Apply least-privilege control."),
        })

    return {
        "session_id": session_id,
        "title": title,
        "doc_path": doc_ref,
        "targets": targets,
        "scripts": scripts,
        "findings": findings,
    }


def validate_graph(session: dict[str, Any]) -> dict[str, Any]:
    """Verify node/link integrity (dangling references, orphan nodes, severity summary)."""
    known_targets = {t["id"] for t in session["targets"]}
    known_scripts = {s["id"] for s in session["scripts"]}
    known_findings = {f["id"] for f in session["findings"]}
    all_nodes = known_targets | known_scripts | known_findings

    edges: list[dict[str, str]] = []
    dangling_links: list[dict[str, str]] = []
    connected_nodes: set[str] = set()

    for s in session["scripts"]:
        for tid in s["targets"]:
            if tid in known_targets:
                edges.append({"from": s["id"], "to": tid, "type": "inspects"})
                connected_nodes.update((s["id"], tid))
            else:
                dangling_links.append({"source": s["id"], "missing_target": tid, "field": "targets"})

    for f in session["findings"]:
        if f["target"]:
            if f["target"] in known_targets:
                edges.append({"from": f["id"], "to": f["target"], "type": "affects"})
                connected_nodes.update((f["id"], f["target"]))
            else:
                dangling_links.append({"source": f["id"], "missing_target": f["target"], "field": "target"})
        if f["script"]:
            if f["script"] in known_scripts:
                edges.append({"from": f["id"], "to": f["script"], "type": "detected_by"})
                connected_nodes.update((f["id"], f["script"]))
            else:
                dangling_links.append({"source": f["id"], "missing_target": f["script"], "field": "script"})

    orphan_nodes = sorted(all_nodes - connected_nodes) if len(all_nodes) > 1 else []
    severity_counts = {sev: 0 for sev in VALID_SEVERITIES}
    for f in session["findings"]:
        severity_counts[f["severity"]] += 1

    status = "OK"
    if dangling_links or not all_nodes:
        status = "FAIL"
    elif orphan_nodes:
        status = "WARN"

    return {
        "status": status,
        "session_id": session["session_id"],
        "counts": {
            "targets": len(known_targets),
            "scripts": len(known_scripts),
            "findings": len(known_findings),
            "total_nodes": len(all_nodes),
            "edges": len(edges),
        },
        "severities": severity_counts,
        "edges": edges,
        "dangling_links": dangling_links,
        "orphan_nodes": orphan_nodes,
    }


def render_lat_markdown(session: dict[str, Any], report: dict[str, Any]) -> str:
    """Render a lat.md-compatible Markdown document with [[wiki-links]] between sections."""
    doc_path = session["doc_path"]

    def wiki_link(section_group: str, node_id: str, label: str | None = None) -> str:
        target_ref = f"{doc_path}#{section_group}#{node_id}"
        return f"[[{target_ref}|{label}]]" if label else f"[[{target_ref}]]"

    lines = [
        "---",
        f'id: "{session["session_id"]}"',
        "type: analysis-brain-map",
        "generator: scripts/analysis/latmap.py",
        "---",
        "",
        f"# {session['title']}",
        "",
        f"Session brain-map (`{session['session_id']}`) generated by `scripts/analysis/latmap.py` "
        f"with **{report['counts']['total_nodes']} nodes** and **{report['counts']['edges']} links** "
        f"(Status: **{report['status']}**).",
        "",
        "## Targets",
        "",
    ]

    if not session["targets"]:
        lines.append("No analysis targets recorded in this session.")
        lines.append("")
    else:
        for t in session["targets"]:
            related_scripts = [
                wiki_link("Scripts", s["id"], s["id"])
                for s in session["scripts"]
                if t["id"] in s["targets"]
            ]
            related_findings = [
                wiki_link("Findings", f["id"], f["id"])
                for f in session["findings"]
                if f["target"] == t["id"]
            ]
            lines.extend([
                f"### {t['id']}",
                "",
                f"{t['name']} (`{t['host']}`, scope: `{t['scope']}`). {t['notes']}",
                "",
                f"- Inspected by scripts: {', '.join(related_scripts) if related_scripts else 'none'}",
                f"- Reported findings: {', '.join(related_findings) if related_findings else 'none'}",
                "",
            ])

    lines.extend(["## Scripts", ""])
    if not session["scripts"]:
        lines.append("No scripts recorded in this session.")
        lines.append("")
    else:
        for s in session["scripts"]:
            linked_targets = [
                wiki_link("Targets", tid, tid)
                for tid in s["targets"]
                if any(t["id"] == tid for t in session["targets"])
            ]
            produced_findings = [
                wiki_link("Findings", f["id"], f["id"])
                for f in session["findings"]
                if f["script"] == s["id"]
            ]
            lines.extend([
                f"### {s['id']}",
                "",
                f"{s['name']} (`{s['path']}`). {s['purpose']}",
                "",
                f"- Evaluates targets: {', '.join(linked_targets) if linked_targets else 'none'}",
                f"- Produces findings: {', '.join(produced_findings) if produced_findings else 'none'}",
                "",
            ])

    lines.extend(["## Findings", ""])
    if not session["findings"]:
        lines.append("No security findings recorded in this session.")
        lines.append("")
    else:
        for f in session["findings"]:
            t_link = (
                wiki_link("Targets", f["target"], f["target"])
                if any(t["id"] == f["target"] for t in session["targets"])
                else f"`{f['target'] or 'unlinked'}`"
            )
            s_link = (
                wiki_link("Scripts", f["script"], f["script"])
                if any(s["id"] == f["script"] for s in session["scripts"])
                else f"`{f['script'] or 'manual'}`"
            )
            lines.extend([
                f"### {f['id']}",
                "",
                f"[{f['severity'].upper()}] {f['title']} affecting {t_link} (detected via {s_link}).",
                "",
                f"- Evidence: {f['evidence']}",
                f"- Remediation: {f['remediation']}",
                "",
            ])

    return "\n".join(lines).rstrip() + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically using a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def build_demo_session() -> dict[str, Any]:
    """Return a built-in sample analysis session (Avelium WAF & Android Lab audit)."""
    return {
        "session_id": "avelium-pentest-session-01",
        "title": "Avelium DMZ WAF & Android Lab Brain-Map",
        "doc_path": "lat.md/session-brain-map.md",
        "targets": [
            {
                "id": "avelium-lms-waf",
                "name": "Avelium Academic LMS WAF Gateway",
                "host": "10.64.60.5:443",
                "scope": "in-scope",
                "tags": ["dmz", "waf", "modsecurity"],
                "notes": "Front-end L7 OWASP CRS reverse proxy protecting 10,000-student LMS backend (10.64.60.10).",
            },
            {
                "id": "avelium-hq-vpn",
                "name": "Istanbul HQ Role-Based VPN Bastion",
                "host": "10.10.10.1:4500",
                "scope": "in-scope",
                "tags": ["vpn", "mfa", "ipsec"],
                "notes": "IPsec IKEv2/NAT-T gateway restricting SSH management to VLAN 10.",
            },
        ],
        "scripts": [
            {
                "id": "waf-crs-probe",
                "name": "OWASP CRS Payload Verifier",
                "path": "scripts/analysis/latmap.py",
                "targets": ["avelium-lms-waf", "avelium-hq-vpn"],
                "purpose": "Verifies SQLi/XSS block rules on LMS WAF and checks UDP 500/4500 ACLs on HQ VPN.",
            }
        ],
        "findings": [
            {
                "id": "waf-sqli-blocked",
                "title": "OWASP CRS Rule 942100 Blocks SQLi on LMS Login",
                "severity": "info",
                "target": "avelium-lms-waf",
                "script": "waf-crs-probe",
                "evidence": "Payload `' OR 1=1 --` returned HTTP 403 Forbidden at 10.64.60.5 without reaching 10.64.60.10.",
                "remediation": "Maintain OWASP CRS paranoia level 2 and forward WAF alerts to Wazuh SIEM.",
            },
            {
                "id": "direct-backend-bypass-prevented",
                "title": "Direct Backend Access Locked to WAF Source IP",
                "severity": "low",
                "target": "avelium-hq-vpn",
                "script": "waf-crs-probe",
                "evidence": "Forward chain drops traffic to 10.64.60.10 unless source is 10.64.60.5; SSH requires MFA VPN.",
                "remediation": "Keep terminal default-deny rules on in, forward, and out firewall chains.",
            },
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, help="Path to session JSON file.")
    parser.add_argument("--demo", action="store_true", help="Run with built-in Avelium pentest session.")
    parser.add_argument("--output", "-o", type=Path, help="Write generated lat.md Markdown to file.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON validation and graph report.")
    parser.add_argument("--check", action="store_true", help="Validate node/link integrity and exit non-zero on FAIL.")
    parser.add_argument("--strict", action="store_true", help="Also exit non-zero on WARN (e.g., orphan nodes).")
    args = parser.parse_args(argv)

    try:
        if args.session:
            raw_data = json.loads(args.session.read_text(encoding="utf-8"))
        elif args.demo:
            raw_data = build_demo_session()
        else:
            parser.error("Provide either --session <path.json> or --demo.")
            return 2
        session = normalize_session(raw_data)
    except Exception as exc:
        print(f"[FAIL] Could not load session: {exc}", file=sys.stderr)
        return 1

    report = validate_graph(session)
    markdown = render_lat_markdown(session, report)

    if args.output:
        atomic_write_text(args.output, markdown)

    if args.json:
        payload = {
            "session": session,
            "validation": report,
            "markdown": markdown,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(markdown, end="")

    if report["status"] == "FAIL":
        return 1
    if args.strict and report["status"] == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
