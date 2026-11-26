# os-lab Cursor plugin

Local stdio MCP connection to the guarded os-lab server, with setup and doctor skills
plus generated lab skills.

## Install

```bash
python3 scripts/cursor-plugin.py install
```

Set `OSLAB_ROOT` when the package is copied away from the checkout.

## Safety

Management tools are `cursor_plugin_*`. Install/update/uninstall run only from
an interactive terminal. MCP apply refuses agent writes.
