# MCP coverage plan — gaps, verification, skills, plugins

Branch: `cursor/mcp-write-abilities-cleanup-widgets-apps-9ed3` (draft PR).  
Server: [[console/mcp_server.py]]. Guides: [[dashboard/src/lib/mcp-guides.ts]].  
Verification registry: [[console/mcp_verification.json]] (defaults `none` / `pending`, with a `proof` slot).

## Status legend

| Status | Meaning |
| --- | --- |
| `none` | Not started / not applicable yet |
| `pending` | Scaffolded or shipped without contributor proof |
| `verified` | Proof filled (test name, PR, or artifact) |
| `n/a` | Deliberately out of scope |

Every tool and every MCP section carries:

- `engineUsage` — proof the engine/API path was exercised through the MCP tool
- `widget` / `widgets` — MCP Apps widget HTML for tool-related UX
- `app` / `apps` — fuller MCP App built from lab dashboard UX

Contributors open PRs that flip `pending` → `verified` and set `proof`.

## Shipped in this PR (first batch)

- Cleanup write abilities + Cleanup widgets/apps (see lat.md/cleanup-lab MCP section)
- `macos_request_access`
- MCP `resources/*` + UI extension capability
- MCP `prompts/*` (standard prompts)
- Skills under `console/mcp_skills/`
- Host plugins under `plugins/mcp/`
- Verification registry + dashboard fields

## Gap inventory — labs with little or no MCP surface

| Lab | Dashboard / API surface | MCP today | TODO |
| --- | --- | --- | --- |
| **Android Lab** | `/api/labs/android…`, Frida inventory, lab jobs | **missing** | Add `android_*` tools (status, devices, jobs, frida inventory) on the same guards as the console |
| **iOS Lab** | `/api/labs/ios/devices\|simulator\|resources\|screenshot` | **missing** (macOS Lab is separate) | Add `ios_*` observe tools; keep device actions confirm-gated |
| **Linux Lab** | labctl / linux-lab scripts, readiness | **missing** | Read-only status/doctor first; scripted actions only through existing plan/start |
| **Web Lab** | `/api/web/*` (engine, windows, injections, profiles) | **missing** | `web_*` tools mirroring [[console/web_api.py]] |
| **Source Lab** | `/api/source/*` | **missing** | `source_*` tools for overview, detection, analyzer jobs |
| **Firewall Lab** | content/companies (mostly static) | **missing** | Content/browse tools only; no network mutate |
| **Cleanup Lab (extra)** | explorer, deep-scan, containers, simulators, emulators, VMs, leftovers, relocation, privileged, custom-entries, simulator-storage, packages | **partial** — core CUX-10 + writes in this PR | Second batch of tools for each aux surface (preview → confirm) |
| **macOS Lab (extra)** | deep session, audit stream, focused, element/read | **partial** | Optional observe tools; **no arm tool** (deliberate) |
| **Windows Apps (extra)** | dashboard has click/input/elements | **read-only by design** | Keep RO for agents until a human-arm story exists; document as `n/a` for input |
| **Web Sec** | full workbench | **present** | Widgets/apps still `none` — next UI batch |
| **Cleanup widgets/apps** | first batch shipped | **pending proof** | Contributors verify hosts render UI |

## TODO checklist (track in this PR / follow-ups)

### A. Missing lab MCP modules

- [ ] `console/mcp_android.py` + wire into `mcp_server.py`
- [ ] `console/mcp_ios.py` (device/simulator observe)
- [ ] `console/mcp_linux.py` (status/doctor)
- [ ] `console/mcp_web.py` (Web Lab)
- [ ] `console/mcp_source.py` (Source Lab)
- [ ] `console/mcp_firewall.py` (read-only content)
- [ ] Cleanup aux tools: explorer, containers, simulators, emulators, VMs, leftovers, relocation, privileged, custom-entries, simulator-storage

### B. Verification proofs

- [ ] Fill `engineUsage.proof` for each shipped tool (test name or fixture)
- [ ] Fill Cleanup widget/app proofs once a UI host is exercised
- [ ] Mark deliberate non-goals (`macos` arm, `winapps` input) as `n/a` with rationale in proof

### C. Widgets / apps (beyond cleanup)

- [ ] Web Sec widgets (status, review, report)
- [ ] macOS observe widgets (apps list, control state)
- [ ] Lab apps for android / ios / web / source once tools exist

### D. Skills & plugins

- [x] Skill stubs per MCP section (`console/mcp_skills/*/SKILL.md`)
- [x] Plugin scaffolds for Claude, Codex, Antigravity, Zcode, OpenCode, Cursor (`plugins/mcp/`)
- [ ] CI check that `mcp_verification.json` tool keys ⊆ `tools/list`
- [ ] Keep [[dashboard/src/lib/mcp-guides.ts]] in sync with server tool lists

## Related paths

- Prompts: [[console/mcp_prompts.py]]
- UI helpers: [[console/mcp_ui.py]]
- Widgets: [[console/mcp_widgets/]]
- Apps: [[console/mcp_apps/]]
- Skills: [[console/mcp_skills/]]
- Plugins: [[plugins/mcp/]]
