# MCP coverage plan — remaining work

Follow-up to the mergeable MCP coverage PR (`cursor/mcp-write-abilities-cleanup-widgets-apps-9ed3`).  
Server: [[console/mcp_server.py]]. Guides: [[dashboard/src/lib/mcp-guides.ts]].  
Verification: [[console/mcp_verification.json]].

## Status legend

| Status | Meaning |
| --- | --- |
| `none` | Not started / not applicable yet |
| `pending` | Scaffolded or shipped without contributor proof |
| `verified` | Proof filled (test name, PR, or artifact) |
| `n/a` | Deliberately out of scope |

## Shipped (do not re-implement — already on the parent PR)

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

- [ ] Web Sec workbench MCP App (beyond status/review/report widgets)
- [ ] macOS Lab MCP App (beyond apps/control widgets)
- [ ] Optional: Cleanup host UX polish beyond first batch

### B. Per-tool lab widgets

- [ ] Android Lab per-tool widgets (status / Frida inventory / plan)
- [ ] iOS Lab per-tool widgets (devices / simulator / resources / screenshot)
- [ ] Web Lab per-tool widgets (status / windows / engine)
- [ ] Source Lab per-tool widgets (status / candidates / plan)
- [ ] Linux / Firewall widgets only if there is clear UX (otherwise leave `none`)

### C. Lab depth / tool gaps

- [ ] Android: job observe polish (list/poll lab jobs via MCP without arming inject)
- [ ] Linux: doctor depth beyond status/plan
- [ ] Web: injections / profiles tools mirroring `console/web_api.py`
- [ ] Source: analyzer job observe (start stays plan/dashboard unless confirm-gated)
- [ ] iOS: keep device drive confirm-gated on the dashboard (no agent arm)

### D. Verification contributor flips

- [ ] Flip remaining section `engineUsage` slots from `pending` → `verified` with proofs
- [ ] Flip tool `engineUsage` still `pending` (~cleanup / websec / macos / winapps) where tests exist
- [ ] Flip section `widgets`/`apps` from `pending` → `verified` once a real UI host (not just resource-read tests) exercises them
- [ ] Leave deliberate non-goals as `n/a`: `macos` arm tool; WinApps input tools

### E. Docs / dashboard sync

- [ ] Keep [[dashboard/src/lib/mcp-guides.ts]] and `/mcp/` planned sections in sync as widgets/apps land
- [ ] Refresh skills blurbs when new tools ship

## Non-goals (do not add)

- `macos_arm` MCP tool
- WinApps click/input MCP tools (until a human-arm story exists)
- Firewall network mutation tools

## Related paths

- Widgets: [[console/mcp_widgets/]]
- Apps: [[console/mcp_apps/]]
- Skills: [[console/mcp_skills/]]
- Plugins: [[plugins/mcp/]]
