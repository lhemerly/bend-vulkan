#!/usr/bin/env python3
"""Reviewed-grant-only sleep fixtures. Default prints scope; never runs Bend."""
import argparse, ctypes, importlib.util, json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
SOURCE=Path(__file__).with_name('cpu_remaining87_supervisor.py')
spec=importlib.util.spec_from_file_location('supervisor',SOURCE)
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
SELF=Path(__file__).resolve()
GOOD=dict(available=s.MIN_BYTES,pswpout=7,some=0.,full=0.)
SCOPE=dict(execution_authorized=False,maximum_total_wall_seconds=90,
 maximum_fixture_processes=6,fixtures=['exit0','exit7','runner-death','startup-cancel'],
 GPU=False,Bend=False,real_pressure_generation=False,production_coordination_writes=False,
 supervisor_SIGKILL_containment=False,blocking_Popen_hard_deadline_qualified=False)

def write(path,data): path.write_text(json.dumps(data,indent=2)+'\n')
def identity(pid):
 current=s.pid_identity(pid);s.check(current is not None,'fixture PID vanished before registration')
 return dict(pid=pid,start=current[0])
def subreaper():s.check(ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0,'fixture subreaper unavailable')
def command(*args):return [sys.executable,'-I',str(SELF),*map(str,args)]
def wait_file(path,deadline):
 while not path.exists():
  s.check(time.monotonic()<deadline,'fixture handshake timeout');time.sleep(.01)

def fixture_directory(directory):
 d=Path(directory).resolve();base=s.E.resolve()
 s.check(d.is_relative_to(base),'fixture output outside evidence')
 parts=d.relative_to(base).parts
 s.check(len(parts) in (1,2) and parts[0].startswith('cpu-supervisor-sleep-'),'fixture output must be isolated temporary root/case')
 if len(parts)==2:s.check(parts[1] in SCOPE['fixtures'],'unknown fixture case directory')
 admission=json.loads((base/parts[0]/'FIXTURE-ADMISSION.json').read_text())
 s.check(admission.get('sleep_only_qualification_granted') is True,'fixture admission absent')
 s.check(admission.get('supervisor_sha256')==s.sha(SOURCE) and admission.get('fixture_sha256')==s.sha(SELF),'fixture admission source changed')
 s.check(time.monotonic()<admission['deadline_monotonic'],'fixture admission expired')
 return d

def shared_deadline(directory):
 d=Path(directory).resolve();root=s.E.resolve()/d.relative_to(s.E.resolve()).parts[0]
 return json.loads((root/'FIXTURE-ADMISSION.json').read_text())['deadline_monotonic']

def sleep_to_deadline(deadline,clock=time.monotonic,sleep=time.sleep):
 # Absolute shared admission expiry; late-starting helpers get only time remaining.
 remaining=deadline-clock()
 if remaining>0:sleep(remaining)

def pidfd_self_probe(getpid=os.getpid,identify=s.pid_identity,openfd=os.pidfd_open,
                     sendfd=signal.pidfd_send_signal,close=os.close):
 pid=getpid();before=identify(pid);fd=None
 s.check(before is not None and before[1]!='Z','pidfd self identity unavailable')
 try:
  fd=openfd(pid,0)
  s.check(identify(pid)==before,'pidfd self identity changed')
  sendfd(fd,0) # Permission/support check only; never delivers a real signal.
  s.check(identify(pid)==before,'pidfd self identity changed after signal0')
  return dict(pid=pid,start=before[0],pidfd_open_passed=True,pidfd_signal0_passed=True)
 finally:
  if fd is not None:close(fd)

def helper(mode,directory):
 directory=fixture_directory(directory);deadline=shared_deadline(directory)
 pidfd_self_probe() # Must succeed before this helper can create any child.
 if mode in ('exit0','exit7'):time.sleep(max(0,min(.1,deadline-time.monotonic())));return int(mode[-1])
 if mode in ('sentinel','startup-work'):
  write(directory/(mode+'.json'),identity(os.getpid()));sleep_to_deadline(deadline);return 0
 if mode=='resistant':
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  write(directory/'resistant.json',identity(os.getpid()));sleep_to_deadline(deadline);return 0
 if mode=='middle':
  child=subprocess.Popen(command('--helper','resistant','--directory',directory),start_new_session=True,stdin=subprocess.DEVNULL)
  wait_file(directory/'resistant.json',min(deadline,time.monotonic()+5));return 0
 if mode=='runner-death':
  middle=subprocess.Popen(command('--helper','middle','--directory',directory),stdin=subprocess.DEVNULL)
  wait_file(directory/'resistant.json',min(deadline,time.monotonic()+5))
  s.check(middle.wait(timeout=max(0,min(5,deadline-time.monotonic())))==0,'middle helper exit');return 7
 raise RuntimeError('unknown helper')

def inner(mode,directory):
 directory=fixture_directory(directory);probe=pidfd_self_probe();subreaper();pause_path=directory/'CPU-PAUSE';pause_path.touch()
 state=s.new_state();owned={};child=None;gate_read=None;gate_write=None;result=None
 original_cleanup=s.cleanup
 def observed_cleanup(*args,**kwargs):
  try:(directory/'cleanup-started').touch()
  except Exception as exc:state['errors'].append('cleanup marker: '+repr(exc))
  return original_cleanup(*args,**kwargs)
 s.cleanup=observed_cleanup
 def pause():
  pause_path.touch()
  if state['stopped'] is not None and time.monotonic()>=state['stopped']+s.GRACE:
   (directory/'cleanup-started').touch()
 def cancelled(signum,frame):s.stop(state,'fixture signal '+str(signum));s.safe_pause(state,pause)
 for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancelled)
 def synthetic():
  return dict(GOOD,pswpout=8) if mode=='runner-death' and (directory/'resistant.json').exists() else GOOD
 def alarm(signum,frame):s.tick(state,7,pause,synthetic)
 signal.signal(signal.SIGALRM,alarm)
 try:
  s.tick(state,7,pause,synthetic)
  signal.setitimer(signal.ITIMER_REAL,s.INTERVAL,s.INTERVAL)
  gate_read,gate_write=os.pipe()
  target='startup-work' if mode=='startup-cancel' else mode
  argv=[sys.executable,'-I','-c',s.LIMIT_SHIM,str(gate_read),*command('--helper',target,'--directory',directory)]
  child=subprocess.Popen(argv,pass_fds=(gate_read,),stdin=subprocess.DEVNULL,close_fds=True,start_new_session=True)
  os.close(gate_read);gate_read=None
  write(directory/'leader.json',identity(child.pid))
  s.discover_owned(owned,s.processes(),os.getpid())
  if mode=='startup-cancel':
   (directory/'gate-waiting').touch()
   wait_file(directory/'cancel-sent',min(shared_deadline(directory),time.monotonic()+5))
  s.release_startup(state,pause,lambda:pause_path.unlink(missing_ok=True),lambda:os.write(gate_write,b'G'))
  os.close(gate_write);gate_write=None
  signal.setitimer(signal.ITIMER_REAL,0)
  # Uses the real35s/5s supervisor path. No actual pressure is created/read.
  result=s.supervise(child,7,owned,pause,state,read=synthetic)
 except Exception as exc:
  state['errors'].append('fixture: '+repr(exc));s.stop(state,'fixture failure')
 finally:
  signal.setitimer(signal.ITIMER_REAL,0)
  for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM):signal.signal(sig,signal.SIG_IGN)
  for fd in (gate_read,gate_write):
   if fd is not None:
    try:os.close(fd)
    except Exception as exc:state['errors'].append('fixture gate close: '+repr(exc))
  if result is None:result=s.cleanup(child,owned,state,pause)
  result['mode']=mode;result['pidfd_self_probe']=probe;write(directory/'INNER-RESULT.json',result)
 return 0 if result['process_cleanup_complete'] and not result['errors'] else 1

def assert_case(mode,result,elapsed,sentinel_alive,survivors,work_started,registered):
 s.check(result.get('process_cleanup_complete') and not result.get('errors'),'inner cleanup failed')
 expected={'exit0':0,'exit7':7,'runner-death':7,'startup-cancel':125}[mode]
 s.check(result.get('runner_exit')==expected,'actual runner status mismatch')
 s.check(sentinel_alive,'unrelated sibling sentinel was signalled')
 s.check(not survivors,'fixture descendants survived inner cleanup')
 if mode=='startup-cancel':
  s.check(not result.get('startup_committed') and not work_started,'cancelled startup gate released work')
 if mode=='runner-death':
  s.check(result.get('reason')=='pressure stop','synthetic stop absent')
  stopped=result['stop_monotonic'];finished=result['cleanup_finished_monotonic']
  s.check(35<=finished-stopped<=40.5,'real35s/5s stop bounds not exercised')
  for entry in registered:
   s.check(result['owned_processes'].get(str(entry['pid']))==entry['start'],'registered descendant not owned')
 s.check(elapsed<80,'fixture window exceeded outer fallback boundary')

def outer(directory):
 directory=fixture_directory(directory);probe=pidfd_self_probe();subreaper();begin=time.monotonic();owned={};children=[];records=[];error=None
 sentinel=None;sentinel_identity=None;stop_requested=[False]
 def cancel(sig,frame):stop_requested[0]=True
 for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancel)
 try:
  sentinel=subprocess.Popen(command('--helper','sentinel','--directory',directory),stdin=subprocess.DEVNULL,start_new_session=True)
  children.append(sentinel);sentinel_identity=identity(sentinel.pid);owned[sentinel.pid]=sentinel_identity['start']
  for mode in SCOPE['fixtures']:
   s.check(not stop_requested[0] and time.monotonic()-begin<80,'outer cancelled/deadline')
   case=directory/mode;case.mkdir()
   child=subprocess.Popen(command('--inner',mode,'--directory',case),stdin=subprocess.DEVNULL,start_new_session=True)
   children.append(child);owned[child.pid]=identity(child.pid)['start'];case_begin=time.monotonic();cancel_sent=False;repeats=0;signal_times=[]
   while child.poll() is None:
    snap=s.processes();s.discover_owned(owned,snap,os.getpid())
    s.check(not stop_requested[0] and time.monotonic()-begin<80,'outer fallback deadline/cancellation')
    if mode=='startup-cancel' and (case/'gate-waiting').exists() and not cancel_sent:
     s.check(not s.signal_owned({child.pid:owned[child.pid]},signal.SIGTERM),'startup signal failed')
     signal_times.append(time.monotonic())
     (case/'cancel-sent').touch();cancel_sent=True
    if mode=='startup-cancel' and (case/'cleanup-started').exists() and repeats<3:
     s.check(not s.signal_owned({child.pid:owned[child.pid]},signal.SIGTERM),'repeated signal failed')
     signal_times.append(time.monotonic());repeats+=1
    time.sleep(.01)
   s.check(child.returncode==0,'inner checker failed')
   result=json.loads((case/'INNER-RESULT.json').read_text())
   registered=[json.loads(p.read_text()) for p in case.glob('resistant.json')]
   snap=s.processes();s.discover_owned(owned,snap,os.getpid())
   sentinel_alive=sentinel.poll() is None and snap.get(sentinel.pid,{}).get('start')==sentinel_identity['start']
   fixture_ids={int(pid):start for pid,start in result['owned_processes'].items()}
   for entry in registered:fixture_ids[entry['pid']]=entry['start']
   # Outer additionally checks its current adopted descendants, excluding sentinel.
   outer_desc={pid:start for pid,start in owned.items() if pid!=sentinel.pid}
   survivors=s.alive_owned({**outer_desc,**fixture_ids},snap)
   elapsed=time.monotonic()-case_begin
   assert_case(mode,result,elapsed,sentinel_alive,survivors,(case/'startup-work.json').exists(),registered)
   if mode=='startup-cancel':s.check(cancel_sent and repeats>=1,'startup/repeated signals not delivered')
   records.append(dict(mode=mode,elapsed_seconds=elapsed,inner_exit=child.returncode,
     sentinel=sentinel_identity,sentinel_alive=sentinel_alive,survivors=survivors,
     repeated_signals=repeats,signal_monotonic_times=signal_times,result=result,registered=registered))
 except Exception as exc:error=repr(exc)
 finally:
  for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,signal.SIG_IGN)
  # Independent fallback cleanup includes adopted descendants and owned sentinel.
  deadline=min(shared_deadline(directory),begin+90,time.monotonic()+5);cleanup_errors=[];empty_since=None;complete=False
  while True:
   try:snap=s.processes();s.discover_owned(owned,snap,os.getpid())
   except Exception as exc:cleanup_errors.append(repr(exc));snap=None
   cleanup_errors.extend(s.signal_owned(owned,signal.SIGKILL))
   for child in children:child.poll() # Retain each Popen leader status.
   if snap is not None:
    for pid,start in owned.items():
     item=snap.get(pid)
     if item and item['start']==start and item['state']=='Z' and pid not in {c.pid for c in children}:
      try:os.waitpid(pid,os.WNOHANG)
      except ChildProcessError:pass
    # Fresh post-signal discovery, never certify against the pre-signal scan.
    try:
     snap=s.processes();s.discover_owned(owned,snap,os.getpid())
     if not s.alive_owned(owned,snap):
      if empty_since is None:empty_since=time.monotonic()
      elif time.monotonic()-empty_since>=.2:complete=True;break
     else:empty_since=None
    except Exception as exc:cleanup_errors.append(repr(exc))
   if time.monotonic()>=deadline:break
   time.sleep(.05)
  result=dict(passed=error is None and complete and not cleanup_errors,cases=records,error=error,
   outer_cleanup_complete=complete,outer_cleanup_errors=cleanup_errors,pidfd_self_probe=probe,
   outer_owned_processes=owned,outer_elapsed_seconds=time.monotonic()-begin,
   outer_leader_statuses={str(c.pid):c.poll() for c in children},scope=SCOPE)
  write(directory/'QUALIFICATION-RESULT.json',result)
 return 0 if result['passed'] else 1

def main():
 a=argparse.ArgumentParser();a.add_argument('--execute',action='store_true');a.add_argument('--authorization');a.add_argument('--authorization-sha256')
 a.add_argument('--helper');a.add_argument('--inner');a.add_argument('--directory');args=a.parse_args()
 # Internal modes are only tiny sleep fixtures and isolated result writes.
 if args.helper:return helper(args.helper,args.directory)
 if args.inner:return inner(args.inner,args.directory)
 if not args.execute:print(json.dumps(SCOPE,indent=2));return 0
 s.check(args.authorization and args.authorization_sha256,'explicit sleep-only grant required')
 raw=Path(args.authorization).read_bytes();s.check(s.hashlib.sha256(raw).hexdigest()==args.authorization_sha256,'grant hash changed')
 grant=json.loads(raw)
 s.check(grant.get('sleep_only_qualification_granted') is True and grant.get('source_review_passed') is True and grant.get('execution_scope')=='sleep-only-isolated-fixture','fixture window not granted')
 s.check(grant.get('supervisor_sha256')==s.sha(SOURCE) and grant.get('fixture_sha256')==s.sha(SELF),'reviewed source changed')
 directory=Path(tempfile.mkdtemp(prefix='cpu-supervisor-sleep-',dir=s.E))
 write(directory/'FIXTURE-ADMISSION.json',dict(sleep_only_qualification_granted=True,supervisor_sha256=s.sha(SOURCE),fixture_sha256=s.sha(SELF),deadline_monotonic=time.monotonic()+90,grant_sha256=args.authorization_sha256))
 print(str(directory),flush=True);return outer(directory)
if __name__=='__main__':sys.exit(main())
