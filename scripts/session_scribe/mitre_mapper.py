import os;import shlex;from dataclasses import asdict,dataclass;from.redactor import SecretRedactor;RISK_LEVELS=('LOW','MEDIUM','HIGH','CRITICAL_BLOCKED');_REQUIRED_AI_FIELDS=('agent_id','model','reasoning','tool_name','prompt_hash')
@dataclass(frozen=True)
class MitreMapping:
 technique_id:str;technique_name:str;tactic_id:str;tactic_name:str;risk_level:str
 @property
 def label(self):return f'{self.technique_id} - {self.technique_name}'
 def to_dict(self):return{**asdict(self),'label':self.label}
_TOOL_GROUPS=((('nmap','nc','netcat'),('T1046','Network Service Discovery','TA0007','Discovery','MEDIUM')),(('curl','whatweb'),('T1595.002','Active Scanning: Vulnerability Scanning','TA0043','Reconnaissance','LOW')),(('nikto','gobuster'),('T1595.002','Active Scanning: Vulnerability Scanning','TA0043','Reconnaissance','MEDIUM')),(('ping','traceroute'),('T1018','Remote System Discovery','TA0007','Discovery','LOW')),(('dig','nslookup','whois'),('T1590.002','Gather Victim Network Information: DNS','TA0043','Reconnaissance','LOW')),(('frida-ps','frida-ls-devices'),('T1057','Process Discovery','TA0007','Discovery','MEDIUM')),(('adb',),('T1082','System Information Discovery','TA0007','Discovery','MEDIUM')),(('python','python3','echo','openssl'),('T1082','System Information Discovery','TA0007','Discovery','LOW')));_TOOL_MAP={t:v for tools,v in _TOOL_GROUPS for t in tools};_FALLBACK_MAPPING=('T1595','Active Scanning','TA0043','Reconnaissance','HIGH');_STATUS_OVERRIDES={'REFUSED_PROMPT_INJECTION':('T1059','Command and Scripting Interpreter (Prompt Injection)','TA0002','Execution','CRITICAL_BLOCKED'),'CIRCUIT_RESET':('T1078','Valid Accounts (Human Operator Unlock)','TA0005','Defense Evasion','LOW'),'KILL_SWITCH_TRIPPED':('T1499','Endpoint Denial of Service (Circuit Breaker Lock)','TA0040','Impact','CRITICAL_BLOCKED')}
def _extract_tokens(command):
 text=(command or '').strip()
 if not text:return[]
 try:return shlex.split(text,posix=True)
 except ValueError:return text.split()
class MitreMapper:
 def __init__(self,tool_map=None):
  self._tool_map=dict(_TOOL_MAP)
  if tool_map:self._tool_map.update(tool_map)
 def map_step(self,command,*,status='EXECUTED'):
  if status in _STATUS_OVERRIDES:return MitreMapping(*_STATUS_OVERRIDES[status])
  tokens=_extract_tokens(command);exe=os.path.basename(tokens[0]).lower().removesuffix('.exe')if tokens else '';tech_id,tech_name,tactic_id,tactic_name,risk=self._tool_map.get(exe,_FALLBACK_MAPPING);low=[t.lower()for t in tokens[1:]]
  if exe in('nmap','nc','netcat'):
   if any((f in low for f in('-sv','-a','-sc')))or('-p' in low and(i:=low.index('-p'))+1<len(low)and(',' in low[i+1]or '-' in low[i+1])):risk='HIGH'
  elif exe=='curl' and any((t in low for t in('-h','--header','-d','--data','-u','--user'))):risk='MEDIUM'
  if status=='REFUSED_OUT_OF_SCOPE':risk='CRITICAL_BLOCKED'
  return MitreMapping(tech_id,tech_name,tactic_id,tactic_name,risk)
def compute_compliance_score(entries,*,chain_valid=True):
 score=100 if chain_valid else 60;mapper,redactor=(MitreMapper(),SecretRedactor());counts={'EXECUTED':0,'ALLOWED':0,'REFUSED_OUT_OF_SCOPE':0,'REFUSED_PROMPT_INJECTION':0};circuit_events=redacted_secrets=ai_disclosed=0;risk_breakdown={lvl:0 for lvl in RISK_LEVELS}
 for entry in entries:
  st=str(entry.get('status',''))
  if st in counts:counts[st]+=1
  elif st in('CIRCUIT_RESET','KILL_SWITCH_TRIPPED'):circuit_events+=1
  redacted_secrets+=int(entry.get('redacted_count')or 0)
  if redactor.redact(str(entry.get('command',''))).redacted_count or redactor.redact(str(entry.get('output_summary',''))).redacted_count:score-=20
  ai=entry.get('ai_disclosure')or{}
  if isinstance(ai,dict)and all((isinstance(ai.get(f),str)and bool(str(ai.get(f)).strip())for f in _REQUIRED_AI_FIELDS))and isinstance(ai.get('human_approved'),bool):ai_disclosed+=1
  else:score-=15
  if st=='EXECUTED' and(not bool(ai.get('human_approved',False))):score-=25
  mitre=entry.get('mitre');risk=str(mitre['risk_level'])if isinstance(mitre,dict)and mitre.get('risk_level')in risk_breakdown else str(entry['risk_level'])if entry.get('risk_level')in risk_breakdown else mapper.map_step(str(entry.get('command','')),status=st).risk_level;risk_breakdown[risk]+=1
 score=max(0,min(100,score));grade='A+ (EXCELLENT)' if score>=95 else 'A (COMPLIANT)' if score>=85 else 'B (WARNING)' if score>=70 else 'F (NON-COMPLIANT)';ex,al,ros,rpi=(counts['EXECUTED'],counts['ALLOWED'],counts['REFUSED_OUT_OF_SCOPE'],counts['REFUSED_PROMPT_INJECTION']);return{'score':score,'grade':grade,'total_steps':len(entries),'in_scope_steps':ex+al,'executed_steps':ex,'allowed_steps':al,'blocked_steps':ros+rpi,'refused_out_of_scope':ros,'prompt_injection_blocks':rpi,'circuit_events':circuit_events,'redacted_secrets':redacted_secrets,'ai_disclosed_count':ai_disclosed,'chain_valid':bool(chain_valid),'risk_breakdown':risk_breakdown}
