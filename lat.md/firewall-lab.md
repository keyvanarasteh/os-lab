# Firewall Lab

Firewall Lab is a content lab: student company network designs under `firewall-lab/companies/`, browsed in the dashboard and queried by AI agents. Nothing boots and nothing touches a live firewall.

Contributors add a company as described in [[firewall-lab/README.md]];
[[firewall-lab/scripts/validate.py]] checks it (the slugs `device` and `devices` are
taken by dashboard pages). [[tooling#Firewall rule renderer]] covers the VM prototype
and [[content]] how newer companies reach an installed app.

## Devices and products

A device is one deployed firewall (a branch segment's chosen product); a product groups every quote of one model, chosen or only compared.

[[console/firewall_catalog.py#Catalog]] and [[dashboard/src/firewall/devices.ts#listDevices]]
build the same devices, with ids `company--branch--segment`. Both read the vendor
spellings, model clean-up and WAF rules in `firewall-lab/normalize.json`;
`dashboard/scripts/firewall-devices.test.mjs` fails when they disagree.

Throughput and prices are student-quoted, not vendor datasheets. Pages and tool
results say so.

## Pages

`/firewall/devices/` searches and filters every device; `/firewall/device/?id=` shows one with its alternatives and rule set.

[[dashboard/src/views/firewall-devices-page.tsx]] keeps filters in the address bar.
[[dashboard/src/views/firewall-device-page.tsx]] is a single static page for all ids,
so the committed build does not grow with every company and downloaded content packs
work without prerendering.

## MCP tools

The `firewall_*` tools are read-only. [[console/mcp_server.py]] serves them with every other lab; [[console/mcp_firewall_server.py]] serves them alone.

[[console/mcp_firewall.py]] validates arguments and offers `firewall_devices`,
`firewall_device`, `firewall_products`, `firewall_compare` and `firewall_recommend`
beside status, catalog, company and guides. The `firewall_advisor` prompt and the
firewall skill steer an agent from requirements to a cited shortlist.

## Recommendation

[[console/firewall_catalog.py#Catalog#recommend]] applies hard limits first (category, vendors, throughput, budget), then ranks what is left.

Required throughput is given, or link speed times headroom (1.5). The score weighs
headroom, price, throughput, quotes for the same role and segment, and how often the
product was chosen; `priority` picks the weights. It plans with the lower median
throughput and keeps high-availability pair prices apart from single units. A product
with one quote is scored down. With no result it returns the nearest misses.

Tests: [[android-lab/lab/tests/test_mcp_firewall.py]].
