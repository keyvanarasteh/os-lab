"""Step 1 of a scan: read manifest.json and score what the extension asks for."""
import json
import re
from pathlib import Path

from . import Finding


class ManifestError(Exception):
    """The folder is not an extension or manifest.json cannot be read."""


# How much each permission adds to the score, and why it is risky.
PERMISSIONS = {
    "debugger":         (15, "high",   "can attach the debugger to any tab and read/alter everything"),
    "nativeMessaging":  (12, "high",   "can talk to programs installed on the computer"),
    "userScripts":      (12, "high",   "can register scripts that run inside web pages"),
    "cookies":          (10, "high",   "can read session cookies (account takeover)"),
    "proxy":            (10, "high",   "can route all browser traffic through another server"),
    "scripting":        (8,  "medium", "can inject code into web pages"),
    "history":          (8,  "medium", "can read the full browsing history"),
    "management":       (8,  "medium", "can list, enable or disable other extensions"),
    "webRequestBlocking": (8, "medium", "can block or change requests in flight (MV2)"),
    "webRequest":       (6,  "medium", "can watch every network request"),
    "declarativeNetRequestWithHostAccess": (6, "medium", "can rewrite requests and headers on its hosts"),
    "clipboardRead":    (6,  "medium", "can read the clipboard"),
    "tabs":             (5,  "low",    "can see the URL and title of every tab"),
    "webNavigation":    (5,  "low",    "sees every page navigation"),
    "downloads":        (4,  "low",    "can start and read downloads"),
    "declarativeNetRequest": (4, "low", "can rewrite or block requests and headers"),
    "activeTab":        (2,  "low",    "can access the current tab after a click"),
}
ALL_SITES_POINTS = 25
ALL_SITES = {"<all_urls>", "*://*/*", "http://*/*", "https://*/*"}
SITE_ACCESS_POINTS = 3       # access to some named sites only
FILE_ACCESS_POINTS = 8       # file:// pages on the computer


def load_manifest(folder):
    """Return the parsed manifest.json of an unpacked extension folder."""
    path = Path(folder) / "manifest.json"
    if not path.is_file():
        raise ManifestError(f"no manifest.json in {folder}")
    try:
        # utf-8-sig also accepts a BOM, which some editors add.
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError(f"{path}: the manifest must be a JSON object")
    validate(manifest)
    return manifest


def _strings(manifest, key, where=None):
    """A list-of-strings field, or [] when it is missing."""
    value = (where if where is not None else manifest).get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"manifest field '{key}' must be a list of strings")
    return value


def validate(manifest):
    """Reject wrong field types early, so the audit never crashes on them."""
    for key in ("permissions", "optional_permissions", "host_permissions",
                "optional_host_permissions"):
        _strings(manifest, key)
    scripts = manifest.get("content_scripts", [])
    if not isinstance(scripts, list) or not all(isinstance(s, dict) for s in scripts):
        raise ManifestError("manifest field 'content_scripts' must be a list of objects")
    for script in scripts:
        _strings(manifest, "matches", script)
    csp = manifest.get("content_security_policy", "")
    if not isinstance(csp, (str, dict)):
        raise ManifestError("manifest field 'content_security_policy' must be a string or object")


def _split(names):
    """MV2 mixes host patterns into the permission lists: separate them."""
    hosts = [p for p in names if "://" in p or p == "<all_urls>"]
    apis = [p for p in names if p not in hosts]
    return apis, hosts


def host_patterns(manifest):
    """All URL patterns the extension can reach (required ones), for MV2 and MV3."""
    hosts = list(_strings(manifest, "host_permissions"))            # MV3
    hosts += _split(_strings(manifest, "permissions"))[1]            # MV2
    for script in manifest.get("content_scripts", []):
        hosts += _strings(manifest, "matches", script)
    return list(dict.fromkeys(hosts))                                # no repeats


def optional_host_patterns(manifest):
    hosts = list(_strings(manifest, "optional_host_permissions"))
    hosts += _split(_strings(manifest, "optional_permissions"))[1]
    return list(dict.fromkeys(hosts))


def csp_text(manifest):
    """Content Security Policy as one string (MV2 string or MV3 object)."""
    csp = manifest.get("content_security_policy", "")
    if isinstance(csp, dict):
        csp = " ; ".join(str(v) for v in csp.values())
    return str(csp)


def script_sources(csp):
    """Sources allowed for scripts: script-src(-elem), or default-src when absent."""
    directives = {}
    for part in csp.split(";"):
        words = part.split()
        if words:
            directives.setdefault(words[0].lower(), []).extend(words[1:])
    sources = directives.get("script-src", []) + directives.get("script-src-elem", [])
    if "script-src" not in directives and "script-src-elem" not in directives:
        sources = directives.get("default-src", [])
    return sources


def _host_findings(hosts, optional):
    tag = " (optional, asked at runtime)" if optional else ""
    weight = (lambda p: p // 2) if optional else (lambda p: p)
    prefix = "PERM-OPTIONAL-" if optional else "PERM-"
    findings = []
    web = [h for h in hosts if not h.startswith("file:")]
    if any(h in ALL_SITES for h in web):
        findings.append(Finding(prefix + "ALL-SITES", "high", weight(ALL_SITES_POINTS),
                                "runs on every website (<all_urls>)" + tag))
    elif web:
        shown = ", ".join(web[:3]) + (" ..." if len(web) > 3 else "")
        findings.append(Finding(prefix + "SITE-ACCESS", "low", weight(SITE_ACCESS_POINTS),
                                f"can access {len(web)} site pattern(s): {shown}" + tag))
    if any(h.startswith("file:") for h in hosts):
        findings.append(Finding(prefix + "FILE-ACCESS", "medium", weight(FILE_ACCESS_POINTS),
                                "can open local files (file://)" + tag))
    return findings


def _permission_findings(names, optional):
    tag = " (optional, asked at runtime)" if optional else ""
    prefix = "PERM-OPTIONAL-" if optional else "PERM-"
    findings = []
    for name in dict.fromkeys(names):                 # each permission counts once
        if name in PERMISSIONS:
            points, severity, why = PERMISSIONS[name]
            findings.append(Finding(prefix + re.sub(r"\W", "", name).upper(), severity,
                                    points // 2 if optional else points,
                                    f"permission '{name}': {why}" + tag))
    return findings


def audit_manifest(manifest):
    """Turn the manifest into a list of findings."""
    validate(manifest)
    findings = _host_findings(host_patterns(manifest), optional=False)
    findings += _permission_findings(_split(_strings(manifest, "permissions"))[0], optional=False)

    required = {f.rule.replace("PERM-", "") for f in findings}
    optional = _host_findings(optional_host_patterns(manifest), optional=True)
    optional += _permission_findings(_split(_strings(manifest, "optional_permissions"))[0],
                                     optional=True)
    # An optional grant that is already required adds nothing.
    findings += [f for f in optional if f.rule.replace("PERM-OPTIONAL-", "") not in required]

    sources = script_sources(csp_text(manifest))
    if "'unsafe-eval'" in sources:
        findings.append(Finding("CSP-UNSAFE-EVAL", "high", 15,
                                "CSP allows 'unsafe-eval': text can be run as code"))
    if any(s.startswith(("http:", "https:")) for s in sources):
        findings.append(Finding("CSP-REMOTE-SCRIPT", "medium", 8,
                                "CSP allows scripts from a remote server"))
    return findings
