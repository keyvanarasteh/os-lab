import hashlib;VIOLATION_STATUSES=('REFUSED_OUT_OF_SCOPE','REFUSED_PROMPT_INJECTION');RESET_STATUSES=('EXECUTED','ALLOWED','CIRCUIT_RESET')
class EmergencyKillSwitchError(RuntimeError):
 def __init__(self,reason,*,consecutive_violations,max_violations,state='OPEN (LOCKED)',last_violation_status=''):super().__init__(reason);self.reason=reason;self.consecutive_violations=consecutive_violations;self.max_violations=max_violations;self.state=state;self.last_violation_status=last_violation_status
 def to_dict(self):return{'error':'EmergencyKillSwitchError','state':self.state,'consecutive_violations':self.consecutive_violations,'max_violations':self.max_violations,'last_violation_status':self.last_violation_status,'reason':self.reason}
class SubagentCircuitBreaker:
 def __init__(self,max_violations=3,*,audit_logger=None):
  if int(max_violations)<1:raise ValueError('max_violations >= 1 required')
  self.max_violations=int(max_violations);self._audit_logger=audit_logger;self.consecutive_violations=self.total_violations=self.total_trips=0;self._locked=False;self.last_violation_status=self.last_violation_reason='';self.unlock_history=[]
 @property
 def is_locked(self):return self._locked
 @property
 def state(self):return 'OPEN (LOCKED)' if self._locked else 'CLOSED (ARMED)'
 def check_before_step(self):
  if self._locked:raise EmergencyKillSwitchError(f'Locked ({self.state}): {self.consecutive_violations}/{self.max_violations}',consecutive_violations=self.consecutive_violations,max_violations=self.max_violations,state=self.state,last_violation_status=self.last_violation_status)
 def record_outcome(self,status,reason=''):
  if status in VIOLATION_STATUSES:
   self.consecutive_violations+=1;self.total_violations+=1;self.last_violation_status,self.last_violation_reason=(status,reason)
   if self.consecutive_violations>=self.max_violations:
    if not self._locked:self.total_trips+=1
    self._locked=True;return True
   return False
  if status in RESET_STATUSES:self.consecutive_violations=0;return False
  return self._locked
 def reset_with_human_token(self,operator,reason,*,audit_logger=None):
  if not isinstance(operator,str)or not operator.strip():raise ValueError('Non-empty operator required')
  if not isinstance(reason,str)or not reason.strip():raise ValueError('Non-empty reason required')
  op,rsn=(operator.strip(),reason.strip());self._locked=False;self.consecutive_violations=0;evt={'operator':op,'reason':rsn,'state':self.state,'total_trips':self.total_trips};lg=audit_logger if audit_logger is not None else self._audit_logger
  if lg is not None:ph=hashlib.sha256(f'{op}:{rsn}'.encode('utf-8')).hexdigest();e=lg.log_step(target='localhost',port=None,command=f'circuit-breaker reset --operator {op}',status='CIRCUIT_RESET',duration_ms=0.0,output_summary=f'UNLOCK operator={op}: {rsn}',matched_rule='human_operator_override',ai_disclosure={'agent_id':f'human-operator:{op}','model':'human-in-the-loop','reasoning':rsn,'human_approved':True,'tool_name':'circuit_breaker','prompt_hash':ph,'prompt_summary':f'Reset by {op}'});evt.update({'seq':e['seq'],'entry_hash':e['entry_hash'],'timestamp':e['timestamp']})
  self.unlock_history.append(evt);return evt
 def summary(self):return{'state':self.state,'is_locked':self._locked,'consecutive_violations':self.consecutive_violations,'max_violations':self.max_violations,'total_violations':self.total_violations,'total_trips':self.total_trips,'last_violation_status':self.last_violation_status,'last_violation_reason':self.last_violation_reason,'unlock_history':list(self.unlock_history)}
