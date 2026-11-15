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


# --- review fixes (Sourcery findings on #207) ---------------------------------

@pytest.mark.parametrize("src, rule", [
    ("browser.cookies.getAll({})", "CODE-COOKIE-READ"),          # Firefox namespace
    ("let c = document['cookie']", "CODE-COOKIE-READ"),          # bracket notation
    ("const ws = new WebSocket(u)", "CODE-NETWORK"),
    ("xhr.open('GET', u)", "CODE-NETWORK"),
    ("chrome.userScripts.register([s])", "CODE-USER-SCRIPTS"),
    ("const s = `${eval(x)}`", "CODE-EVAL"),                     # code inside a template runs
])
def test_review_rule_matches(src, rule):
    assert rule in rules(src)


@pytest.mark.parametrize("src", [
    "const f = self['eval']",                    # read, not called
    "log(\"example: self['eval'](x)\")",          # example inside a string
    "const t = 'createElement(\"iframe\")'",
    "const x = new XMLHttpRequest()",            # built but never opened
    "const s = `text with eval( inside`",       # template text, not code
])
def test_review_no_false_alarm(src):
    assert rules(src) - {"CODE-NETWORK"} == set()
    if "XMLHttpRequest" in src:
        assert "CODE-NETWORK" not in rules(src)


def test_websocket_endpoint_is_collected():
    _, endpoints = scan_source("new WebSocket('wss://127.0.0.1:9/x')", "t.js")
    assert endpoints == ["wss://127.0.0.1:9/x"]


def test_fetch_into_script_element_is_two_stage():
    src = "fetch(u).then(r => r.text()).then(t => { const s = document.createElement('script'); s.textContent = t; })"
    assert "CODE-TWO-STAGE" in rules(src)


def test_line_numbers_in_a_long_file():
    src = "x = 1;\n" * 5000 + "eval(a)\n"
    findings, _ = scan_source(src, "t.js")
    assert [f.line for f in findings if f.rule == "CODE-EVAL"] == [5001]


def test_module_scripts_are_scanned(make_ext):
    found = {f["rule"] for f in scan(make_ext({}, {"m.mjs": "eval(x)"}))["findings"]}
    assert "CODE-EVAL" in found


def test_large_file_is_reported_not_silently_skipped(make_ext, monkeypatch):
    import ext_scan.patterns as patterns
    monkeypatch.setattr(patterns, "MAX_FILE", 10)
    result = scan(make_ext({}, {"big.js": "// " + "a" * 100}))
    assert "SCAN-SKIPPED-LARGE" in {f["rule"] for f in result["findings"]}
    assert result["risk"]["score"] > 0


@pytest.mark.parametrize("manifest", [
    [],                                          # root is not an object
    {"permissions": "cookies"},                  # string instead of list
    {"content_scripts": [{"matches": 7}]},
    {"content_security_policy": 5},
])
def test_wrong_field_types_are_input_errors(tmp_path, manifest):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 2


def test_duplicate_permissions_count_once():
    once = audit_manifest({"permissions": ["tabs"]})
    twice = audit_manifest({"permissions": ["tabs", "tabs", "tabs"]})
    assert [f.points for f in once] == [f.points for f in twice] == [5]


def test_more_permissions_and_hosts_are_scored():
    found = {f.rule for f in audit_manifest({
        "permissions": ["userScripts", "webNavigation", "declarativeNetRequestWithHostAccess"],
        "host_permissions": ["file:///*", "https://example.test/*"],
        "optional_permissions": ["cookies"],
        "optional_host_permissions": ["<all_urls>"],
    })}
    assert {"PERM-USERSCRIPTS", "PERM-WEBNAVIGATION", "PERM-DECLARATIVENETREQUESTWITHHOSTACCESS",
            "PERM-FILE-ACCESS", "PERM-SITE-ACCESS", "PERM-OPTIONAL-COOKIES",
            "PERM-OPTIONAL-ALL-SITES"} <= found


def test_optional_counts_half_and_not_twice():
    only_optional = audit_manifest({"optional_permissions": ["cookies"]})
    assert [f.points for f in only_optional] == [5]
    both = audit_manifest({"permissions": ["cookies"], "optional_permissions": ["cookies"]})
    assert [f.rule for f in both] == ["PERM-COOKIES"]


@pytest.mark.parametrize("csp, remote", [
    ("script-src 'self'; connect-src https://api.test", False),   # not a script source
    ("script-src 'self' https://cdn.test", True),
    ("default-src 'self' https://cdn.test", True),                 # fallback for scripts
    ({"extension_pages": "script-src 'self'; img-src https://img.test"}, False),
])
def test_csp_remote_only_counts_script_sources(csp, remote):
    found = {f.rule for f in audit_manifest({"content_security_policy": csp})}
    assert ("CSP-REMOTE-SCRIPT" in found) is remote


def test_terminal_control_characters_are_escaped(make_ext, capsys):
    folder = make_ext({"name": "evil\x1b[2J\x1b[31mname\u202e"})
    main(["scan", str(folder)])
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\u202e" not in out
    assert "evil\\u001b[2J" in out
