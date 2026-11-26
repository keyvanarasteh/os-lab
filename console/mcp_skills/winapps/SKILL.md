---
name: os-lab-mcp-winapps
description: Use the os-lab MCP Windows Apps Lab MCP tools (winapps_*). Prefer guarded review→confirm flows; fill verification proofs in console/mcp_verification.json.
---

# Windows Apps Lab MCP

Related MCP tools: `winapps_*`.

Windows-only, read-only allowlist. No agent input tools.

## Rules

- Call only tools from `tools/list` on the os-lab stdio server (`console/mcp_server.py`).
- Read `docs/PLAN-mcp-coverage.md` for gaps; do not fabricate missing tools.
- When verifying, update `console/mcp_verification.json` (`engineUsage` / `widget` / `app`) with a proof (test name, PR, or artifact).
- Prefer MCP prompts: `cleanup_review_flow`, `macos_observe_act_verify`, `websec_scoped_scan`, `mcp_verify_tool`, `mcp_coverage_status`, `mcp_gap_plan`.

## Verification fields

| Field | Default | Proof slot |
| --- | --- | --- |
| engineUsage | none / pending | test or fixture that called the tool |
| widget | none / pending | UI host rendered the resourceUri |
| app | none / pending | UI host rendered the lab app |
