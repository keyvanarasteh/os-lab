# MCP coverage plan — remaining work

Follow-up to the merged MCP coverage PR (#370).  
Server: [[console/mcp_server.py]] (v0.6.0). Guides: [[dashboard/src/lib/mcp-guides.ts]].  
Verification: [[console/mcp_verification.json]].

## Status legend

| Status | Meaning |
| --- | --- |
| `none` | Not started / not applicable yet |
| `pending` | Scaffolded or shipped without contributor proof |
| `verified` | Proof filled (test name, PR, or artifact) |
| `n/a` | Deliberately out of scope |

## Shipped on #370 (do not re-implement)

- Missing-lab modules: android / ios / linux / web / source / firewall
- Cleanup writes + aux tools (preview → confirm)
- macOS observe extras (`focused` / `audit` / `sessions`) + `macos_request_access` — **no arm tool**
- Cleanup widgets/apps + host proofs (`test_mcp_ui_hosts.py`)
- Web Sec widgets: status / review / report
- macOS widgets: apps / control
- Lab overview apps: android / ios / web / source
- Prompts, skills, plugins, verification registry + CI sync test

## Remaining TODO checklist

### A. Fuller MCP Apps

- [x] Web Sec workbench MCP App (`websec_app_workbench` + `mcp_apps/websec/workbench.html`)
- [x] macOS Lab MCP App (`macos_app_overview` + `mcp_apps/macos/overview.html`)
- [x] Cleanup host UX polish (overview refresh + monitor chip)

### B. Per-tool lab widgets

- [x] Android Lab per-tool widgets (status / Frida / plan / jobs)
- [x] iOS Lab per-tool widgets (status / devices / simulator / resources / screenshot)
- [x] Web Lab per-tool widgets (status / windows / engine / injections / profiles)
- [x] Source Lab per-tool widgets (status / candidates / plan / analyzer)
- [x] Linux widgets (status / doctor) — Firewall left `none` (no clear UX)

### C. Lab depth / tool gaps

- [x] Android: job observe (`android_jobs` / `android_job` via console `/api/jobs`)
- [x] Linux: doctor depth (`linux_doctor` host + plan preview)
- [x] Web: injections / profiles tools (`web_injections` / `web_profiles`)
- [x] Source: analyzer job observe (`source_analyzer` / `source_jobs` / `source_job`)
- [x] iOS: device drive stays confirm-gated on the dashboard (documented; no agent arm)

### D. Verification contributor flips

- [x] Flip section `engineUsage` slots to `verified` with test proofs
- [x] Flip tool `engineUsage` where suites exist (cleanup / websec / labs / winapps / macos observe)
- [x] Flip section `widgets`/`apps` to `verified` with `test_mcp_ui_hosts.py` proofs
- [x] Leave deliberate non-goals as `n/a`: `macos` arm tool; WinApps input tools

### E. Docs / dashboard sync

- [x] Keep [[dashboard/src/lib/mcp-guides.ts]] and `/mcp/` planned sections in sync
- [x] Refresh skills blurbs for new tools

## Non-goals (do not add)

- `macos_arm` MCP tool
- WinApps click/input MCP tools (until a human-arm story exists)
- Firewall network mutation tools

## Related paths

- Widgets: [[console/mcp_widgets/]]
- Apps: [[console/mcp_apps/]]
- Skills: [[console/mcp_skills/]]
- Plugins: [[plugins/mcp/]]
