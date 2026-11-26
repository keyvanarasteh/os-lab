# Claude Code

Preferred: install the [os-lab plugin](../../claude/os-lab/README.md), which adds the server,
lab skills and a setup check:

```bash
python3 <REPO>/scripts/claude-plugin.py install
```

Server only, without the plugin (do not use both):

```bash
claude mcp add os-lab -- python3 <REPO>/console/mcp_server.py
```

Optional: copy or symlink `console/mcp_skills/*/SKILL.md` into your Claude skills path
so the agent loads lab-specific guidance with the MCP tools.
