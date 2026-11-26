# Web Sec Lab — domain portfolio, scheduled checks and CVE Lab (TODO)

**Important — do later.** Plan: [PLAN-websec-domain-portfolio.md](PLAN-websec-domain-portfolio.md).
Starts after the Web Sec Lab branch (`feat/web-sec-lab`) has landed. Each item ships
engine + console + dashboard + MCP + tests (one-click standard), in its own PR.

## Phase 1 — Domain portfolio

- [ ] **WSD-01** Store and schema: `websec/portfolio.py`, `portfolio.json` (0600, versioned), CLI `portfolio list|add|update|remove`, at most 200 domains.
- [ ] **WSD-02** Ownership: scope.json coverage required; optional DNS TXT / `.well-known` verification; `activeAuthorized` per domain, never a default.
- [ ] **WSD-03** Stack inventory: detected (from scans) and declared (CPE/purl) components, kept apart.
- [ ] **WSD-04** Import from scope.json, CSV and the monitor's targets; merge duplicates.
- [ ] **WSD-05** Domains row/page in the workbench and `websec_portfolio_*` MCP tools.

## Phase 2 — Scheduled checks

- [ ] **WSD-06** RDAP client (allowlisted, written reason), WHOIS fallback.
- [ ] **WSD-07** Certificate and domain-registration expiry events with day thresholds (30/14/7/1; 60/30/7).
- [ ] **WSD-08** Per-domain, per-check scheduler in the monitor (jitter, no stampede after sleep, one scan at a time).
- [ ] **WSD-09** Per-check timeline per domain; runs stored like workbench runs.
- [ ] **WSD-10** "Test everything now" per domain (the primary action).
- [ ] **WSD-11** Offline tests for every signal with injected clocks.

## Phase 3 — Notifications

- [ ] **WSD-12** Channels: desktop (exists), email (SMTP, keychain secret), webhook (Slack/Teams/JSON), in-app inbox; "send test".
- [ ] **WSD-13** Routing per domain and severity; immediate or digest; quiet hours (never for critical).
- [ ] **WSD-14** Acknowledge, snooze, escalate, remind, auto-resolve.
- [ ] **WSD-15** Inbox UI with filters and bulk acknowledge.
- [ ] **WSD-16** MCP tools for notifications and channel config (no secret ever returned).

## Phase 4 — CVE Lab (separate lab)

- [ ] **CVE-01** Sources: NVD 2.0, OSV, GitHub advisories, CISA KEV, EPSS; incremental, rate-limited, bounded store.
- [ ] **CVE-02** Normalised records (CPE 2.3 ranges, purls, CVSS, EPSS, KEV, fixed versions).
- [ ] **CVE-03** Match the portfolio stack against affected ranges, with confidence levels.
- [ ] **CVE-04** Prioritisation: CVSS × EPSS × KEV × exposure.
- [ ] **CVE-05** "You are likely affected" warnings through the Phase 3 notifications, with evidence.
- [ ] **CVE-06** Crawl hygiene: advisory APIs only, no exploit code, no probing of sites.
- [ ] **CVE-07** UI: per-domain list, CVE detail, "not affected" triage, export.
- [ ] **CVE-08** MCP read and triage tools (`confirm: true` for triage).
- [ ] **CVE-09** Fixture-based tests for every source and matching edge case.

## Cross-cutting

- [ ] `lat.md/web-sec.md` sections per phase; `lat.md/cve-lab.md` for Phase 4.
- [ ] Translations for every new string in all active locales.
- [ ] `knowledge/scope-and-authorization.md`: RDAP and every advisory source with a written reason.
