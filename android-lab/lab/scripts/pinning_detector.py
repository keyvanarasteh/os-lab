#!/usr/bin/env python3
"""
PENT-11 - SSL / Certificate Pinning Detector & Classifier (Static)

Classifies HOW an Android app pins its TLS certificates *before* any dynamic
analysis is attempted, so the right next step can be picked:

  * network_security_config  <pin-set> in a Network Security Config (res/xml)
  * okhttp                   OkHttp CertificatePinner / "sha256/<b64>" pins
  * trustmanager             custom X509TrustManager / SSLContext / key checks
  * third_party_library      TrustKit, react-native-ssl-pinning, Cordova plugins
  * flutter                  Dart SecurityContext / BoringSSL inside libflutter
  * native                   OpenSSL / BoringSSL / libcurl pinning in .so files
  * embedded_certificate     certificates / keystores bundled in assets or res/raw

It also reports weak validation (trust-all managers, allow-all hostname
verifiers, WebView onReceivedSslError -> proceed) because those mean there is
nothing to bypass at all.

Static only: it reads a local APK or a decompiled source directory and never
touches a network, a device or a running process. Use it on applications you
own or are explicitly authorised to assess (lab scope only).

Usage:
    python3 pinning_detector.py app.apk
    python3 pinning_detector.py ./decompiled-sources -o artifacts/pinning-detect
    python3 pinning_detector.py app.apk --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime

TOOL_NAME = "pinning_detector"
TOOL_VERSION = "1.0.0"
TASK_ID = "PENT-11"

MAX_FILE_BYTES = 128 * 1024 * 1024      # skip anything larger (zip-bomb guard)
MAX_TOTAL_FILES = 50_000                # aggregate work limits
MAX_TOTAL_BYTES = 1024 * 1024 * 1024    # total (decompressed) bytes scanned
MAX_SKIPPED_RECORDED = 200
_ZIP_READ_ERRORS = (
    zipfile.BadZipFile, RuntimeError, OSError, EOFError, NotImplementedError, zlib.error, lzma.LZMAError,
)
REPORT_NAMES = ("pinning-report.json", "pinning-report.md")
POINTER_NAME = "pinning-report.latest"
MAX_EVIDENCE_PER_RULE = 3               # evidence snippets kept per rule
ANDROID_NS = "http://schemas.android.com/apk/res/android"

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp3", ".mp4", ".ogg", ".wav",
    ".ttf", ".otf", ".woff", ".woff2", ".arsc", ".ttc",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "META-INF", ".runs"}
TEXT_EXTENSIONS = {
    ".java", ".kt", ".smali", ".xml", ".json", ".js", ".txt", ".gradle", ".properties",
    ".html", ".yaml", ".yml", ".md", ".cfg", ".conf", ".dart", ".ts",
}
CERT_EXTENSIONS = {".crt", ".cer", ".pem", ".der", ".bks", ".jks", ".p12", ".pfx", ".keystore", ".truststore"}

WEIGHT_STRONG, WEIGHT_MEDIUM, WEIGHT_WEAK = 3, 2, 1

METHOD_LABELS = {
    "network_security_config": "Network Security Config <pin-set>",
    "okhttp": "OkHttp CertificatePinner",
    "trustmanager": "Custom TrustManager / key check",
    "third_party_library": "Third-party pinning library",
    "flutter": "Flutter / Dart (BoringSSL)",
    "native": "Native (.so) TLS verification",
    "embedded_certificate": "Embedded certificate / keystore",
}

# What to look at in the lab once the method is known (existing lab assets only).
NEXT_STEP = {
    "network_security_config": "Static: scripts/apk_patcher.py injects a permissive Network Security Config. "
                               "Dynamic: hooks/ssl-pinning-bypass.js.",
    "okhttp": "Dynamic: hooks/ssl-pinning-bypass.js (OkHttp3 CertificatePinner hook) under the lab WF2.",
    "trustmanager": "Dynamic: hooks/ssl-pinning-bypass.js (TrustManager / HostnameVerifier replacement). "
                    "Read the custom checkServerTrusted first - it may pin a key, not a CA.",
    "third_party_library": "Dynamic: hooks/ssl-pinning-bypass.js, then library-specific hooks "
                           "(TrustKit, RN ssl-pinning, Cordova plugin) if the generic path is not enough.",
    "flutter": "Dynamic: hooks/flutter-ssl-bypass.js. Java-level hooks do not see Flutter TLS.",
    "native": "No generic Java hook applies. Locate the verify callback in the .so (static RE) "
              "before choosing a native hook.",
    "embedded_certificate": "Inspect the bundled certificate/keystore and find which code loads it; "
                            "the loader tells you which of the other methods is in use.",
}


# ---------------------------------------------------------------------------
# Rule table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    id: str
    method: str                 # key of METHOD_LABELS, or "weakness"
    weight: int
    description: str
    patterns: tuple             # every pattern must match in the SAME file
    kinds: tuple = ("source", "dex")  # source (smali/java/kt) | dex | native | any (every file)
    lib_ok: bool = False        # may fire inside well-known third-party library paths


def _b(*pats: str) -> tuple:
    return tuple(re.compile(p.encode("utf-8")) for p in pats)


PIN_B64 = r"[A-Za-z0-9+/]{43}="          # SHA-256 digest, base64
PIN_B64_SHA1 = r"[A-Za-z0-9+/]{27}="     # SHA-1 digest, base64

RULES: tuple = (
    # -- OkHttp ----------------------------------------------------------
    Rule("okhttp.pin_string", "okhttp", WEIGHT_STRONG,
         "Hard-coded OkHttp pin literal (sha256/<base64>)",
         _b(r"sha256/" + PIN_B64 + r"|sha1/" + PIN_B64_SHA1), ("any",), True),
    Rule("okhttp.builder_call", "okhttp", WEIGHT_STRONG,
         "CertificatePinner.Builder.add(...) / .certificatePinner(...) call site",
         _b(r"CertificatePinner\$Builder;->add\(|CertificatePinner\.Builder\(\)|\.certificatePinner\(|CertificatePinner\.Builder\b[\s\S]{0,200}\.add\("),
         ("source",)),
    Rule("okhttp.class_present", "okhttp", WEIGHT_WEAK,
         "OkHttp CertificatePinner class present (library bundled; not proof of use)",
         _b(r"okhttp3[/.]CertificatePinner|com[/.]squareup[/.]okhttp[/.]CertificatePinner")),

    # -- Custom TrustManager / key checks --------------------------------
    Rule("trustmanager.key_compare", "trustmanager", WEIGHT_STRONG,
         "checkServerTrusted combined with public-key / digest comparison (key pinning in code)",
         _b(r"checkServerTrusted", r"getPublicKey|getEncoded|MessageDigest|SubjectPublicKeyInfo"),
         ("source",)),
    Rule("trustmanager.custom_manager", "trustmanager", WEIGHT_WEAK,
         "Class implementing X509TrustManager that also builds an SSLContext (no pin comparison seen)",
         _b(r"X509TrustManager", r"checkServerTrusted", r"SSLContext"), ("source",)),
    Rule("trustmanager.factory_keystore", "trustmanager", WEIGHT_WEAK,
         "TrustManagerFactory + KeyStore referenced (app-supplied trust store?)",
         _b(r"TrustManagerFactory", r"KeyStore")),
    Rule("trustmanager.socket_factory", "trustmanager", WEIGHT_WEAK,
         "Custom SSLSocketFactory installed on a connection/client",
         _b(r"setSSLSocketFactory|setDefaultSSLSocketFactory|sslSocketFactory\(")),
    Rule("trustmanager.api_present", "trustmanager", WEIGHT_WEAK,
         "X509TrustManager / checkServerTrusted referenced",
         _b(r"checkServerTrusted")),

    # -- Third-party libraries -------------------------------------------
    Rule("lib.trustkit_init", "third_party_library", WEIGHT_STRONG,
         "TrustKit initialised (pins from NSC or config)",
         _b(r"TrustKit;->initialize|TrustKit\.initialize|initializeWithNetworkSecurityConfiguration")),
    Rule("lib.trustkit_present", "third_party_library", WEIGHT_WEAK,
         "TrustKit library present",
         _b(r"com[/.]datatheorem[/.]android[/.]trustkit")),
    Rule("lib.rn_ssl_pinning", "third_party_library", WEIGHT_WEAK,
         "react-native-ssl-pinning module present (no call-site evidence)",
         _b(r"react-native-ssl-pinning|RNSslPinning|RNSslPinningPackage"), ("any",)),
    Rule("lib.rn_ssl_pinning_config", "third_party_library", WEIGHT_MEDIUM,
         "react-native-ssl-pinning used with an sslPinning option (call-site evidence)",
         _b(r"react-native-ssl-pinning|RNSslPinning", r"sslPinning\s*:"), ("any",)),
    Rule("lib.cordova_plugin", "third_party_library", WEIGHT_WEAK,
         "Cordova certificate-pinning plugin present (no call-site evidence)",
         _b(r"sslCertificateChecker|cordova-plugin-advanced-http|CordovaHttpPlugin|sslPinning"), ("any",)),
    Rule("lib.appmattus", "third_party_library", WEIGHT_WEAK,
         "Certificate-transparency / pinning library (appmattus)",
         _b(r"com[/.]appmattus[/.]certificatetransparency")),

    # -- Flutter ----------------------------------------------------------
    Rule("flutter.security_context", "flutter", WEIGHT_MEDIUM,
         "Dart SecurityContext with custom trusted certificates",
         _b(r"setTrustedCertificatesBytes|setTrustedCertificates"), ("any",)),
    Rule("flutter.bad_cert_callback", "flutter", WEIGHT_WEAK,
         "Dart badCertificateCallback referenced (may accept or reject certs)",
         _b(r"badCertificateCallback"), ("any",)),
    Rule("flutter.pin_package", "flutter", WEIGHT_MEDIUM,
         "Dart pinning package (http_certificate_pinning / ssl_pinning_plugin)",
         _b(r"http_certificate_pinning|ssl_pinning_plugin|HttpCertificatePinning"), ("any",)),

    # -- Native ------------------------------------------------------------
    Rule("native.curl_pin", "native", WEIGHT_STRONG,
         "libcurl public-key pin (CURLOPT_PINNEDPUBLICKEY / sha256// literal)",
         _b(r"CURLOPT_PINNEDPUBLICKEY|pinnedpublickey|sha256//" + PIN_B64), ("native", "any")),
    Rule("native.peer_cert_check", "native", WEIGHT_MEDIUM,
         "OpenSSL/BoringSSL peer-certificate retrieval used for manual comparison",
         _b(r"SSL_get(?:1)?_peer_certificate|SSL_get_peer_cert_chain", r"X509_get_pubkey|X509_digest|X509_pubkey_digest|i2d_X509"),
         ("native",)),
    Rule("native.verify_callback", "native", WEIGHT_WEAK,
         "Verify callback installed (SSL_CTX_set_verify / set_custom_verify); may be ordinary CA validation",
         _b(r"SSL_CTX_set_verify|SSL_set_verify|SSL_CTX_set_cert_verify_callback|SSL_set_custom_verify|SSL_CTX_set_custom_verify"),
         ("native",)),
    Rule("native.x509_verify", "native", WEIGHT_WEAK,
         "OpenSSL X509 verification primitives referenced",
         _b(r"X509_verify_cert|X509_check_host|SSL_CTX_load_verify_locations|X509_STORE_add_cert"), ("native",)),
    Rule("native.pinning_word", "native", WEIGHT_WEAK,
         "Native library mentions certificate pinning",
         _b(r"(?i)cert(?:ificate)?[_ -]?pin(?:ning|ned)?|ssl[_ -]?pinning"), ("native",)),

    # -- Weak validation (nothing to bypass) -------------------------------
    Rule("weak.allow_all_hostname", "weakness", WEIGHT_STRONG,
         "Allow-all / no-op HostnameVerifier",
         _b(r"ALLOW_ALL_HOSTNAME_VERIFIER|AllowAllHostnameVerifier|NoopHostnameVerifier")),
    Rule("weak.trust_all", "weakness", WEIGHT_STRONG,
         "Trust-all TrustManager by name (TrustAll* / Insecure* / Unsafe*)",
         _b(r"(?i)trust[_-]?all(?:cert|manager|trust)\w*|Insecure(?:Trust|X509)\w*|UnsafeTrust\w*|AcceptAllCert\w*")),
    Rule("weak.webview_proceed", "weakness", WEIGHT_MEDIUM,
         "WebView onReceivedSslError that proceeds past TLS errors",
         _b(r"onReceivedSslError", r"SslErrorHandler;->proceed|handler\.proceed\("), ("source",)),
)


# ---------------------------------------------------------------------------
# Binary XML (AXML) decoder - lets us read the manifest and res/xml/*.xml
# straight out of an APK without apktool.
# ---------------------------------------------------------------------------

_RES_XML_TYPE = 0x0003
_RES_STRING_POOL = 0x0001
_RES_START_ELEMENT = 0x0102
_RES_END_ELEMENT = 0x0103
_RES_TEXT = 0x0104
_TYPE_REFERENCE, _TYPE_STRING, _TYPE_INT_DEC, _TYPE_INT_HEX, _TYPE_BOOL = 0x01, 0x03, 0x10, 0x11, 0x12


def _read_pool_string(data: bytes, base: int, utf8: bool) -> str:
    if utf8:
        n = data[base]
        o = base + 1
        if n & 0x80:
            n = ((n & 0x7F) << 8) | data[o]
            o += 1
        blen = data[o]
        o += 1
        if blen & 0x80:
            blen = ((blen & 0x7F) << 8) | data[o]
            o += 1
        return data[o:o + blen].decode("utf-8", "replace")
    (n,) = struct.unpack_from("<H", data, base)
    o = base + 2
    if n & 0x8000:
        (lo,) = struct.unpack_from("<H", data, o)
        n = ((n & 0x7FFF) << 16) | lo
        o += 2
    return data[o:o + n * 2].decode("utf-16-le", "replace")


def _parse_string_pool(data: bytes, pos: int) -> list:
    count, _styles, flags, strings_start = struct.unpack_from("<IIII", data, pos + 8)
    (header_size,) = struct.unpack_from("<H", data, pos + 2)
    utf8 = bool(flags & 0x100)
    out = []
    offsets_at = pos + header_size
    (chunk_size,) = struct.unpack_from("<I", data, pos + 4)
    # the offset table must fit inside the chunk (and the file): never trust `count`
    if count > (chunk_size - header_size) // 4 or offsets_at + 4 * count > len(data):
        raise ValueError("string pool count exceeds chunk bounds")
    for i in range(count):
        (off,) = struct.unpack_from("<I", data, offsets_at + 4 * i)
        try:
            out.append(_read_pool_string(data, pos + strings_start + off, utf8))
        except (IndexError, struct.error) as exc:
            raise ValueError("string pool offset out of bounds") from exc
    return out


def decode_axml(data: bytes):
    """Decode Android binary XML into an ElementTree element (None if not AXML)."""
    if len(data) < 16 or struct.unpack_from("<H", data, 0)[0] != _RES_XML_TYPE:
        return None
    strings: list = []

    def s(idx: int) -> str:
        return strings[idx] if 0 <= idx < len(strings) else ""

    root = None
    stack: list = []
    pos = 8
    try:
        while pos + 8 <= len(data):
            ctype, _hsize, csize = struct.unpack_from("<HHI", data, pos)
            if csize < 8 or pos + csize > len(data):
                break
            if ctype == _RES_STRING_POOL:
                strings = _parse_string_pool(data, pos)
            elif ctype == _RES_START_ELEMENT:
                _ns, name = struct.unpack_from("<II", data, pos + 16)
                attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, pos + 24)
                elem = ET.Element(s(name))
                base = pos + 16 + attr_start
                for i in range(attr_count):
                    o = base + i * (attr_size or 20)
                    a_ns, a_name, a_raw = struct.unpack_from("<III", data, o)
                    _sz, _res0, dtype, ddata = struct.unpack_from("<HBBI", data, o + 12)
                    if a_raw != 0xFFFFFFFF:
                        value = s(a_raw)
                    elif dtype == _TYPE_BOOL:
                        value = "true" if ddata else "false"
                    elif dtype == _TYPE_STRING:
                        value = s(ddata)
                    elif dtype == _TYPE_REFERENCE:
                        value = "@0x%08x" % ddata
                    elif dtype in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                        value = str(struct.unpack("<i", struct.pack("<I", ddata))[0])
                    else:
                        value = str(ddata)
                    key = ("android:" if s(a_ns) == ANDROID_NS else "") + s(a_name)
                    elem.set(key, value)
                if stack:
                    stack[-1].append(elem)
                else:
                    root = elem
                stack.append(elem)
            elif ctype == _RES_END_ELEMENT:
                if stack:
                    stack.pop()
            elif ctype == _RES_TEXT and stack:
                (idx,) = struct.unpack_from("<I", data, pos + 16)
                text = s(idx).strip()
                if text:
                    stack[-1].text = (stack[-1].text or "") + text
            pos += csize
    except (struct.error, IndexError, ValueError):
        return root
    return root


def parse_xml_bytes(data: bytes):
    """Binary AXML or plain-text XML -> Element; None when it is neither."""
    root = decode_axml(data)
    if root is not None:
        return root
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if not head.startswith(b"<") or b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


# ---------------------------------------------------------------------------
# Network Security Config + manifest analysis
# ---------------------------------------------------------------------------

def _tf(value):
    if value is None:
        return None
    return str(value).strip().lower() == "true"


def analyze_nsc(root, today: date | None = None) -> dict:
    """Summarise a <network-security-config> element tree."""
    today = today or date.today()
    configs = []
    warnings = []

    for dc in root.iter("domain-config"):
        domains = [{"name": (d.text or "").strip(),
                    "include_subdomains": _tf(d.get("includeSubdomains"))}
                   for d in dc.findall("domain")]
        pin_set = dc.find("pin-set")
        pins, expiration, expired = [], None, False
        if pin_set is not None:
            expiration = pin_set.get("expiration")
            for p in pin_set.findall("pin"):
                pins.append({"digest": p.get("digest", "SHA-256"), "value": (p.text or "").strip()})
            if expiration:
                try:
                    expired = datetime.strptime(expiration.strip(), "%Y-%m-%d").date() < today
                except ValueError:
                    pass
            names = ", ".join(d["name"] for d in domains) or "?"
            if len(pins) == 1:
                warnings.append(f"{names}: only one pin - no backup pin (lock-out risk)")
            if expired:
                warnings.append(f"{names}: pin-set expired on {expiration} - Android stops enforcing it")
        anchors = [c.get("src", "") for ta in dc.findall("trust-anchors") for c in ta.findall("certificates")]
        configs.append({
            "domains": domains,
            "pins": pins,
            "pin_set_expiration": expiration,
            "pin_set_expired": expired,
            "trust_anchors": anchors,
            "cleartext_permitted": _tf(dc.get("cleartextTrafficPermitted")),
        })

    base = root.find("base-config")
    base_info = None
    if base is not None:
        base_anchors = [c.get("src", "") for ta in base.findall("trust-anchors") for c in ta.findall("certificates")]
        base_info = {"trust_anchors": base_anchors, "cleartext_permitted": _tf(base.get("cleartextTrafficPermitted"))}
        if "user" in base_anchors:
            warnings.append("base-config trusts user-installed CAs (interception-friendly)")
        if base_info["cleartext_permitted"]:
            warnings.append("base-config permits cleartext traffic")

    debug = root.find("debug-overrides")
    debug_info = None
    if debug is not None:
        d_anchors = [c.get("src", "") for ta in debug.findall("trust-anchors") for c in ta.findall("certificates")]
        debug_info = {"trust_anchors": d_anchors}
        warnings.append("debug-overrides present: extra trust anchors apply to debuggable builds only")

    total_pins = sum(len(c["pins"]) for c in configs)
    active = any(c["pins"] and not c["pin_set_expired"] for c in configs)
    return {
        "domain_configs": configs,
        "base_config": base_info,
        "debug_overrides": debug_info,
        "pin_count": total_pins,
        "pinning_active": active,
        "warnings": warnings,
    }


def analyze_manifest(root) -> dict:
    info = {"package": root.get("package"), "network_security_config_ref": None,
            "uses_cleartext_traffic": None, "debuggable": None,
            "min_sdk": None, "target_sdk": None}
    app = root.find("application")
    if app is not None:
        info["network_security_config_ref"] = app.get("android:networkSecurityConfig") or app.get("networkSecurityConfig")
        info["uses_cleartext_traffic"] = _tf(app.get("android:usesCleartextTraffic") or app.get("usesCleartextTraffic"))
        info["debuggable"] = _tf(app.get("android:debuggable") or app.get("debuggable"))
    sdk = root.find("uses-sdk")
    if sdk is not None:
        info["min_sdk"] = sdk.get("android:minSdkVersion") or sdk.get("minSdkVersion")
        info["target_sdk"] = sdk.get("android:targetSdkVersion") or sdk.get("targetSdkVersion")
    return info


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    file: str
    where: str          # "line 12" or "offset 0x1f40"
    snippet: str

    def to_dict(self) -> dict:
        return {"file": self.file, "where": self.where, "snippet": self.snippet}


@dataclass
class ScanState:
    hits: dict = field(default_factory=dict)       # rule id -> list[Evidence]
    files_scanned: int = 0
    entries_seen: int = 0
    nsc_files: list = field(default_factory=list)  # list of {"paths": [...], "analysis": dict}
    manifest: dict | None = None
    frameworks: set = field(default_factory=set)
    native_libs: list = field(default_factory=list)
    cert_files: list = field(default_factory=list)
    nsc_seen: dict = field(default_factory=dict)      # content hash -> entry in nsc_files
    skipped: list = field(default_factory=list)     # up to MAX_SKIPPED_RECORDED (path, reason)
    skipped_count: int = 0
    total_bytes: int = 0
    truncated: bool = False


def _record_skip(state: ScanState, path: str, reason: str) -> None:
    state.skipped_count += 1
    if len(state.skipped) < MAX_SKIPPED_RECORDED:
        state.skipped.append((path, reason))


def _file_kind(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    if ext == ".so":
        return "native"
    if ext == ".dex":
        return "dex"
    if ext in (".smali", ".java", ".kt"):
        return "source"
    return "other"


LIBRARY_PATH = re.compile(
    r"(^|/)(okhttp3|okhttp|okio|kotlin|kotlinx|androidx|android/support|retrofit2|"
    r"org/conscrypt|org/bouncycastle|org/apache|com/google/(android|gson|common)|"
    r"com/squareup|io/reactivex|com/bumptech)/")


def _is_texty(path: str, data: bytes) -> bool:
    ext = os.path.splitext(path.lower())[1]
    if ext in TEXT_EXTENSIONS:
        return True
    return b"\x00" not in data[:1024]


def _snippet(data: bytes, start: int, end: int, texty: bool) -> tuple:
    if texty:
        line_no = data.count(b"\n", 0, start) + 1
        ls = data.rfind(b"\n", 0, start) + 1
        le = data.find(b"\n", end)
        le = len(data) if le == -1 else le
        text = data[ls:le].decode("utf-8", "replace").strip()
        return f"line {line_no}", text[:160]
    text = data[start:end].decode("latin-1", "replace")
    text = "".join(ch if 32 <= ord(ch) < 127 else "." for ch in text)
    return f"offset 0x{start:x}", text[:160]


FRAMEWORK_MARKERS = (
    (re.compile(r"(^|/)libflutter\.so$"), "flutter"),
    (re.compile(r"(^|/)libapp\.so$"), "flutter"),
    (re.compile(r"(^|/)libreactnativejni\.so$|index\.android\.bundle$"), "react-native"),
    (re.compile(r"(^|/)libil2cpp\.so$|libunity\.so$"), "unity"),
    (re.compile(r"(^|/)libmonosgen-2\.0\.so$|assemblies/.*\.dll$"), "xamarin"),
    (re.compile(r"(^|/)cordova\.js$|assets/www/"), "cordova"),
    (re.compile(r"(^|/)libcurl\.so$"), "libcurl"),
    (re.compile(r"(^|/)lib(ssl|crypto)(\.\d+)*\.so$|libboringssl\.so$|libconscrypt_jni\.so$"), "bundled-tls"),
)


def scan_blob(state: ScanState, path: str, data: bytes) -> None:
    """Scan one file's bytes against every rule."""
    state.files_scanned += 1
    norm = path.replace("\\", "/")
    low = norm.lower()
    ext = os.path.splitext(low)[1]

    for rx, name in FRAMEWORK_MARKERS:
        if rx.search(low):
            state.frameworks.add(name)
    if ext == ".so":
        state.native_libs.append(norm)

    base = os.path.basename(low)
    if low == "androidmanifest.xml" or base == "androidmanifest.xml":
        root = parse_xml_bytes(data)
        if root is not None and root.tag == "manifest" and state.manifest is None:
            state.manifest = analyze_manifest(root)
        return

    if ext == ".xml":
        root = parse_xml_bytes(data)
        if root is not None and root.tag == "network-security-config":
            digest = hashlib.sha256(data).hexdigest()
            if digest in state.nsc_seen:      # identical copies share one scored entry, preserve all paths
                state.nsc_seen[digest]["paths"].append(norm)
            else:
                entry = {"paths": [norm], "analysis": analyze_nsc(root)}
                state.nsc_seen[digest] = entry
                state.nsc_files.append(entry)
            return
        if root is not None and ext == ".xml" and low.startswith("res/"):
            # compiled resource XML that is not an NSC: nothing else to learn
            return

    if ext in CERT_EXTENSIONS and "meta-inf" not in low:
        state.cert_files.append(norm)

    kind = _file_kind(norm)
    texty = _is_texty(norm, data)
    in_library = kind == "source" and bool(LIBRARY_PATH.search(re.sub(r"^(smali[^/]*|src|sources)/", "", low)))
    for rule in RULES:
        if kind not in rule.kinds and "any" not in rule.kinds:
            continue
        if in_library and not rule.lib_ok and rule.weight > WEIGHT_WEAK:
            continue
        first = None
        ok = True
        for pat in rule.patterns:
            m = pat.search(data)
            if m is None:
                ok = False
                break
            if first is None:
                first = m
        if not ok:
            continue
        bucket = state.hits.setdefault(rule.id, [])
        if len(bucket) >= MAX_EVIDENCE_PER_RULE:
            continue
        where, snip = _snippet(data, first.start(), first.end(), texty)
        bucket.append(Evidence(norm, where, snip))


def _budget_exceeded(state: ScanState, path: str) -> bool:
    if state.entries_seen >= MAX_TOTAL_FILES or state.total_bytes >= MAX_TOTAL_BYTES:
        state.truncated = True
        _record_skip(state, path, "aggregate scan limit reached")
        return True
    state.entries_seen += 1
    return False


def scan_apk(state: ScanState, apk_path: str) -> None:
    with zipfile.ZipFile(apk_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if os.path.splitext(name.lower())[1] in SKIP_EXTENSIONS or name.startswith("META-INF/"):
                continue
            if _budget_exceeded(state, name):
                break
            if info.file_size > MAX_FILE_BYTES:
                _record_skip(state, name, "file larger than per-file limit")
                continue
            allowance = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - state.total_bytes)
            try:
                with zf.open(info) as fh:
                    # bound the real decompressed size, not the declared one
                    data = fh.read(allowance + 1)
            except _ZIP_READ_ERRORS as exc:
                _record_skip(state, name, f"unreadable: {exc.__class__.__name__}")
                continue
            if len(data) > MAX_FILE_BYTES:
                _record_skip(state, name, "decompressed size over limit")
                continue
            if len(data) > allowance:
                state.truncated = True
                _record_skip(state, name, "aggregate scan limit reached")
                break
            state.total_bytes += len(data)
            scan_blob(state, name, data)


def scan_dir(state: ScanState, root_dir: str, exclude: tuple = ()) -> None:
    excluded = {os.path.normcase(os.path.abspath(x)) for x in exclude}

    def _on_error(err):
        _record_skip(state, str(getattr(err, "filename", root_dir)), f"inaccessible: {err.__class__.__name__}")

    for root, dirs, files in os.walk(root_dir, onerror=_on_error):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and os.path.normcase(os.path.abspath(os.path.join(root, d))) not in excluded]
        for fn in files:
            if os.path.splitext(fn.lower())[1] in SKIP_EXTENSIONS:
                continue
            full = os.path.join(root, fn)
            if os.path.normcase(os.path.abspath(full)) in excluded:
                continue
            if fn in REPORT_NAMES or fn == POINTER_NAME:      # never re-scan our own previous reports or pointer
                continue
            rel = os.path.relpath(full, root_dir)
            if _budget_exceeded(state, rel):
                return
            try:
                size = os.path.getsize(full)
                if size > MAX_FILE_BYTES:
                    _record_skip(state, rel, "file larger than per-file limit")
                    continue
                allowance = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - state.total_bytes)
                if size > allowance:
                    state.truncated = True
                    _record_skip(state, rel, "aggregate scan limit reached")
                    return
                with open(full, "rb") as fh:
                    data = fh.read(allowance + 1)
                if len(data) > MAX_FILE_BYTES:
                    _record_skip(state, rel, "file larger than per-file limit")
                    continue
                if len(data) > allowance:
                    state.truncated = True
                    _record_skip(state, rel, "aggregate scan limit reached")
                    return
                if len(data) != size:
                    _record_skip(state, rel, "file changed while scanning")
                    continue
            except OSError as exc:
                _record_skip(state, rel, f"unreadable: {exc.__class__.__name__}")
                continue
            state.total_bytes += len(data)
            scan_blob(state, rel, data)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _confidence(score: int, strongest: int) -> str:
    if strongest <= WEIGHT_WEAK:      # many weak hints never add up to real evidence
        return "low"
    if strongest >= WEIGHT_STRONG or score >= 4:
        return "high"
    if score >= WEIGHT_MEDIUM:
        return "medium"
    return "low"


_XML_RES_PATH = re.compile(
    r"^(?:(?:[^/]+/)?src/[^/]+/)?res/xml(?:-[a-zA-Z0-9_+.-]+)?/([^/]+)\.xml$"
)


def _nsc_referenced(manifest, path: str):
    """True when manifest @xml/<name> matches a res/xml* resource path, False on mismatch/non-res path, None when unknown."""
    norm = path.replace("\\", "/").lstrip("./")
    m = _XML_RES_PATH.match(norm)
    if m is None:
        return False
    stem = m.group(1)
    if manifest is None:
        return None
    ref = manifest.get("network_security_config_ref")
    if not ref:
        return False
    if ref.startswith("@xml/"):
        return stem == ref[len("@xml/"):]
    return None     # compiled resource id (@0x...): cannot be mapped to a file name here


def _resolve_nsc_entry(manifest, entry) -> tuple:
    """Resolve a deduplicated NSC entry (or legacy tuple) against the manifest reference."""
    if isinstance(entry, tuple):
        paths, nsc = [entry[0]], entry[1]
    else:
        paths, nsc = entry["paths"], entry["analysis"]
    best_path, best_ref = paths[0], _nsc_referenced(manifest, paths[0])
    for p in paths[1:]:
        ref = _nsc_referenced(manifest, p)
        if ref is True or (ref is None and best_ref is False):
            best_path, best_ref = p, ref
            if best_ref is True:
                break
    return best_path, nsc, best_ref


def classify(state: ScanState) -> dict:
    methods: dict = {}
    weaknesses: list = []
    rule_by_id = {r.id: r for r in RULES}

    for rid, ev in state.hits.items():
        rule = rule_by_id[rid]
        entry = {"rule": rid, "weight": rule.weight, "description": rule.description,
                 "evidence": [e.to_dict() for e in ev]}
        if rule.method == "weakness":
            weaknesses.append(entry)
            continue
        m = methods.setdefault(rule.method, {"score": 0, "strongest": 0, "signals": []})
        m["score"] += rule.weight
        m["strongest"] = max(m["strongest"], rule.weight)
        m["signals"].append(entry)

    # Network Security Config: parsed structurally, so it outranks regex hints when confirmed referenced.
    resolved_nsc = []
    for entry in state.nsc_files:
        path, nsc, referenced = _resolve_nsc_entry(state.manifest, entry)
        resolved_nsc.append((path, nsc))
        if nsc["pin_count"] == 0:
            continue
        m = methods.setdefault("network_security_config", {"score": 0, "strongest": 0, "signals": []})
        if not nsc["pinning_active"] or referenced is False:
            weight = WEIGHT_WEAK
        elif referenced is True:
            weight = WEIGHT_STRONG
        else:
            weight = WEIGHT_MEDIUM
        m["score"] += weight
        m["strongest"] = max(m["strongest"], weight)
        suffix = "" if nsc["pinning_active"] else " (all pin-sets expired)"
        if referenced is False:
            suffix += " (not referenced by the manifest)"
        elif referenced is None and nsc["pinning_active"]:
            suffix += " (manifest reference unverified)"
        m["signals"].append({
            "rule": "nsc.pin_set", "weight": weight,
            "description": f"{nsc['pin_count']} pin(s) in {len(nsc['domain_configs'])} domain-config(s){suffix}",
            "evidence": [{"file": path, "where": "pin-set", "snippet": ", ".join(
                d["name"] for c in nsc["domain_configs"] if c["pins"] for d in c["domains"])[:160]}],
        })
        if referenced is False:
            ref = (state.manifest or {}).get("network_security_config_ref")
            nsc["warnings"].append(
                "manifest has no android:networkSecurityConfig - this file may be unused" if not ref
                else f"manifest references {ref}, not this file - pins here are probably not enforced")
        elif referenced is None:
            nsc["warnings"].append(
                "manifest reference could not be verified (missing manifest or compiled resource ID)")

    if state.cert_files:
        methods["embedded_certificate"] = {
            "score": WEIGHT_WEAK, "strongest": WEIGHT_WEAK,
            "signals": [{"rule": "cert.bundled", "weight": WEIGHT_WEAK,
                         "description": f"{len(state.cert_files)} certificate/keystore file(s) bundled "
                                        "(no evidence yet that TLS validation uses them)",
                         "evidence": [{"file": f, "where": "file", "snippet": ""} for f in state.cert_files[:5]]}],
        }

    # Framework hints strengthen the matching method but never create pinning on their own.
    # ...and only when the method already has independent (>= medium) evidence.
    if "flutter" in state.frameworks and methods.get("flutter", {}).get("strongest", 0) >= WEIGHT_MEDIUM:
        methods["flutter"]["score"] += WEIGHT_WEAK
    if "react-native" in state.frameworks and \
            methods.get("third_party_library", {}).get("strongest", 0) >= WEIGHT_MEDIUM:
        methods["third_party_library"]["score"] += WEIGHT_WEAK

    ranked = []
    for name, m in methods.items():
        ranked.append({
            "method": name,
            "label": METHOD_LABELS[name],
            "confidence": _confidence(m["score"], m["strongest"]),
            "score": m["score"],
            "signals": sorted(m["signals"], key=lambda s: -s["weight"]),
            "next_step": NEXT_STEP[name],
        })
    order = {"high": 0, "medium": 1, "low": 2}
    ranked.sort(key=lambda r: (order[r["confidence"]], -r["score"]))

    strong_weak = any(w["weight"] >= WEIGHT_STRONG for w in weaknesses)
    top = ranked[0] if ranked else None
    if top and top["confidence"] == "high":
        status = "pinned"
    elif top and top["confidence"] == "medium":
        status = "likely_pinned"
    elif top:
        status = "possible"
    else:
        status = "none_detected"
    complete = state.skipped_count == 0
    if not complete and status == "none_detected":
        status = "incomplete_scan"

    return {
        "scan_complete": complete,
        "skipped": [{"path": pth, "reason": why} for pth, why in state.skipped],
        "skipped_count": state.skipped_count,
        "skipped_truncated": state.skipped_count > len(state.skipped),
        "scan_truncated": state.truncated,
        "pinning_status": status,
        "primary_method": top["method"] if top and top["confidence"] != "low" else None,
        "methods": ranked,
        "weak_validation": weaknesses,
        "weak_validation_note": ("Trust-all / allow-all validation found: TLS may be interceptable "
                                 "without any bypass." if strong_weak else None),
        "_resolved_nsc": resolved_nsc,
    }


def analyze(target: str, exclude: tuple = ()) -> dict:
    """Run the full static analysis on an APK or decompiled directory."""
    state = ScanState()
    if os.path.isdir(target):
        kind = "directory"
        scan_dir(state, target, exclude)
    else:
        kind = "apk"
        scan_apk(state, target)

    result = classify(state)
    resolved_nsc = result.pop("_resolved_nsc")
    return {
        "task": TASK_ID,
        "tool": f"{TOOL_NAME} {TOOL_VERSION}",
        "target": os.path.abspath(target),
        "target_type": kind,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scope_notice": "Static analysis of a local file only. Use on apps you own or are authorised to assess.",
        "files_scanned": state.files_scanned,
        "manifest": state.manifest,
        "frameworks": sorted(state.frameworks),
        "native_libs": sorted(state.native_libs),
        "network_security_config": [{"file": p, **a} for p, a in resolved_nsc],
        **result,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _md_escape(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for ch, repl in (("\\", "\\\\"), ("`", "\\`"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|")):
        text = text.replace(ch, repl)
    return text


def _md_code(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    max_run = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * (max_run + 1)
    if text.startswith("`") or text.endswith("`") or (text.startswith(" ") and text.endswith(" ") and text.strip()):
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def render_markdown(r: dict) -> str:
    out = [f"# SSL / Certificate Pinning Report ({r['task']})", "",
           f"- **Target:** {_md_code(r['target'])} ({_md_escape(r['target_type'])})",
           f"- **Timestamp:** {_md_escape(r['timestamp'])}",
           f"- **Files scanned:** {r['files_scanned']}",
           f"- **Status:** **{_md_escape(r['pinning_status'])}**",
           f"- **Primary method:** {_md_escape(METHOD_LABELS.get(r['primary_method'], 'n/a'))}"]
    if r["manifest"]:
        mf = r["manifest"]
        out.append(f"- **Package:** {_md_code(mf.get('package'))} "
                   f"(minSdk {_md_escape(mf.get('min_sdk'))}, targetSdk {_md_escape(mf.get('target_sdk'))})")
    if r["frameworks"]:
        out.append(f"- **Frameworks:** {', '.join(_md_escape(fw) for fw in r['frameworks'])}")
    if not r.get("scan_complete", True):
        skipped_total = r.get("skipped_count", len(r.get("skipped", [])))
        out.append(f"- **Coverage:** INCOMPLETE - {skipped_total} input(s) skipped"
                   + (" (aggregate limit hit)" if r.get("scan_truncated") else ""))
    out += ["", f"> {r['scope_notice']}", "", "## Classification", ""]
    if not r["methods"]:
        out.append("No pinning indicators found.")
    else:
        out += ["| Method | Confidence | Score | Next step |", "|---|---|---|---|"]
        for m in r["methods"]:
            out.append(f"| {_md_escape(m['label'])} | {_md_escape(m['confidence'])} | {m['score']} | {_md_escape(m['next_step'])} |")
        for m in r["methods"]:
            out += ["", f"### {_md_escape(m['label'])}", ""]
            for s in m["signals"]:
                out.append(f"- ({s['weight']}) {_md_escape(s['description'])}")
                for e in s["evidence"]:
                    out.append(f"  - {_md_code(e['file'])} {_md_escape(e['where'])}: {_md_code(e['snippet'])}")
    for nsc in r["network_security_config"]:
        out += ["", f"## Network Security Config: {_md_code(nsc['file'])}", ""]
        for c in nsc["domain_configs"]:
            doms = ", ".join(_md_escape(d["name"]) for d in c["domains"]) or "?"
            exp = f", expires {_md_escape(c['pin_set_expiration'])}" if c["pin_set_expiration"] else ""
            out.append(f"- **{doms}** - {len(c['pins'])} pin(s){exp}")
        for w in nsc["warnings"]:
            out.append(f"- WARNING: {_md_escape(w)}")
    if r.get("skipped"):
        out += ["", "## Skipped input (coverage incomplete)", ""]
        out += [f"- {_md_code(s['path'])}: {_md_escape(s['reason'])}" for s in r["skipped"]]
        skipped_total = r.get("skipped_count", len(r["skipped"]))
        if r.get("skipped_truncated") and skipped_total > len(r["skipped"]):
            out.append(f"- ... and {skipped_total - len(r['skipped'])} more skipped input(s) omitted.")
    if r["weak_validation"]:
        out += ["", "## Weak validation", ""]
        if r["weak_validation_note"]:
            out.append(_md_escape(r["weak_validation_note"]))
        for w in r["weak_validation"]:
            out.append(f"- {_md_escape(w['description'])}")
            for e in w["evidence"]:
                out.append(f"  - {_md_code(e['file'])} {_md_escape(e['where'])}: {_md_code(e['snippet'])}")
    return "\n".join(out) + "\n"


def _publish_report_pair(out_dir: str, report: dict) -> tuple:
    """Serialize writers, publish a versioned report pair, and atomically switch the latest pointer."""
    os.makedirs(out_dir, exist_ok=True)
    runs_dir = os.path.join(out_dir, ".runs")
    os.makedirs(runs_dir, exist_ok=True)
    pointer_path = os.path.join(out_dir, POINTER_NAME)
    json_path = os.path.join(out_dir, REPORT_NAMES[0])
    md_path = os.path.join(out_dir, REPORT_NAMES[1])
    lock_path = os.path.join(out_dir, ".pinning.lock")
    lock_fd = None
    deadline = time.monotonic() + 5.0
    while True:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for report lock: {lock_path}")
            time.sleep(0.05)

    ver_dir = None
    tmp = None
    committed = False
    try:
        prev_ptr_bytes = None
        prev_seq = 0
        if os.path.exists(pointer_path):
            with open(pointer_path, "rb") as fh:
                prev_ptr_bytes = fh.read()
            try:
                prev_seq = int(json.loads(prev_ptr_bytes.decode("utf-8")).get("seq", 0))
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                prev_seq = 0

        ver_name = f"scan-{prev_seq + 1:06d}-{os.getpid()}"
        ver_dir = os.path.join(runs_dir, ver_name)
        os.makedirs(ver_dir, exist_ok=True)
        vj = os.path.join(ver_dir, REPORT_NAMES[0])
        vm = os.path.join(ver_dir, REPORT_NAMES[1])
        md_text = render_markdown(report)
        with open(vj, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        with open(vm, "w", encoding="utf-8") as fh:
            fh.write(md_text)

        tmp = tempfile.mkdtemp(prefix=".pinning-", dir=out_dir)
        tj = os.path.join(tmp, REPORT_NAMES[0])
        tm = os.path.join(tmp, REPORT_NAMES[1])
        tp = os.path.join(tmp, POINTER_NAME)
        shutil.copy2(vj, tj)
        shutil.copy2(vm, tm)
        ptr_payload = {"seq": prev_seq + 1, "run": ver_name,
                       "json": os.path.join(".runs", ver_name, REPORT_NAMES[0]),
                       "md": os.path.join(".runs", ver_name, REPORT_NAMES[1])}
        with open(tp, "w", encoding="utf-8") as fh:
            json.dump(ptr_payload, fh, indent=2)

        backup_json = os.path.join(tmp, "prev.json")
        backup_md = os.path.join(tmp, "prev.md")
        had_json = os.path.exists(json_path)
        had_md = os.path.exists(md_path)
        if had_json:
            shutil.copy2(json_path, backup_json)
        if had_md:
            shutil.copy2(md_path, backup_md)

        try:
            os.replace(tj, json_path)
            os.replace(tm, md_path)
            os.replace(tp, pointer_path)
            committed = True
        except BaseException:
            if prev_ptr_bytes is not None:
                restore_p = os.path.join(tmp, "restore.latest")
                with open(restore_p, "wb") as fh:
                    fh.write(prev_ptr_bytes)
                shutil.move(restore_p, pointer_path)
            elif os.path.exists(pointer_path):
                os.remove(pointer_path)
            if had_json and os.path.exists(backup_json):
                shutil.move(backup_json, json_path)
            elif os.path.exists(json_path):
                os.remove(json_path)
            if had_md and os.path.exists(backup_md):
                shutil.move(backup_md, md_path)
            elif os.path.exists(md_path):
                os.remove(md_path)
            raise
    finally:
        if not committed and ver_dir and os.path.isdir(ver_dir):
            shutil.rmtree(ver_dir, ignore_errors=True)
        if tmp and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        if lock_fd is not None:
            os.close(lock_fd)
            if os.path.exists(lock_path):
                os.remove(lock_path)
    return json_path, md_path


def read_report_pair(out_dir: str) -> tuple:
    """Read the committed JSON + Markdown pair atomically via the single latest pointer."""
    pointer_path = os.path.join(out_dir, POINTER_NAME)
    if os.path.exists(pointer_path):
        with open(pointer_path, encoding="utf-8") as fh:
            ptr = json.load(fh)
        jp = os.path.join(out_dir, ptr["json"])
        mp = os.path.join(out_dir, ptr["md"])
    else:
        jp = os.path.join(out_dir, REPORT_NAMES[0])
        mp = os.path.join(out_dir, REPORT_NAMES[1])
    with open(jp, encoding="utf-8") as fh:
        rep = json.load(fh)
    with open(mp, encoding="utf-8") as fh:
        md = fh.read()
    return rep, md


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    p = argparse.ArgumentParser(
        description="PENT-11 static SSL/certificate-pinning detector & classifier (lab scope only)")
    p.add_argument("target", help="Path to an APK or a decompiled source directory")
    p.add_argument("-o", "--out", help="Directory for JSON + Markdown reports "
                                       "(default: artifacts/pinning-detect)")
    p.add_argument("--json", action="store_true", help="Print the JSON report to stdout and write no files")
    args = p.parse_args(argv)

    if not os.path.exists(args.target):
        print(f"Error: target does not exist: {args.target}", file=sys.stderr)
        return 1
    if os.path.isfile(args.target) and not zipfile.is_zipfile(args.target):
        print(f"Error: not a valid APK/zip archive: {args.target}", file=sys.stderr)
        return 1

    out_dir = args.out or os.path.join("artifacts", "pinning-detect")
    report = analyze(args.target, exclude=() if args.json else (out_dir,))

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("=== SSL / Certificate Pinning Detector (static) ===")
    print(f"Status        : {report['pinning_status']}")
    print(f"Primary method: {METHOD_LABELS.get(report['primary_method'], 'n/a')}")
    for m in report["methods"]:
        print(f"  - {m['label']}: {m['confidence']} (score {m['score']})")
    if report["weak_validation_note"]:
        print(f"WARNING: {report['weak_validation_note']}")

    json_path, md_path = _publish_report_pair(out_dir, report)
    print(f"\nReports saved to:\n  JSON : {json_path}\n  MD   : {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
