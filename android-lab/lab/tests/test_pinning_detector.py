"""PENT-11: static SSL/certificate-pinning detector & classifier.

All fixtures are synthetic and built in-memory; nothing here touches a network or a device.
"""
import json
import os
import struct
import zipfile
import zlib
from datetime import date

import pytest

from scripts import pinning_detector as pd

PIN = "sha256/" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/AbCdE" + "="  # 43 b64 chars + '='
assert len(PIN) == len("sha256/") + 44


# --------------------------------------------------------------------------
# Minimal Android binary-XML (AXML) encoder, used only to build fixtures
# --------------------------------------------------------------------------

def build_axml(tree):
    """tree = (tag, {attr: str|bool}, [children], text). 'android:x' attrs get the android namespace."""
    strings = []

    def sid(text):
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    sid(pd.ANDROID_NS)
    body = bytearray()

    def emit(node):
        tag, attrs, kids, text = node
        name = sid(tag)
        packed = b""
        for key, val in attrs.items():
            ns = 0xFFFFFFFF
            if key.startswith("android:"):
                ns, key = sid(pd.ANDROID_NS), key[len("android:"):]
            if isinstance(val, bool):
                raw, dtype, data = 0xFFFFFFFF, 0x12, 0xFFFFFFFF if val else 0
            else:
                raw = sid(val)
                dtype, data = 0x03, raw
            packed += struct.pack("<IIIHBBI", ns, sid(key), raw, 8, 0, dtype, data)
        size = 36 + len(packed)
        body.extend(struct.pack("<HHIII", 0x0102, 16, size, 1, 0xFFFFFFFF))
        body.extend(struct.pack("<IIHHHHHH", 0xFFFFFFFF, name, 0x14, 0x14, len(attrs), 0, 0, 0))
        body.extend(packed)
        if text:
            body.extend(struct.pack("<HHIII", 0x0104, 16, 28, 1, 0xFFFFFFFF))
            body.extend(struct.pack("<IHBBI", sid(text), 8, 0, 3, 0))
        for kid in kids:
            emit(kid)
        body.extend(struct.pack("<HHIIIII", 0x0103, 16, 24, 1, 0xFFFFFFFF, 0xFFFFFFFF, name))

    emit(tree)

    pool_strings = b""
    offsets = []
    for s in strings:
        offsets.append(len(pool_strings))
        enc = s.encode("utf-16-le")
        pool_strings += struct.pack("<H", len(s)) + enc + b"\x00\x00"
    while len(pool_strings) % 4:
        pool_strings += b"\x00"
    strings_start = 28 + 4 * len(strings)
    pool = struct.pack("<HHIIIIII", 0x0001, 28, strings_start + len(pool_strings),
                       len(strings), 0, 0, strings_start, 0)
    pool += b"".join(struct.pack("<I", o) for o in offsets) + pool_strings
    total = 8 + len(pool) + len(body)
    return struct.pack("<HHI", 0x0003, 8, total) + pool + bytes(body)


def nsc_tree(pins=("AAAA", "BBBB"), expiration=None, domain="api.lab.test"):
    pin_set_attrs = {"expiration": expiration} if expiration else {}
    pin_kids = [("pin", {"digest": "SHA-256"}, [], p) for p in pins]
    return ("network-security-config", {}, [
        ("domain-config", {}, [
            ("domain", {"includeSubdomains": True}, [], domain),
            ("pin-set", pin_set_attrs, pin_kids, None),
        ], None),
    ], None)


def manifest_tree(nsc_ref=True):
    app_attrs = {"android:networkSecurityConfig": "@xml/network_security_config"} if nsc_ref else {}
    return ("manifest", {"package": "lab.test.app"}, [
        ("uses-sdk", {"android:minSdkVersion": "24", "android:targetSdkVersion": "34"}, [], None),
        ("application", app_attrs, [], None),
    ], None)


def make_apk(tmp_path, files, name="t.apk"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for fname, data in files.items():
            zf.writestr(fname, data)
    return str(path)


def dex(*strings):
    """Fake dex: header magic + NUL-separated strings (what the detector sees in a real dex)."""
    return b"dex\n035\x00" + b"\x00".join(s.encode() for s in strings) + b"\x00"


def methods_of(report):
    return {m["method"]: m for m in report["methods"]}


# --------------------------------------------------------------------------
# AXML / NSC
# --------------------------------------------------------------------------

def test_axml_roundtrip_decodes_tags_attrs_and_text():
    root = pd.decode_axml(build_axml(nsc_tree()))
    assert root.tag == "network-security-config"
    dc = root.find("domain-config")
    assert dc.find("domain").text == "api.lab.test"
    assert dc.find("domain").get("includeSubdomains") == "true"
    assert [p.text for p in dc.find("pin-set").findall("pin")] == ["AAAA", "BBBB"]


def test_decode_axml_rejects_garbage():
    assert pd.decode_axml(b"not axml at all, definitely") is None
    assert pd.decode_axml(b"") is None


def test_analyze_manifest_reads_package_sdk_and_nsc_ref():
    info = pd.analyze_manifest(pd.decode_axml(build_axml(manifest_tree())))
    assert info["package"] == "lab.test.app"
    assert (info["min_sdk"], info["target_sdk"]) == ("24", "34")
    assert info["network_security_config_ref"] == "@xml/network_security_config"


def test_nsc_pinning_classified_high(tmp_path):
    apk = make_apk(tmp_path, {
        "AndroidManifest.xml": build_axml(manifest_tree()),
        "res/xml/network_security_config.xml": build_axml(nsc_tree()),
        "classes.dex": dex("Lcom/example/Main;"),
    })
    report = pd.analyze(apk)
    assert report["pinning_status"] == "pinned"
    assert report["primary_method"] == "network_security_config"
    assert methods_of(report)["network_security_config"]["confidence"] == "high"
    nsc = report["network_security_config"][0]
    assert nsc["pin_count"] == 2 and nsc["pinning_active"]
    assert report["manifest"]["package"] == "lab.test.app"


def test_nsc_expired_pin_set_is_downgraded():
    root = pd.decode_axml(build_axml(nsc_tree(expiration="2020-01-01")))
    nsc = pd.analyze_nsc(root, today=date(2026, 1, 1))
    assert nsc["pin_count"] == 2
    assert not nsc["pinning_active"]
    assert any("expired" in w for w in nsc["warnings"])


def test_nsc_single_pin_warns_about_missing_backup():
    nsc = pd.analyze_nsc(pd.decode_axml(build_axml(nsc_tree(pins=("ONLY",)))))
    assert any("backup" in w for w in nsc["warnings"])


def test_nsc_without_manifest_reference_is_flagged(tmp_path):
    apk = make_apk(tmp_path, {
        "AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=False)),
        "res/xml/network_security_config.xml": build_axml(nsc_tree()),
    })
    nsc = pd.analyze(apk)["network_security_config"][0]
    assert any("unused" in w for w in nsc["warnings"])


def test_plain_text_nsc_in_decompiled_directory(tmp_path):
    xml = tmp_path / "res" / "xml"
    xml.mkdir(parents=True)
    (xml / "network_security_config.xml").write_text(
        '<network-security-config><domain-config><domain>a.lab.test</domain>'
        '<pin-set><pin digest="SHA-256">XYZ=</pin></pin-set></domain-config>'
        '<debug-overrides><trust-anchors><certificates src="user"/></trust-anchors></debug-overrides>'
        '</network-security-config>', encoding="utf-8")
    report = pd.analyze(str(tmp_path))
    assert report["target_type"] == "directory"
    assert report["primary_method"] == "network_security_config"
    assert any("debug-overrides" in w for w in report["network_security_config"][0]["warnings"])


def test_nsc_without_pins_is_not_pinning(tmp_path):
    tree = ("network-security-config", {}, [
        ("base-config", {"cleartextTrafficPermitted": True}, [], None)], None)
    apk = make_apk(tmp_path, {"res/xml/nsc.xml": build_axml(tree)})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "none_detected"
    assert any("cleartext" in w for w in report["network_security_config"][0]["warnings"])


def test_xml_with_entities_is_refused():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><network-security-config>&a;</network-security-config>'
    assert pd.parse_xml_bytes(evil) is None


# --------------------------------------------------------------------------
# Code-level methods
# --------------------------------------------------------------------------

def test_okhttp_pin_literal_in_dex_is_high(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", PIN, "api.lab.test")})
    report = pd.analyze(apk)
    assert report["primary_method"] == "okhttp"
    assert methods_of(report)["okhttp"]["confidence"] == "high"
    ev = methods_of(report)["okhttp"]["signals"][0]["evidence"][0]
    assert ev["where"].startswith("offset 0x")


def test_okhttp_class_only_is_just_possible(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", "Lokhttp3/OkHttpClient;")})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "possible"
    assert report["primary_method"] is None
    assert methods_of(report)["okhttp"]["confidence"] == "low"


def test_okhttp_builder_call_in_smali_reports_line_number(tmp_path):
    smali = tmp_path / "smali" / "com" / "lab"
    smali.mkdir(parents=True)
    (smali / "Net.smali").write_text(
        ".class public Lcom/lab/Net;\n.method build()V\n"
        "    invoke-virtual {v0, v1, v2}, Lokhttp3/CertificatePinner$Builder;->add(Ljava/lang/String;[Ljava/lang/String;)Lokhttp3/CertificatePinner$Builder;\n"
        ".end method\n", encoding="utf-8")
    report = pd.analyze(str(tmp_path))
    assert report["primary_method"] == "okhttp"
    ev = methods_of(report)["okhttp"]["signals"][0]["evidence"][0]
    assert ev["where"] == "line 3"


def test_okhttp_library_smali_does_not_count_as_app_pinning(tmp_path):
    lib = tmp_path / "smali" / "okhttp3"
    lib.mkdir(parents=True)
    (lib / "CertificatePinner.smali").write_text(
        ".class public Lokhttp3/CertificatePinner;\n"
        "invoke-virtual {p0}, Lokhttp3/CertificatePinner$Builder;->add(Ljava/lang/String;)V\n"
        'const-string v0, "sha256/"\n', encoding="utf-8")
    report = pd.analyze(str(tmp_path))
    assert report["pinning_status"] == "possible"          # class-present only


def test_custom_trustmanager_key_comparison_is_high(tmp_path):
    src = tmp_path / "src" / "com" / "lab"
    src.mkdir(parents=True)
    (src / "PinningTrustManager.java").write_text(
        "class PinningTrustManager implements X509TrustManager {\n"
        "  public void checkServerTrusted(X509Certificate[] chain, String a) {\n"
        "    byte[] enc = chain[0].getPublicKey().getEncoded();\n"
        "    if (!Arrays.equals(MessageDigest.getInstance(\"SHA-256\").digest(enc), PINNED)) throw new CertificateException();\n"
        "  }\n}\n", encoding="utf-8")
    report = pd.analyze(str(tmp_path))
    assert report["primary_method"] == "trustmanager"
    assert methods_of(report)["trustmanager"]["confidence"] == "high"


def test_trustmanager_api_references_alone_are_low(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Ljavax/net/ssl/X509TrustManager;", "checkServerTrusted",
                                                 "MessageDigest", "getEncoded")})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "possible"
    assert methods_of(report)["trustmanager"]["confidence"] == "low"


def test_trustkit_initialisation_detected(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lcom/datatheorem/android/trustkit/TrustKit;",
                                                 "TrustKit;->initializeWithNetworkSecurityConfiguration")})
    report = pd.analyze(apk)
    assert report["primary_method"] == "third_party_library"


def test_react_native_ssl_pinning_package(tmp_path):
    apk = make_apk(tmp_path, {"assets/index.android.bundle": b"import 'react-native-ssl-pinning'; fetch(url,{sslPinning:{}})"})
    report = pd.analyze(apk)
    assert "react-native" in report["frameworks"]
    assert report["primary_method"] == "third_party_library"


# --------------------------------------------------------------------------
# Flutter / native / embedded certs
# --------------------------------------------------------------------------

def test_flutter_security_context(tmp_path):
    apk = make_apk(tmp_path, {
        "lib/arm64-v8a/libflutter.so": b"\x7fELF" + b"\x00" * 16 + b"ssl_crypto_x509_session_verify_cert_chain",
        "lib/arm64-v8a/libapp.so": b"\x7fELF" + b"\x00" * 16 + b"setTrustedCertificatesBytes\x00SecurityContext",
    })
    report = pd.analyze(apk)
    assert "flutter" in report["frameworks"]
    assert report["primary_method"] == "flutter"
    assert "flutter-ssl-bypass.js" in methods_of(report)["flutter"]["next_step"]


def test_flutter_without_pinning_signals_is_not_pinned(tmp_path):
    apk = make_apk(tmp_path, {"lib/arm64-v8a/libflutter.so": b"\x7fELF" + b"\x00" * 64})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "none_detected"
    assert "flutter" in report["frameworks"]


def test_native_curl_pin(tmp_path):
    pin = ("sha256//" + "A" * 43 + "=").encode()
    apk = make_apk(tmp_path, {"lib/x86_64/libnet.so": b"\x7fELF" + b"\x00" * 8 + b"CURLOPT_PINNEDPUBLICKEY\x00" + pin})
    report = pd.analyze(apk)
    assert report["primary_method"] == "native"
    assert "libnet.so" in report["native_libs"][0]


def test_native_verify_primitives_alone_stay_low(tmp_path):
    apk = make_apk(tmp_path, {"lib/x86_64/libssl_user.so": b"\x7fELF\x00X509_verify_cert\x00"})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "possible"
    assert methods_of(report)["native"]["confidence"] == "low"


def test_embedded_certificate_in_assets(tmp_path):
    apk = make_apk(tmp_path, {
        "assets/server.crt": b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
        "META-INF/CERT.RSA": b"signature, must be ignored",
    })
    report = pd.analyze(apk)
    m = methods_of(report)["embedded_certificate"]
    assert m["confidence"] == "low"  # bundled cert alone is not pinning evidence
    assert report["pinning_status"] == "possible"
    assert all("META-INF" not in e["file"] for s in m["signals"] for e in s["evidence"])


# --------------------------------------------------------------------------
# Weak validation / negatives
# --------------------------------------------------------------------------

def test_trust_all_and_allow_all_reported_as_weak_validation(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lorg/apache/http/conn/ssl/SSLSocketFactory;->ALLOW_ALL_HOSTNAME_VERIFIER",
                                                 "Lcom/lab/TrustAllCerts;")})
    report = pd.analyze(apk)
    assert report["weak_validation_note"]
    ids = {w["rule"] for w in report["weak_validation"]}
    assert {"weak.allow_all_hostname", "weak.trust_all"} <= ids
    assert report["pinning_status"] == "none_detected"      # weakness is not pinning


def test_webview_proceed_in_source(tmp_path):
    (tmp_path / "Web.java").write_text(
        "public void onReceivedSslError(WebView v, SslErrorHandler handler, SslError e) { handler.proceed(); }",
        encoding="utf-8")
    ids = {w["rule"] for w in pd.analyze(str(tmp_path))["weak_validation"]}
    assert "weak.webview_proceed" in ids


def test_clean_app_has_no_findings(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lcom/example/Main;", "onCreate"),
                              "res/layout/a.xml": b"<LinearLayout/>"})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "none_detected"
    assert report["methods"] == [] and report["weak_validation"] == []


def test_multiple_methods_ranked_by_confidence(tmp_path):
    apk = make_apk(tmp_path, {
        "AndroidManifest.xml": build_axml(manifest_tree()),
        "res/xml/network_security_config.xml": build_axml(nsc_tree()),
        "classes.dex": dex("Lokhttp3/CertificatePinner;"),
    })
    ranked = [m["method"] for m in pd.analyze(apk)["methods"]]
    assert ranked[0] == "network_security_config"
    assert "okhttp" in ranked


# --------------------------------------------------------------------------
# Reports & CLI
# --------------------------------------------------------------------------

def test_markdown_report_lists_method_and_evidence(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", PIN)})
    md = pd.render_markdown(pd.analyze(apk))
    assert "PENT-11" in md and "OkHttp CertificatePinner" in md and "sha256/" in md


def test_cli_writes_reports(tmp_path, capsys):
    apk = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", PIN)})
    out = tmp_path / "out"
    assert pd.main([apk, "-o", str(out)]) == 0
    data = json.loads((out / "pinning-report.json").read_text(encoding="utf-8"))
    assert data["task"] == "PENT-11" and data["primary_method"] == "okhttp"
    assert (out / "pinning-report.md").exists()
    assert "okhttp" in capsys.readouterr().out.lower()


def test_cli_json_mode_prints_and_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    apk = make_apk(tmp_path, {"classes.dex": dex("x")})
    assert pd.main([apk, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pinning_status"] == "none_detected"
    assert not (tmp_path / "artifacts").exists()


def test_cli_rejects_missing_and_non_zip_targets(tmp_path):
    assert pd.main([str(tmp_path / "nope.apk")]) == 1
    bogus = tmp_path / "bogus.apk"
    bogus.write_bytes(b"this is not a zip")
    assert pd.main([str(bogus)]) == 1


def test_oversized_entries_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "MAX_FILE_BYTES", 10)
    apk = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", PIN)})
    assert pd.analyze(apk)["files_scanned"] == 0


# --------------------------------------------------------------------------
# Review follow-ups (PR #173 Sourcery findings)
# --------------------------------------------------------------------------

SHA1_PIN = "sha1/" + "AbCdEfGhIjKlMnOpQrStUvWxYz0=" 


def test_okhttp_sha1_pin_literal_detected(tmp_path):
    apk = make_apk(tmp_path, {"classes.dex": dex(SHA1_PIN)})
    assert "okhttp" in methods_of(pd.analyze(apk))


def test_unreferenced_nsc_does_not_report_pinned(tmp_path):
    apk = make_apk(tmp_path, {
        "AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=False)),
        "res/xml/network_security_config.xml": build_axml(nsc_tree()),
    })
    report = pd.analyze(apk)
    assert report["pinning_status"] != "pinned"
    assert methods_of(report)["network_security_config"]["confidence"] == "low"


def test_bundled_rn_and_cordova_modules_stay_low(tmp_path):
    apk = make_apk(tmp_path, {"assets/index.android.bundle": b"require('react-native-ssl-pinning')",
                              "assets/www/cordova.js": b"sslCertificateChecker"})
    report = pd.analyze(apk)
    assert report["pinning_status"] == "possible"
    assert methods_of(report)["third_party_library"]["confidence"] == "low"


def test_flutter_marker_does_not_upgrade_weak_signal(tmp_path):
    apk = make_apk(tmp_path, {"lib/arm64-v8a/libflutter.so": b"x", "assets/app.dart": b"badCertificateCallback"})
    assert methods_of(pd.analyze(apk))["flutter"]["confidence"] == "low"


def test_ordinary_custom_trustmanager_without_pin_is_not_likely_pinned(tmp_path):
    src = b"class T implements X509TrustManager { void checkServerTrusted() {} } SSLContext c;"
    apk = make_apk(tmp_path, {"smali/app/T.smali": src})
    assert pd.analyze(apk)["pinning_status"] == "possible"


def test_duplicate_expired_nsc_copies_are_deduplicated(tmp_path):
    files = {"AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=True))}
    for i in range(6):
        files[f"res/xml/copy{i}.xml"] = build_axml(nsc_tree(expiration="2001-01-01"))
    report = pd.analyze(make_apk(tmp_path, files))
    assert len(report["network_security_config"]) == 1
    assert report["pinning_status"] != "pinned"


def test_malformed_string_pool_count_is_rejected_without_blowup():
    good = build_axml(nsc_tree())
    # chunk header at 8: type(2) hsize(2) size(4) count(4) -> claim a huge string count
    bad = good[:16] + struct.pack("<I", 0x7FFFFFFF) + good[20:]
    with pytest.raises(ValueError, match="exceeds chunk bounds"):
        pd._parse_string_pool(bad, 8)
    assert pd.decode_axml(bad) is None


def test_unreadable_entries_mark_scan_incomplete(tmp_path, monkeypatch):
    apk = make_apk(tmp_path, {"a.txt": b"hello"})
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    report = pd.analyze(apk)
    assert report["scan_complete"] is False
    assert report["pinning_status"] == "incomplete_scan"
    assert report["skipped"]


def test_corrupt_apk_decompressor_error_marks_incomplete(tmp_path, monkeypatch):
    apk = make_apk(tmp_path, {"a.txt": b"hello"})
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: (_ for _ in ()).throw(zlib.error("bad stream")))
    report = pd.analyze(apk)
    assert report["scan_complete"] is False
    assert report["pinning_status"] == "incomplete_scan"
    assert "zlib" in report["skipped"][0]["reason"].lower() or "error" in report["skipped"][0]["reason"].lower()


def test_aggregate_file_limit_truncates_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "MAX_TOTAL_FILES", 2)
    apk = make_apk(tmp_path, {f"f{i}.txt": b"x" for i in range(5)})
    report = pd.analyze(apk)
    assert report["scan_truncated"] is True and report["scan_complete"] is False


def test_skipped_entries_respect_budget_and_report_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "MAX_FILE_BYTES", 1)
    monkeypatch.setattr(pd, "MAX_TOTAL_FILES", 4)
    monkeypatch.setattr(pd, "MAX_SKIPPED_RECORDED", 2)
    apk = make_apk(tmp_path, {f"big{i}.txt": b"0123456789" for i in range(10)})
    report = pd.analyze(apk)
    assert report["scan_truncated"] is True
    assert len(report["skipped"]) == 2
    assert report["skipped_count"] == 5
    assert report["skipped_truncated"] is True
    md = pd.render_markdown(report)
    assert "5 input(s) skipped" in md
    assert "3 more skipped input(s) omitted" in md


def test_dir_scan_enforces_aggregate_byte_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "MAX_TOTAL_BYTES", 10)
    (tmp_path / "a.txt").write_bytes(b"12345678")
    (tmp_path / "b.txt").write_bytes(b"12345678")
    report = pd.analyze(str(tmp_path))
    assert report["scan_truncated"] is True
    assert report["scan_complete"] is False
    assert report["pinning_status"] == "incomplete_scan"


def test_nsc_outside_res_xml_not_treated_as_referenced(tmp_path):
    for bad_path in ("assets/network_security_config.xml", "xml/network_security_config.xml",
                     "assets/res/xml/network_security_config.xml"):
        sub = tmp_path / bad_path.replace("/", "_")
        sub.mkdir()
        apk = make_apk(sub, {
            "AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=True)),
            bad_path: build_axml(nsc_tree()),
        })
        report = pd.analyze(apk)
        assert report["pinning_status"] != "pinned", bad_path
        assert methods_of(report)["network_security_config"]["confidence"] == "low", bad_path

    # Resource qualifiers like res/xml-v24/ ARE valid Android xml resource directories
    qual = tmp_path / "qual"
    qual.mkdir()
    apk_ok = make_apk(qual, {
        "AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=True)),
        "res/xml-v24/network_security_config.xml": build_axml(nsc_tree()),
    })
    assert pd.analyze(apk_ok)["pinning_status"] == "pinned"


def test_nsc_without_manifest_does_not_claim_pinned(tmp_path):
    apk = make_apk(tmp_path, {
        "res/xml/network_security_config.xml": build_axml(nsc_tree()),
    })
    report = pd.analyze(apk)
    assert report["pinning_status"] != "pinned"


def test_duplicate_nsc_prefers_referenced_copy_regardless_of_scan_order(tmp_path):
    nsc_bytes = build_axml(nsc_tree())
    apk = make_apk(tmp_path, {
        "assets/unreferenced_copy.xml": nsc_bytes,
        "res/xml/network_security_config.xml": nsc_bytes,
        "AndroidManifest.xml": build_axml(manifest_tree(nsc_ref=True)),
    })
    report = pd.analyze(apk)
    assert report["pinning_status"] == "pinned"
    assert report["network_security_config"][0]["file"] == "res/xml/network_security_config.xml"


def test_markdown_escapes_crafted_paths(tmp_path):
    crafted = "a`<img src=x>`b"
    apk = make_apk(tmp_path, {f"smali/app/{crafted}.smali": b"Lokhttp3/CertificatePinner;\n" + PIN.encode()})
    md = pd.render_markdown(pd.analyze(apk))
    # Dynamic double-backtick fence prevents closing the code span at the inner single backtick
    assert f"``smali/app/{crafted}.smali``" in md


def test_output_dir_inside_target_is_not_rescanned(tmp_path, capsys):
    out = tmp_path / "reports"
    out.mkdir()
    (out / "pinning-report.md").write_text(PIN, encoding="utf-8")
    (tmp_path / "Clean.java").write_text("class Clean {}", encoding="utf-8")
    assert pd.main([str(tmp_path), "-o", str(out)]) == 0
    written = json.loads((out / "pinning-report.json").read_text(encoding="utf-8"))
    assert written["pinning_status"] == "none_detected"

    # --json writes no report files, so files inside -o must still be scanned
    (out / "RealPin.java").write_text(f'String p = "{PIN}";', encoding="utf-8")
    capsys.readouterr()
    assert pd.main([str(tmp_path), "-o", str(out), "--json"]) == 0
    json_out = json.loads(capsys.readouterr().out)
    assert json_out["pinning_status"] == "pinned"


def test_cli_publishes_report_pair_atomically(tmp_path, monkeypatch):
    apk_a = make_apk(tmp_path, {"classes.dex": dex("Lokhttp3/CertificatePinner;", PIN)}, name="a.apk")
    apk_b = make_apk(tmp_path, {"classes.dex": dex("x")}, name="b.apk")
    out = tmp_path / "out"
    assert pd.main([apk_a, "-o", str(out)]) == 0
    orig_json = (out / "pinning-report.json").read_text(encoding="utf-8")
    orig_md = (out / "pinning-report.md").read_text(encoding="utf-8")
    rep_via_ptr, md_via_ptr = pd.read_report_pair(str(out))
    assert rep_via_ptr == json.loads(orig_json) and md_via_ptr == orig_md

    real_replace = os.replace

    def fail_on_md(src, dst):
        if str(dst).endswith("pinning-report.md"):
            raise OSError("simulated failure publishing md")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_on_md)
    with pytest.raises(OSError, match="simulated failure"):
        pd.main([apk_b, "-o", str(out)])

    rep_after, md_after = pd.read_report_pair(str(out))
    assert rep_after == json.loads(orig_json) and md_after == orig_md
    assert (out / "pinning-report.json").read_text(encoding="utf-8") == orig_json
    assert (out / "pinning-report.md").read_text(encoding="utf-8") == orig_md
    assert {"pinning-report.json", "pinning-report.md", "pinning-report.latest"} <= set(os.listdir(out))
