---
name: setup
description: Install or reconfigure the os-lab Claude plugin with a preview and the user's approval.
disable-model-invocation: true
argument-hint: "[install|update|configure|enable|disable]"
---

# os-lab plugin setup

1. Call `plugin_doctor`, then `plugin_status`.
2. Pick the action: `$ARGUMENTS` if given, else `install` when the plugin is absent and `update` when present.
3. Call `plugin_plan` with that action and scope `user` unless the user asked for another scope.
4. Show every command and warning from the plan and ask the user to approve it.
5. Only after approval call `plugin_apply` with the plan's `token` and `confirm: true`.
6. Call `plugin_verify`, then say whether a restart or `/reload-plugins` is needed.

`plugin_apply` refuses `uninstall` and `remove-duplicate`. Give the user the terminal command
from the plan and let them run it; do not run it for them.
Never edit Claude settings files by hand.
