import copy,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('guard',Path(__file__).with_name('cpu_idle_host_guard.py'))
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
def policy():
 return dict(one_window=True,HZ=100,boot_id='boot',host_pid_namespace='pid:[host]',pressure=g.PRESSURE,maximum_sample_gap_seconds=5.5,expiry_seconds=660,
  hosts={str(pid):dict(limits=copy.deepcopy(limits),uid=[1000]*4,exe_object=dict(device=1,inode=pid)) for pid,limits in g.LIMITS.items()})
def observed():
 hosts={};rows={900:dict(pid=900,start=5,ppid=1,comm='python',state='S')}
 for pid,limits in g.LIMITS.items():
  host=dict(pid=pid,start=limits['start'],comm=limits['comm'],exe=limits['exe'],ppid=limits['ppid'],pgrp=limits['pgrp'],session=limits['session'],uid=[1000]*4,exe_object=dict(device=1,inode=pid),state='S',rss=limits['rss'],cpu=0,child_cpu=0,io={k:0 for k in g.IO_KEYS})
  hosts[str(pid)]=host;rows[pid]=copy.deepcopy(host)
 return dict(HZ=100,boot_id='boot',host_pid_namespace='pid:[host]',rows=rows,hosts=hosts,pressure=dict(available=g.PRESSURE['minimum_available_bytes'],pswpout=7,some=.1,full=.1))
def state():return dict(created=0,owner=dict(pid=900,start=5),anchors=[],next_due=0,last_observed=None,refusal=None)
def commit(st,obs,t):
 record=g.evaluate(policy(),st,obs,t,True)
 if not st['anchors']:st.update(baseline_hosts=copy.deepcopy(obs['hosts']),baseline_pswpout=7)
 st['anchors'].append(copy.deepcopy(record));st['last_observed']=copy.deepcopy(record);st['next_due']=t+5
 return record
class Tests(unittest.TestCase):
 def initial(self):
  st=state();obs=observed();commit(st,obs,0);return st,obs
 def reject(self,mutate,pattern=None):
  st,obs=self.initial();mutate(obs)
  with self.assertRaisesRegex(RuntimeError,pattern or '.'):
   g.evaluate(policy(),st,obs,5,True)
 def test_pending_boot_uid_executable_bindings_fail(self):
  for key in ('boot_id','host_pid_namespace'):
   p=policy();p[key]=None
   with self.assertRaises(RuntimeError):g.validate_policy(p)
  for key in ('uid','exe_object'):
   p=policy();p['hosts']['778'][key]=None
   with self.assertRaises(RuntimeError):g.validate_policy(p)
 def test_caps_cannot_autoincrease(self):
  p=policy();p['hosts']['778']['limits']['cpu5']=2
  with self.assertRaisesRegex(RuntimeError,'frozen'):g.validate_policy(p)
 def test_same_name_wrong_PID_still_blocks(self):
  self.reject(lambda o:o['rows'].update({123:dict(ppid=1,start=1,comm='agy')}),'other matching')
 def test_reused_start_blocks(self):self.reject(lambda o:o['hosts']['778'].update(start=999),'identity')
 def test_boot_namespace_HZ_changes_block(self):
  for key,value in [('boot_id','reboot'),('host_pid_namespace','pid:[sandbox]'),('HZ',250)]:
   self.reject(lambda o,k=key,v=value:o.update({k:v}),'view changed')
 def test_UID_executable_path_object_changes_block(self):
  for key,value in [('uid',[0]*4),('exe_object',dict(device=1,inode=0)),('exe','/other')]:
   self.reject(lambda o,k=key,v=value:o['hosts']['778'].update({k:v}))
 def test_parent_group_session_comm_changes_block(self):
  for key,value in [('ppid',1),('pgrp',1),('session',1),('comm','other')]:
   self.reject(lambda o,k=key,v=value:o['hosts']['778'].update({k:v}),'identity')
 def test_descendant_any_depth_including_zombie_blocks(self):
  for state_name in ('S','Z'):
   self.reject(lambda o,v=state_name:o['rows'].update({456:dict(ppid=778,start=1,comm='sleep',state=v)}),'descendant')
 def test_counter_regression_blocks(self):
  st,obs=self.initial();st['last_observed']['hosts']['778']['cpu']=2
  with self.assertRaisesRegex(RuntimeError,'regression'):g.evaluate(policy(),st,obs,5,True)
 def test_reaped_child_growth_blocks(self):self.reject(lambda o:o['hosts']['778'].update(child_cpu=1),'reaped-child')
 def test_disk_growth_blocks(self):
  for key in ('read_bytes','write_bytes','cancelled_write_bytes'):
   self.reject(lambda o,k=key:o['hosts']['778']['io'].update({k:1}),'disk')
 def test_CPU_boundaries_and_rolling(self):
  st,obs=self.initial()
  for t in (5,10,15,20):
   obs['hosts']['778']['cpu']=int(t/5);commit(st,obs,t)
  obs['hosts']['778']['cpu']=5
  with self.assertRaisesRegex(RuntimeError,'rolling'):g.evaluate(policy(),st,obs,20.2,False)
  st,obs=self.initial();obs['hosts']['19417']['cpu']=3;g.evaluate(policy(),st,obs,5,True)
  obs['hosts']['19417']['cpu']=4
  with self.assertRaisesRegex(RuntimeError,'5s CPU'):g.evaluate(policy(),st,obs,5,True)
 def test_stream_RSS_state_boundaries(self):
  st,obs=self.initial();obs['hosts']['778']['io']['rchar']=128;g.evaluate(policy(),st,obs,5,True)
  obs['hosts']['778']['io']['rchar']=129
  with self.assertRaisesRegex(RuntimeError,'stream'):g.evaluate(policy(),st,obs,5,True)
  self.reject(lambda o:o['hosts']['778'].update(rss=g.LIMITS[778]['rss']+1),'RSS')
  self.reject(lambda o:o['hosts']['778'].update(state='R'),'state')
 def test_extra_checks_do_not_reset_current_interval_budget(self):
  st,obs=self.initial();obs['hosts']['19417']['cpu']=2
  for t in (1,2,3,4):
   r=g.evaluate(policy(),st,obs,t,False);st['last_observed']=r
  self.assertEqual(st['anchors'][0]['hosts']['19417']['cpu'],0)
  obs['hosts']['19417']['cpu']=4
  with self.assertRaisesRegex(RuntimeError,'5s CPU'):g.evaluate(policy(),st,obs,4.1,False)
 def test_early_or_overdue_scheduled_samples_block(self):
  st,obs=self.initial()
  for t,pattern in [(4.9,'early'),(5.5001,'overdue')]:
   with self.assertRaisesRegex(RuntimeError,pattern):g.evaluate(policy(),st,obs,t,True)
  g.evaluate(policy(),st,obs,5.5,True)
 def test_only_proven_owned_worker_tree_accounted(self):
  st,obs=self.initial();obs['rows'][901]=dict(ppid=900,start=7,comm='bun');obs['rows'][902]=dict(ppid=901,start=8,comm='native')
  r=g.evaluate(policy(),st,obs,5,True);self.assertEqual(r['owned_identities']['902'],8)
  obs['rows'][900]['start']=6
  with self.assertRaisesRegex(RuntimeError,'controller'):g.evaluate(policy(),st,obs,5,True)
 def test_pressure_caps_unchanged(self):
  for key,value in [('available',g.PRESSURE['minimum_available_bytes']-1),('pswpout',8),('some',.101),('full',.101)]:
   self.reject(lambda o,k=key,v=value:o['pressure'].update({k:v}),'pressure')
 def test_expiry_latch_blocks(self):
  st,obs=self.initial();st['refusal']=dict(time=0,reason='first')
  with self.assertRaisesRegex(RuntimeError,'latched'):g.evaluate(policy(),st,obs,1,False)
  st['refusal']=None
  with self.assertRaisesRegex(RuntimeError,'expiry'):g.evaluate(policy(),st,obs,661,False)
 def test_shared_state_reader_error_latched_and_no_signals(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(g.signal,'pthread_sigmask',return_value=set()),patch.object(g.os,'kill') as kill:
   p=Path(tmp)/'policy.json';p.write_text(json.dumps(policy()));o=observed();o['rows'][os.getpid()]=dict(start=5,ppid=1,comm='python')
   guard=g.IdleGuard.create(p,g.digest(p.read_bytes()),'grant',Path(tmp)/'window',lambda:o,lambda:0)
   guard.check(True)
   def unreadable():raise PermissionError('metadata')
   guard.reader=unreadable
   with self.assertRaisesRegex(RuntimeError,'metadata'):guard.check()
   st=json.loads((guard.directory/'STATE.json').read_text());self.assertIn('metadata',st['refusal']['reason'])
   with self.assertRaises(RuntimeError):guard.status()
   kill.assert_not_called()
 def test_one_window_directory_cannot_be_reused(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'policy.json';p.write_text(json.dumps(policy()));o=observed();o['rows'][os.getpid()]=dict(start=5,ppid=1,comm='python')
   directory=Path(tmp)/'window';g.IdleGuard.create(p,g.digest(p.read_bytes()),'grant',directory,lambda:o,lambda:0)
   with self.assertRaises(FileExistsError):g.IdleGuard.create(p,g.digest(p.read_bytes()),'grant',directory,lambda:o,lambda:0)
 def test_collect_failure_not_silently_recorded_only(self):
  with patch.object(g.Path,'iterdir',side_effect=PermissionError('inventory')),self.assertRaises(PermissionError):g.collect()
 def test_completed_window_cannot_serve_later_checks(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(g.signal,'pthread_sigmask',return_value=set()):
   p=Path(tmp)/'policy.json';p.write_text(json.dumps(policy()));o=observed();o['rows'][os.getpid()]=dict(start=5,ppid=1,comm='python')
   guard=g.IdleGuard.create(p,g.digest(p.read_bytes()),'grant',Path(tmp)/'window',lambda:o,lambda:0)
   guard.check(True);guard.finish()
   with self.assertRaisesRegex(RuntimeError,'completed'):guard.status()
if __name__=='__main__':unittest.main()
