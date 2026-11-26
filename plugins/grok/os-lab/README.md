# os-lab Grok Build plugin

Local stdio MCP connection to the guarded os-lab server, with setup and doctor skills
plus generated lab skills.

## Install

```bash
python3 scripts/grok-plugin.py install
```

Set `OSLAB_ROOT` when the package is copied away from the checkout.

## Safety

Management tools are `grok_plugin_*`. Install/update/uninstall run only from
an interactive terminal. MCP apply refuses agent writes.
