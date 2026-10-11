#!/usr/bin/env python3
"""Fixed remaining87 CPU supervisor. Default is source/protocol inspection only."""
import argparse, ctypes, hashlib, json, os, re, signal, subprocess, sys, time, resource
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'evidence'
REVIEW = E / 'cpu-v5-exact-idle-host-policy-v1'
RUNNER_SHA = '53ddaa2d2a427148c1d62e1d4c3a8a8693f892751a74ec079d74660eede3082f'
SELECTION_SHA = '58aece08b8be9da04b20433888383c8aa81d50bfdc31523960a0ab3a8ae50319'
DELTA_SHA = 'bb4000bbafa81a8379384eab50fd38a55368cd555ddf75c6b4b6493f47fae942'
STORAGE_SHA = 'd0bc2f72e9028cc09b87999e19f8d499bed672cc60229893746d178bcfbbb1e5'
OUTPUT_NAME = 'cpu-v5-remaining87-correctness-fresh-v2'
MIN_BYTES = 12 * 1024**3
PSI_MAX = .10
INTERVAL = 5
QUIET = 20
WALL = 600
GRACE = 35
KILL_WAIT = 5
PROTOCOL = dict(quiet_seconds=QUIET, monitor_seconds=INTERVAL,
 minimum_available_bytes=MIN_BYTES, maximum_PSI_some_full_avg10=PSI_MAX,
 allowed_new_swapout_pages=0, execution_wall_seconds=WALL,
 graceful_stop_seconds=GRACE, forced_cleanup_seconds=KILL_WAIT,
 startup_sampling_armed_before_Popen=True, blocking_Popen_hard_deadline_qualified=False, stage_limits_unchanged=True, sandbox_qualified=False,
 execution_authorized=False, cleanup_is_resource_admission=False, startup_gate="one-byte pipe, pause-clear before commit, cancellation latched", pause_write_failure="immediate owned cleanup, no grace", idle_host_policy="correctness-only v2: resident telemetry; exact reservation/identity/resource and overlap gates")

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok, why):
 if not ok: raise RuntimeError(why)
def pressure_ok(sample, baseline):
 return (sample['available'] >= MIN_BYTES and sample['pswpout'] == baseline
         and 0 <= sample['some'] <= PSI_MAX and 0 <= sample['full'] <= PSI_MAX)
def sample():
 mem = dict(re.findall(r'^(\w+):\s+(\d+)', Path('/proc/meminfo').read_text(), re.M))
 vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
 psi = {}
 for line in Path('/proc/pressure/memory').read_text().splitlines():
  words = line.split(); psi[words[0]] = float(dict(x.split('=') for x in words[1:])['avg10'])
 return dict(available=int(mem['MemAvailable'])*1024, pswpout=int(vm['pswpout']), **psi)
def processes():
 """Identity includes kernel start ticks; never read environment or credentials."""
 result = {}
 for p in Path('/proc').iterdir():
  if not p.name.isdigit(): continue
  try:
   text = (p/'stat').read_text(); end = text.rfind(')'); fields = text[end+2:].split()
   result[int(p.name)] = dict(start=int(fields[19]), ppid=int(fields[1]),
                             state=fields[0], comm=text[text.find('(')+1:end])
  except (FileNotFoundError, ProcessLookupError): continue
 return result
WORKER = re.compile(r'(bend|clang|hvm|deno|opencode|agy|pmi|^bun$|^native$)', re.I)
def quiet_admission(read=sample, procs=processes, clock=time.monotonic, sleep=time.sleep):
 begin = clock(); first = read(); baseline = first['pswpout']; samples = [first]
 check(pressure_ok(first, baseline), 'initial pressure gate')
 while True:
  check(not any(WORKER.search(p['comm']) for p in procs().values()), 'candidate/compiler/model worker present')
  if clock()-begin >= QUIET: return samples
  sleep(min(INTERVAL, QUIET-(clock()-begin)))
  current = read(); samples.append(current)
  check(pressure_ok(current, baseline), 'quiet pressure gate')
def discover_owned(owned, snapshot, supervisor_pid):
 # Refresh stale PID identities only after current ancestry/adoption is proven.
 changed = True
 while changed:
  changed = False
  for pid, p in snapshot.items():
   parent = snapshot.get(p['ppid'])
   inherited = parent and owned.get(p['ppid']) == parent['start']
   if p['ppid'] == supervisor_pid or inherited:
    if owned.get(pid) != p['start']: owned[pid] = p['start']; changed = True
 return owned

def alive_owned(owned, snapshot):
 return [pid for pid, start in owned.items() if pid in snapshot
         and snapshot[pid]['start'] == start and snapshot[pid]['state'] != 'Z']

def pid_identity(pid):
 try:
  text=Path('/proc',str(pid),'stat').read_text(); fields=text[text.rfind(')')+2:].split()
  return int(fields[19]), fields[0]
 except (FileNotFoundError,ProcessLookupError): return None

def signal_owned(owned, sig, identity=pid_identity, openfd=os.pidfd_open,
                 sendfd=signal.pidfd_send_signal, close=os.close):
 # Stable handle prevents signalling a different PID incarnation after recheck.
 errors=[]
 for pid,start in list(owned.items()):
  fd=None
  try:
   fd=openfd(pid,0)
   if identity(pid) == (start,'Z'): continue
   current=identity(pid)
   if current and current[0] == start and current[1] != 'Z': sendfd(fd,sig)
  except ProcessLookupError: pass
  except Exception as exc: errors.append('signal '+str(pid)+': '+repr(exc))
  finally:
   if fd is not None:
    try: close(fd)
    except Exception as exc: errors.append('pidfd close: '+repr(exc))
 return errors

def new_state(clock=time.monotonic):
 return dict(begin=clock(), stopped=None, reason=None, samples=[], errors=[])

def stop(state, reason, clock=time.monotonic):
 if state['stopped'] is None:
  state['stopped']=clock();state['reason']=reason

def safe_pause(state, pause):
 try: pause();state['pause_write_succeeded']=True
 except Exception as exc:
  state['pause_write_succeeded']=False;state['errors'].append('pause: '+repr(exc))

def tick(state, baseline, pause, read=sample, clock=time.monotonic):
 # Used both by launch-time SIGALRM and execution monitoring; never throws.
 guard=state.get('idle_guard')
 if guard is not None:
  try:guard.status()
  except Exception as exc:
   state['errors'].append('idle-host guard: '+repr(exc));stop(state,'idle-host guard refusal',clock)
 try:
  current=read();state['samples'].append(current)
  if not pressure_ok(current,baseline): stop(state,'pressure stop',clock)
 except Exception as exc:
  state['errors'].append('pressure read: '+repr(exc));stop(state,'pressure read failure',clock)
 if clock()-state['begin'] >= WALL: stop(state,'execution wall cap',clock)
 if state['stopped'] is not None: safe_pause(state,pause)

def cleanup(child, owned, state, pause, procs=processes, clock=time.monotonic,
            sleep=time.sleep, send=signal_owned, reap=os.waitpid, pid=None):
 pid=os.getpid() if pid is None else pid
 safe_pause(state,pause)
 # One budget: repeated requests cannot restart grace or forced cleanup.
 deadline=min(state['begin']+WALL+GRACE+KILL_WAIT, clock()+KILL_WAIT)
 if state['stopped'] is not None: deadline=min(deadline,state['stopped']+GRACE+KILL_WAIT)
 deadline=state.setdefault('cleanup_deadline',deadline) # A fallback cannot restart this budget.
 complete=False;empty_since=None; runner_exit=None
 while True:
  verified=False;snapshot={}
  if state.get('idle_guard') is not None:
   try:state['idle_guard'].status()
   except Exception as exc:
    text='idle-host cleanup check: '+repr(exc)
    if text not in state['errors']:state['errors'].append(text)
  try:
   snapshot=procs();discover_owned(owned,snapshot,pid);verified=True
  except Exception as exc: state['errors'].append('process scan: '+repr(exc))
  # Popen exclusively owns leader status; never waitpid(-1).
  if child is not None:
   try: runner_exit=child.poll()
   except Exception as exc: state['errors'].append('runner poll: '+repr(exc))
  state['errors'].extend(send(owned,signal.SIGTERM if empty_since is None else signal.SIGKILL))
  # Rediscover AFTER signalling: TERM handlers may fork/adopt new descendants.
  try:
   snapshot=procs();discover_owned(owned,snapshot,pid);verified=True
  except Exception as exc:
   state['errors'].append('post-signal scan: '+repr(exc));verified=False
  if verified:
   for child_pid,start in list(owned.items()):
    item=snapshot.get(child_pid)
    if child is not None and child_pid==child.pid: continue
    if item and item['start']==start and item['state']=='Z':
     try: reap(child_pid,os.WNOHANG)
     except ChildProcessError: pass
     except Exception as exc: state['errors'].append('reap: '+repr(exc))
   # Only quiescence across fresh scans can certify emptiness; not cached IDs.
   if not alive_owned(owned,snapshot) and (child is None or runner_exit is not None):
    if empty_since is None: empty_since=clock()
    elif clock()-empty_since>=.2: complete=True;break
   else: empty_since=None
  if clock() >= deadline: break
  # Force known owned handles every iteration even when enumeration fails.
  state['errors'].extend(send(owned,signal.SIGKILL))
  sleep(min(.1,max(0,deadline-clock())))
 return dict(reason=state['reason'],runner_exit=runner_exit,samples=state['samples'],
             errors=state['errors'],owned_processes=owned,process_cleanup_complete=complete,
             pause_write_succeeded=state.get('pause_write_succeeded',False),
             startup_committed=state.get('startup_committed',False),
             launch_monotonic=state['begin'],stop_monotonic=state['stopped'],
             cleanup_finished_monotonic=clock(),cleanup_deadline_monotonic=deadline)

def supervise(child, baseline, owned, pause, state=None, read=sample, procs=processes,
              clock=time.monotonic, sleep=time.sleep, send=signal_owned, reap=os.waitpid, pid=None):
 state=new_state(clock) if state is None else state
 pid=os.getpid() if pid is None else pid;next_sample=clock()
 try:
  while True:
   snapshot=procs();discover_owned(owned,snapshot,pid)
   exited=child.poll() if child is not None else None
   if child is not None and exited is not None and not alive_owned(owned,snapshot): break
   now=clock()
   if state.get('idle_guard') is not None:
    try:state['idle_guard'].status()
    except Exception as exc:
     text='idle-host guard: '+repr(exc)
     if text not in state['errors']:state['errors'].append(text)
     stop(state,'idle-host guard refusal',clock);safe_pause(state,pause)
   if now>=next_sample:
    tick(state,baseline,pause,read,clock);next_sample=now+INTERVAL
   if state['stopped'] is not None and state.get('pause_write_succeeded') is False: break
   if state['stopped'] is not None and now>=state['stopped']+GRACE: break
   if state['stopped'] is None and now-state['begin']>=WALL:
    stop(state,'execution wall cap',clock);safe_pause(state,pause)
   sleep(.1)
 except Exception as exc:
  state['errors'].append('monitor: '+repr(exc));stop(state,'monitor failure',clock)
 return cleanup(child,owned,state,pause,procs,clock,sleep,send,reap,pid)

# No preexec_fn: the exec shim sets exactly the existing file/core limits.
LIMIT_SHIM = ('import os,resource,sys\n'
 'resource.setrlimit(resource.RLIMIT_FSIZE,(2097152,2097152))\n'
 'resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
 'os.umask(0o077)\n'
 'fd=int(sys.argv[1]); token=os.read(fd,1); os.close(fd)\n'
 'if token != b"G": sys.exit(125)\n'
 'os.execv(sys.argv[2],sys.argv[2:])\n')
STARTUP_SIGNALS={signal.SIGINT,signal.SIGTERM,signal.SIGALRM}
def release_startup(state,pause,clear,write,mask=signal.pthread_sigmask,
                    pending=signal.sigpending,clock=time.monotonic):
 # The pipe is the commit point. No child work can precede pause clear.
 previous=mask(signal.SIG_BLOCK,STARTUP_SIGNALS)
 try:
  if pending() & STARTUP_SIGNALS: stop(state,'pending startup signal',clock)
  if state['stopped'] is not None: safe_pause(state,pause);return False
  clear()
  # Also catches a cancellation latched by an injected/reentrant callback.
  if pending() & STARTUP_SIGNALS: stop(state,'pending startup signal',clock)
  if state['stopped'] is not None: safe_pause(state,pause);return False
  check(write()==1,'startup pipe commit failed')
  state['startup_committed']=True
  return True
 finally: mask(signal.SIG_SETMASK,previous)

def verify_inputs(pins):
 for path,digest in pins: check(sha(path)==digest,'reviewed input changed: '+str(path))

def read_prepared_delta(path,runner):
 import types
 source=ROOT/'tools/cpu_delta_store.py';raw=source.read_bytes()
 check(hashlib.sha256(raw).hexdigest()==STORAGE_SHA,'bounded reader changed')
 module=types.ModuleType('_supervisor_bounded_reader');module.__file__=str(source)
 exec(compile(raw,str(source),'exec'),module.__dict__)
 delta=module.Store(path.parent).load()
 check(delta.get('schema')=='bend-strict-raw-golden-delta-v1','unexpected logical delta schema')
 check(len(delta['records'])==87 and len({r['path'] for r in delta['records']})==87,'exact remaining87 required')
 check(all(r['status']=='pending' and r['stages']=={} for r in delta['records']),'fresh empty receipts required')
 check(delta.get('execution_started') is False and delta.get('GPU_dispatches')==0,'fresh CPU-only delta required')
 check(delta['binding']['integration_policy_sha256']==sha(runner),'runner binding changed')
 check(delta['binding']['approved_pins']['persistence']==STORAGE_SHA,'reader binding changed')
 check(delta['binding']['output_directory']==str(path.parent),'output binding changed')
 return delta

def held_coordination(result):
 return dict(released=False, PMI_next_build_may_start=False,
 resource_admission_granted=False, heavy_work_admitted=False,
 all_heavy_work_held=True, CPU_PAUSE=result.get('pause_write_succeeded',False), **result)
def main():
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true')
 a.add_argument('--authorization');a.add_argument('--authorization-sha256');a.add_argument('--idle-host-policy');a.add_argument('--idle-host-policy-sha256');args=a.parse_args()
 if not args.execute: print(json.dumps(PROTOCOL,indent=2));return
 check(args.authorization and args.authorization_sha256,'reviewed grant required')
 auth=Path(args.authorization).resolve();check(auth.is_relative_to(E.resolve()),'authorization outside evidence')
 auth_bytes=auth.read_bytes();check(hashlib.sha256(auth_bytes).hexdigest()==args.authorization_sha256,'grant hash changed')
 grant=json.loads(auth_bytes)
 check(grant.get('supervisor_review_passed') is True and grant.get('supervisor_sha256')==sha(Path(__file__)),'supervisor grant absent')
 for k in ('binding_review_passed','CPU_window_granted','resource_pressure_qualification_granted','resource_admission_granted','CPU_baseline_only'):
  check(grant.get(k) is True,'missing grant: '+k)
 check(grant.get('supervisor_protocol')==PROTOCOL,'protocol changed')
 runner=ROOT/'tools/cpu_raw_baseline.py';selection=E/'cpu-v5-remaining87-preparation-v1/SELECTION.json';delta=E/OUTPUT_NAME/'DELTA.json'
 pins=((runner,RUNNER_SHA),(selection,SELECTION_SHA),(delta,DELTA_SHA),(ROOT/'tools/cpu_delta_store.py',STORAGE_SHA),(auth,args.authorization_sha256))
 verify_inputs(pins)
 prepared=read_prepared_delta(delta,runner)
 check(grant.get('delta_binding')==prepared['binding'],'fresh bounded delta grant mismatch')
 check(ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0,'subreaper unavailable')
 pause_path=E/'CPU-PAUSE';pause=pause_path.touch;child=None;owned={};state=new_state();gate_read=None;gate_write=None
 result=dict(process_cleanup_complete=False,errors=[])
 def cancelled(signum,frame):
  if state is not None: stop(state,'supervisor signal '+str(signum));safe_pause(state,pause)
 def alarm(signum,frame):
  if state is not None: tick(state,preflight[0]['pswpout'],pause)
 # Cancellation handlers latch only: fork-before-return cannot discard Popen.
 for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,cancelled)
 try:
  if args.idle_host_policy:
   check(grant.get('idle_host_policy_review_passed') is True and grant.get('idle_host_policy_sha256')==args.idle_host_policy_sha256,'exact idle policy review absent')
   policy_path=Path(args.idle_host_policy).resolve();check(policy_path.is_relative_to(E.resolve()),'idle policy outside evidence')
   guard_path=ROOT/'tools/cpu_correctness_host_guard_v2.py';raw=guard_path.read_bytes();check(hashlib.sha256(raw).hexdigest()==grant.get('idle_guard_source_sha256'),'idle guard source changed')
   import types
   module=types.ModuleType('cpu_idle_host_guard');module.__file__=str(guard_path);exec(compile(raw,str(guard_path),'exec'),module.__dict__)
   policy_bytes=policy_path.read_bytes();check(hashlib.sha256(policy_bytes).hexdigest()==args.idle_host_policy_sha256,'correctness policy changed')
   correctness_policy=json.loads(policy_bytes);module.validate_policy(correctness_policy)
   check(grant.get('parent_owned_reservation')==correctness_policy['reservation'],'parent reservation not bound to grant/policy')
   guard_directory=E/('cpu-correctness-host-window-'+args.authorization_sha256)
   guard=module.IdleGuard.create(policy_path,args.idle_host_policy_sha256,args.authorization_sha256,guard_directory)
   state['idle_guard']=guard
   qualification=guard.qualify();preflight=[x['pressure'] for x in qualification]
   pins=pins+((policy_path,args.idle_host_policy_sha256),(guard_path,grant['idle_guard_source_sha256']))
  else:
   raise RuntimeError('reviewed correctness-v2 policy and reservation required')
  verify_inputs(pins) # ALL linked inputs, alongside the same captured grant bytes.
  check(state['stopped'] is None,'cancelled during quiet admission')
  state['begin']=time.monotonic() # Execution deadline begins before logs/Popen; preserve cancellation.
  signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,INTERVAL,INTERVAL)
  tick(state,preflight[0]['pswpout'],pause)
  check(state['stopped'] is None,'startup admission stopped')
  if state.get('idle_guard') is not None:state['idle_guard'].check()
  gate_read,gate_write=os.pipe()
  command=[sys.executable,'-I','-c',LIMIT_SHIM,str(gate_read),sys.executable,'-I',str(runner),
   '--selection','cpu-v5-remaining87-preparation-v1/SELECTION.json','--output',OUTPUT_NAME,
   '--execute','--authorization',str(auth),'--authorization-sha256',args.authorization_sha256]
  if state.get('idle_guard') is not None:command.extend(['--idle-host-guard-state',str(guard_directory),'--idle-host-policy-sha256',args.idle_host_policy_sha256])
  with (REVIEW/'runner.stdout').open('xb') as out,(REVIEW/'runner.stderr').open('xb') as err:
   # CPU_PAUSE remains set until Popen returns and cancellation is inspected.
   child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
    start_new_session=True,close_fds=True,pass_fds=(gate_read,),env={'PATH':os.environ['PATH'],'LANG':'C'})
   os.close(gate_read);gate_read=None
   discover_owned(owned,processes(),os.getpid())
   tick(state,preflight[0]['pswpout'],pause)
   def clear_ready_pause():
    if state.get('idle_guard') is not None:state['idle_guard'].check()
    pause_path.unlink(missing_ok=True)
   release_startup(state,pause,clear_ready_pause,lambda:os.write(gate_write,b'G'))
   os.close(gate_write);gate_write=None
   signal.setitimer(signal.ITIMER_REAL,0)
   result=supervise(child,preflight[0]['pswpout'],owned,pause,state)
   result['preflight_samples']=preflight
 except Exception as exc:
  result['errors'].append('lifecycle: '+repr(exc))
  if state is not None: stop(state,'lifecycle failure')
 finally:
  # Repeated signals cannot restart cleanup; no throwing handlers anywhere.
  signal.setitimer(signal.ITIMER_REAL,0)
  for fd in (gate_read,gate_write):
   if fd is not None:
    try: os.close(fd)
    except Exception as exc: result['errors'].append('gate close: '+repr(exc))
  for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM): signal.signal(sig,signal.SIG_IGN)
  if state is not None and 'cleanup_finished_monotonic' not in result:
   original=result['errors'];result=cleanup(child,owned,state,pause);result['errors'].extend(original)
  else:
   try: pause();result['pause_write_succeeded']=True
   except Exception as exc:
    result['pause_write_succeeded']=False;result['errors'].append('final pause: '+repr(exc))
  if state.get('idle_guard') is not None:
   try:state['idle_guard'].finish();result['idle_host_window_closed']=True
   except Exception as exc:result['errors'].append('idle-host close: '+repr(exc))
  # Bookkeeping failures never bypass cleanup, and writes are independent.
  held=held_coordination(result)
  try: (REVIEW/'SUPERVISOR-RESULT.json').write_text(json.dumps(held,indent=2)+'\n')
  except Exception as exc: print('held result write failed: '+repr(exc),file=sys.stderr)
  try:
   coordination=E/'BASELINE-CPU-RELEASE.json';prior=json.loads(coordination.read_text());prior.update(held)
   coordination.write_text(json.dumps(prior,indent=2)+'\n')
  except Exception as exc: print('held coordination write failed: '+repr(exc),file=sys.stderr)
 check(result.get('process_cleanup_complete') and not result['errors'] and result.get('runner_exit')==0,'supervisor failed; resource hold retained')
if __name__=='__main__':main()
