# AI agent plugins — plan (Claude first)

Branch `feat/ai-agent-plugins`. Checklist: [TODO](TODO-ai-agent-plugins.md).
Status: proposed, nothing implemented yet.

## Goal

The os-lab MCP server can describe, check, install and set up os-lab as a
complete Claude plugin:

1. **Describe** every Claude plugin requirement, with its source and whether
   os-lab uses it.
2. **Check** the plugin, the host and the current installation automatically.
3. **Install** and **set up** with a preview first and an explicit confirmation.
4. **Verify** that the installed server starts and lists its tools.

## Where master stands

Measured on `origin/master` at `e2ebebf46`.

| Area | Today | Gap |
| --- | --- | --- |
| Server | `console/mcp_server.py`, stdio, standard library, version 0.6.0, protocol `2024-11-05` | No server `instructions` |
| Tools | 141 plus 5 Windows-only, all annotated; longest name 30, longest description 273 characters; `tools/list` about 80 KB | No tool knows about plugins or clients |
| Resources, prompts | 46 resources, 6 prompts | None for plugin requirements |
| Claude Code | `plugins/mcp/claude-code/.mcp.json` with a `<REPO>` placeholder | No `plugin.json`, marketplace or hooks |
| Skills | 10 under `console/mcp_skills/`, named `os-lab-mcp-<lab>` | Copied or linked by hand |
| Claude Desktop | JSON fragment | No `.mcpb` bundle |

Related open work, to settle before Phase 3:

- [#317](https://github.com/keyvanarasteh/os-lab/pull/317) adds
  `console/mcp_clients.py` (preview → token → connect, including Claude Code and
  Claude Desktop), MCP dev mode and `scripts/mcp-dev.py`. Reuse its plan and
  token code; do not write a second one. It registers the server as
  `os-lab-macos`.
- [#306](https://github.com/keyvanarasteh/os-lab/pull/306) adds an installable
  wheel and `OSLAB_ROOT`, which points an installed copy at a checkout. The
  plugin launcher needs the same variable.

## Design

### The plugin stays thin and points at a checkout

Claude Code copies a marketplace plugin into its own cache, and files outside the
plugin folder are not copied. The server imports `console/` and reads lab
folders from the repository, so a copied plugin cannot run it by relative path.

The plugin therefore ships a small launcher that finds a checkout, in order:

1. the `repo_path` plugin option (`userConfig`, type `directory`);
2. `OSLAB_ROOT`;
3. a walk up from the plugin folder (marketplace added from a local path).

If none holds `console/mcp_server.py`, the launcher still answers MCP with only
`plugin_doctor` and `plugin_status`, which say how to set the path. A silent
start failure would leave the user nothing to act on.

Rejected: using the repository root as the plugin source (copies about 2,100
files, 44 MB, per version) and vendoring `console/` into the plugin (the labs it
drives would still be missing).

### Layout

```text
.claude-plugin/marketplace.json      marketplace "os-lab"
plugins/claude/os-lab/
  .claude-plugin/plugin.json
  .mcp.json                          server "os-lab" → launcher
  launcher.py
  skills/<lab>/SKILL.md              generated from console/mcp_skills/
  skills/setup/SKILL.md              /os-lab:setup
  skills/doctor/SKILL.md             /os-lab:doctor
  hooks/hooks.json                   SessionStart check
  hooks/session_check.py
  README.md, LICENSE
console/mcp_plugin.py                the plugin_* tools
console/claude_plugin.py             requirement catalog, checks, plans
console/claude_requirements.json     catalog data
scripts/claude-plugin.py             build | check | doctor | install | verify
```

Symlinks that leave the plugin folder are rejected, so the lab skills are
generated and committed. `scripts/claude-plugin.py build --check` fails CI when
they differ from `console/mcp_skills/`.

### Tools

| Tool | Writes | Result |
| --- | --- | --- |
| `plugin_requirements` | no | The catalog, filterable by area and status |
| `plugin_doctor` | no | Host: Claude Code and version, Python, checkout, platform, console reachability |
| `plugin_status` | no | Marketplace and plugin state from `claude plugin … --json`, plus hand-made os-lab MCP entries that would duplicate the plugin |
| `plugin_check` | no | Every catalog rule with pass, fail, warn or skipped and a fix; adds `claude plugin validate --json --strict` when the CLI is present |
| `plugin_plan` | no | The exact commands and file changes for install, update, configure, enable, disable or uninstall, with a token |
| `plugin_apply` | yes | Runs one plan: needs the token and `confirm: true` |
| `plugin_verify` | no | Starts the installed server, runs `initialize` and `tools/list`, compares with this checkout |

Also: resource `oslab://plugin/requirements`, prompt `claude_plugin_setup_flow`
and a status widget (after the tools work as plain results).

`scripts/claude-plugin.py` calls the same functions. It is how the first install
happens, because the server is not connected before something installs it.

### Requirement catalog

One JSON entry per rule: `id`, `area`, `rule`, `severity`, `usage` (`used`,
`n/a` with a reason), `check` (function name or `manual`), `source` (doc URL),
`minVersion`, `reviewedOn`.

| Area | Rules covered | os-lab |
| --- | --- | --- |
| Manifest | `name` required and not starting with `claude-`; metadata; `version`; `engines`; `defaultEnabled`; paths start with `./`, stay inside the root, no `..`; unknown keys | used |
| Marketplace | `name`, `owner`, `plugins`; entry `source`; reserved names; version precedence; `strict` | used |
| MCP server | `.mcp.json`; `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${user_config.*}`; full tool name at most 128 characters; schema property names; descriptions and instructions truncated at 4,096 characters; results over 50,000 characters saved to a file; `anthropic/maxResultSizeChars` | used |
| Skills | frontmatter on line 1; allowed fields; `description` listing limit 1,536 characters; body under 500 lines; extra fields rejected by claude.ai uploads | used |
| Hooks | `hooks/hooks.json` shape; event names; matchers; exec form; timeouts; exit codes | used (SessionStart) |
| User config | option types; `title` and `description`; `sensitive`; key syntax | used (`repo_path`, `console_port`) |
| Cache and state | copy into cache; no writes to the plugin root; state in the data folder | used |
| CLI | install, update, uninstall, enable, disable, list, details, configure, marketplace, validate; scopes; `--json` | used |
| Settings | `enabledPlugins`, `extraKnownMarketplaces`, managed allow and block lists | read only |
| Distribution | README, license, validate directory profile | used |
| Claude Desktop | `.mcpb` manifest | Phase 5 |
| Agents, commands, LSP, monitors, themes, output styles, workflows, channels, dependencies, mods | location and shape | `n/a`: nothing to ship; `commands/` is superseded by skills |
| `bin/` | claude.ai and Cowork do not install plugins that have it | `n/a`: must stay absent |

Documented limits change between Claude Code releases (this machine has 2.1.332).
Each entry records its review date, and `plugin_check` reports `skipped` rather
than `fail` when the installed version predates a rule.

### Automatic check, install and setup

- **Check:** the SessionStart hook runs a read-only check with a short timeout,
  always exits 0, stays silent when healthy and otherwise adds one line pointing
  to `/os-lab:doctor`. No network, no writes.
- **Install:** `scripts/claude-plugin.py install` shows the plan, asks, then runs
  `claude plugin marketplace add <checkout>` and
  `claude plugin install os-lab@os-lab --config repo_path=<checkout> --json`.
- **Setup:** `/os-lab:setup` walks doctor → status → plan → confirm → apply →
  verify, and ends by saying what needs a restart or `/reload-plugins`.

Nothing installs or changes configuration without a confirmation.

## Safety rules

- `plugin_apply` runs only fixed argument lists built on the server. Callers
  choose an action and a scope; they pass no command, path or marketplace source.
- A plan token binds the commands and the observed state, expires, and works
  once. A changed state refuses the token.
- Never pass `--accept-command`, never use command-type marketplace sources,
  never edit permission rules or managed settings.
- Never install host software (Claude Code, Python, SDKs): report the command.
- Duplicate hand-made entries are reported; removing one is its own plan.
- Plans, results and refusals go to an audit log. Secrets are never logged.
- `plugin_*` tools are refused inside `macos_task`.
- Writes carry `readOnlyHint: false`; uninstall also `destructiveHint: true`.

## Phases

One reviewable PR each, in order. Each ends with tests and `lat check`.

| Phase | Delivers | Done when |
| --- | --- | --- |
| 0 | Spikes for the open questions below | Answers written into this plan |
| 1 | Plugin, marketplace, launcher, generated skills | `claude plugin validate --strict` passes; a local install in a temporary `CLAUDE_CONFIG_DIR` lists the tools |
| 2 | Catalog, checks, `requirements`, `doctor`, `status`, `check` | Each rule has a passing and a failing fixture; works without the CLI |
| 3 | `plan`, `apply`, `verify`, the script, setup and doctor skills | Install, configure and uninstall round-trip against a fake CLI and once against the real one |
| 4 | SessionStart hook, server instructions, widget, `/mcp/` page, docs | Healthy start adds no text; e2e and i18n pass |
| 5 | `.mcpb` bundle for Claude Desktop | Bundle validates and installs by hand on macOS |

## Open questions (Phase 0)

1. Does `claude plugin install` work from a server that Claude Code itself
   started? The docs say `-y` is ignored inside a session. If it refuses,
   `plugin_apply` returns the command for the user to run instead.
2. What reaches the server when an optional `userConfig` value is unset: an empty
   string, the literal placeholder, or a load error?
3. `.mcp.json` takes one `command`. Windows often has no `python3`. Which
   launcher works on all three systems?
4. Does `CLAUDE_CONFIG_DIR` isolate plugin installs well enough for tests?
5. `confirm: true` is set by the model, so the real human gate is the client's
   permission prompt, which a user can turn off. Is that enough for
   `plugin_apply`, or should it also need arming from the dashboard? Proposed:
   the token flow alone for install, update and enable; the terminal script only
   for uninstall.
6. Which tool packs and validates `.mcpb`? The manifest specification does not
   say, and none is installed here.

## Out of scope

- Plugins for Codex, Cursor and other agents (the existing fragments stay).
- Submitting to Anthropic's plugin directory.
- Checking or installing third-party plugins.
- Any new device or app control.

## Sources

Read on 2026-11-26:
[manifest](https://code.claude.com/docs/en/plugins-reference),
[CLI](https://code.claude.com/docs/en/plugins/cli-reference),
[marketplace](https://code.claude.com/docs/en/plugins/marketplace-reference),
[loading](https://code.claude.com/docs/en/plugins/loading),
[MCP](https://code.claude.com/docs/en/mcp),
[skills](https://code.claude.com/docs/en/skills),
[hooks](https://code.claude.com/docs/en/hooks),
[MCPB](https://raw.githubusercontent.com/anthropics/mcpb/main/MANIFEST.md).
Parts of the CLI, marketplace, skills, hooks and MCP pages were read only as
summaries, so Phase 2 must confirm each catalog limit against its page.
