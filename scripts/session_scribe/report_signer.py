import hashlib;import hmac;import json;import os;import secrets;from dataclasses import asdict,dataclass;from pathlib import Path;from.audit_logger import GENESIS_HASH,AuditLogger,utc_now_iso,verify_log_chain;from.forensic_exporter import ForensicExporter;from.html_dashboard import generate_html_dashboard;from.mitre_mapper import MitreMapper,compute_compliance_score;from.redactor import SecretRedactor;from.scope_guard import ScopeGuard;KEY_ENV_VAR='PENT20_SIGNING_KEY';DEFAULT_KEY_FILENAME='session_signing.key'
@dataclass(frozen=True)
class ReportVerificationResult:
 valid:bool;status:str;report_path:str;sig_path:str;expected_sha256:str|None;actual_sha256:str|None;reason:str
 def to_dict(self):return asdict(self)
def _key_bytes(k):
 raw=k if isinstance(k,bytes)else k.encode('utf-8')if isinstance(k,str)else b''
 if not raw:raise ValueError('Signing key must be non-empty bytes or str.')
 return raw
def _get_key(*,secret_key,key_path,base_dir,create):
 if secret_key is not None:return(_key_bytes(secret_key),None)
 if(ev:=os.environ.get(KEY_ENV_VAR)):return(_key_bytes(ev),None)
 kp=Path(key_path)if key_path is not None else base_dir/DEFAULT_KEY_FILENAME
 if kp.exists():
  t=kp.read_text(encoding='utf-8').strip()
  if not t:raise ValueError(f'Empty key file: {kp}')
  return(t.encode('utf-8'),kp)
 if not create:raise FileNotFoundError(f'Signing key missing at {kp}. Set {KEY_ENV_VAR} or pass --key.')
 kp.parent.mkdir(parents=True,exist_ok=True);g=secrets.token_hex(32);kp.write_text(g+'\n',encoding='utf-8')
 try:os.chmod(kp,384)
 except OSError:pass
 return(g.encode('utf-8'),kp)
def _md(v):return str('' if v is None else v).replace('|','\\|').replace('\n',' ').replace('\r',' ')
def sign_report(report_path,sig_path=None,secret_key=None,key_path=None):
 rp=Path(report_path)
 if not rp.is_file():raise FileNotFoundError(f'Report missing: {rp}')
 sp=Path(sig_path)if sig_path else Path(f'{rp}.sig');rb=rp.read_bytes();kb,kf=_get_key(secret_key=secret_key,key_path=key_path,base_dir=sp.parent,create=True);p={'version':1,'algorithm':'HMAC-SHA256','hash_algorithm':'SHA-256','report_file':rp.name,'report_bytes':len(rb),'content_sha256':hashlib.sha256(rb).hexdigest(),'hmac_sha256':hmac.new(kb,rb,hashlib.sha256).hexdigest(),'key_fingerprint':hashlib.sha256(kb).hexdigest()[:16],'signed_at':utc_now_iso()}
 if kf is not None:p['key_file']=kf.name
 sp.parent.mkdir(parents=True,exist_ok=True);sp.write_text(json.dumps(p,indent=2)+'\n',encoding='utf-8');return p
def verify_report(report_path,sig_path=None,secret_key=None,key_path=None):
 rp,sp=(Path(report_path),Path(sig_path)if sig_path else Path(f'{report_path}.sig'));bad=lambda r,exp=None,act=None:ReportVerificationResult(False,'SIGNATURE INVALID / TAMPER DETECTED',str(rp),str(sp),exp,act,r)
 if not rp.is_file():return bad(f'Report missing: {rp}')
 if not sp.is_file():return bad(f'Sig missing: {sp}',None,hashlib.sha256(rp.read_bytes()).hexdigest())
 try:sd=json.loads(sp.read_text(encoding='utf-8'))
 except(OSError,UnicodeDecodeError,json.JSONDecodeError)as e:return bad(f'Corrupt sig JSON: {e}')
 if not isinstance(sd,dict):return bad('Sig JSON must be an object.')
 rb=rp.read_bytes();asha,esha,ehmac=(hashlib.sha256(rb).hexdigest(),sd.get('content_sha256'),sd.get('hmac_sha256'))
 if not isinstance(esha,str)or not isinstance(ehmac,str):return bad('Sig missing hash fields.',esha if isinstance(esha,str)else None,asha)
 if not hmac.compare_digest(asha,esha):return bad(f'SHA-256 mismatch: {esha[:12]} != {asha[:12]}',esha,asha)
 ikp=sp.parent/Path(sd['key_file']).name if key_path is None and isinstance(sd.get('key_file'),str)and(sp.parent/Path(sd['key_file']).name).exists()else key_path
 try:kb,_=_get_key(secret_key=secret_key,key_path=ikp,base_dir=sp.parent,create=False)
 except(FileNotFoundError,ValueError)as e:return bad(str(e),esha,asha)
 if not hmac.compare_digest(hmac.new(kb,rb,hashlib.sha256).hexdigest(),ehmac):return bad('HMAC-SHA256 mismatch.',esha,asha)
 return ReportVerificationResult(True,'SIGNATURE VALID',str(rp),str(sp),esha,asha,'SHA-256 and HMAC-SHA256 verified.')
def generate_session_report(*,log_path,scope_path,report_path,sig_path=None,html_path=None,sarif_path=None,manifest_path=None,signing_key=None,key_path=None,circuit_breaker_info=None):
 lp,sp,rp=(Path(log_path),Path(scope_path),Path(report_path));sig_p,html_p=(Path(sig_path)if sig_path else Path(f'{rp}.sig'),Path(html_path)if html_path else rp.parent/'SESSION_DASHBOARD.html');sarif_p,man_p=(Path(sarif_path)if sarif_path else rp.parent/'SESSION_FINDINGS.sarif.json',Path(manifest_path)if manifest_path else rp.parent/'EVIDENCE_MANIFEST.json');g=ScopeGuard.from_file(sp);cr=verify_log_chain(lp);log=AuditLogger(lp,session_id=g.session_id)if lp.exists()else None;ents=log.read_entries()if log and cr.status!='TAMPER_DETECTED' else[]
 if not ents and lp.exists():
  for raw in lp.read_text(encoding='utf-8').splitlines():
   if raw.strip():
    try:
     if isinstance((o:=json.loads(raw)),dict):ents.append(o)
    except json.JSONDecodeError:pass
 red,mp,fx=(SecretRedactor(),MitreMapper(),ForensicExporter());ex=[e for e in ents if e.get('status')=='EXECUTED'];inj=[e for e in ents if e.get('status')=='REFUSED_PROMPT_INJECTION'];ref=[e for e in ents if e.get('status')in('REFUSED_OUT_OF_SCOPE','REFUSED_PROMPT_INJECTION')];cbe=[e for e in ents if e.get('status')in('KILL_SWITCH_TRIPPED','CIRCUIT_RESET')];mk=fx.build_merkle_tree([str(e.get('entry_hash',''))for e in ents if e.get('entry_hash')]);mr=str(mk['merkle_root']);cb=circuit_breaker_info or{'state':'OPEN (LOCKED)' if cbe and cbe[-1].get('status')=='KILL_SWITCH_TRIPPED' else 'CLOSED (ARMED)','total_trips':sum((1 for e in cbe if e.get('status')=='KILL_SWITCH_TRIPPED')),'resets_count':sum((1 for e in cbe if e.get('status')=='CIRCUIT_RESET')),'consecutive_violations':0,'max_violations':3};cp,si,ga=(compute_compliance_score(ents,chain_valid=cr.valid),g.summary(),utc_now_iso());lns=['# PENT-20 Pentest Session Report','','## 1. Session Summary','| Field | Value |','|---|---|',f"| Session / Scope | `{_md(si['session_id'])}` / {_md(si['name'])} |",f"| Auth / Generated | {_md(si['authorization'])} / `{ga}` |",f"| Counts (Tot/Exec/Ref/DLP) | {len(ents)}/{len(ex)}/{len(ref)}/{cp['redacted_secrets']} |",f"| Score / Chain / Merkle | {cp['score']}/100 ({_md(cp['grade'])}) / **{cr.status}** / `{mr}` |",f"| Circuit Breaker | `{_md(cb.get('state', 'CLOSED (ARMED)'))}` ({int(cb.get('total_trips', 0))}) |",'','## 2. Authorized Scope',f"- CIDRs:{si['allowed_cidrs']} Domains:{si['allowed_domains']} Ports:{si['allowed_ports']} Cmds:{si['allowed_commands']}",'','## 3. Audit Trail','| Seq | Target | Command | MITRE | Risk | DLP | Status | Output |','|---:|---|---|---|---|---|---:|---|']+[f"| {e.get('seq', '?')} | `{_md(e.get('target', ''))}` | `{_md(red.redact_text(str(e.get('command', '')))[0])}` | `{_md((e.get('mitre') or mp.map_step(str(e.get('command', '')), status=str(e.get('status', ''))).to_dict()).get('technique_id'))}` | `{_md(e.get('risk_level', 'LOW'))}` | {int(e.get('redacted_count') or 0)} | **{_md(e.get('status', ''))}** | {_md(red.redact_text(str(e.get('output_summary', '')))[0])} |" for e in ents]+['','## 4. Blocked Out-of-Scope & Policy Violations','| Seq | Target | Command | Reason |','|---:|---|---|---|']+[f"| {e.get('seq', '?')} | `{_md(e.get('target', ''))}` | `{_md(red.redact_text(str(e.get('command', '')))[0])}` | {_md(red.redact_text(str(e.get('output_summary', '')))[0])} |" for e in ref]+['','## 5. Hash-Chain & Merkle Summary',f'- Genesis:`{GENESIS_HASH}` Head:`{cr.head_hash}` Merkle:`{mr}`','','## 6. AI-Use Disclosure Appendix','| Seq | Agent | Model | Tool | Approved | Prompt Hash | Reasoning |','|---:|---|---|---|---|---|---|']+[f"| {e.get('seq', '?')} | `{(ai := (e.get('ai_disclosure') or {})).get('agent_id', '-')}` | `{ai.get('model', '-')}` | `{ai.get('tool_name', '-')}` | `{ai.get('human_approved', False)}` | `{ai.get('prompt_hash', '-')}` | {_md(ai.get('reasoning', '-'))} |" for e in ents]
 rp.parent.mkdir(parents=True,exist_ok=True);rp.write_text('\n'.join(lns)+'\n',encoding='utf-8');sig=sign_report(rp,sig_path=sig_p,secret_key=signing_key,key_path=key_path);sar=fx.export_sarif(entries=ents,scope_info=si,sarif_path=sarif_p,log_filename=lp.name);up=[p for p in(sp,lp,rp,sig_p,sarif_p)if p.exists()];ext={'compliance_score':cp['score'],'audit_chain_status':cr.status,'sarif_findings':sar['total_findings'],'circuit_breaker_state':cb.get('state')};pm=fx.export_evidence_manifest(session_id=str(si.get('session_id','session')),entries=ents,artifact_paths=up,manifest_path=man_p,extra_metadata=ext);generate_html_dashboard(entries=ents,scope_info=si,chain_result=cr,compliance=cp,signature=sig,generated_at=ga,html_path=html_p,merkle_info=mk,sarif_summary=sar,manifest_data=pm,circuit_breaker_info=cb);man=fx.export_evidence_manifest(session_id=str(si.get('session_id','session')),entries=ents,artifact_paths=[*up,html_p],manifest_path=man_p,extra_metadata=ext);return{'report_path':str(rp),'sig_path':str(sig_p),'html_path':str(html_p),'sarif_path':str(sarif_p),'manifest_path':str(man_p),'chain_status':cr.status,'merkle_root':mr,'merkle_tree':{'merkle_root':mr,'leaf_count':mk['leaf_count'],'tree_depth':mk['tree_depth']},'total_entries':len(ents),'executed_count':len(ex),'refused_count':len(ref),'prompt_injection_blocks':len(inj),'redacted_secrets':cp['redacted_secrets'],'compliance':cp,'signature':sig,'sarif_summary':{'sarif_path':sar['sarif_path'],'total_findings':sar['total_findings'],'rule_counts':sar['rule_counts']},'manifest':man,'circuit_breaker':cb}
