# Pull request labels

Optional **activity** and **priority** labels for open PRs on `keyvanarasteh/os-lab`. They help agents and maintainers triage parked vs in-rotation work. They do **not** replace os-lab's existing PR standards.

## What these labels do not change

Keep following the repo as written:

- [CONTRIBUTING.md](../../CONTRIBUTING.md) — one logical change per PR, reservations, checks, [landing a branch](../../CONTRIBUTING.md#landing-a-branch), Conventional Commits
- [.github/PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md) — Summary, Type of change, Component, How was this tested, Proof, Checklist
- [AGENTS.md](../../AGENTS.md) — worktrees, test limits, no `dashboard/dist` in PRs, rebase/landing order
- Existing GitHub labels such as `bug`, `enhancement`, `documentation`, `good first issue`, `help wanted` — keep using them

Do not add qLar-only body sections (`## Plan`, `## Todo`, `## Deploy`) to os-lab PRs unless a separate os-lab rule says so.

## Activity (pick one)

| Label | Meaning |
| --- | --- |
| `ACTIVE` | In active rotation — being worked, or ready to resume soon. |
| `ON-HOLD` | Parked. Prefer this over leaving a stale draft unmarked when work has stopped. |

Do not put both on the same PR.

## Priority (pick one)

| Label | Meaning |
| --- | --- |
| `CRITICAL` | Must land before other open work on the same area. |
| `PRIORITY-LEVEL-HIGH` | High priority; schedule ahead of `MID` and `LOW`. |
| `MID` | Normal priority; the default when none of the others fit. |
| `LOW` | Low priority; defer behind the labels above. |

Do not stack multiple priority labels on one PR. If priority changes, replace the previous priority label.

## Agents

When opening a PR (still fill the os-lab template and run the usual checks):

1. Add `ACTIVE` and a priority (`MID` unless the task or user says otherwise).
2. Switch to `ON-HOLD` when work stops and the branch is parked.
3. Raise or lower priority with a single replace — never leave two priority labels.

## Migration from older labels

| Old | Replace with |
| --- | --- |
| `critical` | `CRITICAL` |
| `important` | `PRIORITY-LEVEL-HIGH` |

Remove the old label after adding the new one.

Same activity/priority **names** as qLar and aQ for cross-repo triage; process and PR body rules stay os-lab's own.
