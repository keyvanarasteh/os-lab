# Firewall Lab next steps: checklist

Companion to [PLAN-firewall-lab-next.md](PLAN-firewall-lab-next.md). **On hold.** Tick
an item only with proof: a test name, a pull request or a recorded run.

## Before starting

- [ ] Owner picks the tasks and the order, and changes the PR label from `ON-HOLD` to `ACTIVE`.
- [ ] Answer the plan's open questions.
- [ ] Decide the overlap with FW-16, FW-20, FW-26, FW-31 and FW-38.
- [ ] Re-measure the data table on current `master`.

## Phase 0: correctness

- [ ] FWX-01: all `firewall_*` tools read the content store.
  - [ ] Counts come from the loaded companies; every result reports `dataSource` and `dataVersion`.
  - [ ] Test with an installed pack: status, catalog and search agree.
- [ ] FWX-02: an old pack no longer hides newer bundled data.
  - [ ] Bundle records what it can be compared by.
  - [ ] Dashboard and MCP show which data is in force; test both directions.
- [ ] FWX-03: model aliases in `normalize.json`.
  - [ ] Merged groups listed in the parity test; real variants stay separate.

## Phase 1: data

- [ ] FWX-06: data quality report in the workflow summary.
- [ ] FWX-04: optional spec fields.
  - [ ] Schema, validator, template and schema README.
  - [ ] Python and TypeScript builders, pages, recommendation wording.
  - [ ] Existing companies validate unchanged.
- [ ] FWX-05: verified product sheets.
  - [ ] Format, validator and content-pack allowlist.
  - [ ] "Verified" and "student-quoted" labels in tools and pages.
  - [ ] First sheets with datasheet URL and date.

## Phase 2: pages

- [ ] FWX-07: product list and product page.
- [ ] FWX-08: compare page.
- [ ] FWX-09: advisor page, with a parity test against `firewall_recommend`.
- [ ] FWX-10: rule search page.
- [ ] FWX-11: insights page with table fallback.
- [ ] FWX-12: CSV and Markdown export.
- [ ] Each page: 8 locales, phone width, e2e spec in `affected.json`, `lat.md` updated.

## Phase 3: MCP

- [ ] FWX-13: `firewall_rules`.
- [ ] FWX-15: `firewall_render` (text only).
- [ ] FWX-14: `firewall_audit`, after choosing port or build-time output.
- [ ] FWX-16: `firewall_check_design`.
- [ ] FWX-17: `firewall_cve`.
- [ ] FWX-18: `firewall_recommend_site`.
- [ ] FWX-19: trade-offs and custom weights.
- [ ] FWX-20: resources and compare widget.
- [ ] FWX-21: recommendation scenarios in CI.
- [ ] Each tool: argument validation tests, `mcp_verification.json`, skill and plugin copies, `mcp-guides.ts`, standalone server.

## Finish

- [ ] `lat check`, dashboard `check` / `test:i18n` / `test:tooling`, unit and e2e results in the PR.
- [ ] Update [`lat.md/firewall-lab.md`](../lat.md/firewall-lab.md) and `firewall-lab/README.md`.
