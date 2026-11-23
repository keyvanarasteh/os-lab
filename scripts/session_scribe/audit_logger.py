import datetime as _dt,hashlib,hmac,json,os;from dataclasses import asdict,dataclass;from pathlib import Path;from.mitre_mapper import MitreMapper;from.redactor import SecretRedactor;GENESIS_HASH='0'*64;VALID_STATUSES=('ALLOWED','REFUSED_OUT_OF_SCOPE','REFUSED_PROMPT_INJECTION','EXECUTED','CIRCUIT_RESET','KILL_SWITCH_TRIPPED')
def utc_now_iso():return _dt.datetime.now(_dt.timezone.utc).isoformat().replace('+00:00','Z')
def compute_entry_hash(e):payload={k:v for k,v in e.items()if k!='entry_hash'};return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
@dataclass(frozen=True)
class ChainVerificationResult:
 valid:bool;status:str;total_entries:int;verified_entries:int;failed_seq:int|None=None;reason:str='';head_hash:str=GENESIS_HASH
 def to_dict(self):return asdict(self)
def verify_log_chain(log_path):
 p=Path(log_path);tot=ver=0;bad=lambda seq,rsn,hd=GENESIS_HASH:ChainVerificationResult(False,'TAMPER_DETECTED',tot,ver,seq,rsn,hd)
 if not p.exists()or not p.is_file():return bad(None,f'Audit log missing: {p}')
 try:lines=p.read_text(encoding='utf-8').splitlines()
 except(OSError,UnicodeDecodeError)as exc:return bad(None,f'Read failed: {exc}')
 if not lines:return ChainVerificationResult(True,'EMPTY',0,0,None,'Empty audit log.',GENESIS_HASH)
 tot,ep=(len(lines),GENESIS_HASH)
 for idx,ln in enumerate(lines,1):
  if not ln.strip():return bad(idx,f'Blank line #{idx}',ep)
  try:e=json.loads(ln)
  except json.JSONDecodeError as exc:return bad(idx,f'Bad JSON #{idx}: {exc}',ep)
  if not isinstance(e,dict):return bad(idx,f'Not object #{idx}',ep)
  seq=e.get('seq')
  if not isinstance(seq,int)or isinstance(seq,bool)or seq!=idx:return bad(idx,f'Seq mismatch at #{idx}: {seq!r}',ep)
  ph=e.get('prev_hash')
  if not isinstance(ph,str)or not hmac.compare_digest(ph,ep):return bad(seq,f'prev_hash mismatch at #{seq}',ep)
  sh=e.get('entry_hash')
  if not isinstance(sh,str)or len(sh)!=64:return bad(seq,f'Bad entry_hash at #{seq}',ep)
  rc=compute_entry_hash(e)
  if not hmac.compare_digest(sh,rc):return bad(seq,f'Digest mismatch at #{seq}',ep)
  ep=sh;ver+=1
 return ChainVerificationResult(True,'VALID',tot,ver,None,f'Chain verified ({ver}/{tot}).',ep)
class AuditLogger:
 def __init__(self,log_path,session_id='pent20-lab-session'):
  self.log_path=Path(log_path);self.session_id=session_id;self.log_path.parent.mkdir(parents=True,exist_ok=True);self._seq,self._last_hash=(0,GENESIS_HASH);self._redactor,self._mitre_mapper=(SecretRedactor(),MitreMapper())
  if not self.log_path.exists():self.log_path.touch()
  else:
   lines=[ln for ln in self.log_path.read_text(encoding='utf-8').splitlines()if ln.strip()]
   if lines:last=json.loads(lines[-1]);self._seq,self._last_hash=(int(last['seq']),str(last['entry_hash']))
 def log_step(self,*,target,command,status,duration_ms=0.0,output_summary='',ai_disclosure=None,port=None,matched_rule=None,timestamp=None,redacted_count=0,mitre=None):
  if status not in VALID_STATUSES:raise ValueError(f"Invalid status '{status}'")
  cr,or_=(self._redactor.redact(command),self._redactor.redact(output_summary));md=dict(mitre)if mitre is not None else self._mitre_mapper.map_step(cr.redacted_text,status=status).to_dict();nseq=self._seq+1;e={'seq':nseq,'timestamp':timestamp or utc_now_iso(),'session_id':self.session_id,'target':target,'port':port,'command':cr.redacted_text,'status':status,'duration_ms':round(float(duration_ms),3),'output_summary':or_.redacted_text,'redacted_count':int(redacted_count)+cr.redacted_count+or_.redacted_count,'matched_rule':matched_rule,'mitre':md,'risk_level':str(md.get('risk_level','LOW')),'ai_disclosure':ai_disclosure if ai_disclosure is not None else{},'prev_hash':self._last_hash};e['entry_hash']=compute_entry_hash(e)
  with self.log_path.open('a',encoding='utf-8',newline='\n')as fh:
   fh.write(json.dumps(e,sort_keys=True,ensure_ascii=False)+'\n');fh.flush()
   try:os.fsync(fh.fileno())
   except OSError:pass
  self._seq,self._last_hash=(nseq,e['entry_hash']);return e
 def read_entries(self):return[json.loads(ln)for ln in self.log_path.read_text(encoding='utf-8').splitlines()if ln.strip()]if self.log_path.exists()else[]
 def verify(self):return verify_log_chain(self.log_path)
