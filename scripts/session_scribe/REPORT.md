# PENT-20 — Pentest Session Scribe: Scoped, Logged, AI-Disclosed

- **Öğrenci / Ders:** Aydın Arda Demiralp (`@aardademiralp`) · `MYO062` · [PR #275](https://github.com/keyvanarasteh/os-lab/pull/275) (`feat/pent-20-session-scribe`) · [`PENT-20.json`](../../reservations/PENT-20.json)
- **Ortam & Video:** Python 3.11+ Stdlib · [YouTube Kanıt Videosu](https://youtu.be/VFLu1myMy_o)

| Gereksinim | Modül | Özet |
|---|---|---|
| Scope Guard | [`scope_guard.py`](scope_guard.py), [`scope.json`](scope.json) | CIDR, `*.lab.local`/`localhost`, port, komut allowlist |
| Prompt Shield | [`prompt_guard.py`](prompt_guard.py) | Jailbreak, Base64/Hex/ROT13, `$AWS_SECRET`/`/etc/shadow` |
| Kill-Switch | [`circuit_breaker.py`](circuit_breaker.py) | 3 ihlalde `OPEN (LOCKED)`; insan tokenı ile `CIRCUIT_RESET` |
| DLP | [`redactor.py`](redactor.py) | Bearer, JWT, API/AWS key, parola, PEM -> `[REDACTED:<TYPE>]` |
| MITRE ATT&CK | [`mitre_mapper.py`](mitre_mapper.py) | Teknik/taktik (`T1046`, `T1595.002`, `T1059`), risk, skor/100 |
| Audit Log | [`audit_logger.py`](audit_logger.py) | SHA-256 JSONL zinciri ve `TAMPER_DETECTED` |
| AI Subagent | [`subagent.py`](subagent.py) | Zorunlu `AIDisclosure`, `subprocess(shell=False)`/`--simulate` |
| Merkle/SARIF | [`forensic_exporter.py`](forensic_exporter.py) | İkili Merkle kökü, SARIF v2.1.0, `EVIDENCE_MANIFEST.json` |
| Rapor/4-Tab UI | [`report_signer.py`](report_signer.py), [`html_dashboard.py`](html_dashboard.py) | HMAC-SHA256 `.sig` ve `SESSION_DASHBOARD.html` |
| CLI/Showcase | [`cli.py`](cli.py), [`__main__.py`](__main__.py) | `init`, `check-scope`, `exec`, `verify-logs`, `export-report`, `verify-report`, `demo`, `showcase` |
| Test/CI | [`tests/test_session_scribe.py`](tests/test_session_scribe.py), [`run-tests.sh`](../../scripts/run-tests.sh) | 42 birim testi, `android-lab`, [`lat.md/tooling.md`](../../lat.md/tooling.md) |

```bash
python scripts/session_scribe/cli.py showcase --out-dir /tmp/pent20-showcase
python -m unittest discover -s scripts/session_scribe/tests -v
```

- **AI-Use Disclosure:** `agent_id`, `model`, `reasoning`, `human_approved`, `tool_name`, `prompt_hash` loglanır; Antigravity IDE desteğiyle geliştirildi ve **Aydın Arda Demiralp** tarafından doğrulandı.
