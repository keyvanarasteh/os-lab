"""Step 1 of a scan: read manifest.json and score what the extension asks for."""
import json
from pathlib import Path

from . import Finding


class ManifestError(Exception):
    """The folder is not an extension or manifest.json cannot be read."""


# How much each permission adds to the score, and why it is risky.
PERMISSIONS = {
    "debugger":         (15, "high",   "can attach the debugger to any tab and read/alter everything"),
    "nativeMessaging":  (12, "high",   "can talk to programs installed on the computer"),
    "cookies":          (10, "high",   "can read session cookies (account takeover)"),
    "proxy":            (10, "high",   "can route all browser traffic through another server"),
    "scripting":        (8,  "medium", "can inject code into web pages"),
    "history":          (8,  "medium", "can read the full browsing history"),
    "management":       (8,  "medium", "can list, enable or disable other extensions"),
    "webRequestBlocking": (8, "medium", "can block or change requests in flight (MV2)"),
    "webRequest":       (6,  "medium", "can watch every network request"),
    "clipboardRead":    (6,  "medium", "can read the clipboard"),
    "tabs":             (5,  "low",    "can see the URL and title of every tab"),
    "downloads":        (4,  "low",    "can start and read downloads"),
    "declarativeNetRequest": (4, "low", "can rewrite or block requests and headers"),
    "activeTab":        (2,  "low",    "can access the current tab after a click"),
}
ALL_SITES_POINTS = 25
ALL_SITES = {"<all_urls>", "*://*/*", "http://*/*", "https://*/*"}


def load_manifest(folder):
    """Return the parsed manifest.json of an unpacked extension folder."""
    path = Path(folder) / "manifest.json"
    if not path.is_file():
        raise ManifestError(f"no manifest.json in {folder}")
    try:
        # utf-8-sig also accepts a BOM, which some editors add.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc


def host_patterns(manifest):
    """All URL patterns the extension can reach, for MV2 and MV3."""
    hosts = list(manifest.get("host_permissions", []))  # MV3
    # MV2 mixes host patterns into "permissions".
    hosts += [p for p in manifest.get("permissions", []) if "://" in p or p == "<all_urls>"]
    for script in manifest.get("content_scripts", []):
        hosts += script.get("matches", [])
    return hosts


def csp_text(manifest):
    """Content Security Policy as one string (MV2 string or MV3 object)."""
    csp = manifest.get("content_security_policy", "")
    if isinstance(csp, dict):
        csp = " ".join(str(v) for v in csp.values())
    return str(csp)


def audit_manifest(manifest):
    """Turn the manifest into a list of findings."""
    findings = []

    if any(h in ALL_SITES for h in host_patterns(manifest)):
        findings.append(Finding("PERM-ALL-SITES", "high", ALL_SITES_POINTS,
                                "runs on every website (<all_urls>)"))

    for name in manifest.get("permissions", []):
        if name in PERMISSIONS:
            points, severity, why = PERMISSIONS[name]
            findings.append(Finding(f"PERM-{name.upper()}", severity, points,
                                    f"permission '{name}': {why}"))

    csp = csp_text(manifest)
    if "'unsafe-eval'" in csp:
        findings.append(Finding("CSP-UNSAFE-EVAL", "high", 15,
                                "CSP allows 'unsafe-eval': text can be run as code"))
    if "http://" in csp or "https://" in csp:
        findings.append(Finding("CSP-REMOTE-SCRIPT", "medium", 8,
                                "CSP allows scripts from a remote server"))
    return findings
