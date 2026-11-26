# OS Lab plugin for Codex

This plugin connects Codex to the guarded os-lab MCP server in a local checkout. Use it only on systems and apps you own or are authorized to test.

Set `OSLAB_ROOT` to the absolute checkout path before launching Codex when the plugin is installed from a copied package. When running directly from this repository's local marketplace, the launcher can find the checkout automatically. Python 3 must be on `PATH` as `python3`.

From a trusted checkout, open the Codex plugin browser and select the `OS Lab (local)` source. In the CLI, add the local marketplace first, then install:

```bash
codex plugin marketplace add /absolute/path/to/os-lab
codex plugin list --marketplace os-lab-local --available --json
codex plugin add os-lab@os-lab-local
```

After installation, restart the client and use the `os-lab-setup` or `os-lab-doctor` skill. Confirm that the MCP server lists tools before running a lab workflow. Run `python3 scripts/codex-plugin.py check` from the checkout to check the package and `python3 scripts/codex-plugin.py build --check` to detect generated-skill drift.

The older `plugins/mcp/codex/config.toml` is a manual MCP connection. Remove that entry if both routes register the same server. The plugin never arms macOS control or changes the lab authorization scope. License: Apache-2.0; see the packaged `LICENSE`.
