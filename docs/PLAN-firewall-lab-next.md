# Plan: Firewall Lab after the search pages and MCP advisor

Status: **on hold**, plan only. Checklist: [TODO-firewall-lab-next.md](TODO-firewall-lab-next.md).
Builds on #404 (`/firewall/devices/`, `/firewall/device/`, the `firewall_*` MCP tools).
Current behavior: [`lat.md/firewall-lab.md`](../lat.md/firewall-lab.md).

Task ids use `FWX-` so they do not collide with the `FW-` student roadmap in
[CONTRIBUTING.md](../CONTRIBUTING.md). Effort: **S** about a day or less, **M** a few
days, **L** more than that.

## Where the data stands

Measured on the bundled companies at `64987a933`.

| Measure | Value | What it limits |
|---|--:|---|
| Companies / branches / deployed firewalls | 21 / 89 / 110 | |
| Distinct products (chosen or compared) | 214, from 550 quotes | Only chosen ones have a page |
| Products quoted once | 118 | Ranking rests on one student's number |
| Products with no throughput | 56 | Dropped from sized recommendations |
| Products with no price | 10 | Dropped from budgeted recommendations |
| Products whose quoted throughput differs 2x or more | 27 | Raw and threat-protection figures are mixed |
| Model numbers spelled more than one way | 22 groups, some real variants | Evidence is split between entries |
| Rules | 2013 | Not searchable |
| Deployments quoted below the branch downlink | 4 | Not surfaced next to the device |
| CVE watch entries | 32, in 17 companies | Not visible to the tools |

Two examples of the spread: FortiGate 100F is quoted at 1 to 10 Gbps, and Netgate
6100 appears under three names.

## Phase 0: correctness (do first)

### FWX-01 One data source for every MCP tool (S, bug from #404)

`firewall_devices`, `firewall_device`, `firewall_products`, `firewall_compare` and
`firewall_recommend` read the downloaded content pack when one is installed.
`firewall_status`, `firewall_catalog`, `firewall_company` and `firewall_guides` read
the repository. On a machine with an older pack, status reports 110 firewalls and
search returns 96.

- Read companies and guides through `content.ContentStore` in all nine tools; compute
  counts from the loaded companies; report `dataSource` and `dataVersion` everywhere.
- Done when a test with an installed pack shows the same counts from status, catalog
  and search.

### FWX-02 An old content pack should not hide newer bundled data (M)

An installed pack overrides the bundled files whatever its age, in the dashboard and
in MCP. The pack seen above was dated 2026-11-16.

- Decide how to compare them (the bundle would need to record its own sequence or
  date), then prefer the newer one or say the pack is older and offer **Reset**.
- Done when updating the app never shows fewer companies than the app ships.

### FWX-03 Product identity (S)

- Extend `firewall-lab/normalize.json` with model aliases: Netgate and OPNsense
  hardware names, `pfSense+` / `pfSense Plus`, the six Cloudflare WAF plan labels.
- Keep real variants apart (bundles such as `600F + FortiWeb WAF`, HA pairs).
- Done when the parity test passes and each merged group is listed in the test.

## Phase 1: data people can trust

### FWX-04 Optional spec fields in the company schema (M)

`threatProtectionGbps`, `firewallGbps`, `licenseUsdPerYear`, `units`, `sourceUrl`,
`quotedAt`. All optional, so existing companies stay valid. Recommendations size on
threat-protection throughput when present and say which figure they used. Update the
schema, `validate.py`, the template, both device builders and the pages.

### FWX-05 Verified product sheets (L)

`firewall-lab/products/<productKey>.json`: figures a maintainer read from a vendor
datasheet, with URL and date. Tools and pages show **verified** or **student-quoted**
per figure and prefer verified. Needs the new folder in the content-pack allowlist and
a staleness rule (for example, flag sheets older than a year). Entered by hand; no
scraping.

### FWX-06 Data quality report (S)

A script that lists missing figures, 2x spreads, unmatched spellings and chosen
products below the branch downlink. Print it in the `firewall-lab` workflow summary so
a student sees it on their PR. It warns; it does not fail the build.

## Phase 2: pages

| Id | Page | Notes | Effort |
|---|---|---|:-:|
| FWX-07 | `/firewall/products/` and `/firewall/product/?key=` | All 214 products with spread, price basis, where chosen and why passed over | M |
| FWX-08 | `/firewall/compare/?keys=` | 2 to 5 side by side, shareable URL, "add to compare" on both lists | M |
| FWX-09 | `/firewall/advisor/` | Form for link, budget, role, HA; ranked answers with warnings. Must work on public Pages, so a TypeScript port of `recommend` with a parity test | M |
| FWX-10 | `/firewall/rules/` | Search all rules by port, action, direction, segment; link to the device | M |
| FWX-11 | `/firewall/insights/` | Vendor share, price against throughput, choices by role. Charts need a table fallback | M |
| FWX-12 | Export | CSV and Markdown of a filtered list or shortlist | S |

Every page: 8 locales, filters in the address bar, phone width, entry in
`dashboard/e2e/affected.json`.

## Phase 3: MCP tools

All stay read-only and are served by both servers.

| Id | Tool | What it adds | Effort |
|---|---|---|:-:|
| FWX-13 | `firewall_rules` | Search rules across designs ("who allows 3389, and from where") | S |
| FWX-14 | `firewall_audit` | The company page's gap audit ([`audit.ts`](../dashboard/src/firewall/audit.ts)) for agents. Port with a parity test, or generate findings at build time and lose pack companies | L |
| FWX-15 | `firewall_render` | A branch's rules as UFW, nftables or table text through `render-rules.py`. Returns text only, never applies | S |
| FWX-16 | `firewall_check_design` | Validate a draft company passed as JSON (schema, then audit) so an agent can help a student fix it. No file paths, no writes | M (after FWX-14) |
| FWX-17 | `firewall_cve` | Tracked CVEs by product or vendor, with status, as recorded by students; not a live feed | S |
| FWX-18 | `firewall_recommend_site` | Several segments or branches at once: one shortlist per slot, total cost, vendor-consistency option | M |
| FWX-19 | Trade-offs in `firewall_recommend` | What changes with 20% more budget or a higher headroom; accept custom weights | S |
| FWX-20 | MCP resources and a compare widget | `firewall://device/{id}`, `ui://` comparison table. The verification registry lists firewall widgets and apps as `none` | M |
| FWX-21 | Recommendation scenarios | Fixed contexts with expected shortlists, so a data or weight change that moves answers is visible in CI | S |

## Overlap with the student roadmap

Maintainers should decide these before anyone reserves them.

| Student task | Overlap |
|---|---|
| FW-26 Product comparison and segment selector | Largely covered by #404; FWX-04, 05 and 08 finish it. Mark it, or narrow it to licence-versus-trial notes |
| FW-16 Duplicate and shadowed rule detector | Its engine could feed FWX-14 |
| FW-20 Subnet and bandwidth planner | A planner tool belongs to that task; none is planned here |
| FW-31 UFW to nftables generator | `render-rules.py` already renders both from company rules; FWX-15 only exposes it |
| FW-38 Explain-your-rule audit | The schema already requires `note`; check before reserving |

## Order

1. FWX-01, FWX-03, FWX-02.
2. FWX-06, FWX-04, then FWX-05.
3. FWX-07, FWX-08, FWX-13, FWX-15.
4. FWX-09, FWX-18, FWX-19, FWX-21.
5. The rest as wanted.

One pull request per task, except FWX-07 with FWX-08, which share components.

## Out of scope

Controlling or scanning real firewalls, applying rules, collecting prices
automatically, and a hosted service. A tool that did any of these would need the
lab's scope guard and its own plan.

## Open questions

1. Who verifies product sheets (FWX-05), and for which products first?
2. Should student-quoted figures be hidden once a verified one exists, or shown beside it?
3. Is the gap audit better ported to Python (works with packs) or generated at build time?
4. Should the advisor page ship on public GitHub Pages, given the data is coursework?
