import hashlib,hmac,json;from pathlib import Path;from.audit_logger import GENESIS_HASH,utc_now_iso;SARIF_SCHEMA_URI='https://json.schemastore.org/sarif-2.1.0.json'
def _sha256_file(path):
 h=hashlib.sha256()
 with path.open('rb')as fh:
  for chunk in iter(lambda:fh.read(65536),b''):h.update(chunk)
 return h.hexdigest()
def build_merkle_tree(entry_hashes):
 leaves=[str(h).strip().lower()for h in entry_hashes if isinstance(h,str)and h.strip()]
 if not leaves:return{'merkle_root':GENESIS_HASH,'leaf_count':0,'tree_depth':1,'levels':[[GENESIS_HASH]]}
 levels,cur=([leaves],leaves)
 while len(cur)>1:w=[*cur,cur[-1]]if len(cur)%2 else list(cur);cur=[hashlib.sha256(f'{w[i]}:{w[i + 1]}'.encode('utf-8')).hexdigest()for i in range(0,len(w),2)];levels.append(cur)
 return{'merkle_root':cur[0],'leaf_count':len(leaves),'tree_depth':len(levels),'levels':levels}
def compute_merkle_root(entry_hashes):return str(build_merkle_tree(entry_hashes)['merkle_root'])
_SARIF_RULES=[{'id':rid,'name':nm,'shortDescription':{'text':desc},'fullDescription':{'text':desc},'defaultConfiguration':{'level':lvl},'properties':{'tags':[tag,'PENT-20']}}for rid,nm,desc,lvl,tag in[('PENT20-SCOPE-001','OutOfScopeTarget','Scope violation blocked','error','scope-guard'),('PENT20-PROMPT-002','PromptInjection','Prompt injection blocked','error','prompt-injection'),('PENT20-DLP-003','SecretRedacted','Secret redacted by DLP','warning','dlp'),('PENT20-CIRCUIT-004','CircuitBreakerEvent','Circuit breaker event','note','kill-switch')]]
class ForensicExporter:
 def compute_merkle_root(self,entry_hashes):return compute_merkle_root(entry_hashes)
 def build_merkle_tree(self,entry_hashes):return build_merkle_tree(entry_hashes)
 def build_sarif_payload(self,*,entries,scope_info,log_filename='session_audit.jsonl'):
  results,counts=([],{r['id']:0 for r in _SARIF_RULES})
  for e in entries:
   seq,st,tgt,out=(int(e.get('seq')or 0),str(e.get('status','')),str(e.get('target','')),str(e.get('output_summary','')));rc,mit,ai=(int(e.get('redacted_count')or 0),e.get('mitre')or{},e.get('ai_disclosure')or{});loc=[{'physicalLocation':{'artifactLocation':{'uri':log_filename},'region':{'startLine':max(1,seq)}}}];props={'seq':seq,'target':tgt,'status':st,'entry_hash':e.get('entry_hash'),'mitre_technique':mit.get('technique_id'),'risk_level':e.get('risk_level'),'agent_id':ai.get('agent_id')};sm={'REFUSED_OUT_OF_SCOPE':('PENT20-SCOPE-001','error'),'REFUSED_PROMPT_INJECTION':('PENT20-PROMPT-002','error'),'KILL_SWITCH_TRIPPED':('PENT20-CIRCUIT-004','note'),'CIRCUIT_RESET':('PENT20-CIRCUIT-004','note')}
   if st in sm:rid,lvl=sm[st];counts[rid]+=1;results.append({'ruleId':rid,'level':lvl,'message':{'text':f'[{seq}] {st} {tgt}: {out}'},'locations':loc,'properties':props})
   if rc>0:counts['PENT20-DLP-003']+=1;results.append({'ruleId':'PENT20-DLP-003','level':'warning','message':{'text':f'[{seq}] DLP masked {rc} secret(s) on {tgt}'},'locations':loc,'properties':{**props,'redacted_count':rc}})
  doc={'$schema':SARIF_SCHEMA_URI,'version':'2.1.0','runs':[{'tool':{'driver':{'name':'PENT-20 Session Scribe','semanticVersion':'2.0.0','informationUri':'https://github.com/keyvanarasteh/os-lab','rules':_SARIF_RULES}},'automationDetails':{'id':f"pent20/{scope_info.get('session_id', 'session')}"},'results':results}]};return(doc,counts)
 def export_sarif(self,*,entries,scope_info,sarif_path,log_filename='session_audit.jsonl'):dest=Path(sarif_path);dest.parent.mkdir(parents=True,exist_ok=True);doc,counts=self.build_sarif_payload(entries=entries,scope_info=scope_info,log_filename=log_filename);dest.write_text(json.dumps(doc,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');return{'sarif_path':str(dest),'total_findings':sum(counts.values()),'rule_counts':counts,'sarif':doc}
 def export_evidence_manifest(self,*,session_id,entries,artifact_paths,manifest_path,extra_metadata=None):
  dest=Path(manifest_path);dest.parent.mkdir(parents=True,exist_ok=True);mk=self.build_merkle_tree([str(e.get('entry_hash',''))for e in entries if e.get('entry_hash')]);arts,seen=([],set())
  for rp in artifact_paths:
   p=Path(rp);k=str(p.resolve())
   if k not in seen and p.exists()and p.is_file():seen.add(k);arts.append({'filename':p.name,'path':str(p),'bytes':p.stat().st_size,'sha256':_sha256_file(p)})
  man={'manifest_version':'1.0','generated_at_utc':utc_now_iso(),'session_id':session_id,'hash_algorithm':'SHA-256','merkle_root':mk['merkle_root'],'merkle_leaf_count':mk['leaf_count'],'merkle_tree_depth':mk['tree_depth'],'artifact_count':len(arts),'artifacts':arts}
  if extra_metadata:man['metadata']=extra_metadata
  dest.write_text(json.dumps(man,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');return man
 def verify_evidence_manifest(self,manifest_path):
  mp=Path(manifest_path);man=json.loads(mp.read_text(encoding='utf-8'));arts=man.get('artifacts',[]);ver,mis=(0,[])
  for it in arts:
   fn,exp=(str(it.get('filename','')),str(it.get('sha256','')));c=mp.parent/fn if fn else Path(str(it.get('path','')))
   if not c.exists():c=Path(str(it.get('path','')))
   if not c.exists()or not c.is_file():mis.append({'filename':fn,'reason':'missing'})
   elif not hmac.compare_digest((act:=_sha256_file(c)),exp):mis.append({'filename':fn,'reason':'sha256_mismatch','expected':exp,'actual':act})
   else:ver+=1
  return{'valid':not mis and ver==len(arts),'verified_files':ver,'total_files':len(arts),'mismatches':mis,'merkle_root':man.get('merkle_root')}
