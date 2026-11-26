# Codex plugin implementation checklist

Companion to [PLAN-codex-plugin.md](PLAN-codex-plugin.md). All items below are open. Mark each with the implementation PR, test proof and platform when completed.

## Stage 0: verify current client behavior

- [ ] Record `codex --version`, desktop version and OS for the proof environment.
- [ ] Fetch the current portable plugin and MCP schema; prove the local stdio entry works in a throwaway package.
- [ ] Test repo marketplace discovery in a fresh worktree and in the Codex desktop app after restart.
- [ ] Inspect a copied local install to confirm what files and environment the launcher receives.
- [ ] Decide path configuration and Windows interpreter strategy from observed behavior.
- [ ] Record expected CLI status/install/update commands, without editing the user's live Codex profile.

## Stage 1: installable package

- [ ] Add `plugins/codex/os-lab/plugin.json`, `mcp.json`, README and license.
- [ ] Add `.agents/plugins/marketplace.json` with a repo-relative local source and complete policy fields.
- [ ] Add package-local launcher with bounded checkout discovery, clear failure output and no stdout noise.
- [ ] Add `setup` and `doctor` skills; distinguish read-only diagnosis from an approved write.
- [ ] Validate manifests, path containment and copied-package behavior with success and failure fixtures.

## Stage 2: full skill coverage

- [ ] Inventory each `console/mcp_skills/` skill and map it to a packaged Codex skill or explain why it is excluded.
- [ ] Add deterministic generation and `--check` drift detection for packaged lab skills.
- [ ] Check frontmatter, trigger descriptions, supporting files and live tool names.
- [ ] Test direct, indirect, incomplete, out-of-scope and unsupported requests for setup, doctor and representative labs.

## Stage 3: diagnosis and verification

- [ ] Implement structured prerequisite/status checks without writing config.
- [ ] Detect the manual `plugins/mcp/codex/config.toml` route and duplicate MCP connections; explain migration.
- [ ] Verify installed server initialize, tools, resources, prompts, annotations and guarded refusal behavior.
- [ ] Test missing Python, bad root, symlink escape, malformed config, timeout, crash, stale state and partial install.
- [ ] If adding setup automation, require exact preview, fresh confirmation, bounded commands and post-write verification.
- [ ] Prove secrets stay out of diagnostics and logs; leave host permissions and managed settings alone.

## Stage 4: release proof

- [ ] Test fresh-profile CLI install, desktop discovery/install, update, disable, uninstall and re-install.
- [ ] Confirm macOS, Linux and Windows support separately; document any platform without direct proof.
- [ ] Update `plugins/mcp/README.md`, relevant `lat.md/` nodes and `console/mcp_verification.json` with observed proofs.
- [ ] Run focused tests and `scripts/run-tests.sh --changed`; run `lat check` after graph edits.
- [ ] If dashboard changes, run check, i18n and build; show `scripts/e2e.sh --dry-run` and ask for mode before e2e.
- [ ] Open implementation PRs as drafts until checks and install proof are attached. Keep unrelated Cleanup Lab work in separate PRs.

## Optional public distribution

- [ ] Confirm current public-directory policy for local stdio servers, host permissions, privacy and metadata.
- [ ] Submit only after local plugin behavior and distribution requirements are met.
