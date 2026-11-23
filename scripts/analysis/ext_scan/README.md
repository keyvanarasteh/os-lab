# ext_scan — browser extension scanner (PENT-02)

Static scanner for unpacked Chrome/Firefox extensions (Manifest V2 and V3). It reports
risky permissions and dangerous code patterns (`eval`, hidden `eval`, `Function`,
`executeScript`, injected iframes/scripts, cookie reads) and flags two-stage payloads:
code that downloads text and runs it. Python standard library only.

> **Lab use only.** Scan extensions you wrote or are allowed to test. The samples in `lab/`
> were written for this task; every URL in them points to `127.0.0.1`.

```bash
cd scripts/analysis
python -m ext_scan scan ext_scan/lab/two-stage-loader          # text report
python -m ext_scan scan ext_scan/lab/two-stage-loader --json   # full JSON
python -m ext_scan scan path/to/extension --fail-on high       # CI gate, exit 3
python -m pytest ext_scan/tests -q
```

Exit codes: `0` ok, `2` no or broken `manifest.json`, `3` grade at or above `--fail-on`.

**Score** = capability (manifest, max 40) + behaviour (code, max 60; each rule counts once).
Grades: low < 20 ≤ medium < 45 ≤ high < 70 ≤ critical. Permissions alone stop at medium.

| Sample | Expected |
|---|---|
| `lab/clean-notes` | 0, low (mentions `eval(` only in a comment and a string) |
| `lab/over-privileged` | 40, medium (harmless code, too many permissions) |
| `lab/two-stage-loader` | 100, critical (fetch → `self['ev'+'al']`, cookie exfiltration, hidden iframe) |

Files: `manifest.py` (permissions, CSP), `patterns.py` (code rules), `scanner.py` (score,
report), `__main__.py` (CLI), `tests/`. The full report is in
[`docs/tasks/PENT-02/REPORT.md`](../../../docs/tasks/PENT-02/REPORT.md).
