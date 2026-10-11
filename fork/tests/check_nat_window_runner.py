"""Dry and explicit CPU fake-worker runner coverage; no device entry."""
from pathlib import Path
import sys,json,os,struct,time,subprocess,hashlib,unittest.mock,signal,ctypes
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'));import nat_window_runner as w
out=ROOT/'evidence/nat-window-runner-tests-v6';out.mkdir(exist_ok=False);spec_path=out/'FROZEN.json';w.freeze(spec_path);spec=json.loads(spec_path.read_text());spec.update(device={},driver={'files':spec['driver_files']},explicit_CPU_test_identity=True);spec_path.write_text(json.dumps(spec,indent=2)+'\n');w.verify_files(spec)
class Fake:
 def __init__(self,mode='valid'):self.mode=mode;self.calls=0;self.guards=0
 def preflight(self,approval):
  self.guards+=1
  if self.mode=='invisible':raise RuntimeError('host/render invisible')
  if self.mode=='expire-after-guard' and self.guards==2:approval['deadline_monotonic']=0
  return {'explicit_CPU_fixture':True}
 def run(self,row,cfg,budget,args,env):
  self.calls+=1;receipts=Path(cfg['receipt_directory']);receipts.mkdir()
  identity=json.loads((w.CANDIDATE/row['case']/'source-identity.json').read_text());plan=json.loads(Path(cfg['plan']).read_text())
  depths=[row['depth']] if row['kind']=='direct' else {'target':[2],'two_io_handoffs':[2,1],'root_order_a':[1,2],'root_order_b':[2,1]}[row['case']]
  roots=[cfg['roots'][0]] if row['kind']=='direct' else [g['root_id'] for g in identity['gateways']]
  raws=[]
  for n,(root,depth) in enumerate(zip(roots,depths)):
   d=receipts/f'call-{n:02d}';d.mkdir();words=w.simulate(plan,root,depth,row['order']);raw=struct.pack('<772I',*words)
   if self.mode=='bad-buffer':raw=raw[:-1]+bytes([raw[-1]^1])
   initial=[0]*772;initial[:6]=[1,root,depth,63,31,192];initial[13]=row['order'];initial[-4:]=words[-4:]
   (d/'input.bin').write_bytes(struct.pack('<772I',*initial));(d/'output.bin').write_bytes(raw)
   (d/'receipt.json').write_text(json.dumps(dict(status='validated',native_exit=0,clean_native_exit_and_EOF=True,caller=cfg['caller'],output_sha256=hashlib.sha256(raw).hexdigest(),root=root,full_Nat_argument=depth,order=row['order'])));raws.append(raw)
  b=json.loads(Path(budget).read_text());b['reserved_calls']+=row['calls'];Path(budget).write_text(json.dumps(b))
  stdout=raws[0] if row['kind']=='direct' else (w.CANDIDATE/row['case']/('cpu-reference-t'+str(row['threads'])+'.stdout')).read_bytes()
  if self.mode=='extra-frame':stdout+=b'x'
  return subprocess.CompletedProcess(args,2 if self.mode=='exit-failure' else 0,stdout,b'Nat validated handoff\n'*row['calls'] if row['kind']=='host' else b'')
def approval():return dict(schema='bend-nat-assigned-window-v1',admitted=True,assigned_window='CPU-FAKE-ONLY',spec_sha256=w.sha(spec_path),start_monotonic=time.monotonic(),deadline_monotonic=time.monotonic()+600,max_calls=36,device={},driver={'files':spec['driver_files']})
rows=[]
for mode in ['valid','invisible','bad-buffer','extra-frame','exit-failure']:
 a=out/(mode+'-approval.json');a.write_text(json.dumps(approval()));fake=Fake(mode)
 try:result=w.execute(spec_path,a,out/mode,os.getppid(),test_backend=fake)
 except RuntimeError:assert mode!='valid'
 else:assert mode=='valid' and result['charged_calls']==36 and len(result['rows'])==30
 result=json.loads((out/mode/'RESULT.json').read_text());assert result['revoked'] and result['GPU_dispatches']==0
 if mode!='valid':assert fake.calls<2
 for cfg in (out/mode).glob('call-*/config.json'):assert json.loads(cfg.read_text())['admitted'] is False
 assert json.loads((out/mode/'budget.json').read_text())['deadline_monotonic']==0
 rows.append({'mode':mode,'fake_invocations':fake.calls,'revoked':True})
# Reserve all two handoffs and 20 seconds before launching any host.
b=out/'capacity.json';b.write_text(json.dumps(dict(deadline_monotonic=time.monotonic()+100,max_calls=36,reserved_calls=35)))
for calls,seconds in [(2,100),(1,19)]:
 try:w.capacity(b,calls,time.monotonic()+seconds,20)
 except RuntimeError:pass
 else:raise AssertionError('partial host reserve accepted')
# Guard consumed the window: immediately-before-launch reserve recheck rejects.
fake=Fake();a=out/'guard-expiry-approval.json';a.write_text(json.dumps(approval()))
original=w.capacity;count=0
def expire_on_recheck(*args):
 global count
 count+=1
 if count==2:raise RuntimeError('guard consumed deadline')
 return original(*args)
with unittest.mock.patch.object(w,'capacity',side_effect=expire_on_recheck):
 try:w.execute(spec_path,a,out/'guard-expiry',os.getppid(),test_backend=fake)
 except RuntimeError:pass
 else:raise AssertionError('expiry after guard accepted')
assert fake.calls==0
# Actual host-scope preflight in this sandbox must reject before a child/device.
try:w.host_preflight({'device':{'node':'/no/render'},'driver':{}})
except (RuntimeError,OSError):pass
else:raise AssertionError('invisible device accepted')
# Exact own child group timeout kills and reaps; no Vulkan executable involved.
try:w.child_run(['/usr/bin/python3','-c','import time;time.sleep(5)'],dict(os.environ),0.05)
except subprocess.TimeoutExpired:pass
else:raise AssertionError('child timeout ignored')
try:w.bind_parent(1)
except RuntimeError:pass
else:
 if os.getppid()!=1:raise AssertionError('wrong parent accepted')
# Runner-owned child gets SIGKILL when its actual parent disappears.
# A test subreaper adopts it solely so we can verify and reap the owned child.
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
marker=out/'owned-child-pid.txt'
parent=os.fork()
if parent==0:
 code="import os,time;open("+repr(str(marker))+",'w').write(str(os.getpid()));time.sleep(10)"
 w.child_run(['/usr/bin/python3','-c',code],dict(os.environ),12)
 os._exit(0)
limit=time.monotonic()+3
while not marker.exists() and time.monotonic()<limit:time.sleep(.01)
assert marker.exists();child=int(marker.read_text());os.kill(parent,signal.SIGKILL);os.waitpid(parent,0)
_,status=os.waitpid(child,0);assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
# Repeated real cancellation while cleanup writes run must defer, not raise.
original_write=Path.write_text
for mode in ['cleanup-signals','first-config-write-failure']:
 saved_handlers={sig:signal.getsignal(sig) for sig in [signal.SIGTERM,signal.SIGINT,signal.SIGALRM]};saved_timer=signal.getitimer(signal.ITIMER_REAL)
 target=out/mode;approval_path=out/(mode+'-approval.json');approval_path.write_text(json.dumps(approval()));fired=[]
 def hooked_write(path,data,*args,**kwargs):
  if path.parent.name=='call-00' and path.name=='config.json' and '"admitted": false' in data and not fired:
   fired.append(str(path))
   if mode=='cleanup-signals':
    os.kill(os.getpid(),signal.SIGTERM);os.kill(os.getpid(),signal.SIGINT);os.kill(os.getpid(),signal.SIGTERM)
   else:raise OSError('injected first config revocation failure')
  return original_write(path,data,*args,**kwargs)
 with unittest.mock.patch.object(Path,'write_text',hooked_write):
  try:w.execute(spec_path,approval_path,target,os.getppid(),test_backend=Fake())
  except RuntimeError:pass
  else:raise AssertionError('cleanup failure/cancellation not reported')
 assert all(signal.getsignal(sig)==handler for sig,handler in saved_handlers.items()) and signal.getitimer(signal.ITIMER_REAL)==saved_timer
 # The exclusive lock must have been released after cleanup failure/cancellation.
 import fcntl
 with open('/tmp/bend-nat-exclusive-window.lock','a') as check_lock:fcntl.flock(check_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 result=json.loads((target/'RESULT.json').read_text());assert fired and result['status']=='failed'
 attempts=result['revocation_attempts'];assert len(attempts)==31 and attempts[0]['kind']=='budget' and attempts[0]['revoked']
 assert json.loads((target/'budget.json').read_text())['deadline_monotonic']==0
 for cfg in sorted(target.glob('call-*/config.json'))[1:]:assert json.loads(cfg.read_text())['admitted'] is False
 if mode=='cleanup-signals':assert len(result['cleanup_deferred_signals'])==3 and result['revoked']
 else:assert result['cleanup_errors'][0]['phase']=='config-write' and not result['revoked']
 rows.append({'mode':mode,'all31_revocations_attempted':True,'budget_expired':True})
# Corrupt first config and budget reads still cause disabled writes and all attempts.
corrupt=out/'corrupt-revocation';corrupt.mkdir();paths=[corrupt/'one.json',corrupt/'two.json'];paths[0].write_text('invalid');paths[1].write_text('{"admitted":true}');budget=corrupt/'budget.json';budget.write_text('invalid');summary={'status':'passed'};w.revoke_all(paths,budget,summary)
assert summary['revoked'] and len(summary['cleanup_errors'])==2 and summary['status']=='failed'
assert all(json.loads(p.read_text())['admitted'] is False for p in paths);assert json.loads(budget.read_text())['deadline_monotonic']==0
# Even a failed FIRST budget write must not prevent any config attempt.
blocked=out/'budget-write-failure';blocked.mkdir();paths=[blocked/'one.json',blocked/'two.json'];budget=blocked/'budget.json'
for p in paths:p.write_text('{"admitted":true}')
budget.write_text('{"reserved_calls":2}');summary={'status':'passed'}
def fail_budget_write(path,data,*args,**kwargs):
 if path==budget:raise OSError('injected budget expiry write failure')
 return original_write(path,data,*args,**kwargs)
with unittest.mock.patch.object(Path,'write_text',fail_budget_write):w.revoke_all(paths,budget,summary)
assert not summary['revoked'] and summary['status']=='failed' and summary['cleanup_errors'][0]['phase']=='budget-write'
assert summary['revocation_attempts'][0]['kind']=='budget' and all(x['revoked'] for x in summary['revocation_attempts'][1:])
assert all(json.loads(p.read_text())['admitted'] is False for p in paths)
(out/'RESULT.json').write_text(json.dumps(dict(scope='explicit CPU fake worker and real CPU process lifetime only',GPU_dispatches=0,cases=rows,full_matrix_fake_calls=36,whole_host_capacity_and_time_reserve=True,guard_expiry_before_launch=True,invisible_device_rejected=True,owned_child_timeout_killed_reaped=True,parent_loss_killed_and_reaped_owned_child=True,all_failure_configs_and_budgets_revoked=True,repeated_signals_during_cleanup_deferred=True,first_config_write_failure_still_attempts_budget_and_remaining=True,corrupt_config_budget_reads_use_disabled_fallback=True,budget_revocation_first=True,budget_write_failure_still_attempts_all_configs=True,handlers_timer_lock_restored_after_cleanup_failures=True),indent=2)+'\n')
print('Frozen dry identities, 36-call fake matrix, first failure/revocation/reserves/host visibility/CPU child timeout PASS')
