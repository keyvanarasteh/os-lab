"""mitmproxy addon tests — the pure formatter/host helpers, no mitmproxy."""
import mitm_addon as m


def test_format_flow_line_fields():
    line = m.format_flow_line("get", 200, "https://api.securebank.local/v1/login", 1234)
    assert "GET" in line
    assert "200" in line
    assert "1234B" in line
    assert "https://api.securebank.local/v1/login" in line


def test_format_flow_line_defaults():
    line = m.format_flow_line("", "?", "http://x/")
    assert "?" in line
    assert "0B" in line


def test_host_of():
    assert m.host_of("https://api.securebank.local/v1/login") == "api.securebank.local"
    assert m.host_of("http://10.0.2.2:8080/path?x=1") == "10.0.2.2:8080"
    assert m.host_of("api.example.com/thing") == "api.example.com"


def test_addons_list_present():
    assert isinstance(m.addons, list) and m.addons
    assert isinstance(m.addons[0], m.FlowLogger)


def test_main_previews_line(capsys):
    rc = m.main(["POST", "201", "https://api.securebank.local/v1/accounts", "--length", "42"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "POST" in out and "42B" in out
