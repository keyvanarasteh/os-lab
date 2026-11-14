import json

import pytest

from ext_scan.__main__ import main
from ext_scan.manifest import ManifestError, audit_manifest, load_manifest
from ext_scan.patterns import fold_strings, mask_strings, scan_source, strip_comments
from ext_scan.scanner import scan


def rules(src):
    findings, _ = scan_source(src, "t.js")
    return {f.rule for f in findings}


# --- cleaning steps ---------------------------------------------------------

def test_comments_removed_but_lines_kept():
    code = strip_comments("a()\n// eval(x)\n/* fetch(y)\n */ b()")
    assert "eval" not in code and "fetch" not in code
    assert code.count("\n") == 3


def test_comment_markers_inside_strings_are_kept():
    assert strip_comments('u = "http://x/*y*/"') == 'u = "http://x/*y*/"'


def test_fold_strings():
    assert fold_strings("x['ev' + \"al\"]") == 'x["eval"]'
    assert fold_strings("'a' + 'b' + 'c'") == '"abc"'


def test_mask_strings_keeps_length_and_quotes():
    assert mask_strings('f("eval(1)")') == 'f("       ")'


# --- code rules -------------------------------------------------------------

@pytest.mark.parametrize("src, rule", [
    ("eval(x)", "CODE-EVAL"),
    ("window['ev' + 'al'](x)", "CODE-HIDDEN-EVAL"),
    ("self[\"Function\"](s)", "CODE-HIDDEN-EVAL"),
    ("new Function('a', b)", "CODE-FUNCTION"),
    ("setTimeout('alert(1)', 5)", "CODE-STRING-TIMER"),
    ("chrome.scripting.executeScript({target, func})", "CODE-EXECUTE-SCRIPT"),
    ("document.createElement('iframe')", "CODE-IFRAME-INJECT"),
    ("document.createElement(\"script\")", "CODE-SCRIPT-INJECT"),
    ("chrome.cookies.getAll({})", "CODE-COOKIE-READ"),
    ("let c = document.cookie", "CODE-COOKIE-READ"),
    ("fetch(url)", "CODE-NETWORK"),
])
def test_rule_matches(src, rule):
    assert rule in rules(src)


@pytest.mark.parametrize("src", [
    "// eval(x)",                       # comment
    "/* new Function() */",             # block comment
    "const tip = 'never call eval(x)'",  # string
    "obj.evaluate(x)",                  # longer name
    "setTimeout(() => go(), 5)",        # timer with a function, not a string
])
def test_no_false_alarm(src):
    assert rules(src) - {"CODE-NETWORK"} == set()


def test_two_stage_needs_network_and_dynamic_code():
    assert "CODE-TWO-STAGE" in rules("fetch(u).then(r => r.text()).then(t => eval(t))")
    assert "CODE-TWO-STAGE" not in rules("fetch(u)")
    assert "CODE-TWO-STAGE" not in rules("eval(local)")


def test_cookie_exfil_correlation():
    assert "CODE-COOKIE-EXFIL" in rules("chrome.cookies.getAll({}, c => fetch(u, {body: c}))")


def test_line_numbers_point_at_the_call():
    findings, _ = scan_source("// one\nlet a = 1;\n\nself['ev'+'al'](a)", "t.js")
    assert {f.line for f in findings if f.rule == "CODE-HIDDEN-EVAL"} == {4}


def test_endpoints_are_collected_and_folded():
    _, endpoints = scan_source("fetch('http://127.0.0.1:8765' + '/x')", "t.js")
    assert endpoints == ["http://127.0.0.1:8765/x"]


# --- manifest -----------------------------------------------------------------

def test_mv2_host_permissions_inside_permissions():
    found = {f.rule for f in audit_manifest({"manifest_version": 2,
                                             "permissions": ["<all_urls>", "cookies"]})}
    assert {"PERM-ALL-SITES", "PERM-COOKIES"} <= found


def test_content_script_on_all_sites_counts():
    m = {"content_scripts": [{"matches": ["*://*/*"], "js": ["a.js"]}]}
    assert "PERM-ALL-SITES" in {f.rule for f in audit_manifest(m)}


@pytest.mark.parametrize("csp", [
    "script-src 'self' 'unsafe-eval'; object-src 'self'",                 # MV2 string
    {"extension_pages": "script-src 'self' 'unsafe-eval'"},               # MV3 object
])
def test_csp_unsafe_eval(csp):
    assert "CSP-UNSAFE-EVAL" in {f.rule for f in audit_manifest({"content_security_policy": csp})}


def test_missing_or_broken_manifest(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_manifest_with_bom(make_ext):
    folder = make_ext({"permissions": ["cookies"]})
    path = folder / "manifest.json"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_manifest(folder)["permissions"] == ["cookies"]


# --- score and lab samples --------------------------------------------------

@pytest.mark.parametrize("name, score, grade", [
    ("clean-notes", 0, "low"),
    ("over-privileged", 40, "medium"),
    ("two-stage-loader", 100, "critical"),
])
def test_lab_samples(lab, name, score, grade):
    risk = scan(lab / name)["risk"]
    assert (risk["score"], risk["grade"]) == (score, grade)


def test_two_stage_sample_findings(lab):
    result = scan(lab / "two-stage-loader")
    found = {(f["rule"], f["file"], f["line"]) for f in result["findings"]}
    assert ("CODE-HIDDEN-EVAL", "sw.js", 14) in found
    assert ("CODE-TWO-STAGE", "sw.js", 14) in found
    assert ("CODE-IFRAME-INJECT", "inject.js", 3) in found
    assert all("127.0.0.1" in url for url in result["endpoints"])


def test_permissions_alone_cannot_reach_critical(make_ext):
    everything = ["debugger", "nativeMessaging", "cookies", "proxy", "scripting", "history"]
    risk = scan(make_ext({"permissions": everything, "host_permissions": ["<all_urls>"]}))["risk"]
    assert risk["capability"] == 40 and risk["grade"] == "medium"


def test_repeated_rule_counts_once(make_ext):
    one = scan(make_ext({}, {"a.js": "eval(a)"}))["risk"]["behaviour"]
    many = scan(make_ext({}, {"a.js": "eval(a)\n" * 10}))["risk"]["behaviour"]
    assert one == many == 18


# --- command line -------------------------------------------------------------

def test_cli_exit_codes(lab, tmp_path, capsys):
    assert main(["scan", str(lab / "clean-notes"), "--fail-on", "high"]) == 0
    assert main(["scan", str(lab / "two-stage-loader"), "--fail-on", "high"]) == 3
    assert main(["scan", str(tmp_path)]) == 2


def test_cli_json(lab, capsys):
    main(["scan", str(lab / "over-privileged"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["risk"]["grade"] == "medium"
