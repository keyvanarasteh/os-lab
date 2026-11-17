import base64;import binascii;import codecs;import re;from dataclasses import asdict,dataclass;REFUSED_PROMPT_INJECTION='REFUSED_PROMPT_INJECTION';_OVERRIDE_PATTERNS=tuple(((k,re.compile(p))for k,p in(('INSTRUCTION_OVERRIDE','(?i)\\bignore\\s+(?:all\\s+|any\\s+)?(?:previous|prior|above|system)\\s+(?:instructions|prompts|rules|constraints|policies)\\b'),('SCOPE_OVERRIDE_ATTEMPT','(?i)\\boverride\\s+(?:the\\s+|all\\s+)?scope(?:\\.json|\\s+policy|\\s+rules|\\s+manifest)?\\b'),('GUARD_BYPASS_ATTEMPT','(?i)\\bbypass\\s+(?:the\\s+|all\\s+)?(?:scope\\s*)?(?:guard|filter|policy|check|restrictions)\\b'),('SYSTEM_PROMPT_EXPOSURE','(?i)\\bsystem\\s+prompt\\b'),('JAILBREAK_PERSONA','(?i)\\b(?:disregard\\s+(?:all\\s+)?(?:scope|safety|authorization|previous|rules)|(?:enter|switch\\s+to|act\\s+as|you\\s+are\\s+now\\s+in)\\s+(?:dan|jailbreak|unrestricted|developer|god)\\s+mode)\\b'))));_EXFIL_PATTERNS=tuple(((k,re.compile(p))for k,p in(('ENV_SECRET_EXFILTRATION','(?i)(?:\\$|\\$\\{)(?:AWS_SECRET(?:_ACCESS_KEY)?|AWS_ACCESS_KEY_ID|AWS_SESSION_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|SECRET_KEY|GITHUB_TOKEN|PENT20_SIGNING_KEY|PASSWORD|DB_PASS)\\b'),('SENSITIVE_FILE_EXFILTRATION','(?i)(?:\\b(?:cat|head|tail|less|more|type|grep|awk|sed)\\s+[^\\n]*?)?(?:/etc/shadow|/etc/passwd|~/\\.ssh/id_rsa|\\bid_rsa\\b|session_signing\\.key)\\b'),('ENV_DUMP_ATTEMPT','(?:(?:^|[;\\s|&])\\b(?:env|printenv)\\b(?=\\s*$|\\s+[A-Z_-]+|\\s*[|;>&])|(?i:\\b(?:printenv|os\\.environ|process\\.env)\\b))'))))
_EXPLICIT_ENCODING_PATTERNS=tuple(((k,re.compile(p))for k,p in(('ENCODED_PAYLOAD','(?i)\\b(?:base64\\s+-d|base64\\s+--decode|codecs\\.decode\\(|bytes\\.fromhex\\(|fromhex\\(|eval\\s*\\(\\s*compile\\b|(?:rot13|b64|base64_payload|hex_payload)\\s*:)'),('ENCODED_PAYLOAD','(?:\\\\x[0-9a-fA-F]{2}){6,}'))));_BASE64_CANDIDATE_RE=re.compile('(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])');_HEX_CANDIDATE_RE=re.compile('\\b(?:0x)?([0-9a-fA-F]{24,})\\b');_DECODED_SUSPICIOUS_RE=re.compile('(?i)\\b(?:ignore|override|bypass|scope\\.json|system\\s+prompt|shadow|passwd|aws_secret|printenv|os\\.environ|jailbreak|disregard|rm\\s+-rf|bash\\s+-c)\\b')
@dataclass(frozen=True)
class PromptThreatResult:
 safe:bool;status:str;matched_rules:tuple[str,...];reason:str;severity:str='NONE'
 def to_dict(self):return asdict(self)
class PromptInjectionError(PermissionError):
 def __init__(self,result):super().__init__(result.reason);self.result=result
 def to_dict(self):return{'error':'PromptInjectionError',**self.result.to_dict()}
def _is_mostly_printable_ascii(raw):return bool(raw)and sum((1 for b in raw if 32<=b<=126 or b in(9,10,13)))/len(raw)>=0.85
class PromptInjectionGuard:
 def _scan_plain_patterns(self,text):return[(n,m.group(0).strip())for n,pat in _OVERRIDE_PATTERNS+_EXFIL_PATTERNS+_EXPLICIT_ENCODING_PATTERNS if(m:=pat.search(text))]
 def _check_decoded(self,raw,rule,hits):
  if _is_mostly_printable_ascii(raw):
   dec=raw.decode('ascii',errors='ignore')
   if _DECODED_SUSPICIOUS_RE.search(dec)or self._scan_plain_patterns(dec):hits.append((rule,dec[:80]))
 def _scan_obfuscations(self,text):
  hits=[]
  for m in _BASE64_CANDIDATE_RE.finditer(text):
   tok=m.group(0)
   if len(tok)%4==0:
    try:self._check_decoded(base64.b64decode(tok,validate=True),'ENCODED_BASE64_PAYLOAD',hits)
    except(binascii.Error,ValueError):pass
  for m in _HEX_CANDIDATE_RE.finditer(text):
   hp=m.group(1)
   if len(hp)%2==0:
    try:self._check_decoded(bytes.fromhex(hp),'ENCODED_HEX_PAYLOAD',hits)
    except ValueError:pass
  rot=codecs.decode(text,'rot_13')
  for _,pat in _OVERRIDE_PATTERNS+_EXFIL_PATTERNS:
   if(m:=pat.search(rot)):hits.append(('ENCODED_ROT13_PAYLOAD',f'ROT13->{m.group(0).strip()}'))
  return hits
 def inspect_text(self,text,*,context='input'):
  if not text or not str(text).strip():return PromptThreatResult(True,'SAFE',(),'No threat patterns detected.','NONE')
  sample=str(text);hits=self._scan_plain_patterns(sample)+self._scan_obfuscations(sample)
  if not hits:return PromptThreatResult(True,'SAFE',(),'No threat patterns detected.','NONE')
  rules=[];snippets=[]
  for r,s in hits:
   if r not in rules:rules.append(r)
   if s and s not in snippets and(len(snippets)<3):snippets.append(s)
  return PromptThreatResult(False,REFUSED_PROMPT_INJECTION,tuple(rules),f"Prompt Injection / Jailbreak blocked in {context}: rules=[{', '.join(rules)}], matched={snippets!r}",'CRITICAL_BLOCKED')
 def inspect_prompt(self,*,prompt='',reasoning='',command=''):
  for ctx,val in(('prompt',prompt),('reasoning',reasoning),('command',command)):
   res=self.inspect_text(val,context=ctx)
   if not res.safe:return res
  return PromptThreatResult(True,'SAFE',(),'Prompt, reasoning, and command passed PromptInjectionGuard.','NONE')
