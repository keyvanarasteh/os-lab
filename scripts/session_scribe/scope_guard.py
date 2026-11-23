import datetime as _dt;import ipaddress;import json;import os;import re;import shlex;import urllib.parse;from dataclasses import asdict,dataclass;from pathlib import Path;DEFAULT_SCOPE_PATH=Path(__file__).with_name('scope.json');MAX_SCOPE_BYTES,MAX_TARGET_LENGTH,MAX_COMMAND_LENGTH=(256*1024,2048,4096);_LBL='[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?';_HOST_RE=re.compile(f'^{_LBL}(?:\\.{_LBL})*$');_DATE_RE=re.compile('^\\d{4}-\\d{2}-\\d{2}$');_NUM_RE=re.compile('^(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)(?:\\.(?:0x[0-9a-f]+|0[0-7]+|[0-9]+)){0,3}$');_URL_RE=re.compile('https?://[^\\s\'\\"`<>]+',re.I);_HP_RE=re.compile('(?:\\[[0-9a-fA-F:]+\\]|[A-Za-z0-9.-]+):[0-9]{1,5}');_METAS=(';','&&','||','|','`','$(','>','<','\n','\r');_SCHEMES={'http','https','ws','wss','tcp','ssh'};_EXTS={'py','json','jsonl','md','txt','log','sig','key','sh','ps1','csv','xml','html','yml','yaml','js','ts','apk','so'};_BAD_WILD={'*','*.*','*.com','*.net','*.org','*.io','com.*','net.*','org.*'}
class ScopeViolationError(PermissionError):
 def __init__(self,target,reason,violation_type='OUT_OF_SCOPE',rule=None):super().__init__(reason);self.target,self.reason,self.violation_type,self.rule=(target,reason,violation_type,rule)
 def to_dict(self):return{'error':'ScopeViolationError','violation_type':self.violation_type,'target':self.target,'reason':self.reason,'rule':self.rule}
def _err(t,r,vt='OUT_OF_SCOPE',rule=None):raise ScopeViolationError(str(t),r,vt,rule)
@dataclass(frozen=True)
class ScopeCheckResult:
 allowed:bool;target:str;matched_rule:str|None;reason:str;port:int|None=None;command:str|None=None
 def to_dict(self):return asdict(self)
def _ip(v):
 try:a=ipaddress.ip_address(v);return a.ipv4_mapped if isinstance(a,ipaddress.IPv6Address)and a.ipv4_mapped is not None else a
 except ValueError:return None
def _extract_ports_from_spec(spec):
 ports=[]
 for raw in spec.split(','):
  it=raw.strip()
  if not it:_err(spec,f'Empty port spec: {spec}','OUT_OF_SCOPE_PORT')
  if '-' in it:
   b=it.split('-')
   if len(b)!=2 or not b[0].isdigit()or(not b[1].isdigit()):_err(spec,f'Bad port range: {it}','OUT_OF_SCOPE_PORT')
   s,e=(int(b[0]),int(b[1]))
   if s<1 or e>65535 or s>e or(e-s>1024):_err(spec,f'Invalid/broad range: {it}','OUT_OF_SCOPE_PORT')
   ports.extend(range(s,e+1))
  else:
   if not it.isdigit()or not 1<=(p:=int(it))<=65535:_err(spec,f'Bad port: {it}','OUT_OF_SCOPE_PORT')
   ports.append(p)
 return ports
class ScopeGuard:
 def __init__(self,scope_path=None,scope_data=None):
  self.scope_path=Path(scope_path)if scope_path is not None else None if scope_data is not None else DEFAULT_SCOPE_PATH;raw=self._val(scope_data if scope_data is not None else self._read(self.scope_path));self._raw=raw;self.session_id=str(raw.get('session_id','pent20-lab-session'));self.name=str(raw.get('name','Authorized Lab Scope'));self.authorization=str(raw['authorization']);self.expires=self._exp(raw.get('expires'));self.allowed_cidrs=tuple(raw['allowed_cidrs']);self.allowed_domains=tuple((d.lower()for d in raw['allowed_domains']));self.allowed_ports=frozenset((int(p)for p in raw['allowed_ports']));self.allowed_commands=frozenset((c.lower()for c in raw['allowed_commands']));self.forbidden_flags=tuple((str(f)for f in raw.get('forbidden_flags',())));self._nets=[]
  for c in self.allowed_cidrs:
   n=ipaddress.ip_network(c,strict=True)
   if isinstance(n,ipaddress.IPv6Network)and n.network_address.ipv4_mapped is not None:n=ipaddress.IPv4Network((n.network_address.ipv4_mapped,max(0,n.prefixlen-96)),strict=False)
   self._nets.append((c,n))
  self._exact={p for p in self.allowed_domains if not p.startswith('*.')};self._wild=[(p,p[1:])for p in self.allowed_domains if p.startswith('*.')]
 @classmethod
 def from_file(cls,p):return cls(scope_path=p)
 @classmethod
 def from_dict(cls,d):return cls(scope_data=d)
 @staticmethod
 def _read(p):
  if not p.is_file():_err(p,f'Scope missing: {p}','MISSING_SCOPE')
  if p.stat().st_size>MAX_SCOPE_BYTES:_err(p,'Scope exceeds size limit.','INVALID_SCOPE')
  try:d=json.loads(p.read_text(encoding='utf-8'))
  except(OSError,UnicodeDecodeError,json.JSONDecodeError)as e:_err(p,f'Bad scope JSON: {e}','INVALID_SCOPE')
  if not isinstance(d,dict):_err(p,'Scope must be object.','INVALID_SCOPE')
  return d
 @staticmethod
 def _exp(v):
  if v is None:return None
  if not isinstance(v,str)or not _DATE_RE.match(v):_err(v,'expires must be YYYY-MM-DD.','INVALID_SCOPE')
  try:d=_dt.date.fromisoformat(v)
  except ValueError:_err(v,f'Bad date: {v}','INVALID_SCOPE')
  if _dt.date.today()>d:_err(v,f'Scope expired on {v}.','EXPIRED_SCOPE')
  return d
 @staticmethod
 def _val(d):
  for k in('authorization','allowed_cidrs','allowed_domains','allowed_ports','allowed_commands'):
   if k not in d:_err(k,f"Missing '{k}'.",'INVALID_SCOPE')
  if not isinstance(d['authorization'],str)or not d['authorization'].strip():_err('authorization','Non-empty auth required.','INVALID_SCOPE')
  for k in('allowed_cidrs','allowed_domains','allowed_commands'):
   if not isinstance(d[k],list)or not all((isinstance(x,str)and x.strip()for x in d[k])):_err(k,f"Bad list '{k}'.",'INVALID_SCOPE')
  if not isinstance(d['allowed_ports'],list)or not all((isinstance(p,int)and(not isinstance(p,bool))and(1<=p<=65535)for p in d['allowed_ports'])):_err('allowed_ports','Bad allowed_ports.','INVALID_SCOPE')
  for c in d['allowed_cidrs']:
   try:
    if ipaddress.ip_network(c,strict=True).prefixlen==0:_err(c,f'Wildcard CIDR forbidden: {c}','INVALID_SCOPE')
   except ValueError as e:_err(c,f'Bad CIDR {c}: {e}','INVALID_SCOPE')
  for dom in d['allowed_domains']:
   lw=dom.lower()
   if lw in _BAD_WILD or '*' in lw[2:]or(lw.startswith('*')and(not lw.startswith('*.'))):_err(dom,f'Bad domain rule: {dom}','INVALID_SCOPE')
  return d
 def _parse_t(self,t):
  if not isinstance(t,str)or not t or len(t)>MAX_TARGET_LENGTH or(t!=t.strip())or any((ord(c)<32 or ord(c)==127 or c.isspace()for c in t)):_err(str(t)[:64],'Malformed target.','MALFORMED_TARGET')
  if t.lower().startswith('file:'):_err(t,'file:// refused.','MALFORMED_TARGET')
  port,host=(None,t)
  if '://' in t:
   u=urllib.parse.urlsplit(t)
   if u.scheme.lower()not in _SCHEMES or u.username is not None or u.password is not None or(not u.hostname):_err(t,'Bad URL scheme/userinfo/host.','MALFORMED_TARGET')
   host=u.hostname
   try:port=u.port
   except ValueError:_err(t,'Bad URL port.','MALFORMED_TARGET')
  elif(ip:=_ip(t))is not None:host=str(ip)
  elif t.startswith('['):
   m=re.fullmatch('\\[([^\\]]+)\\](?::([0-9]{1,5}))?',t)
   if not m or _ip(m.group(1))is None:_err(t,'Bad [IPv6].','MALFORMED_TARGET')
   host,port=(m.group(1),int(m.group(2))if m.group(2)else None)
  elif t.count(':')==1:
   hp,pp=t.split(':',1)
   if not hp or not pp.isdigit():_err(t,'Bad host:port.','MALFORMED_TARGET')
   host,port=(hp,int(pp))
  elif ':' in t:_err(t,'Bad IPv6/port.','MALFORMED_TARGET')
  if port is not None and(not 1<=port<=65535):_err(t,f'Bad port {port}.','OUT_OF_SCOPE_PORT')
  if '%' in host:_err(t,'Zone ID refused.','MALFORMED_TARGET')
  return(host,port)
 def _chk_host(self,h,orig):
  if(ip:=_ip(h))is not None:
   for rule,net in self._nets:
    if ip.version==net.version and ip in net:return rule
   _err(orig,f'IP {ip} out of scope.','OUT_OF_SCOPE_IP')
  n=h.lower().rstrip('.')
  if not n or _NUM_RE.match(n)or(not _HOST_RE.match(n)):_err(orig,f'Bad/numeric hostname: {h}','MALFORMED_TARGET')
  if n in self._exact:return n
  for rule,sfx in self._wild:
   if n.endswith(sfx)and len(n)>len(sfx):return rule
  _err(orig,f"Domain '{n}' out of scope.",'OUT_OF_SCOPE_DOMAIN')
 def _chk_port(self,p,ctx):
  if p is not None and(not isinstance(p,int)or isinstance(p,bool)or p not in self.allowed_ports):_err(ctx,f'Port {p} not allowed.','OUT_OF_SCOPE_PORT')
 @staticmethod
 def _dom_tok(t):
  if not t or t.startswith('-')or any((c in t for c in '/\\='))or('.' not in t):return False
  ps=t.lower().rstrip('.').split('.');return len(ps)>=2 and ps[-1]not in _EXTS and all((re.fullmatch(_LBL,p)for p in ps))
 def _chk_cmd(self,cmd):
  if not isinstance(cmd,str)or not cmd.strip()or len(cmd)>MAX_COMMAND_LENGTH or any((m in cmd for m in _METAS)):_err(str(cmd)[:64],'Forbidden/empty command or shell metachar.','FORBIDDEN_COMMAND')
  lc=cmd.lower()
  for bf in self.forbidden_flags:
   if ' ' in bf and bf.lower()in lc:_err(cmd,f'Forbidden pattern: {bf}','FORBIDDEN_FLAG',bf)
  try:toks=shlex.split(cmd,posix=True)
  except ValueError as e:_err(cmd,f'Bad quotes: {e}','FORBIDDEN_COMMAND')
  if not toks:_err(cmd,'No command tokens.','FORBIDDEN_COMMAND')
  exe=os.path.basename(toks[0]).lower()
  if exe.removesuffix('.exe')not in self.allowed_commands and exe not in self.allowed_commands:_err(cmd,f"Command '{exe}' not allowed.",'FORBIDDEN_COMMAND')
  forbid={f.lower()for f in self.forbidden_flags if ' ' not in f};ep=es=False
  for tk in toks[1:]:
   tl=tk.lower()
   if tl in forbid or(es and f'--script={tl}' in forbid):_err(cmd,f'Forbidden flag: {tk}','FORBIDDEN_FLAG',tk)
   es=tl=='--script'
   if ep:
    ep=False
    for p in _extract_ports_from_spec(tk):self._chk_port(p,cmd)
    continue
   if tl in('-p','--ports'):ep=True;continue
   if tl.startswith('-p')and len(tl)>2 and tl[2].isdigit():
    for p in _extract_ports_from_spec(tk[2:]):self._chk_port(p,cmd)
    continue
   for eu in _URL_RE.findall(tk):uh,up=self._parse_t(eu);self._chk_host(uh,eu);self._chk_port(up,eu)
   if '://' in tk or(not tk.startswith('-')and _HP_RE.fullmatch(tk)):th,tp=self._parse_t(tk);self._chk_host(th,tk);self._chk_port(tp,tk)
   elif _ip(tk)is not None or self._dom_tok(tk):self._chk_host(tk,tk)
  if ep:_err(cmd,"'-p' missing port spec.",'OUT_OF_SCOPE_PORT')
 def verify(self,target,command=None,port=None):
  h,pp=self._parse_t(target);rule=self._chk_host(h,target);ep=port if port is not None else pp
  if port is not None and pp is not None and(port!=pp):_err(target,f'Port conflict: {pp} vs {port}','OUT_OF_SCOPE_PORT')
  self._chk_port(ep,target)
  if command is not None:self._chk_cmd(command)
  return ScopeCheckResult(True,target,rule,f"'{h}' matches '{rule}'.",ep,command)
 def check(self,target,command=None,port=None):
  try:return self.verify(target,command=command,port=port)
  except ScopeViolationError as e:return ScopeCheckResult(False,target,None,e.reason,port,command)
 def check_target(self,target,port=None):return self.verify(target,port=port)
 def check_command(self,command):self._chk_cmd(command);return ScopeCheckResult(True,'','allowed_commands','OK',command=command)
 def summary(self):return{'session_id':self.session_id,'name':self.name,'authorization':self.authorization,'expires':self.expires.isoformat()if self.expires else None,'allowed_cidrs':list(self.allowed_cidrs),'allowed_domains':list(self.allowed_domains),'allowed_ports':sorted(self.allowed_ports),'allowed_commands':sorted(self.allowed_commands),'forbidden_flags':list(self.forbidden_flags)}
