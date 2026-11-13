#!/usr/bin/env python3
"""PENT-18: offline native-messaging audit of explicitly scoped lab files.

Never starts a browser, executes a host binary, reads the registry or uses the
network. JavaScript matches are lexical clues, not proof of execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys

MAX_JSON = 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_BINARY = 32 * 1024 * 1024
MAX_FILES = 500
MAX_HOSTS = 100
LEVELS = {"info": 0, "medium": 1, "high": 2}
CALL = re.compile(
    r"\b(?:chrome|browser)\s*\.\s*runtime\s*\.\s*"
    r"(connectNative|sendNativeMessage)\s*\(\s*"
    r"(?:(['\"])([^'\"\r\n]*)\2)?"
)
CHROME_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}/\Z")


class AnalysisError(ValueError):
    """Invalid input, incomplete scan or an out-of-scope input file."""


def scoped(path: Path, root: Path) -> Path:
    """Resolve links before checking containment, including Windows junctions."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise AnalysisError("path is outside the declared lab root")
    return resolved


def read_bytes(path: Path, root: Path, limit: int) -> bytes:
    path = scoped(path, root)
    # Refuse devices, pipes and directories before opening them.
    if not path.is_file():
        raise AnalysisError(f"not a regular file: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AnalysisError(f"file exceeds {limit} byte limit: {path.name}")
    return data


def load_json(path: Path, root: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AnalysisError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(read_bytes(path, root, MAX_JSON).decode("utf-8-sig"),
                           object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"invalid UTF-8 JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"expected JSON object: {path.name}")
    return value


def string_list(value, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise AnalysisError(f"{label} must be an array of strings")
    return value


def analyze(lab_root: Path, extension: Path, hosts: list[Path], *,
            platform: str, extension_id: str | None = None) -> dict:
    root = lab_root.resolve(strict=True)
    if not root.is_dir():
        raise AnalysisError("lab root must be a directory")
    extension = scoped(extension, root)
    if not extension.is_dir():
        raise AnalysisError("extension must be a directory")
    if len(hosts) > MAX_HOSTS:
        raise AnalysisError(f"at most {MAX_HOSTS} host manifests may be supplied")
    if extension_id is not None and not CHROME_ORIGIN.fullmatch(
            f"chrome-extension://{extension_id}/"):
        raise AnalysisError("extension-id must contain 32 lowercase letters a-p")
    findings = []

    def relative(path):
        return scoped(path, root).relative_to(root).as_posix()

    def flag(rule, severity, location, message, remediation):
        findings.append(dict(rule=rule, severity=severity, location=location,
                             message=message, remediation=remediation))

    manifest = load_json(extension / "manifest.json", root)
    if manifest.get("manifest_version") not in (2, 3):
        raise AnalysisError("extension manifest_version must be 2 or 3")
    permissions = string_list(manifest.get("permissions", []), "permissions")
    optional = string_list(manifest.get("optional_permissions", []), "optional_permissions")
    native = "nativeMessaging" in permissions
    optional_native = "nativeMessaging" in optional
    if native or optional_native:
        flag("native-permission", "info", relative(extension / "manifest.json"),
             "nativeMessaging permits a browser-to-local-process bridge"
             + (" after an optional permission grant" if not native else ""),
             "Review both the extension and the native host's message validation.")

    calls = []
    # os.walk does not follow directory symlinks; explicitly refuse them so a
    # clean-looking partial report cannot conceal an omitted source subtree.
    count = 0
    for folder, dirs, files in os.walk(extension, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
        dirs.sort()
        for name in dirs:
            child = Path(folder) / name
            if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                raise AnalysisError("linked source directories are not supported")
        for name in sorted(files):
            count += 1
            if count > MAX_FILES:
                raise AnalysisError(f"extension exceeds {MAX_FILES} file limit")
            path = Path(folder) / name
            scoped(path, root)
            if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".html"}:
                continue
            try:
                source = read_bytes(path, root, MAX_SOURCE).decode("utf-8-sig")
            except UnicodeError as exc:
                raise AnalysisError(f"source is not UTF-8: {name}") from exc
            for match in CALL.finditer(source):
                host = match.group(3)
                call = dict(file=relative(path), line=source.count("\n", 0, match.start()) + 1,
                            api=match.group(1), host=host)
                calls.append(call)
                if host is None:
                    flag("dynamic-host", "medium", f"{call['file']}:{call['line']}",
                         "Native host name is not a simple string literal; target unresolved.",
                         "Review the argument and its data flow manually.")
    if calls and not (native or optional_native):
        flag("missing-native-permission", "medium", relative(extension / "manifest.json"),
             "Lexical native API calls found without nativeMessaging permission.",
             "Check whether this is dead code, a comment or a broken permission declaration.")

    gecko = manifest.get("browser_specific_settings", manifest.get("applications", {}))
    firefox_id = None
    if isinstance(gecko, dict) and isinstance(gecko.get("gecko"), dict):
        firefox_id = gecko["gecko"].get("id")
    inspected = []
    names = set()
    for host_path in hosts:
        host_path = scoped(host_path, root)
        location = relative(host_path)
        host = load_json(host_path, root)
        name = host.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", name):
            raise AnalysisError(f"invalid native host name: {location}")
        if name in names:
            raise AnalysisError(f"duplicate native host name: {name}")
        names.add(name)
        if host.get("type") != "stdio":
            flag("invalid-host-type", "high", location, "Native host type must be stdio.",
                 "Use the browser's documented native messaging manifest schema.")
        if not isinstance(host.get("description"), str) or not host["description"].strip():
            flag("missing-description", "medium", location, "Host description is missing or empty.",
                 "Document the host's purpose.")
        if "allowed_origins" in host and "allowed_extensions" in host:
            raise AnalysisError("host manifest must specify one browser allowlist format")
        field = "allowed_extensions" if "allowed_extensions" in host else "allowed_origins"
        allowed = string_list(host.get(field, []), field)
        if not allowed:
            flag("empty-allowlist", "high", location, "No extensions are authorized by this manifest.",
                 "Supply an explicit nonempty browser-specific allowlist.")
        for item in allowed:
            valid = bool(CHROME_ORIGIN.fullmatch(item)) if field == "allowed_origins" else bool(item.strip()) and not any(c.isspace() for c in item) and "*" not in item
            if not valid:
                flag("invalid-allowlist", "high", location,
                     f"Invalid {field} entry; wildcard access is not a valid authorization.",
                     "Use exact extension origins/IDs; remove wildcards and unrelated callers.")
        identity = f"chrome-extension://{extension_id}/" if field == "allowed_origins" and extension_id else firefox_id if field == "allowed_extensions" else None
        if identity is None:
            flag("identity-unverified", "medium", location,
                 "Caller identity was not supplied; authorization match is unverified.",
                 "Pass --extension-id for Chromium or declare the Gecko ID in the extension.")
        elif identity not in allowed:
            flag("caller-not-allowed", "high", location,
                 "The analyzed extension's identity is absent from the host allowlist.",
                 "Verify the intended caller and correct the manifest.")
        if len(allowed) > 1:
            flag("multiple-callers", "medium", location,
                 "The host accepts more than one extension identity.",
                 "Review whether every allowed extension needs this bridge.")
        if field == "allowed_origins" and name != name.lower():
            flag("invalid-chromium-name", "high", location,
                 "Chromium host names must be lowercase.", "Use a lowercase host name.")

        raw_path = host.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip() or "\x00" in raw_path:
            raise AnalysisError(f"host path must be a nonempty path: {location}")
        windows = PureWindowsPath(raw_path)
        # Foreign-platform absolute paths cannot be inspected on this machine.
        foreign = os.name != "nt" and bool(windows.drive or raw_path.startswith("\\"))
        path = Path(raw_path)
        item = dict(name=name, manifest=location, allowlist_kind=field,
                    caller_count=len(allowed), binary={"inspected": False})
        inspected.append(item)
        if foreign or (platform == "windows" and os.name != "nt") or (platform == "posix" and os.name == "nt"):
            flag("platform-unverified", "medium", location,
                 "Binary path/permissions require inspection on the selected native platform.",
                 "Re-run on the matching platform with a contained lab copy.")
            continue
        if not path.is_absolute():
            if platform != "windows":
                flag("relative-posix-path", "high", location,
                     "Linux/macOS native host path must be absolute.", "Use an absolute lab host path.")
            path = host_path.parent / path
        try:
            path = scoped(path, root)
        except AnalysisError:
            flag("binary-out-of-scope", "high", location,
                 "Referenced binary resolves outside the lab root; it was not read.",
                 "Copy the owned test binary into the declared lab root.")
            continue
        if not path.is_file():
            flag("binary-missing", "high", location, "Referenced binary is missing or not a regular file.",
                 "Provide the owned lab host binary.")
            continue
        data = read_bytes(path, root, MAX_BINARY)
        kind = "PE" if data.startswith(b"MZ") else "ELF" if data.startswith(b"\x7fELF") else "script" if data.startswith(b"#!") else "other"
        item["binary"] = dict(inspected=True, path=relative(path), size=len(data),
                              sha256=hashlib.sha256(data).hexdigest(), format=kind,
                              permissions="POSIX mode bits" if os.name != "nt" else "Windows ACLs not inspected")
        if os.name == "nt":
            flag("acl-unverified", "medium", location,
                 "Windows ACLs and effective execution privileges were not inspected.",
                 "Review file and parent directory ACLs on the native lab machine.")
        else:
            mode = path.stat().st_mode
            if mode & (stat.S_ISUID | stat.S_ISGID):
                flag("privileged-mode", "high", relative(path), "Host has setuid/setgid mode bits.",
                     "Remove unnecessary privilege bits and review the execution model.")
            if not mode & 0o111:
                flag("not-executable", "medium", relative(path), "Host lacks executable mode bits.",
                     "Verify the intended native executable.")
            for candidate in [path, *path.parents]:
                if not candidate.is_relative_to(root):
                    break
                if candidate.stat().st_mode & 0o022:
                    flag("writable-host-chain", "high", relative(candidate),
                         "Host or containing lab directory is group/world writable.",
                         "Restrict write access; review group ownership and ACLs.")
        if kind == "other":
            flag("unknown-binary-format", "medium", relative(path),
                 "File header is not a recognized PE/ELF/shebang host.",
                 "Inspect the actual host type; format detection is a header heuristic.")
    for call in calls:
        if call["host"] is not None and call["host"] not in names:
            flag("host-not-provided", "medium", f"{call['file']}:{call['line']}",
                 f"No supplied manifest for literal native host {call['host']!r}.",
                 "Provide the matching owned host manifest with --host.")
    findings.sort(key=lambda f: (-LEVELS[f["severity"]], f["location"], f["rule"]))
    return dict(schema_version=1, task="PENT-18", mode="offline-static",
                extension=dict(manifest=relative(extension / "manifest.json"),
                               manifest_version=manifest["manifest_version"],
                               native_permission=native, optional_native_permission=optional_native),
                coverage=dict(files_considered=count, supplied_hosts=len(hosts),
                              source_matching="lexical; comments/strings may match; computed calls may be missed",
                              binary_execution=False, network_access=False,
                              limitations=["No browser registration, message validation or effective privilege verification",
                                           "No signature verification, malware verdict or Windows ACL inspection"]),
                calls=calls, hosts=inspected, findings=findings,
                summary={level: sum(f["severity"] == level for f in findings) for level in LEVELS})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extension", type=Path, help="owned unpacked lab extension directory")
    parser.add_argument("--lab-root", type=Path, required=True, help="explicit boundary for all input reads")
    parser.add_argument("--host", type=Path, action="append", default=[], help="owned native manifest; repeatable")
    parser.add_argument("--extension-id", help="known Chromium ID (never guessed from an unpacked extension)")
    parser.add_argument("--platform", choices=("windows", "posix"), default="windows" if os.name == "nt" else "posix")
    parser.add_argument("--json", action="store_true", help="emit a structured JSON report")
    parser.add_argument("--fail-on", choices=("medium", "high", "never"), default="high")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.lab_root, args.extension, args.host,
                         platform=args.platform, extension_id=args.extension_id)
    except (AnalysisError, OSError, RuntimeError) as exc:
        print(f"analysis refused: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print("PENT-18 | offline native-messaging audit")
        print(f"Coverage: {report['coverage']['files_considered']} files, {len(report['hosts'])} hosts")
        for finding in report["findings"]:
            print(f"[{finding['severity'].upper()}] {finding['rule']} @ {finding['location']}: {finding['message']}")
        print("Summary: " + ", ".join(f"{n} {level}" for level, n in report["summary"].items()))
        print("Static clues only; no host execution, browser registration or network access.")
    return int(args.fail_on != "never" and any(
        LEVELS[f["severity"]] >= LEVELS[args.fail_on] for f in report["findings"]))


if __name__ == "__main__":
    sys.exit(main())
