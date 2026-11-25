# Agent homes: make "Review removal" work — plan (draft PR)

**Priority: critical.** The Cleanup Lab's headline action does nothing for the items that
actually fill a developer's disk. On the maintainer's own machine on 25.11.2026 the macOS
volume hit 100 % (137 MiB free), the monitor warned, and **Catalogs → AI agents & models**
showed 14 GB of agent data that the lab could measure but not remove. The maintainer had to
delete it by hand in a shell. A cleaner that cannot clean the biggest items is a broken
cleaner.

No implementation starts until the maintainer approves each task. Task series:
`CLNA-01…CLNA-08` (Cleaner, Agent homes).

## What happens today (grounded in the code)

1. `catalog/agents.json` defines `agents.zcode`, `agents.gemini`, `agents.codex`,
   `agents.claude`, `agents.opencode` with `"risk": "credentials"` and
   `"cleanable": false` ("Report-only."). `catalog/developers.json` defines
   `developers.codex-runtimes` with `"cleanable": false` ("Report-only until reviewed.").
2. `dashboard/src/views/cleanup/catalog-page.tsx`:
   - `blocked(entry)` is `entry.cleanable === false || entry.needsPrivilege` (line ~82);
   - `reviewable` is the ticked ids that are not blocked (line ~83);
   - **Review removal** is `disabled={!canWork || !reviewable.length}` (line ~137).
   So a selection made only of report-only items leaves `reviewable` empty and the button
   stays grey with no explanation.
3. The row checkbox is **not** disabled for blocked rows (line ~115), while "Select visible"
   skips them (line ~107). A user can tick rows that can never be reviewed.
4. `engine/tests/test_catalog.py` (~line 248) asserts every `agents.*` entry is
   `cleanable: false` with `risk: credentials`; the engine also refuses to plan them.

## Why it was built this way (and why we keep the safety)

The whole home folder of an agent mixes three kinds of data:

| Kind | Examples (Codex / ZCode) | Loss if deleted |
|---|---|---|
| Credentials and settings | `auth.json`, `config.toml`, `AGENTS.md`, `rules/`, `skills/`, `memories_*.sqlite` | sign-in and hand-written config gone |
| History | `sessions/`, `archived_sessions/`, `thread_history_*.sqlite` | old conversations gone |
| Regenerable bulk | `packages/`, `plugins/`, `cache/`, `generated_images/`, `computer-use/`, `worktrees/`, `cli/`, `v2/`, `logs_*.sqlite` | re-downloaded or rebuilt on next use |

Marking the **whole** home report-only was the safe default, but it also protects the bulk.
Measured on 25.11: ~/.zcode 5.2 GB (3.8 GB worktrees, 1.1 GB cli), ~/.codex 2.7 GB
(0.84 GB packages, 0.48 GB plugins, 0.46 GB sessions), ~/.cache/codex-runtimes 1.6 GB. About
9 GB was removable with zero credential loss.

**Decision:** keep the parent `agents.*` entries report-only, and add *narrow child entries*
for the regenerable bulk and (opt-in, never pre-selected) history. No catalog path may
contain a credential or config file.

## Tasks

### CLNA-01 — Child catalog entries for regenerable agent data
- [ ] `agents.codex-bulk`: `packages`, `plugins`, `cache`, `generated_images`, `computer-use`,
      `worktrees`, `attachments` under `~/.codex` (macOS, Linux, Windows `%USERPROFILE%`).
- [ ] `agents.zcode-bulk`: `worktrees`, `cli`, `v2`, `computer-use`, `tmp` under `~/.zcode`.
- [ ] `agents.gemini-bulk`: the equivalent regenerable folders under `~/.gemini` (measure
      first: list sizes on a real home, include only what the tool re-creates).
- [ ] `agents.claude-bulk`: only caches/telemetry that Claude Code re-creates; never
      `settings*.json`, `projects/`, `.credentials*`.
- [ ] `risk: medium`, `cleanable: true`, `defaultSelected: false`, `owningProcesses` set so
      the existing busy-process refusal applies, `impact` says what is re-downloaded.
- [ ] Reasoning: removes the 9 GB case without a single credential path in scope.

### CLNA-02 — History entries (opt-in)
- [ ] `agents.codex-history` (`sessions`, `archived_sessions`, `thread_history_*.sqlite`,
      `logs_*.sqlite`), `agents.zcode-history` equivalents; `risk: privacy`,
      `defaultSelected: false`, `impact: "Conversation history is lost."`.
- [ ] Never suggested by `suggest.py` (privacy risk is already excluded there; add a test).

### CLNA-03 — `developers.codex-runtimes` becomes cleanable
- [ ] Flip `cleanable` to `true`; drop the "Report-only until reviewed" note; keep
      `risk: medium`, `owningProcesses: ["codex"]`. Update the test that pins it.
- [ ] Reasoning: `impact` already says "Runtimes are downloaded again on the next use".

### CLNA-04 — Engine guard: credentials can never be in a cleanable entry
- [ ] Catalog validation (`catalog.py`) rejects a `cleanable: true` entry whose paths are
      inside a known credential/config location, or whose resolved children include
      `auth.json`, `config.toml`, `*.credentials*`, `.env`, `settings*.json` (deny-list).
- [ ] Plan builder re-checks at plan time (defence in depth) and records the refusal reason.
- [ ] Reasoning: the safety no longer depends on someone remembering not to flip a flag.

### CLNA-05 — Dashboard: explain and prevent dead selections
- [ ] Disable the row checkbox when `blocked(entry)`; add a tooltip/`aria-description`
      "Measured only — cannot be removed here".
- [ ] When `reviewable` is empty but something is ticked, show the reason under the
      disabled **Review removal** button instead of leaving it silently grey.
- [ ] "Select visible" and the row checkbox use the same predicate (one source of truth).
- [ ] Seven-locale translations for the new strings (see the i18n workflow in `lat.md`).

### CLNA-06 — Dashboard e2e
- [ ] `cleanup.spec.ts`: report-only row cannot be ticked and shows the hint; a cleanable
      agent child can be ticked and **Review removal** opens the confirm dialog with the
      exact paths and size; credentials path never appears in the dialog.

### CLNA-07 — Engine tests
- [ ] Catalog: child entries valid per `schema.json`; none contain a deny-listed file.
- [ ] Plan: planning `agents.codex-bulk` on a fixture home keeps `auth.json`/`config.toml`
      untouched; planning the parent `agents.codex` is still refused.
- [ ] `suggest.py`: history/privacy entries never suggested.

### CLNA-08 — Docs, roadmap, STATUS
- [ ] `cleanup-lab/README`/`VERIFY.md`/`STATUS.md` and the `lat.md` Cleanup Lab nodes
      describe report-only parents vs cleanable children; roadmap page gets CLNA-01…08.

## Out of scope
- Making the credential-bearing parents cleanable. Signing out of a tool stays a manual act.
- Touching `~/.claude` conversation data from the lab.

## Acceptance
1. With the 25.11 layout (zcode 5.2 GB, codex 2.7 GB, runtimes 1.6 GB), ticking the three
   `*-bulk` children and `codex-runtimes` enables **Review removal**, the dialog lists only
   regenerable paths, and cleaning frees ≈ 9 GB with `auth.json`/`config.toml` intact.
2. A selection containing only report-only parents keeps the button disabled **and says why**.
3. Engine and dashboard suites green; no credential path reachable from any cleanable entry.
