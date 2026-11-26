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

## Shipped in this PR

- Cleanup write abilities + Cleanup widgets/apps (see lat.md/cleanup-lab MCP section)
- Cleanup aux tools (explorer, deep-scan, containers, simulators, emulators, VMs, packages, leftovers, relocation, privileged, simulator-storage, custom-entries) with preview → confirm
- Missing-lab modules: `android_*`, `ios_*`, `linux_*`, `web_*`, `source_*`, `firewall_*`
- macOS observe extras: `macos_focused`, `macos_audit`, `macos_sessions` (still **no arm tool**)
- `macos_request_access`
- MCP `resources/*` + UI extension capability
- MCP `prompts/*` (standard prompts)
- Skills under `console/mcp_skills/`
- Host plugins under `plugins/mcp/`
- Verification registry + dashboard fields + CI subset/coverage test

## Gap inventory — labs

| Lab | Dashboard / API surface | MCP today | TODO |
| --- | --- | --- | --- |
| **Android Lab** | `/api/labs/android…`, Frida inventory, lab jobs | **status / frida / plan / overview app** | Per-tool widgets; job observe polish |
| **iOS Lab** | `/api/labs/ios/devices\|simulator\|resources\|screenshot` | **observe + plan / overview app** | Per-tool widgets; keep device drive confirm-gated on dashboard |
| **Linux Lab** | labctl / linux-lab scripts, readiness | **status / plan** | Doctor depth; scripted actions only through plan/start |
| **Web Lab** | `/api/web/*` | **status / overview / windows / engine start·stop / overview app** | Injections/profiles tools; per-tool widgets |
| **Source Lab** | `/api/source/*` | **status / readiness / candidates / runtime / plan / overview app** | Analyzer job observe; per-tool widgets |
| **Firewall Lab** | content/companies (mostly static) | **catalog / company / guides** | Keep content-only; no network mutate |
| **Cleanup Lab (extra)** | explorer … custom-entries | **aux tools + widgets/apps + host proofs** | More host UX polish |
| **macOS Lab (extra)** | deep session, audit, focused | **focused / audit / sessions + apps/control widgets** | Fuller MCP app; **no arm tool** (deliberate) |
| **Windows Apps (extra)** | dashboard has click/input/elements | **read-only by design** | Keep RO; input `n/a` |
| **Web Sec** | full workbench | **tools + status/review/report widgets** | Fuller workbench MCP app |
| **Cleanup widgets/apps** | first batch shipped | **host proofs verified** (`test_mcp_ui_hosts.py`) | Optional further host UX |

## TODO checklist (track in this PR / follow-ups)

### A. Missing lab MCP modules

- [x] `console/mcp_android.py` + wire into `mcp_server.py`
- [x] `console/mcp_ios.py` (device/simulator observe)
- [x] `console/mcp_linux.py` (status/doctor)
- [x] `console/mcp_web.py` (Web Lab)
- [x] `console/mcp_source.py` (Source Lab)
- [x] `console/mcp_firewall.py` (read-only content)
- [x] Cleanup aux tools: explorer, containers, simulators, emulators, VMs, leftovers, relocation, privileged, custom-entries, simulator-storage

### B. Verification proofs

- [x] Fill `engineUsage.proof` for shipped tools that have unit coverage
- [x] Fill Cleanup widget/app proofs via host-style resource read + structuredContent (`test_mcp_ui_hosts.py`)
- [x] Mark deliberate non-goals (`macos` arm, `winapps` input) as `n/a` with rationale in section `nonGoals`

### C. Widgets / apps (beyond cleanup)

- [x] Web Sec widgets (status, review, report)
- [x] macOS observe widgets (apps list, control state)
- [x] Lab overview apps for android / ios / web / source
- [ ] Fuller Web Sec / macOS apps and per-tool lab widgets (follow-up)

### D. Skills & plugins

- [x] Skill stubs per MCP section (`console/mcp_skills/*/SKILL.md`)
- [x] Plugin scaffolds for Claude, Codex, Antigravity, Zcode, OpenCode, Cursor (`plugins/mcp/`)
- [x] CI check that `mcp_verification.json` tool keys ⊆ defined tools (`test_mcp_verification.py`)
- [x] Keep [[dashboard/src/lib/mcp-guides.ts]] in sync with server tool lists

## Related paths

- Prompts: [[console/mcp_prompts.py]]
- UI helpers: [[console/mcp_ui.py]]
- Widgets: [[console/mcp_widgets/]]
- Apps: [[console/mcp_apps/]]
- Skills: [[console/mcp_skills/]]
- Plugins: [[plugins/mcp/]]
