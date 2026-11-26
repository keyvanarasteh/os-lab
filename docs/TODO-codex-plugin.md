# Codex plugin implementation checklist

Companion to [PLAN-codex-plugin.md](PLAN-codex-plugin.md). All items below are open. Mark each with the implementation PR, test proof and platform when completed.

This checklist includes every implemented Claude plugin feature inspected at `feat/ai-agent-plugins` commit `e0ab48942`; the [parity table](PLAN-codex-plugin.md#claude-implementation-parity-audit) records the Codex counterpart or exclusion. Rebase on master only after the user confirms that the Claude branch merged.

## Stage 0: verify current client behavior

- [ ] Record `codex --version`, desktop version and OS for the proof environment.
- [ ] Fetch the current portable plugin and MCP schema; prove the local stdio entry works in a throwaway package.
- [ ] Test repo marketplace discovery in a fresh worktree and in the Codex desktop app after restart.
- [ ] Inspect a copied local install to confirm what files and environment the launcher receives.
- [ ] Decide path configuration and Windows interpreter strategy from observed behavior.
- [ ] Record expected CLI status/install/update commands, without editing the user's live Codex profile.
- [ ] Verify what Codex exposes for plugin-scoped `repo_path`, `console_port` and Python interpreter settings; do not use Claude `${user_config.*}` placeholders without Codex proof.
- [ ] Check whether Codex CLI and desktop support lifecycle hooks, MCP Apps widgets, resources and prompts for locally installed plugins; record the version and observed behavior.
- [ ] Decide the actual human approval gate for an MCP-triggered apply action; treat `confirm: true` as insufficient by itself.
- [ ] After the Claude merge, inspect shared `console/mcp_server.py`, `console/mcp_plugin.py`, `console/claude_plugin.py`, skills and verification registry; identify reusable helpers and namespace conflicts.

## Stage 1: installable package

- [ ] Add `plugins/codex/os-lab/plugin.json`, `mcp.json`, README and license.
- [ ] Add `.agents/plugins/marketplace.json` with a repo-relative local source and complete policy fields.
- [ ] Add package-local launcher with bounded checkout discovery, clear failure output and no stdout noise.
- [ ] Resolve a configured checkout first, then `OSLAB_ROOT`, then a verified local marketplace root if available. Refuse an invalid configured path rather than silently falling back.
- [ ] Serve read-only `codex_plugin_doctor` and `codex_plugin_status` over MCP when no checkout exists; test initialize, tools/list, tool calls, ping and notification handling in setup-only mode.
- [ ] Add `setup` and `doctor` skills; distinguish read-only diagnosis from an approved write.
- [ ] Validate manifest, marketplace, MCP config, license/README, path containment, no escaping symlinks and copied-package behavior with success and failure fixtures.

## Stage 2: full skill coverage

- [ ] Inventory each `console/mcp_skills/` skill and map it to a packaged Codex skill or explain why it is excluded.
- [ ] Add deterministic generation and `--check` drift detection for packaged lab skills.
- [ ] Cover the ten current lab skills: Android, Cleanup, Firewall, iOS, Linux, macOS, Source, Web, Web Sec and WinApps, plus setup and doctor.
- [ ] Check frontmatter, allowed fields, trigger descriptions, body length guidance, supporting files and live tool names against current Codex rules.
- [ ] Test direct, indirect, incomplete, out-of-scope and unsupported requests for setup, doctor and representative labs.

## Stage 3: requirement catalog and MCP management surface

- [ ] Add a dated Codex requirement catalog with `id`, area, rule, severity, usage/reason, check, source URL and optional minimum client version.
- [ ] Cover portable manifest and OpenAI extension, marketplace source/policy, local stdio MCP and tool schemas/annotations, skills, cache/state, CLI/desktop, config precedence, hooks if used, distribution and deliberately absent components.
- [ ] Implement `codex_plugin_requirements` with area/usage filters and `codex_plugin_check` with pass/fail/warn/skipped/manual results, fixes and version-aware behavior. Do not reuse Claude-only numeric limits.
- [ ] Give each automatic rule a passing and failing fixture; check duplicate rule IDs, valid source URLs, malformed package files, old or missing CLI, and unreadable CLI output.
- [ ] Add `codex_plugin_doctor` and `codex_plugin_status` with platform, Python, checkout, plugin and marketplace state, and specific fixes.
- [ ] Add a Codex requirement resource and guided setup prompt; prove resources/list/read and prompts/list/get, while preserving plain tool results.
- [ ] Register Codex management tools in the shared server and `console/mcp_verification.json`; refuse their use inside `macos_task`.

## Stage 4: preview, apply and verification

- [ ] Detect the manual `plugins/mcp/codex/config.toml` route and duplicate MCP connections; explain migration.
- [ ] Implement `codex_plugin_plan` for supported install/update/configure/enable/disable and removal commands with exact steps, warnings, one-use token, expiration, root and state binding.
- [ ] Implement `codex_plugin_apply` only with a proven human approval gate plus token and `confirm: true`; fixed argument lists, timeout, unchanged-state recheck, stop on first failed step and report unrun steps.
- [ ] Keep uninstall and duplicate removal interactive-terminal-only unless a separate human approval path is proven. Refuse a marketplace name collision pointing to another source and never start its code.
- [ ] Audit plans, applied steps, failures and refusals without credentials, config secrets or environment values.
- [ ] Add `scripts/codex-plugin.py` or an equivalent helper using the same engine for build/check/doctor/status/plan/apply/verify before MCP connection exists.
- [ ] Implement `codex_plugin_verify`: inspect the installed source and saved checkout setting, start its launcher, initialize, list tools/resources/prompts, compare names and annotations with this checkout, and report missing/extra tools.
- [ ] Test missing Python, bad root, symlink escape, malformed config, timeout, crash, stale/reused token, changed state, partial failure, duplicate MCP entry and wrong-source marketplace.
- [ ] Test `codex_plugin_*` calls through the actual MCP server, including invalid arguments, read-only annotations, guarded refusal and no secrets in status/logs.

## Stage 5: client surfaces and release proof

- [ ] Add or update shared server `instructions` for Codex tool names and guarded operation; keep host-independent safety text intact and test the initialize result.
- [ ] Verify large read results and UI metadata in Codex. Preserve Claude's existing result hints after merge; add only Codex-supported hints.
- [ ] If supported, add a read-only startup hook: short timeout, silent on healthy startup, useful one-line fix on failure, always nonblocking. Prove it in a live client session.
- [ ] If supported, add a status widget with escaped data and read-only refresh; test in a Codex MCP Apps host. Keep a complete plain result when UI is unavailable.
- [ ] If a dashboard `/mcp/` Codex section is added, tie actions to live readiness and available capabilities, show errors, and verify local and public Pages routes.
- [ ] Test the helper against a fake CLI for success, refusal, stale state and partial failure; test one real isolated install/configure/update/disable/enable/uninstall/re-install cycle.

- [ ] Test fresh-profile CLI install and desktop marketplace discovery/install, copied-cache launcher and tool discovery. Record client version and restart/refresh requirements.
- [ ] Confirm macOS, Linux and Windows support separately; document any platform without direct proof.
- [ ] Update `plugins/mcp/README.md`, relevant `lat.md/` nodes and `console/mcp_verification.json` with observed proofs.
- [ ] Run focused tests and `scripts/run-tests.sh --changed`; run `lat check` after graph edits.
- [ ] If dashboard changes, run check, i18n and build; show `scripts/e2e.sh --dry-run` and ask for mode before e2e.
- [ ] Keep the implementation PR draft until required checks, the isolated install proof and the platform claims are reviewable; then mark it ready. Keep unrelated Cleanup Lab work in separate PRs.

## Optional public distribution

- [ ] Confirm current public-directory policy for local stdio servers, host permissions, privacy and metadata.
- [ ] Keep any local-only lifecycle hook out of a public-directory package when the current policy excludes hooks.
- [ ] Record that Claude Desktop `.mcpb` has no Codex counterpart; use Codex desktop install proof instead.
- [ ] Submit only after local plugin behavior and distribution requirements are met.
