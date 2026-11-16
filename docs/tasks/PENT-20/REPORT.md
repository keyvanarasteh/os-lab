# PENT-20 — Pentest Session Scribe: Scoped, Logged, AI-Disclosed

- **Öğrenci / Ders:** Aydın Arda Demiralp (`@aardademiralp`) · `MYO062` · [PR #275](https://github.com/keyvanarasteh/os-lab/pull/275) (`feat/pent-20-session-scribe`) · [`PENT-20.json`](../../../reservations/PENT-20.json)
- **Kod & Video:** [`scripts/session_scribe/`](../../../scripts/session_scribe/) (Python Stdlib) · [YouTube Kanıt Videosu](https://youtu.be/VFLu1myMy_o)

| Gereksinim | Modül | Özet |
|---|---|---|
| Scope Guard | [`scope_guard.py`](../../../scripts/session_scribe/scope_guard.py), [`scope.json`](../../../scripts/session_scribe/scope.json) | CIDR, `*.lab.local`/`localhost`, port, komut allowlist |
| Prompt Shield | [`prompt_guard.py`](../../../scripts/session_scribe/prompt_guard.py) | Jailbreak, Base64/Hex/ROT13, `$AWS_SECRET`/`/etc/shadow` |
| Kill-Switch | [`circuit_breaker.py`](../../../scripts/session_scribe/circuit_breaker.py) | 3 ihlalde `OPEN (LOCKED)`; insan tokenı ile `CIRCUIT_RESET` |
| DLP | [`redactor.py`](../../../scripts/session_scribe/redactor.py) | Bearer, JWT, API/AWS key, parola, PEM -> `[REDACTED:<TYPE>]` |
| MITRE ATT&CK | [`mitre_mapper.py`](../../../scripts/session_scribe/mitre_mapper.py) | Teknik/taktik (`T1046`, `T1595.002`, `T1059`), risk, skor/100 |
| Audit Log | [`audit_logger.py`](../../../scripts/session_scribe/audit_logger.py) | SHA-256 JSONL zinciri ve `TAMPER_DETECTED` |
| AI Subagent | [`subagent.py`](../../../scripts/session_scribe/subagent.py) | Zorunlu `AIDisclosure`, `subprocess(shell=False)`/`--simulate` |
| Merkle/SARIF | [`forensic_exporter.py`](../../../scripts/session_scribe/forensic_exporter.py) | İkili Merkle kökü, SARIF v2.1.0, `EVIDENCE_MANIFEST.json` |
| Rapor/4-Tab UI | [`report_signer.py`](../../../scripts/session_scribe/report_signer.py), [`html_dashboard.py`](../../../scripts/session_scribe/html_dashboard.py) | HMAC-SHA256 `.sig` ve `SESSION_DASHBOARD.html` |
| CLI/Showcase | [`cli.py`](../../../scripts/session_scribe/cli.py), [`__main__.py`](../../../scripts/session_scribe/__main__.py) | 8 alt komut + 10 aşamalı `showcase` |
| Test/CI | [`test_session_scribe.py`](../../../scripts/session_scribe/tests/test_session_scribe.py), [`run-tests.sh`](../../../scripts/run-tests.sh) | 42 birim testi, `android-lab`, [`lat.md/tooling.md`](../../../lat.md/tooling.md) |

- **AI-Use Disclosure:** Adım başına `agent_id`, `model`, `reasoning`, `human_approved`, `tool_name`, `prompt_hash` kaydedilir; Antigravity IDE desteğiyle geliştirildi ve **Aydın Arda Demiralp** tarafından doğrulandı.
