import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('qualify_cpu_supervisor_sleep.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
class Tests(unittest.TestCase):
 def result(self,status=0):return dict(process_cleanup_complete=True,errors=[],runner_exit=status,startup_committed=True)
 def test_exact_nonzero_status_accepted(self):
  f.assert_case('exit7',self.result(7),.5,True,[],False,[])
 def test_wrong_status_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'status'):f.assert_case('exit7',self.result(0),.5,True,[],False,[])
 def test_sentinel_survival_required(self):
  with self.assertRaisesRegex(RuntimeError,'sentinel'):f.assert_case('exit0',self.result(),.5,False,[],False,[])
 def test_surviving_fixture_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'survived'):f.assert_case('exit0',self.result(),.5,True,[123],False,[])
 def test_startup_work_marker_rejected(self):
  r=self.result(125);r['startup_committed']=False
  with self.assertRaisesRegex(RuntimeError,'startup gate'):f.assert_case('startup-cancel',r,.5,True,[],True,[])
 def test_startup_commit_rejected(self):
  with self.assertRaisesRegex(RuntimeError,'startup gate'):f.assert_case('startup-cancel',self.result(125),.5,True,[],False,[])
 def test_runner_death_real_grace_bounds(self):
  r=self.result(7);r.update(reason='pressure stop',stop_monotonic=5,cleanup_finished_monotonic=40.2,owned_processes={'123':7})
  f.assert_case('runner-death',r,36,True,[],False,[dict(pid=123,start=7)])
  r['cleanup_finished_monotonic']=5.5
  with self.assertRaisesRegex(RuntimeError,'35s'):f.assert_case('runner-death',r,36,True,[],False,[])
 def test_missing_registered_identity_rejected(self):
  r=self.result(7);r.update(reason='pressure stop',stop_monotonic=5,cleanup_finished_monotonic=40.2,owned_processes={})
  with self.assertRaisesRegex(RuntimeError,'registered'):f.assert_case('runner-death',r,36,True,[],False,[dict(pid=123,start=7)])
 def test_default_does_not_spawn(self):
  with patch.object(f.sys,'argv',['fixture']),patch.object(f.subprocess,'Popen') as spawn,patch('builtins.print'):
   self.assertEqual(f.main(),0)
  spawn.assert_not_called()
 def test_execute_requires_explicit_grant(self):
  with patch.object(f.sys,'argv',['fixture','--execute']),patch.object(f.subprocess,'Popen') as spawn,self.assertRaisesRegex(RuntimeError,'grant'):
   f.main()
  spawn.assert_not_called()
 def test_ungranted_or_changed_sources_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'grant.json'
   for permit,expected in [({},'not granted'),({'sleep_only_qualification_granted':True,'source_review_passed':True,'execution_scope':'sleep-only-isolated-fixture'},'source changed')]:
    p.write_text(json.dumps(permit))
    with patch.object(f.sys,'argv',['fixture','--execute','--authorization',str(p),'--authorization-sha256',f.s.sha(p)]),patch.object(f.subprocess,'Popen') as spawn,self.assertRaisesRegex(RuntimeError,expected):f.main()
    spawn.assert_not_called()
 def test_internal_modes_reject_production_directory(self):
  with self.assertRaisesRegex(RuntimeError,'isolated temporary'):f.fixture_directory(f.s.E)
 def test_internal_modes_require_admission(self):
  with tempfile.TemporaryDirectory(prefix='cpu-supervisor-sleep-') as tmp,patch.object(f.s,'E',Path(tmp).parent),self.assertRaises(FileNotFoundError):
   f.fixture_directory(tmp)
 def test_pidfd_open_failure_before_any_children(self):
  def unavailable(*args):raise OSError('pidfd unavailable')
  original=f.pidfd_self_probe
  with patch.object(f,'fixture_directory',return_value=Path('/tmp')),patch.object(f,'pidfd_self_probe',side_effect=lambda:original(lambda:10,lambda pid:(2,'S'),unavailable)),patch.object(f.subprocess,'Popen') as spawn,self.assertRaisesRegex(OSError,'pidfd unavailable'):
   f.outer('/tmp')
  spawn.assert_not_called()
 def test_pidfd_signal0_failure_closes_handle(self):
  closed=[]
  def denied(*args):raise PermissionError('signal0 denied')
  with self.assertRaises(PermissionError):f.pidfd_self_probe(lambda:10,lambda pid:(2,'S'),lambda *a:123,denied,closed.append)
  self.assertEqual(closed,[123])
 def test_pidfd_identity_change_rejects_no_signal(self):
  ids=iter([(2,'S'),(3,'S')]);sent=[];closed=[]
  with self.assertRaisesRegex(RuntimeError,'identity changed'):
   f.pidfd_self_probe(lambda:10,lambda pid:next(ids),lambda *a:123,lambda *a:sent.append(a),closed.append)
  self.assertEqual(sent,[]);self.assertEqual(closed,[123])
 def test_pidfd_self_probe_exact_handle_signal0(self):
  sent=[];closed=[]
  result=f.pidfd_self_probe(lambda:10,lambda pid:(2,'S'),lambda *a:123,lambda *a:sent.append(a),closed.append)
  self.assertEqual(sent,[(123,0)]);self.assertEqual(closed,[123]);self.assertTrue(result['pidfd_signal0_passed'])
 def test_helper_shared_deadline_late_start_not_new_ninety_seconds(self):
  slept=[];f.sleep_to_deadline(90,lambda:85,slept.append);self.assertEqual(slept,[5])
 def test_expired_helper_never_extends_admission(self):
  slept=[];f.sleep_to_deadline(90,lambda:95,slept.append);self.assertEqual(slept,[])
 def test_helper_pidfd_failure_never_spawns(self):
  with patch.object(f,'fixture_directory',return_value=Path('/tmp')),patch.object(f,'shared_deadline',return_value=90),patch.object(f,'pidfd_self_probe',side_effect=PermissionError('signal0 denied')),patch.object(f.subprocess,'Popen') as spawn,self.assertRaises(PermissionError):
   f.helper('runner-death','/tmp')
  spawn.assert_not_called()
 def test_all_sleep_helpers_consume_existing_shared_deadline(self):
  original=f.sleep_to_deadline
  for mode in ('sentinel','startup-work','resistant'):
   slept=[]
   with patch.object(f,'fixture_directory',return_value=Path('/tmp')),patch.object(f,'shared_deadline',return_value=90),patch.object(f,'pidfd_self_probe'),patch.object(f,'identity',return_value={}),patch.object(f,'write'),patch.object(f.signal,'signal'),patch.object(f,'sleep_to_deadline',side_effect=lambda deadline:original(deadline,lambda:85,slept.append)) as expire,patch.object(f.subprocess,'Popen') as spawn:
    self.assertEqual(f.helper(mode,'/tmp'),0)
   self.assertEqual(slept,[5]);expire.assert_called_once_with(90);spawn.assert_not_called()
if __name__=='__main__':unittest.main()
