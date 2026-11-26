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

## Use

- `/os-lab:doctor` checks the setup.
- `/os-lab:setup` previews and applies changes.
- `/os-lab:<lab>` loads guidance for one lab.

The session start check reads files only and prints nothing when healthy. It needs `python3`
or `python` on `PATH`. Licensed under Apache 2.0.
