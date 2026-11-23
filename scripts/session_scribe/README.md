# PENT-20: Pentest Session Scribe — Scoped, Logged, AI-Disclosed (Subagent)

- **Geliştirici / PR:** Aydın Arda Demiralp (`@aardademiralp`) · `MYO062` · [PR #275](https://github.com/keyvanarasteh/os-lab/pull/275) (`feat/pent-20-session-scribe`)
- **Video / Raporlar:** [YouTube Kanıt Videosu](https://youtu.be/VFLu1myMy_o) · [`REPORT.md`](REPORT.md) · [`docs/tasks/PENT-20/REPORT.md`](../../docs/tasks/PENT-20/REPORT.md)

## Modüller (Python Standart Kütüphanesi)

- [`scope_guard.py`](scope_guard.py), [`scope.json`](scope.json), [`prompt_guard.py`](prompt_guard.py), [`circuit_breaker.py`](circuit_breaker.py): CIDR/domain/port/komut allowlist, Prompt Injection kalkanı ve 3-ihlal Kill-Switch.
- [`redactor.py`](redactor.py), [`mitre_mapper.py`](mitre_mapper.py), [`audit_logger.py`](audit_logger.py), [`subagent.py`](subagent.py): DLP sır maskeleme, MITRE ATT&CK + Compliance Score, SHA-256 hash zinciri ve `AIDisclosure`.
- [`forensic_exporter.py`](forensic_exporter.py), [`html_dashboard.py`](html_dashboard.py), [`report_signer.py`](report_signer.py), [`cli.py`](cli.py): Merkle Tree, SARIF v2.1.0, `EVIDENCE_MANIFEST.json`, HMAC-SHA256 `.sig`, 4 sekmeli HTML Paneli ve 10 aşamalı CLI.

```bash
python scripts/session_scribe/cli.py showcase --out-dir /tmp/pent20-showcase
python -m unittest discover -s scripts/session_scribe/tests -v
```
