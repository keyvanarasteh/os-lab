# Web Sec Lab — domain portfolio, scheduled checks and the CVE Lab (plan)

Status: **plan only**. Nothing here is implemented. It builds on the Web Sec Lab
(`web-sec/`, the posture monitor, `console/mcp_websec.py`); land that first.
The tracking checklist is [TODO-websec-domain-portfolio.md](TODO-websec-domain-portfolio.md).

## Why

Today the Web Sec Lab scans a host you name and, with the monitor, re-scans up to ten
hosts on one shared schedule. An owner of several sites needs more than that:

- a **stored list of the domains they own**, with the stack each one runs (web
  server, framework, CMS, runtime, CDN, hosting, versions), detected and correctable;
- **scheduled checks per domain**, chosen per check, not one preset: certificate
  expiry and chain, domain registration expiry (WHOIS/RDAP), DNS and mail
  authentication, headers, exposed files, vulnerable libraries, takeover, lookalikes;
- **notifications** that reach them outside the app, with escalation, snooze and
  acknowledgement;
- later, a **CVE Lab** that collects advisories and tells them when their stack is
  affected, before anyone scans them.

## Principles (unchanged from the lab)

1. **Ownership first.** A portfolio domain must be covered by `scope.json`; a domain
   can additionally be *verified* (DNS TXT record or a file under
   `/.well-known/`), and intrusive checks are allowed only on verified domains with
   the per-domain "active checks authorized" switch on, which is never a default.
2. **Passive by default.** Scheduled checks are passive unless the domain is verified
   and authorized; the CVE Lab never probes a site, it matches inventories.
3. **One engine, every surface.** Each ability ships as engine code, a console
   endpoint, a dashboard view and an MCP tool with the same guards
   (`lat.md/ux-readiness.md`, one-click standard).
4. **Private, bounded storage.** Everything lives in the lab's 0700 storage folder,
   versioned and validated; secrets (SMTP passwords, webhook URLs) go in the OS
   keychain or an env-referenced file, never in the JSON store or the repository.
5. **Defensive only.** No exploit code, payloads or proof-of-concept downloads, in
   either lab.

## Phase 1 — Domain portfolio (WSD-01 … WSD-05)

A `portfolio.json` store in `web-sec/storage`:

```json
{
  "version": 1,
  "domains": [{
    "host": "shop.example.com",
    "label": "Shop",
    "environment": "production",
    "owner": "web team",
    "tags": ["ecommerce"],
    "verified": {"method": "dns-txt", "at": "2026-12-01T10:00:00Z"},
    "activeAuthorized": false,
    "stack": {
      "detected": [{"component": "nginx", "version": "1.24.0", "source": "web_technologies", "at": "…"}],
      "declared": [{"component": "wordpress", "version": "6.5.2", "cpe": "cpe:2.3:a:wordpress:wordpress:6.5.2", "purl": ""}]
    },
    "checks": {"tls": {"enabled": true, "every": "daily", "warnDays": [30, 14, 7]}}
  }]
}
```

- **WSD-01 store and schema**: `websec/portfolio.py` (validate, atomic 0600 write,
  read other versions, keep unknown keys), CLI `portfolio list|add|update|remove`,
  at most 200 domains.
- **WSD-02 ownership**: every domain must match `scope.json`; optional verification by
  a DNS TXT token (`_oslab-websec.<host>`) or `/.well-known/oslab-websec.txt`; the
  token is shown, checked on demand and re-checked monthly.
- **WSD-03 stack inventory**: fill `stack.detected` from `web_technologies`,
  `js_library_vulns`, headers and banners on every scan; the user adds `declared`
  components (with CPE or purl) for what the site does not reveal (database, runtime,
  plugins). Detected and declared stay separate, so a correction is never
  overwritten.
- **WSD-04 import**: from `scope.json` hosts, from a CSV (`host,label,environment,tags`),
  and from the monitor's target list; duplicates merge.
- **WSD-05 UI and agents**: a **Domains** row (later its own page) in the workbench: a
  table with grade, certificate and registration expiry, last check and stack
  chips; add/edit dialog; MCP `websec_portfolio_*` tools (read-only list/get,
  add/update with validation, remove with `confirm: true`).

## Phase 2 — Scheduled checks (WSD-06 … WSD-11)

Generalise the monitor from "preset per target" to **check sets per domain**, each with
its own interval and thresholds:

| Check | Engine source | Default schedule | Signals |
|---|---|---|---|
| Certificate expiry, chain, protocol, key size | `tls_health`, `ssl_san` | daily | expires in 30/14/7/1 days, chain broken, TLS < 1.2 |
| Domain registration expiry, registrar lock, status | `domain_info` (WHOIS) + new RDAP client | weekly; daily under 30 days | expires in 60/30/7 days, `clientTransferProhibited` missing, status change |
| DNS health, CAA, DNSSEC, email auth | `dns_health`, `email_security` | daily | record removed, DMARC weakened, SPF `+all` |
| Security headers and cookies | `security_analysis`, `cookies_cors` | daily | regression against the last run |
| Exposed files, source maps, secrets | `exposed_files`*, `content_scan` | daily | any new exposure (critical) |
| Vulnerable JS libraries | `js_library_vulns` | daily | new advisory for a loaded version |
| Subdomain takeover, origin exposure | `subdomain_takeover`, `origin_exposure` | weekly | new dangling CNAME |
| Lookalike domains | `lookalike_domains` | weekly | new registration |
| Open ports | `port_exposure`* | weekly | new open service |

\* intrusive: only on verified domains with `activeAuthorized: true`.

- **WSD-06 RDAP client**: allowlisted like crt.sh/NVD (written reason in
  `knowledge/scope-and-authorization.md`), registry-bootstrap lookup, WHOIS fallback.
- **WSD-07 expiry checks**: certificate and registration expiry as first-class events
  with day thresholds, independent of the posture grade.
- **WSD-08 scheduler**: per-domain, per-check due times in the monitor state; jitter;
  at most one scan at a time; a backlog that never stampedes after sleep or restart.
- **WSD-09 run log**: every scheduled run stored like a workbench run (compare and
  history work unchanged), plus a compact per-check timeline per domain.
- **WSD-10 "test everything" button** per domain (the one-click action): runs every
  enabled check now and opens the result.
- **WSD-11 tests**: pure evaluation tests for each signal with injected clocks and
  fixtures; no network.

## Phase 3 — Notifications (WSD-12 … WSD-16)

- **WSD-12 channels**: native desktop (exists), email (SMTP with STARTTLS, password from
  the keychain), webhook (Slack, Teams, generic JSON; URL stored as a secret), and the
  in-app inbox. Each channel has a "send test" action.
- **WSD-13 routing**: per domain and per severity; immediate or daily digest; quiet hours
  that never hold back `critical`.
- **WSD-14 lifecycle**: acknowledge, snooze (1 d / 7 d / until resolved), escalate when a
  warning worsens, remind while unresolved, resolve automatically when the check
  recovers (extends the current monitor lifecycle).
- **WSD-15 inbox UI**: a notification list with filters, bulk acknowledge, and links to
  the domain, the finding, the guide and Compare runs.
- **WSD-16 agents**: MCP tools to list, acknowledge and snooze (acknowledge/snooze with
  `confirm: true`), and to configure channels without ever returning a secret.

## Phase 4 — CVE Lab (CVE-01 … CVE-09)

A separate lab (`cve-lab/`, its own readiness, engine and dashboard page), because it
crawls public advisory sources rather than a target:

- **CVE-01 sources**: NVD API 2.0 (with an API key from the keychain, rate-limited), OSV,
  GitHub Security Advisories, CISA KEV, EPSS; incremental sync with cursors, ETags and
  backoff; a bounded local store (SQLite or JSONL shards) with retention.
- **CVE-02 normalisation**: one record per CVE with affected products as CPE 2.3 ranges
  and package purls, CVSS v3/v4, EPSS, KEV flag, references, fixed versions.
- **CVE-03 matching**: the portfolio stack inventory (detected and declared, with CPE or
  purl) against affected ranges; version-range semantics per ecosystem; confidence
  levels (exact CPE, vendor+product, name only).
- **CVE-04 prioritisation**: CVSS × EPSS × KEV × exposure (internet-facing, verified
  domain, component seen in the response) → one ordered list per domain.
- **CVE-05 warnings**: "shop.example.com runs nginx 1.24.0, affected by CVE-…; fixed in
  …" through the Phase 3 notifications, with evidence of where the version was seen.
- **CVE-06 crawl hygiene**: only the advisory APIs above, allowlisted; no exploit
  databases, no proof-of-concept downloads, no probing of the user's sites.
- **CVE-07 UI**: per-domain vulnerability list, per-CVE detail, "mark not affected" with
  a reason (stored, auditable), and an export.
- **CVE-08 agents**: MCP read tools (sync status, matches per domain, CVE detail) and a
  triage tool (`not affected` / `accepted risk`, with `confirm: true`).
- **CVE-09 tests**: fixture feeds for each source, matching edge cases (CPE wildcards,
  semver vs. distro versions), no network in tests.

## Out of scope

Active exploitation or verification of a CVE against a site, fetching exploit code,
scanning domains outside the scope, storing secrets in the repository, and any hosted
or multi-tenant service.

## Verification for each phase

Engine: `cd web-sec/engine && python3 -m pytest -q` (and `cve-lab/engine` later).
Console: `android-lab/lab/tests/test_websec_console.py`, `test_mcp_websec.py`.
Dashboard: `npm run check`, `npm run test:i18n`, the new e2e cases, `scripts/e2e.sh
--changed` in an owner-approved mode. Graph: `lat check` with a `lat.md/web-sec.md`
section per phase (and `lat.md/cve-lab.md` for Phase 4).
