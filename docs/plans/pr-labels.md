# Pull request labels

Canonical labels for open PRs on `keyvanarasteh/os-lab`. Agents apply them when opening or updating a draft ([AGENTS.md](../../AGENTS.md#parallel-agents), [CONTRIBUTING.md](../../CONTRIBUTING.md#landing-a-branch)).

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

When opening a draft PR:

1. Add `ACTIVE` and a priority (`MID` unless the plan says otherwise).
2. Switch to `ON-HOLD` when the Todo stops and the branch is parked.
3. Raise or lower priority with a single replace — never leave two priority labels.

## Migration from older labels

| Old (optional) | Replace with |
| --- | --- |
| `critical` | `CRITICAL` |
| `important` | `PRIORITY-LEVEL-HIGH` |

Remove the old label after adding the new one. Keep issue-oriented labels (`bug`, `enhancement`, `documentation`, …) as needed.

Same label names as qLar (`keyvanarasteh/qLar` → `agents-app/docs/plans/pr-labels.md`) and aQ (`docs/plans/pr-labels.md`) so the three repos stay aligned.
