# Codex plugin: complete local integration plan

Branch: `codex/ai-agent-plugin-plan`. Implementation checklist: [TODO-codex-plugin.md](TODO-codex-plugin.md).
Status: implementation in progress. The package, generated skills, basic requirement checks, terminal-only install preview, MCP management surface and isolated CLI proof are on this branch. The TODO tracks remaining coverage.

## Goal

Ship an installable os-lab plugin for Codex CLI and Codex in the ChatGPT desktop app. A user should discover it from this repository, install it, find focused lab skills, connect to the existing guarded MCP server, diagnose missing prerequisites, and verify real tool discovery. The plugin must make the existing safety boundaries visible and preserve them.

The Claude implementation is committed at `e0ab48942` on `feat/ai-agent-plugins` but is not yet in master. This Codex branch stays on its original master base until the user confirms that merge. Rebase then, reuse stable shared MCP and skill-generation interfaces, and keep Codex-specific install commands, config, requirement rules and approval behavior separate.

## Baseline from `origin/master` (`e2ebebf46`, 2026-11-26)

| Area | Present | Gap |
| --- | --- | --- |
| MCP server | `console/mcp_server.py`, stdio, lab tools/resources/prompts, guarded writes | No bundled Codex plugin connection or plugin setup path |
| Codex scaffold | `plugins/mcp/codex/config.toml` with `<REPO>` | Manual copy and placeholder replacement |
| Skills | `console/mcp_skills/` | No packaged Codex skills or sync check |
| Other clients | Claude plugin worktree in progress; `plugins/mcp/` fragments for seven hosts | Avoid shared-name and config collisions |
| Verification | `console/mcp_verification.json` and MCP host tests | No Codex plugin install/launch proof |

## Claude implementation parity audit

Inspected `feat/ai-agent-plugins` at `e0ab48942` on 2026-11-26, including its files, tests and open TODOs. The table maps **implemented** features to required Codex work. A matching feature means equivalent user behavior under Codex's supported APIs, not a copy of Claude-only formats.

| Claude implementation | Codex deliverable or deliberate boundary |
| --- | --- |
| Marketplace, manifest, `.mcp.json`, README and license | Repo marketplace, portable `plugin.json`, `mcp.json`, README and license; validate Codex format and copied install |
| `launcher.py` resolves configured checkout, `OSLAB_ROOT`, local marketplace and serves two setup tools without a checkout | Codex launcher with verified resolution order, explicit bad-path refusal, and read-only setup-only MCP mode |
| `repo_path`, `console_port`, `python_command` user options | Codex-supported configuration for the same three needs, after live capability check; never assume Claude `${user_config.*}` works |
| Generated copies of ten lab skills and drift check | All current lab skills plus setup and doctor, deterministic build and `--check`, with Codex frontmatter and real tool references |
| Requirement catalog with source, severity, usage, review date, version gate and rule check | Codex-specific catalog covering portable manifest, OpenAI extension, marketplace, MCP, skills, cache, CLI/desktop, settings, hooks and distribution; automatic pass/fail/warn/skipped/manual results and fixtures |
| `plugin_requirements`, `plugin_doctor`, `plugin_status`, `plugin_check` | Separate `codex_plugin_*` tools so Claude's `plugin_*` names remain unambiguous after merge; status includes duplicate manual MCP entries without secrets |
| `plugin_plan`, `plugin_apply`, `plugin_verify` | Codex plan/apply/verify equivalents for supported install/update/configure/enable/disable and terminal-only removal; exact preview, expiring one-use token, state recheck, audit and installed-server handshake |
| CLI helper `build`, `check`, `doctor`, `status`, `verify`, install lifecycle | Codex helper invoking the same engine, usable before the MCP server is connected; no unsupported CLI verb is invented |
| Requirement MCP resource and guided setup prompt | Codex-named requirement resource and setup prompt, plus usable plain tool results when a client lacks prompts/resources |
| Server initialize instructions, tool annotations and large-result hints | Extend shared instructions with Codex-specific names; verify annotations, result size and UI metadata without copying Claude-only `anthropic/maxResultSizeChars` rules into Codex checks |
| SessionStart hook, silent when healthy and always nonblocking | Optional Codex lifecycle hook only where the installed client supports it; read-only, short timeout, no output when healthy, and excluded from public-directory package if policy requires |
| Status widget with refresh action | Codex status widget if supported by the target MCP Apps host; escaped content, read-only refresh and plain-text fallback |
| `.mcpb` builder for Claude Desktop | No `.mcpb` in the Codex package; prove local Codex desktop installation and copied-cache launch instead |
| Requirement checks for paths, symlink escape, frontmatter, hooks, CLI output and package shape | Codex-specific checks and success/failure fixtures, with current official sources for every rule |
| Fake CLI lifecycle tests, real isolated install, verification registry and `macos_task` refusal | Equivalent isolated Codex lifecycle proof, registered tool proofs, failure fixtures and refusal of Codex management tools inside `macos_task` |

The Claude TODO still leaves its `/mcp/` dashboard work, some documentation checks, live hook observation, Windows/Linux proof and manual `.mcpb` install open. Those are not completed Claude features. Codex should document its own `/mcp/` route only if the Codex plugin adds user-facing controls, and run the dashboard gates then. Claude's `.mcpb` manual install is not a Codex deliverable.

## Product and packaging decisions

1. Use a portable root `plugins/codex/os-lab/plugin.json` with the Agent Plugins schema. Put skills at `skills/`, the server declaration at root `mcp.json`, and Codex-specific presentation/onboarding in `extensions.com.openai`. Add `.codex-plugin/plugin.json` only if a tested Codex client needs the compatibility format. Do not maintain two competing metadata sources.
2. Add `.agents/plugins/marketplace.json` at repository root with a local `./plugins/codex/os-lab` source and an available install policy. Codex resolves that path from the marketplace root. Keep the marketplace scoped to this repository; do not change a user's `~/.codex/config.toml` on checkout.
3. A local marketplace install loads a copied plugin from the Codex plugin cache. A launcher inside the package therefore cannot assume `../console` exists. Resolve the checkout through an explicit, documented path, `OSLAB_ROOT`, or a verified local source path. A configured but invalid path must fail closed rather than fall through. If none resolves, serve only read-only setup and status tools over MCP so the client can explain the fix. Validate paths with realpath and a bounded, recognizable repository signature.
4. Use the existing `console/mcp_server.py` as the one server. The plugin must not duplicate lab actions or weaken the scope guard, macOS arming, WinApps allowlist, or confirmation rules. Keep the old manual Codex fragment as a compatibility route, with duplicate-connection detection and migration guidance.
5. Skills are goal-specific instructions around MCP tools, not another command surface. Generate all ten lab skill copies from `console/mcp_skills/` where compatible, with a deterministic build and drift check. Add focused `setup` and `doctor` skills that state what to inspect, how to handle missing tools, and when to stop. Preserve explicit user instructions over skill defaults.
6. Add Codex-specific management names (`codex_plugin_requirements`, `codex_plugin_doctor`, `codex_plugin_status`, `codex_plugin_check`, `codex_plugin_plan`, `codex_plugin_apply`, `codex_plugin_verify`) if the post-merge server can expose both integrations. Never change Claude's `plugin_*` contract just to fit Codex. Reuse generic safety and MCP helpers where possible.
7. Keep requirement, doctor, status, check, plan and verify operations read-only. Any installer or updater that writes Codex or marketplace state must show exact commands and file changes, require a fresh human approval, and verify the result. The model's `confirm: true` alone is not the human gate. Never silently enable capabilities, install host software, edit managed settings, or use a shell command supplied by an MCP caller.

## Functional coverage

### Package and discover

- Portable manifest, OpenAI extension, local marketplace entry, license, README, optional assets.
- Validate schema, path containment, file existence, duplicate names, source path, plugin version and metadata. Check a package copied away from the checkout; reject links that escape the package.
- Keep a dated Codex requirement catalog: `id`, area, severity, usage/reason, check, source URL, optional minimum client version and reviewed date. Cover manifest and extension fields, marketplace policy and source, MCP transport/schema/annotations, skill frontmatter and size guidance, cache/state, CLI/desktop, settings precedence, hooks when used, and distribution. Label unsupported components `n/a` with a reason; validate rule limits against current official pages before encoding them.
- Verify discovery in Codex CLI and the desktop plugin browser. Record observed client versions and platform in test evidence.

### Connect and diagnose

- Declare a stdio MCP server in `mcp.json` using the supported portable transport syntax confirmed in a live client. Resolve Python and the checkout without requiring shell interpolation in configuration. Keep stderr useful and stdout MCP-only.
- Provide a package-local launcher/doctor with structured results for Python, checkout, MCP server startup, plugin files, Codex CLI availability/version, marketplace visibility, connection duplication, and per-platform caveats. A missing checkout should still answer MCP with actionable setup-only tools. Distinguish bad configured root from absent root.
- Expose the seven Codex management tools listed above, with read-only and destructive annotations, strict argument schemas, useful error codes, and Codex-specific requirements. Register a requirement resource and guided setup prompt. Keep their plain results usable even if the host ignores resources, prompts or UI.
- Test initialize, `tools/list`, `resources/list`, and `prompts/list` against the installed connection. Compare required tool names, annotations and server instructions with the checkout. Distinguish unsupported host UI from missing MCP tools. Register the new tools in `console/mcp_verification.json` and refuse them inside `macos_task`.
- Avoid assuming that a Codex plugin can install itself from an MCP tool. Prefer the plugin browser or documented CLI for installation; any automation needs an explicit, tested approval path.

### Skills and user flow

- `setup`: inspect prerequisites, show exact installation/configuration steps, confirm before writes, then verify.
- `doctor`: report failures, their source and next action; never claim healthy from file presence alone.
- Lab skills: map each existing `console/mcp_skills/` workflow to packaged Codex guidance and test references to live tool names.
- CLI/helper workflow: build and drift-check skills, report requirements/checks/doctor/status, preview/apply supported changes, and verify. Use the same engine as the MCP tools so results agree.
- If Codex supports plugin lifecycle hooks in the target install, add a read-only startup check with a short timeout, no healthy output and no session-blocking failure. Test it directly and in a live session. Keep a hook-free public variant if required.
- Show installation and duplicate-connection state in a Codex-compatible status widget when host support is proven; escape all output and allow read-only refresh. The text result remains complete without the widget.
- README: CLI and desktop install, local checkout/path configuration, update, disable, uninstall, troubleshooting, and manual fragment migration.

### Security and compatibility

- Test path spoofing, symlink escape, stale checkout, malformed config, missing Python, duplicate server registration, server crash/timeout, and partial install.
- Audit any write flow for fixed argument lists, one-use preview state, refusal on changed state, timeouts, and secret-free logging. Do not include uninstall as an MCP write unless a human-only approval path is proven.
- An apply plan must bind root, action, scope, exact steps and observed install state; expire and work once. Stop on partial failure, report unrun steps, log outcomes and refusals without secrets, and reject another marketplace with the same name before running its code. Uninstall and duplicate removal should remain interactive-terminal-only unless Codex provides an independently proven human approval gate.
- Test macOS, Linux and Windows command resolution where supported; mark untested platforms rather than claiming parity. Keep local-only stdio packaging separate from public-directory submission requirements.
- Do not turn on macOS control or WinApps input. Verify read-only and guarded tool annotations survive the plugin connection.

## Delivery sequence

Keep each stage reviewable. This draft PR contains implementation in progress; the unchecked TODO items remain gates before it is ready to merge.

| Stage | Deliverable | Gate |
| --- | --- | --- |
| 0 | Confirm Codex client versions, schema, stdio syntax, copied-cache behavior and repo marketplace discovery | Findings and exact commands recorded in TODO |
| 1 | Manifest, marketplace, launcher, README, license and setup-only MCP mode | Local package resolves from checkout and copied cache; missing/bad path yields a useful tool result |
| 2 | Codex requirement catalog, seven management tools, resource/prompt and generated skills | Every rule has source and fixture; every packaged skill references real tools; generation is deterministic |
| 3 | Guarded lifecycle, CLI helper, installed-server verification and audit | Fake CLI success/refusal/partial failure; one real isolated install and handshake |
| 4 | Optional hook and status widget; shared server instructions and registry | Hook and widget are proven in supported host; plain results work without them |
| 5 | Desktop/CLI lifecycle proof, platform matrix, docs and knowledge graph | Fresh-profile install, update, disable, uninstall and re-install documented |
| 6 | Optional public submission | Only after local release is stable and public-directory rules for local servers are met |

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
