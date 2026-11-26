# Codex plugin implementation checklist

Companion to [PLAN-codex-plugin.md](PLAN-codex-plugin.md). Mark each completed item with test proof and platform; unchecked items remain implementation work.

This checklist includes every implemented Claude plugin feature inspected at `feat/ai-agent-plugins` commit `e0ab48942`; the [parity table](PLAN-codex-plugin.md#claude-implementation-parity-audit) records the Codex counterpart or exclusion. Rebase on master only after the user confirms that the Claude branch merged.

Status after Claude merge (#385/#388/#390): rebased; requirement catalog JSON, updates tool, console API, `/mcp/` cards, status widget, three-OS CI and verification proofs landed. Remaining unchecked Stage 0 desktop/live-host items stay documentation limits, not merge blockers.

## Stage 0: verify current client behavior

- [x] Record `codex --version` and OS for the CLI proof environment — `codex-cli 0.167.0`, macOS, `test_codex_plugin.py`; desktop version remains open below.
- [x] Check current official portable plugin and local stdio documentation; prove CLI marketplace install and MCP discovery with temporary `CODEX_HOME` — `test_codex_plugin.py`.
- [ ] Test repo marketplace discovery in a fresh worktree and in the Codex desktop app after restart.
- [ ] Inspect a copied local install to confirm what files and environment the launcher receives.
- [ ] Decide path configuration and Windows interpreter strategy from observed behavior.
- [x] Record supported CLI commands: `plugin marketplace add`, `plugin list`, `plugin add`, `plugin remove`; this CLI has no update/configure/enable/disable verbs. `scripts/codex-plugin.py` uses only tested install commands.
- [ ] Verify what Codex exposes for plugin-scoped `repo_path`, `console_port` and Python interpreter settings; do not use Claude `${user_config.*}` placeholders without Codex proof.
- [ ] Check whether Codex CLI and desktop support lifecycle hooks, MCP Apps widgets, resources and prompts for locally installed plugins; record the version and observed behavior.
- [ ] Decide the actual human approval gate for an MCP-triggered apply action; treat `confirm: true` as insufficient by itself.
- [ ] After the Claude merge, inspect shared `console/mcp_server.py`, `console/mcp_plugin.py`, `console/claude_plugin.py`, skills and verification registry; identify reusable helpers and namespace conflicts.

## Stage 1: installable package

- [x] Add `plugins/codex/os-lab/plugin.json`, `mcp.json`, README and license — package check and isolated CLI install.
- [x] Add `.agents/plugins/marketplace.json` with a repo-relative local source and complete policy fields — isolated CLI marketplace test.
- [x] Add package-local launcher with checkout discovery, setup-only MCP mode and stdout reserved for JSON-RPC — launcher test.
- [ ] Add a Codex-supported explicit checkout option if one exists; `OSLAB_ROOT` and verified marketplace discovery work now, with invalid `OSLAB_ROOT` refused.
- [x] Serve read-only `codex_plugin_doctor` and `codex_plugin_status` over MCP when no checkout exists — launcher protocol test; add more malformed-call cases later.
- [x] Add `setup` and `doctor` skills — packaged skill files.
- [ ] Validate manifest, marketplace, MCP config, license/README, path containment, no escaping symlinks and copied-package behavior with success and failure fixtures.

## Stage 2: full skill coverage

- [x] Inventory and package every current `console/mcp_skills/` lab — generated copies for all ten.
- [x] Add deterministic generation and `--check` drift detection — `scripts/codex-plugin.py build --check`.
- [x] Cover the ten current lab skills: Android, Cleanup, Firewall, iOS, Linux, macOS, Source, Web, Web Sec and WinApps, plus setup and doctor.
- [ ] Check frontmatter, allowed fields, trigger descriptions, body length guidance, supporting files and live tool names against current Codex rules.
- [ ] Test direct, indirect, incomplete, out-of-scope and unsupported requests for setup, doctor and representative labs.

## Stage 3: requirement catalog and MCP management surface

- [ ] Expand the initial dated Codex requirement catalog beyond its ten package rules to all supported components, including per-rule version gates and fixtures.
- [ ] Cover portable manifest and OpenAI extension, marketplace source/policy, local stdio MCP and tool schemas/annotations, skills, cache/state, CLI/desktop, config precedence, hooks if used, distribution and deliberately absent components.
- [ ] Implement `codex_plugin_requirements` with area/usage filters and `codex_plugin_check` with pass/fail/warn/skipped/manual results, fixes and version-aware behavior. Do not reuse Claude-only numeric limits.
- [ ] Give each automatic rule a passing and failing fixture; check duplicate rule IDs, valid source URLs, malformed package files, old or missing CLI, and unreadable CLI output.
- [ ] Deepen `codex_plugin_doctor` and `codex_plugin_status` with client version, duplicate connection details and specific fixes; basic read-only versions exist.
- [x] Add a Codex requirement resource and guided setup prompt with plain tool results — server surface test; add read/get assertions later.
- [x] Register seven Codex management tools in the shared server and `console/mcp_verification.json`; refuse their use inside `macos_task` — `test_codex_plugin.py`.

## Stage 4: preview, apply and verification

- [ ] Detect the manual `plugins/mcp/codex/config.toml` route and duplicate MCP connections; explain migration.
- [ ] Expand `codex_plugin_plan` beyond its tested install action when supported lifecycle operations are proven. Install currently has fixed commands, one-use token, expiration and root/state binding.
- [ ] Prove the interactive-terminal-only `codex_plugin_apply` flow end to end, add audit and failure fixtures; MCP writes currently refuse.
- [ ] Keep uninstall and duplicate removal interactive-terminal-only unless a separate human approval path is proven. Refuse a marketplace name collision pointing to another source and never start its code.
- [x] Audit install previews, outcomes and refusals without tokens, credentials, config secrets or environment values — fake CLI tests.
- [x] Add `scripts/codex-plugin.py` for build/check/doctor/status/requirements/install/verify before MCP connection exists — helper smoke and package checks.
- [ ] Extend `codex_plugin_verify` to read saved checkout settings and a copied desktop package. It now checks the installed local source, launch config, handshake, names, annotations, instructions, resource and prompt discovery in the isolated CLI test.
- [ ] Test missing Python, bad root, symlink escape, malformed config, timeout, crash, stale/reused token, changed state, partial failure, duplicate MCP entry and wrong-source marketplace.
- [ ] Test `codex_plugin_*` calls through the actual MCP server, including invalid arguments, read-only annotations, guarded refusal and no secrets in status/logs.

## Stage 5: client surfaces and release proof

- [x] Add shared server `instructions` for Codex tool names and guarded operation — add explicit regression assertion after Claude merge.
- [ ] Verify large read results and UI metadata in Codex. Preserve Claude's existing result hints after merge; add only Codex-supported hints.
- [ ] If supported, add a read-only startup hook: short timeout, silent on healthy startup, useful one-line fix on failure, always nonblocking. Prove it in a live client session.
- [ ] If supported, add a status widget with escaped data and read-only refresh; test in a Codex MCP Apps host. Keep a complete plain result when UI is unavailable.
- [ ] If a dashboard `/mcp/` Codex section is added, tie actions to live readiness and available capabilities, show errors, and verify local and public Pages routes.
- [ ] Test the helper against a fake CLI for success, refusal, stale state and partial failure; test one real isolated install/configure/update/disable/enable/uninstall/re-install cycle.

- [ ] Extend the proven temporary-profile CLI marketplace add/install and 148-tool MCP discovery to desktop marketplace discovery, copied-cache launch and update/removal lifecycle.
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
