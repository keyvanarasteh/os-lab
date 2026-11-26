# Codex plugin: complete local integration plan

Branch: `codex/ai-agent-plugin-plan`. Implementation checklist: [TODO-codex-plugin.md](TODO-codex-plugin.md).
Status: planning draft; no Codex plugin is implemented by this branch.

## Goal

Ship an installable os-lab plugin for Codex CLI and Codex in the ChatGPT desktop app. A user should discover it from this repository, install it, find focused lab skills, connect to the existing guarded MCP server, diagnose missing prerequisites, and verify real tool discovery. The plugin must make the existing safety boundaries visible and preserve them.

This plan is independent of the uncommitted Claude plugin work in `feat/ai-agent-plugins`. Share only stable MCP server and skill-generation interfaces after that work lands; do not copy its Claude-specific install commands, config, or permission assumptions.

## Baseline from `origin/master` (`e2ebebf46`, 2026-11-26)

| Area | Present | Gap |
| --- | --- | --- |
| MCP server | `console/mcp_server.py`, stdio, lab tools/resources/prompts, guarded writes | No bundled Codex plugin connection or plugin setup path |
| Codex scaffold | `plugins/mcp/codex/config.toml` with `<REPO>` | Manual copy and placeholder replacement |
| Skills | `console/mcp_skills/` | No packaged Codex skills or sync check |
| Other clients | Claude plugin worktree in progress; `plugins/mcp/` fragments for seven hosts | Avoid shared-name and config collisions |
| Verification | `console/mcp_verification.json` and MCP host tests | No Codex plugin install/launch proof |

## Product and packaging decisions

1. Use a portable root `plugins/codex/os-lab/plugin.json` with the Agent Plugins schema. Put skills at `skills/`, the server declaration at root `mcp.json`, and Codex-specific presentation/onboarding in `extensions.com.openai`. Add `.codex-plugin/plugin.json` only if a tested Codex client needs the compatibility format. Do not maintain two competing metadata sources.
2. Add `.agents/plugins/marketplace.json` at repository root with a local `./plugins/codex/os-lab` source and an available install policy. Codex resolves that path from the marketplace root. Keep the marketplace scoped to this repository; do not change a user's `~/.codex/config.toml` on checkout.
3. A local marketplace install loads a copied plugin from the Codex plugin cache. A launcher inside the package therefore cannot assume `../console` exists. Resolve the checkout through an explicit, documented path, `OSLAB_ROOT`, or a verified local source path. If none resolves, return a useful diagnostic without executing an unrelated checkout. Validate paths with realpath and a bounded, recognizable repository signature.
4. Use the existing `console/mcp_server.py` as the one server. The plugin must not duplicate lab actions or weaken the scope guard, macOS arming, WinApps allowlist, or confirmation rules. Keep the old manual Codex fragment as a compatibility route, with duplicate-connection detection and migration guidance.
5. Skills are goal-specific instructions around MCP tools, not another command surface. Generate lab skill copies from `console/mcp_skills/` where compatible, with a deterministic build and drift check. Add focused `setup` and `doctor` skills that state what to inspect, how to handle missing tools, and when to stop. Preserve explicit user instructions over skill defaults.
6. Keep setup and status checks read-only. Any installer or updater that writes Codex or marketplace state must show an exact preview, require a fresh confirmation, and verify the result. Never silently enable capabilities, install host software, edit managed settings, or use a broad shell command supplied by an MCP caller.

## Functional coverage

### Package and discover

- Portable manifest, OpenAI extension, local marketplace entry, license, README, optional assets.
- Validate schema, path containment, file existence, duplicate names, source path, plugin version and metadata. Check a package copied away from the checkout; reject links that escape the package.
- Verify discovery in Codex CLI and the desktop plugin browser. Record observed client versions and platform in test evidence.

### Connect and diagnose

- Declare a stdio MCP server in `mcp.json` using the supported portable transport syntax confirmed in a live client. Resolve Python and the checkout without requiring shell interpolation in configuration. Keep stderr useful and stdout MCP-only.
- Provide a package-local launcher/doctor with structured results for Python, checkout, MCP server startup, plugin files, Codex CLI availability/version, marketplace visibility, connection duplication, and per-platform caveats. A missing checkout should yield an actionable diagnostic, not an opaque process exit.
- Test initialize, `tools/list`, `resources/list`, and `prompts/list` against the installed connection. Compare required tool names and annotations with the checkout. Distinguish unsupported host UI from missing MCP tools.
- Avoid assuming that a Codex plugin can install itself from an MCP tool. Prefer the plugin browser or documented CLI for installation; any automation needs an explicit, tested approval path.

### Skills and user flow

- `setup`: inspect prerequisites, show exact installation/configuration steps, confirm before writes, then verify.
- `doctor`: report failures, their source and next action; never claim healthy from file presence alone.
- Lab skills: map each existing `console/mcp_skills/` workflow to packaged Codex guidance and test references to live tool names.
- README: CLI and desktop install, local checkout/path configuration, update, disable, uninstall, troubleshooting, and manual fragment migration.

### Security and compatibility

- Test path spoofing, symlink escape, stale checkout, malformed config, missing Python, duplicate server registration, server crash/timeout, and partial install.
- Audit any write flow for fixed argument lists, one-use preview state, refusal on changed state, timeouts, and secret-free logging. Do not include uninstall as an MCP write unless a human-only approval path is proven.
- Test macOS, Linux and Windows command resolution where supported; mark untested platforms rather than claiming parity. Keep local-only stdio packaging separate from public-directory submission requirements.
- Do not turn on macOS control or WinApps input. Verify read-only and guarded tool annotations survive the plugin connection.

## Delivery sequence

Keep each stage reviewable. Do not merge this plan branch as if it shipped the plugin.

| Stage | Deliverable | Gate |
| --- | --- | --- |
| 0 | Confirm Codex client versions, schema, stdio syntax, copied-cache behavior and repo marketplace discovery | Findings and exact commands recorded in TODO |
| 1 | Manifest, marketplace, launcher, README and first `doctor`/`setup` skills | Local package resolves from both checkout and copied cache; failure explains fix |
| 2 | Generated lab skills and drift checker | Every packaged skill references real tools; generation is deterministic |
| 3 | Read-only status/check/verify and optional previewed setup helper | Success and failure fixtures, real MCP handshake and tool list |
| 4 | Desktop/CLI install proof, cross-platform matrix, docs and knowledge graph | Fresh-profile install, update, disable, uninstall and re-install documented |
| 5 | Optional public submission | Only after local release is stable and public-directory rules for local servers are met |

For any dashboard addition, first build types, stores, API calls and usable pages; then run `npm run check`, `npm run test:i18n`, `npm run build`, and the agreed e2e mode. Before `scripts/e2e.sh`, show its `--dry-run` and ask the user which mode to run. For plugin and console changes run `scripts/run-tests.sh --changed`, focused MCP tests, script syntax checks, and `lat check` after graph edits. Do not commit `dashboard/dist`.

## Decisions to validate in Stage 0

1. Exact portable local stdio `mcp.json` fields and supported placeholder/environment behavior in current Codex CLI and desktop.
2. Whether repo marketplace discovery follows worktree root automatically and whether restart is required for source refresh.
3. How the installed plugin obtains the checkout path after it is copied to cache on each supported OS.
4. Whether Codex CLI exposes enough read-only plugin status to automate `doctor` without parsing private files.
5. Whether UI resources from this stdio server render in the current desktop client; keep plain tool results usable either way.
6. Whether the Claude branch lands shared MCP changes; rebase before implementation and reuse stable interfaces only.

## References

- [OpenAI: package a plugin](https://developers.openai.com/plugins/build/plugins) — portable manifest, marketplace, Codex extension and local cache behavior (reviewed 2026-11-26).
- [OpenAI: build skills](https://developers.openai.com/plugins/build/skills) — skill format, boundaries and test cases (reviewed 2026-11-26).
- [OpenAI: plugin example](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins) — compatibility manifest and MCP example (reviewed 2026-11-26).
- Repository: `lat.md/lat.md`, `lat.md/tooling.md`, `docs/PLAN-mcp-coverage.md`, `plugins/mcp/README.md`.
