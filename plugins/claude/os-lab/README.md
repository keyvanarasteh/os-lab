# OS Lab plugin for Claude Code

Guarded MCP tools and skills for the os-lab security labs on this computer. Use it only on
systems and apps you own or are authorized to test.

## Install

From an os-lab checkout:

```bash
python3 scripts/claude-plugin.py install
```

Or by hand:

```bash
claude plugin marketplace add /path/to/os-lab
claude plugin install os-lab@os-lab
```

## Options

| Option | Meaning |
| --- | --- |
| `repo_path` | Your os-lab checkout. Empty works when the marketplace was added from it. |
| `console_port` | Local console port, default 5050. |
| `python_command` | Interpreter that starts the server, default `python3`. |
| `update_check` | Daily check at session start for a newer published plugin. Off by default. |

## Claude Desktop

```bash
python3 scripts/claude-plugin.py extension-install   # build, preview, open in Claude Desktop
python3 scripts/claude-plugin.py updates --online    # Claude Code and Claude Desktop
```

Claude Desktop asks you to confirm the install and to choose your checkout folder. Run
`extension-install` again to update. Turn the daily check on with
`python3 scripts/claude-plugin.py configure --auto-check on`.

## Use

- `/os-lab:doctor` checks the setup.
- `/os-lab:setup` previews and applies changes.
- `/os-lab:<lab>` loads guidance for one lab.

The session start check prints nothing when healthy; it uses the network only with `update_check`. It needs `python3`
or `python` on `PATH`. Licensed under Apache 2.0.
