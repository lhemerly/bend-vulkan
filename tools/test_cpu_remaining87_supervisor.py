import importlib.util, json, signal, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
spec=importlib.util.spec_from_file_location('supervisor',Path(__file__).with_name('cpu_remaining87_supervisor.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
GOOD=dict(available=s.MIN_BYTES,pswpout=7,some=.10,full=.10)
def proc(parent,start,state='S',comm='sleep'):return dict(ppid=parent,start=start,state=state,comm=comm)
class Clock:
 def __init__(self):self.t=0
 def now(self):return self.t
 def sleep(self,n):self.t+=n
class Child:
 pid=10
 def __init__(self,snap,status=0):self.snap=snap;self.status=status
 def poll(self):return self.status if self.pid not in self.snap else None
class Tests(unittest.TestCase):
 def test_threshold_boundaries(self):
  self.assertTrue(s.pressure_ok(GOOD,7))
  for key,value in [('available',s.MIN_BYTES-1),('pswpout',8),('pswpout',6),('some',.101),('full',.101),('full',float('nan'))]:
   self.assertFalse(s.pressure_ok(dict(GOOD,**{key:value}),7))
 def test_quiet_twenty_seconds(self):
  c=Clock();r=s.quiet_admission(lambda:GOOD,lambda:{},c.now,c.sleep)
  self.assertEqual(c.t,20);self.assertEqual(len(r),5)
 def test_worker_names(self):
  for name in ('bun','native','clang','bend','hvm','deno','opencode','agy','pmi'):
   c=Clock()
   with self.assertRaisesRegex(RuntimeError,'worker'):
    s.quiet_admission(lambda:GOOD,lambda:{2:proc(1,2,comm=name)},c.now,c.sleep)
   self.assertEqual(c.t,0)
 def test_pressure_during_quiet(self):
  c=Clock();reads=iter([GOOD,dict(GOOD,pswpout=8)])
  with self.assertRaisesRegex(RuntimeError,'quiet pressure'):
   s.quiet_admission(lambda:next(reads),lambda:{},c.now,c.sleep)
 def test_owned_ancestry(self):
  snap={10:proc(1,2),11:proc(10,3),12:proc(11,4),99:proc(2,1)}
  self.assertEqual(s.discover_owned({},snap,1),{10:2,11:3,12:4})
 def test_proven_reused_pid_refreshed_unrelated_not(self):
  owned={10:2,99:1};snap={10:proc(1,4),99:proc(2,3)}
  self.assertEqual(s.discover_owned(owned,snap,1),{10:4,99:1})
 def test_pidfd_reuse_never_signals_other_identity(self):
  sent=[];closed=[]
  s.signal_owned({10:2},9,lambda pid:(3,'S'),lambda pid,flags:123,lambda *a:sent.append(a),closed.append)
  self.assertEqual(sent,[]);self.assertEqual(closed,[123])
 def test_pidfd_handle_used(self):
  sent=[]
  s.signal_owned({10:2},9,lambda pid:(2,'S'),lambda pid,flags:123,lambda *a:sent.append(a),lambda fd:None)
  self.assertEqual(sent,[(123,9)])
 def test_pidfd_unavailable_records_failure(self):
  def bad(*a):raise OSError('unsupported')
  self.assertTrue(s.signal_owned({10:2},9,openfd=bad))
 def exercise(self,snap,read=lambda:GOOD,pause=lambda:None,procs=None,send=None,state=None,child=None):
  c=Clock();state=s.new_state(c.now) if state is None else state
  if send is None:
   def send(owned,sig):
    for pid,start in list(owned.items()):
     if pid in snap and snap[pid]['start']==start:snap.pop(pid)
    return []
  child=Child(snap) if child is None else child
  result=s.supervise(child,7,{},pause,state,read,procs or (lambda:snap),c.now,c.sleep,send,lambda *a:(0,0),1)
  return c,result
 def test_startup_pressure_stops_and_cleans(self):
  snap={10:proc(1,2)};paused=[]
  c,r=self.exercise(snap,lambda:dict(GOOD,pswpout=8),lambda:paused.append(True))
  self.assertEqual(r['reason'],'pressure stop');self.assertLessEqual(c.t,40);self.assertTrue(paused);self.assertTrue(r['process_cleanup_complete'])
 def test_wall_cap(self):
  c,r=self.exercise({10:proc(1,2),99:proc(9,3)})
  self.assertEqual(r['reason'],'execution wall cap');self.assertLessEqual(c.t,640)
 def test_pause_error_does_not_bypass_cleanup(self):
  snap={10:proc(1,2)}
  def bad():raise OSError('pause error')
  c,r=self.exercise(snap,lambda:dict(GOOD,pswpout=8),bad)
  self.assertEqual(snap,{});self.assertTrue(r['errors']);self.assertTrue(r['process_cleanup_complete']);self.assertFalse(s.held_coordination(r)['CPU_PAUSE']);self.assertLess(c.t,1)
 def test_pressure_read_failure_cleanup(self):
  snap={10:proc(1,2)}
  def bad():raise OSError('read failed')
  c,r=self.exercise(snap,bad);self.assertTrue(r['errors']);self.assertEqual(snap,{})
 def test_transient_scan_failure_retains_known_ownership(self):
  snap={10:proc(1,2)};calls=[0]
  def procs():
   calls[0]+=1
   if calls[0]==2:raise OSError('transient scan')
   return snap
  c,r=self.exercise(snap,procs=procs);self.assertEqual(snap,{});self.assertTrue(r['errors'])
 def test_persistent_scan_failure_bounded_not_complete(self):
  c=Clock();state=s.new_state(c.now);sent=[]
  def bad():raise OSError('scan')
  r=s.cleanup(None,{10:2},state,lambda:None,bad,c.now,c.sleep,lambda owned,sig:sent.append(sig) or [],lambda *a:(0,0),1)
  self.assertFalse(r['process_cleanup_complete']);self.assertTrue(sent);self.assertLessEqual(c.t,5.01)
 def test_term_fork_adoption_discovered_before_empty(self):
  c=Clock();snap={10:proc(1,2)};seen=[]
  def send(owned,sig):
   seen.extend(owned)
   if 10 in snap:
    snap.pop(10);snap[11]=proc(1,3)
   elif 11 in owned:snap.pop(11,None)
   return []
  r=s.cleanup(Child(snap),{10:2},s.new_state(c.now),lambda:None,lambda:snap,c.now,c.sleep,send,lambda *a:(0,0),1)
  self.assertIn(11,seen);self.assertEqual(snap,{});self.assertTrue(r['process_cleanup_complete'])
 def test_runner_signal_status_preserved_no_generic_reap(self):
  c=Clock();snap={10:proc(1,2)};reaped=[]
  def send(owned,sig):snap.pop(10,None);return []
  r=s.cleanup(Child(snap,-9),{10:2},s.new_state(c.now),lambda:None,lambda:snap,c.now,c.sleep,send,lambda pid,flags:reaped.append(pid),1)
  self.assertEqual(r['runner_exit'],-9);self.assertNotIn(10,reaped);self.assertNotIn(-1,reaped)
 def test_repeated_cancellation_does_not_reset_budget(self):
  c=Clock();state=s.new_state(c.now);s.stop(state,'first',c.now);c.sleep(35)
  s.stop(state,'second',c.now)
  r=s.cleanup(None,{10:2},state,lambda:None,lambda:{10:proc(1,2)},c.now,c.sleep,lambda *a:[],lambda *a:(0,0),1)
  self.assertEqual(state['stopped'],0);self.assertEqual(state['reason'],'first');self.assertEqual(r['cleanup_deadline_monotonic'],40)
 def test_cleanup_retry_does_not_restart_forced_deadline(self):
  c=Clock();state=s.new_state(c.now);snap={10:proc(1,2)}
  args=(None,{10:2},state,lambda:None,lambda:snap,c.now,c.sleep,lambda *a:[],lambda *a:(0,0),1)
  first=s.cleanup(*args);c.sleep(1);second=s.cleanup(*args)
  self.assertEqual(first['cleanup_deadline_monotonic'],5)
  self.assertEqual(second['cleanup_deadline_monotonic'],5);self.assertEqual(c.t,6)
 def test_tick_before_spawn_latches_deadline(self):
  c=Clock();state=s.new_state(c.now);c.sleep(600)
  s.tick(state,7,lambda:None,lambda:GOOD,c.now)
  self.assertEqual(state['reason'],'execution wall cap');self.assertEqual(state['stopped'],600)
 def test_cleanup_not_admission(self):
  r=s.held_coordination(dict(process_cleanup_complete=True))
  for k in ('released','PMI_next_build_may_start','resource_admission_granted','heavy_work_admitted'):self.assertFalse(r[k])
 def test_changed_inputs_after_quiet_never_launch(self):
  with tempfile.TemporaryDirectory() as tmp:
   files=[Path(tmp)/name for name in ('runner','selection','delta','grant')]
   for p in files:p.write_text('original')
   pins=[(p,s.sha(p)) for p in files]
   for changed in files:
    changed.write_text('changed')
    with patch.object(s.subprocess,'Popen') as spawn,self.assertRaisesRegex(RuntimeError,'input changed'):
     s.verify_inputs(pins)
    spawn.assert_not_called();changed.write_text('original')
 def run_main_mock(self, mode):
  from contextlib import ExitStack
  with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
   root=Path(tmp);e=root/'evidence';review=e/'review';review.mkdir(parents=True)
   (root/'tools').mkdir();runner=root/'tools/cpu_raw_baseline.py';runner.write_text('runner')
   sel=e/'cpu-v5-remaining87-preparation-v1/SELECTION.json';sel.parent.mkdir();sel.write_text('selection')
   delta=e/'cpu-v5-remaining87-idle-guard-fresh-v1/DELTA.json';delta.parent.mkdir();delta.write_text('delta')
   (e/'CPU-PAUSE').touch();(e/'BASELINE-CPU-RELEASE.json').write_text(json.dumps({'unique_accounted_cases':934}))
   auth=e/'grant.json';auth.write_text(json.dumps(dict(supervisor_review_passed=True,supervisor_sha256=s.sha(Path(s.__file__)),supervisor_protocol=s.PROTOCOL,
    **{k:True for k in ('binding_review_passed','CPU_window_granted','resource_pressure_qualification_granted','resource_admission_granted','CPU_baseline_only')})))
   c=Clock();snap={};handlers={};spawned=[];real_supervise=s.supervise;real_cleanup=s.cleanup;real_tick=s.tick
   def send(owned,sig):
    # Repeated signals during cleanup must latch without throwing/restarting.
    if callable(handlers[signal.SIGTERM]):handlers[signal.SIGTERM](signal.SIGTERM,None)
    for pid in owned:snap.pop(pid,None)
    return []
   def preflight():
    changed={'changed_runner':runner,'changed_selection':sel,'changed_delta':delta,'changed_grant':auth}.get(mode)
    if changed:changed.write_text('changed')
    return [GOOD]
   def spawn(*a,**kw):
    spawned.append(True);snap[10]=proc(1,2)
    if mode in ('cancel_spawn','exception_spawn'):
     handlers[signal.SIGTERM](signal.SIGTERM,None)
    if mode=='exception_spawn':raise OSError('post-fork error')
    if mode=='deadline_spawn':
     c.sleep(600);handlers[signal.SIGALRM](signal.SIGALRM,None)
    if mode=='normal':snap.pop(10)
    return Child(snap,0 if mode=='normal' else -9)
   patches=[patch.object(s,'ROOT',root),patch.object(s,'E',e),patch.object(s,'REVIEW',review),
    patch.object(s,'RUNNER_SHA',s.sha(runner)),patch.object(s,'SELECTION_SHA',s.sha(sel)),patch.object(s,'DELTA_SHA',s.sha(delta)),
    patch.object(s,'quiet_admission',side_effect=preflight),patch.object(s.ctypes,'CDLL') ,
    patch.object(s.signal,'signal',side_effect=lambda sig,handler:handlers.update({sig:handler})),
    patch.object(s.signal,'setitimer'),patch.object(s.time,'monotonic',c.now),
    patch.object(s,'new_state',side_effect=lambda:s.new_state_original(c.now)),
    patch.object(s,'tick',side_effect=lambda state,baseline,pause:real_tick(state,baseline,pause,lambda:GOOD,c.now)),
    patch.object(s.os,'pipe',return_value=(101,102)),patch.object(s.os,'close'),patch.object(s.os,'write',return_value=1),
    patch.object(s,'release_startup',side_effect=lambda state,pause,clear,write:s.release_startup_original(state,pause,clear,write,lambda *a:set(),lambda:set(),c.now)),
    patch.object(s,'processes',side_effect=lambda:snap),patch.object(s.os,'getpid',return_value=1),
    patch.object(s.subprocess,'Popen',side_effect=spawn),
    patch.object(s,'supervise',side_effect=lambda child,baseline,owned,pause,state:real_supervise(child,baseline,owned,pause,state,lambda:GOOD,lambda:snap,c.now,c.sleep,send,lambda *a:(0,0),1)),
    patch.object(s,'cleanup',side_effect=lambda child,owned,state,pause,*a:real_cleanup(child,owned,state,pause,lambda:snap,c.now,c.sleep,send,lambda *a:(0,0),1)),
    patch.object(s.sys,'argv',['supervisor','--execute','--authorization',str(auth),'--authorization-sha256',s.sha(auth)])]
   s.new_state_original=s.new_state;s.release_startup_original=s.release_startup
   for item in patches:
    obj=stack.enter_context(item)
    if item.attribute=='CDLL':obj.return_value.prctl.return_value=0
   if mode=='normal':s.main()
   else:
    with self.assertRaises(RuntimeError):s.main()
   result=json.loads((review/'SUPERVISOR-RESULT.json').read_text())
   held=json.loads((e/'BASELINE-CPU-RELEASE.json').read_text())
   self.assertEqual(held['unique_accounted_cases'],934);self.assertFalse(held['released']);self.assertFalse(held['resource_admission_granted'])
   self.assertEqual(snap,{});self.assertTrue((e/'CPU-PAUSE').exists())
   return result,spawned
 def test_main_cancel_inside_Popen_assignment_cleanup(self):
  r,spawned=self.run_main_mock('cancel_spawn');self.assertTrue(spawned);self.assertEqual(r['runner_exit'],-9);self.assertTrue(r['process_cleanup_complete'])
 def test_main_Popen_error_without_assignment_discovers_children(self):
  r,spawned=self.run_main_mock('exception_spawn');self.assertTrue(spawned);self.assertTrue(r['process_cleanup_complete']);self.assertIsNone(r['runner_exit'])
 def test_main_startup_deadline_and_repeated_cleanup_signals(self):
  r,spawned=self.run_main_mock('deadline_spawn');self.assertEqual(r['reason'],'execution wall cap');self.assertEqual(r['stop_monotonic'],600);self.assertLessEqual(r['cleanup_finished_monotonic'],640)
 def test_main_revalidates_runner_after_quiet_no_dispatch(self):
  for mode in ('changed_runner','changed_selection','changed_delta','changed_grant'):
   r,spawned=self.run_main_mock(mode);self.assertEqual(spawned,[]);self.assertTrue(r['errors'])
 def test_main_normal_status_and_hold_recording(self):
  r,spawned=self.run_main_mock('normal');self.assertEqual(r['runner_exit'],0);self.assertTrue(r['process_cleanup_complete'])
 def test_gate_pause_cleared_before_fast_child_can_exit(self):
  c=Clock();state=s.new_state(c.now);trace=[]
  self.assertTrue(s.release_startup(state,lambda:trace.append('pause'),lambda:trace.append('clear'),lambda:trace.append('child exit') or 1,lambda *a:set(),lambda:set(),c.now))
  self.assertEqual(trace,['clear','child exit']);self.assertTrue(state['startup_committed'])
 def test_gate_latched_cancel_never_clears_or_commits(self):
  c=Clock();state=s.new_state(c.now);s.stop(state,'cancel',c.now);trace=[]
  self.assertFalse(s.release_startup(state,lambda:trace.append('pause'),lambda:trace.append('clear'),lambda:trace.append('go') or 1,lambda *a:set(),lambda:set(),c.now))
  self.assertEqual(trace,['pause']);self.assertNotIn('startup_committed',state)
 def test_gate_cancel_during_clear_restores_pause_never_commits(self):
  c=Clock();state=s.new_state(c.now);trace=[]
  def clear():trace.append('clear');s.stop(state,'cancel',c.now);trace.append('handler pause')
  self.assertFalse(s.release_startup(state,lambda:trace.append('pause'),clear,lambda:trace.append('go') or 1,lambda *a:set(),lambda:set(),c.now))
  self.assertEqual(trace,['clear','handler pause','pause'])
 def test_gate_pending_cancel_after_clear_never_commits(self):
  c=Clock();state=s.new_state(c.now);pending=iter([set(),{signal.SIGTERM}]);trace=[]
  self.assertFalse(s.release_startup(state,lambda:trace.append('pause'),lambda:trace.append('clear'),lambda:trace.append('go') or 1,lambda *a:set(),lambda:next(pending),c.now))
  self.assertEqual(trace,['clear','pause'])
 def test_gate_restores_mask_on_clear_error(self):
  c=Clock();calls=[]
  def mask(*args):calls.append(args);return {signal.SIGINT}
  def clear():raise OSError('clear failed')
  with self.assertRaises(OSError):s.release_startup(s.new_state(c.now),lambda:None,clear,lambda:1,mask,lambda:set(),c.now)
  self.assertEqual(calls[-1],(signal.SIG_SETMASK,{signal.SIGINT}))
 def test_child_gate_EOF_aborts_before_exec(self):
  with patch.object(s.resource,'setrlimit'),patch.object(s.os,'umask'),patch.object(s.os,'read',return_value=b''),patch.object(s.os,'close'),patch.object(s.os,'execv') as execute,patch.object(s.sys,'argv',['shim','101','python','target']),self.assertRaises(SystemExit) as caught:
   exec(s.LIMIT_SHIM,{})
  self.assertEqual(caught.exception.code,125);execute.assert_not_called()
 def test_child_gate_G_only_then_exec(self):
  trace=[]
  with patch.object(s.resource,'setrlimit'),patch.object(s.os,'umask'),patch.object(s.os,'read',side_effect=lambda *a:trace.append('gate read') or b'G'),patch.object(s.os,'close'),patch.object(s.os,'execv',side_effect=lambda *a:trace.append('exec')),patch.object(s.sys,'argv',['shim','101','python','target']):
   exec(s.LIMIT_SHIM,{})
  self.assertEqual(trace,['gate read','exec'])
 def test_idle_host_guard_stops_only_owned_Bend_tree(self):
  c=Clock();snap={10:proc(900,2),778:proc(675,1173,comm='agy'),19417:proc(1,480648,comm='opencode')};sent=[]
  class Guard:
   def status(self):raise RuntimeError('exact host violated cap')
  state=s.new_state(c.now);state['idle_guard']=Guard()
  def send(owned,sig):
   sent.extend(owned)
   for pid in owned:snap.pop(pid,None)
   return []
  r=s.supervise(Child(snap),7,{},lambda:None,state,lambda:GOOD,lambda:snap,c.now,c.sleep,send,lambda *a:(0,0),900)
  self.assertEqual(r['reason'],'idle-host guard refusal');self.assertEqual(set(sent),{10});self.assertIn(778,snap);self.assertIn(19417,snap)
if __name__=='__main__':unittest.main()
