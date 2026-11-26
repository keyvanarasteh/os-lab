"""Firewall Lab MCP: search, compare and recommend over the seeded firewalls."""
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "console"))

import firewall_catalog  # noqa: E402
import mcp_firewall  # noqa: E402
import mcp_firewall_server  # noqa: E402
import mcp_server  # noqa: E402

NEW_TOOLS = ("firewall_devices", "firewall_device", "firewall_products", "firewall_compare", "firewall_recommend")


@pytest.fixture(autouse=True)
def bundled_content(tmp_path, monkeypatch):
    """Never read a content pack downloaded on this computer."""
    monkeypatch.setenv("OSLAB_CONTENT_DIR", str(tmp_path / "content"))


def rpc(name, args=None, server=mcp_server):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    result = reply["result"]
    return result["isError"], json.loads(result["content"][0]["text"])


def ok(name, args=None):
    failed, payload = rpc(name, args)
    assert not failed, payload
    return payload


def product(vendor, model, gbps, price):
    return {"product": model, "vendor": vendor, "throughputGbps": gbps, "priceUsd": price}


def company(slug, role, segment, chosen, alternatives, down=1000):
    return {"slug": slug, "name": slug.title(), "sector": "Test", "branches": [{
        "id": "hq", "name": "HQ", "role": role, "location": "X", "population": {"staff": 10},
        "network": {"cidr": "10.0.0.0/16", "vlans": []},
        "bandwidth": {"downMbps": down, "upMbps": down, "drivers": ["web"]},
        "firewalls": [{"segment": segment, "chosen": chosen, "alternatives": alternatives, "rules": []}]}]}


def catalog(*companies):
    return firewall_catalog.Catalog(list(companies), firewall_catalog.load_rules(REPO_ROOT))


def test_every_seeded_firewall_is_searchable_and_openable():
    with open(os.path.join(REPO_ROOT, "firewall-lab", "catalog.json"), encoding="utf-8") as handle:
        total = len(json.load(handle)["firewalls"])
    seen, offset = [], 0
    while offset is not None:
        page = ok("firewall_devices", {"limit": 40, "offset": offset})
        assert page["total"] == total
        seen += [row["deviceId"] for row in page["devices"]]
        offset = page["nextOffset"]
    assert len(seen) == total == len(set(seen))
    detail = ok("firewall_device", {"deviceId": "acme-academy--istanbul-hq--perimeter"})["device"]
    assert detail["product"] == "FortiGate 100F" and detail["rules"] and len(detail["alternatives"]) == 4
    assert detail["dashboardPath"] == "/firewall/device/?id=acme-academy--istanbul-hq--perimeter"


def test_search_filters_and_sorts():
    rows = ok("firewall_devices", {"vendor": "fortinet", "maxPriceUsd": 5000, "sort": "price", "limit": 100})["devices"]
    assert rows and all(r["vendor"] == "Fortinet" and r["priceUsd"] <= 5000 for r in rows)
    assert [r["priceUsd"] for r in rows] == sorted(r["priceUsd"] for r in rows)
    found = ok("firewall_products", {"query": "mikrotik"})
    assert found["products"] and found["products"][0]["vendor"] == "MikroTik"
    assert found["facets"]["devices"] and "Fortinet" in found["facets"]["vendors"]


def test_vendor_spellings_and_ha_variants_group_into_one_product():
    rules = firewall_catalog.load_rules(REPO_ROOT)
    keys = {firewall_catalog.classify(v, p, rules)["productKey"] for v, p in (
        ("Palo Alto", "Palo Alto PA-440"), ("Palo Alto Networks", "PA-440"), ("Palo Alto Networks", "PA-440 (HA)"))}
    assert keys == {"palo-alto-networks-pa-440"}
    assert firewall_catalog.classify("Fortinet", "FortiWeb 400F", rules)["category"] == "waf"
    assert firewall_catalog.classify("Fortinet", "FortiGate 600F + FortiWeb WAF", rules)["category"] == "firewall"


def test_recommendation_respects_hard_limits_and_explains_itself():
    answer = ok("firewall_recommend", {"linkMbps": 1000, "headroom": 2, "budgetUsd": 10000, "role": "branch"})
    assert answer["requirement"]["requiredThroughputGbps"] == 2
    assert answer["recommendations"] and answer["similarDeployments"] and "datasheets" in answer["provenance"]
    scores = [r["score"] for r in answer["recommendations"]]
    assert scores == sorted(scores, reverse=True)
    for row in answer["recommendations"]:
        assert row["throughputGbps"]["median"] >= 2 and row["price"]["usd"] <= 10000
        assert row["why"] and row["evidence"]


def test_recommendation_prices_ha_pairs_and_reports_nearest_misses():
    data = catalog(
        company("a", "branch", "perimeter", product("V", "Single", 5, 1000),
                [product("V", "Pair (HA)", 5, 1800)]))
    rows = {r["model"]: r for r in data.recommend({"haRequired": True})["recommendations"]}
    assert rows["Single"]["price"] == {"usd": 2000, "basis": "estimated-two-units"}
    assert rows["Pair"]["price"] == {"usd": 1800, "basis": "ha-pair-quote"}
    assert any("two single units" in w for w in rows["Single"]["warnings"])
    none = data.recommend({"requiredThroughputGbps": 50, "budgetUsd": 10})
    assert none["recommendations"] == [] and none["nearestMisses"]["fastestWithinBudget"] is None
    assert none["excluded"] == {"belowThroughput": 2}


def test_unknown_specs_are_left_out_unless_asked_for():
    data = catalog(company("a", "branch", "perimeter", {"product": "Mystery", "vendor": "V"}, []))
    assert data.recommend({"requiredThroughputGbps": 1})["excluded"] == {"unknownThroughput": 1}
    kept = data.recommend({"requiredThroughputGbps": 1, "includeUnknownSpecs": True})["recommendations"]
    assert "No throughput was quoted." in kept[0]["warnings"] and "No price was quoted." in kept[0]["warnings"]


def test_priority_changes_the_winner_and_disagreeing_quotes_use_the_lower():
    cheap = product("V", "Cheap", 2, 500)
    fast = product("V", "Fast", 40, 90000)
    data = catalog(company("a", "branch", "perimeter", cheap, [fast]),
                   company("b", "branch", "perimeter", dict(cheap, throughputGbps=9), [fast]))
    assert data.recommend({"priority": "cost"})["recommendations"][0]["model"] == "Cheap"
    assert data.recommend({"priority": "performance"})["recommendations"][0]["model"] == "Fast"
    assert data.products["v-cheap"]["throughputGbps"]["median"] == 2


def test_compare_returns_reasons_for_and_against():
    answer = ok("firewall_compare", {"productKeys": ["fortinet-fortigate-100f", "palo-alto-networks-pa-440"]})
    assert [p["key"] for p in answer["products"]] == ["fortinet-fortigate-100f", "palo-alto-networks-pa-440"]
    assert answer["products"][0]["evidence"]["chosenIn"]


@pytest.mark.parametrize("name,args", [
    ("firewall_devices", {"limit": 0}),
    ("firewall_devices", {"limit": True}),
    ("firewall_devices", {"sort": "random"}),
    ("firewall_devices", {"path": "/etc"}),
    ("firewall_device", {}),
    ("firewall_device", {"deviceId": "nope"}),
    ("firewall_compare", {"productKeys": []}),
    ("firewall_compare", {"productKeys": ["nope"]}),
    ("firewall_compare", {"productKeys": "fortinet-fortigate-100f"}),
    ("firewall_recommend", {"linkMbps": 0}),
    ("firewall_recommend", {"linkMbps": float("inf")}),
    ("firewall_recommend", {"headroom": 100}),
    ("firewall_recommend", {"linkMbps": 1e308}),
    ("firewall_recommend", {"vendors": [1]}),
    ("firewall_guides", {"name": "../README.md"}),
])
def test_bad_requests_are_refused(name, args):
    failed, payload = rpc(name, args)
    assert failed and payload["code"] in ("INVALID_ARGS", "FIREWALL_404"), payload


def test_a_guide_can_be_read():
    assert "throughput" in ok("firewall_guides", {"name": "product-selection.md"})["text"]


def test_standalone_server_offers_only_firewall_tools_over_stdio():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/get",
         "params": {"name": "firewall_advisor", "arguments": {"context": "a school"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "firewall_recommend", "arguments": {"linkMbps": 500, "limit": 2}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "macos_apps", "arguments": {}}},
    ]
    done = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "console", "mcp_firewall_server.py")],
        input="not json\n[]\n" + "".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0 and done.stderr == "", done.stderr
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5]
    assert replies[0]["result"]["serverInfo"]["name"] == "os-lab-firewall"
    names = {tool["name"] for tool in replies[1]["result"]["tools"]}
    assert names == mcp_firewall.NAMES and set(NEW_TOOLS) <= names
    assert all(tool["annotations"]["readOnlyHint"] for tool in replies[1]["result"]["tools"])
    assert "a school" in replies[2]["result"]["messages"][0]["content"]["text"]
    assert replies[3]["result"]["isError"] is False
    assert replies[4]["result"]["isError"] is True
    assert mcp_firewall_server.handle({"jsonrpc": "2.0", "method": "tools/list"}) is None
