"""Step 3 of a scan: put manifest and code findings together and score them.

score = capability (max 40) + behaviour (max 60)
  capability = what the extension may do  (manifest permissions)
  behaviour  = what its code actually does (each code rule counts once)
A scary manifest alone cannot reach "critical"; dangerous code is needed for that.
"""
import re
from pathlib import Path

from . import __version__
from .manifest import audit_manifest, load_manifest
from .patterns import scan_scripts

CAPABILITY_MAX = 40
BEHAVIOUR_MAX = 60
GRADES = [(70, "critical"), (45, "high"), (20, "medium"), (0, "low")]
GRADE_ORDER = ["low", "medium", "high", "critical"]


def grade_for(score):
    return next(name for limit, name in GRADES if score >= limit)


def score(manifest_findings, code_findings):
    capability = min(CAPABILITY_MAX, sum(f.points for f in manifest_findings))
    best = {}                        # one rule = one contribution, however often it occurs
    for f in code_findings:
        best[f.rule] = max(best.get(f.rule, 0), f.points)
    behaviour = min(BEHAVIOUR_MAX, sum(best.values()))
    total = capability + behaviour
    return {"score": total, "grade": grade_for(total),
            "capability": capability, "behaviour": behaviour}


def scan(folder):
    """Scan one unpacked extension folder and return a result dictionary."""
    folder = Path(folder)
    manifest = load_manifest(folder)
    manifest_findings = audit_manifest(manifest)
    code_findings, endpoints = scan_scripts(folder)
    findings = manifest_findings + code_findings
    findings.sort(key=lambda f: (-GRADE_ORDER.index(f.severity) if f.severity in GRADE_ORDER else 1,
                                 f.file, f.line))
    return {
        "tool": f"ext_scan {__version__}",
        "extension": {
            "path": str(folder),
            "name": manifest.get("name", "?"),
            "version": manifest.get("version", "?"),
            "manifest_version": manifest.get("manifest_version"),
        },
        "risk": score(manifest_findings, code_findings),
        "endpoints": endpoints,
        "findings": [f.to_dict() for f in findings],
    }


_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]")


def clean(value):
    """Escape control and bidi characters, so an extension cannot draw on the terminal."""
    return _UNSAFE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", str(value))


def format_text(result):
    """Short human readable report for the terminal."""
    ext, risk = result["extension"], result["risk"]
    lines = [
        f"{clean(ext['name'])} {clean(ext['version'])} (MV{clean(ext['manifest_version'])})",
        f"Risk: {risk['score']}/100  {risk['grade'].upper()}"
        f"   (capability {risk['capability']}/{CAPABILITY_MAX},"
        f" behaviour {risk['behaviour']}/{BEHAVIOUR_MAX})",
        "",
    ]
    shown = [f for f in result["findings"] if f["severity"] != "info"]
    if not shown:
        lines.append("No risky permissions or code patterns found.")
    for f in shown:
        where = clean(f["file"]) + (f":{f['line']}" if f["line"] else "")
        lines.append(f"  [{f['severity'].upper():8}] {f['rule']:20} {where:22} {clean(f['message'])}")
    if result["endpoints"]:
        lines += ["", "Endpoints:"] + [f"  {clean(u)}" for u in result["endpoints"]]
    return "\n".join(lines)
