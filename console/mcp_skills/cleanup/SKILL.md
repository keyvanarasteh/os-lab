---
name: os-lab-mcp-cleanup
description: Use the os-lab MCP Cleanup Lab MCP tools (cleanup_*). Prefer guarded review→confirm flows; fill verification proofs in console/mcp_verification.json.
---

# Cleanup Lab MCP

Related MCP tools: `cleanup_*`.

Catalog ids only. Review never cleans; cleanup_clean needs confirm:true. Widgets/apps under ui://os-lab/cleanup/.

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
