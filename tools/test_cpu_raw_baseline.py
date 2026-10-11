"""Tiny pure integration tests: synthetic sources/receipts, zero dispatches."""
import json,pathlib,tempfile,unittest,types
from unittest.mock import patch
import cpu_raw_baseline as I
import raw_golden_contract as G

class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=pathlib.Path(self.tmp.name);self.source=root/'source';self.source.mkdir()
  samples={'tests/word.bend':(b'import Base\n#|word \n','word','pending',[],True),
   'tests/diagnostic.bend':(b'#|\n#|SOME PROOFS FAIL\n#|exit 1\n','SOME PROOFS FAIL\nexit 1','pending',[],True),
   'tests/none.bend':(b'def main(): 0\n','','pending',[],True),
   'tests/negative.bend':(b'#|error\n#|exit 1\n','error\nexit 1','pending',[],True),
   'tests/risk.bend':(b'import Base\n#|safe-looking\n','safe-looking','pending-safety-review',['held'],True)}
  self.rows=[]
  for rel,(data,golden,status,risk,main) in samples.items():
   p=self.source/rel;p.parent.mkdir(exist_ok=True);p.write_bytes(data)
   self.rows.append({'path':rel,'sha256':I.sha(data),'expected_output':golden,'status':status,'risk':risk,'stages':{},'main_marker_per_upstream_gate':main})
  baseline=json.dumps({'files':self.rows}).encode();inventory=b'immutable inventory';parser=pathlib.Path(G.__file__).read_bytes()
  sidecar=json.dumps({'records':[G.source_record(r,(self.source/r['path']).read_bytes()) for r in self.rows]}).encode()
  freeze=json.dumps({'sidecar_sha256':I.sha(sidecar),'parser_policy_sha256':I.sha(parser),'inventory_sha256':I.sha(inventory),'baseline_ledger_sha256':I.sha(baseline),'review_archive_sha256':'review-pin'}).encode()
  data={'baseline':baseline,'inventory':inventory,'parser':parser,'sidecar':sidecar,'freeze':freeze,'strict':b'raise RuntimeError("never imported in these tests")','resume':b'no execution','probe':b'immutable probe'}
  self.files={};self.pins={}
  for n,b in data.items():p=root/n;p.write_bytes(b);self.files[n]=p;self.pins[n]=I.sha(b)
  self.policy=I.Policy(self.files,self.pins,self.source);self.before=self.files['baseline'].read_bytes()
 def delta(self,path='tests/word.bend'):
  return self.policy.fresh_delta({'purpose':'next-safe100','selection':[path]},pathlib.Path(self.tmp.name)/'out')
 def test_baseline_immutable_and_delta_stages_separate(self):
  d=self.delta();d['records'][0]['stages']['fake']={'new':True};d['records'][0]['status']='pass-new'
  self.assertEqual(self.files['baseline'].read_bytes(),self.before);self.assertEqual(self.policy.row('tests/word.bend')['stages'],{});self.assertEqual(d['baseline_ancestry']['receipts_reattached'],0)
 def test_parser_sidecar_freeze_drift_stops_before_callback(self):
  for n in ('parser','sidecar','freeze'):
   with self.subTest(n=n):
    old=self.files[n].read_bytes();d=self.delta();calls=[];self.files[n].write_bytes(old+b' ')
    with self.assertRaises(ValueError):self.policy.dispatch('tests/word.bend','next-safe100',d['records'][0],lambda binding:calls.append(binding))
    self.assertEqual(calls,[]);self.files[n].write_bytes(old);self.policy=I.Policy(self.files,self.pins,self.source)
 def test_preimport_modified_parser_rejected(self):
  self.files['parser'].write_bytes(b'raise RuntimeError("MUST NOT EXECUTE")')
  with self.assertRaisesRegex(ValueError,'hash changed BEFORE'):I.Policy(self.files,self.pins,self.source)
 def test_raw_trailing_space_and_frozen_diagnostic_fields(self):
  b=self.policy.binding('tests/word.bend','next-safe100');self.assertEqual(bytes.fromhex(b['raw_golden_binding']['successful_runtime_contract']['stdout_hex']),b'word \n');self.assertEqual(b['frozen_diagnostic'],'word')
  b=self.policy.binding('tests/diagnostic.bend','next-safe100');self.assertEqual(b['contract_group'],'checker-negative-contract');self.assertTrue(b['frozen_diagnostic'].startswith('SOME PROOFS FAIL'));self.assertNotIn('raw_golden_binding',b)
 def test_contract_and_safety_holds(self):
  for p in ('tests/none.bend','tests/negative.bend','tests/risk.bend'):
   with self.assertRaises(ValueError):self.delta(p)
 def test_mutable_delta_cannot_substitute_frozen_row(self):
  d=self.delta();d['records'][0]['baseline_row_sha256']='0'*64;calls=[]
  with self.assertRaises(ValueError):self.policy.dispatch('tests/word.bend','next-safe100',d['records'][0],lambda b:calls.append(b))
  self.assertEqual(calls,[])
 def test_old_receipt_has_no_fresh_binding(self):
  row=self.policy.row('tests/word.bend');source=(self.source/row['path']).read_bytes();old={'basis':{},'exit':0,'timeout':False,'stdout_sha256':I.sha(b'word \n'),'stderr_sha256':I.sha(b'')};old['receipt_sha256']=I.digest(old)
  with self.assertRaises(ValueError):self.policy.bundle.exact_fresh_runtime(old,row,source,b'word \n',b'')
 def test_delta_record_selection_cannot_change(self):
  proposed=self.delta();changed=json.loads(json.dumps(proposed));changed['records'][0]['path']='tests/diagnostic.bend'
  with self.assertRaisesRegex(ValueError,'immutable selection'):I.validate_delta(changed,proposed)
  changed=json.loads(json.dumps(proposed));changed['records']=[]
  with self.assertRaisesRegex(ValueError,'selection size'):I.validate_delta(changed,proposed)
 def fake_stage(self,artifact=None):
  d=pathlib.Path(self.tmp.name)/'stage';d.mkdir(exist_ok=True)
  context={'compiler.ts':'compiler-pin','effect.c':'effect-pin','tool':'tool-pin'}
  self.policy.pin_compiler_context(context)
  inputs=[]
  if artifact:
   p=d/artifact;p.write_bytes(b'original producer output');inputs=[p]
  strict=types.SimpleNamespace(compiler_bindings=lambda:dict(context),sha=lambda p:I.sha(pathlib.Path(p).read_bytes()),declared_paths=lambda args:(inputs,[]))
  return d,context,strict,inputs
 def test_initial_context_is_immutable_copy(self):
  d,context,strict,inputs=self.fake_stage();context['tool']='replacement'
  with self.assertRaisesRegex(ValueError,'since initial validation'):self.policy.compiler_context(strict)
  with self.assertRaisesRegex(ValueError,'already pinned'):self.policy.pin_compiler_context(context)
 def test_between_stage_compiler_effect_tool_change_blocks_child(self):
  d,context,strict,inputs=self.fake_stage()
  for key in ('compiler.ts','effect.c','tool','added-effect.js'):
   with self.subTest(key=key),patch.object(I.subprocess,'Popen') as child:
    old=dict(context);context[key]='replacement'
    with self.assertRaisesRegex(ValueError,'since initial validation'):I.run_step(self.policy,strict,{}, {},d,'check',['fake-child'],1)
    child.assert_not_called();context.clear();context.update(old)
  self.assertFalse((d/'check.stdout').exists())
 def test_consumer_substitution_blocks_child_for_all_edges(self):
  d,context,strict,inputs=self.fake_stage('upstream.c');contract={'case':'frozen'};binding={'fresh':'delta'}
  for tag,producer,artifact in [('build-c','emit-upstream-c','upstream.c'),('native-t1','build-c','native'),('native-t2','build-c','native'),('js','emit-js','program.js')]:
   with self.subTest(tag=tag):
    p=d/artifact;p.write_bytes(b'original producer output');inputs[:]=[p]
    receipt={'exit':0,'timeout':False,'basis':{'fresh_delta_binding':binding,'frozen_case_contract':contract,'compiler_hashes':dict(context)},'output_hashes':{str(p):strict.sha(p)}};receipt['receipt_sha256']=I.digest(receipt)
    stages={producer:receipt};hashes={str(p):strict.sha(p)}
    self.assertEqual(I.producer_lineage(tag,d,stages,hashes,binding,contract,context)[str(p)]['producer_receipt_sha256'],receipt['receipt_sha256'])
    p.write_bytes(b'substituted between stages')
    with patch.object(I.subprocess,'Popen') as child:
     with self.assertRaisesRegex(ValueError,'differs from producer'):I.run_step(self.policy,strict,binding,contract,d,tag,['fake-child'],1,stages)
     child.assert_not_called()
    self.assertFalse((d/(tag+'.stdout')).exists())
 def test_after_stage_context_change_rejects_receipt_without_real_child(self):
  d,context,strict,inputs=self.fake_stage()
  class FakeChild:
   pid=123456789
   def wait(self,timeout=None):
    if timeout is not None:context['effect.c']='changed during simulated stage'
    return 0
  with patch.object(I.subprocess,'Popen',return_value=FakeChild()) as child,patch.object(I.os,'killpg'):
   with self.assertRaisesRegex(ValueError,'since initial validation'):I.run_step(self.policy,strict,{}, {},d,'check',['fake-child'],1)
   self.assertEqual(child.call_count,1)
  self.assertFalse((d/'check.json').exists())
 def test_exact_idle_host_guard_refusal_blocks_stage_before_Popen(self):
  d,context,strict,inputs=self.fake_stage()
  guard=types.SimpleNamespace(policy_sha='policy',grant_sha='grant',check=lambda:(_ for _ in ()).throw(RuntimeError('host became active')))
  root=pathlib.Path(self.tmp.name);(root/'evidence').mkdir(exist_ok=True)
  with patch.object(I,'ROOT',root),patch.object(I,'HOST_GUARD',guard),patch.object(I.subprocess,'Popen') as child:
   with self.assertRaisesRegex(RuntimeError,'host became active'):I.run_step(self.policy,strict,{}, {},d,'check',['fake-child'],1)
   child.assert_not_called();self.assertTrue((root/'evidence/CPU-PAUSE').exists())
 def test_host_guard_pause_error_retained_without_dispatch(self):
  guard=types.SimpleNamespace(check=lambda:(_ for _ in ()).throw(RuntimeError('host active')))
  with patch.object(I,'HOST_GUARD',guard),patch.object(I.Path,'touch',side_effect=PermissionError('pause denied')),patch.object(I.subprocess,'Popen') as child:
   with self.assertRaisesRegex(RuntimeError,'pause write failed'):I.require_host_activity()
   child.assert_not_called()
 def ancestry_fixture(self):
  root=pathlib.Path(self.tmp.name);rows=list(self.rows);ancestors=[]
  for index in range(101):
   row=dict(self.rows[0]);row['path']='tests/ancestor'+str(index)+'.bend';rows.append(row)
   (self.source/row['path']).write_bytes((self.source/'tests/word.bend').read_bytes())
   ancestors.append({'path':row['path'],'status':'pass-check-interpreter','stages':{'fixture':{}},'baseline_row_sha256':I.digest(row)})
  baseline=json.dumps({'files':rows}).encode();self.files['baseline'].write_bytes(baseline);self.pins['baseline']=I.sha(baseline)
  sidecar=json.dumps({'records':[G.source_record(r,(self.source/r['path']).read_bytes()) for r in rows]}).encode()
  self.files['sidecar'].write_bytes(sidecar);self.pins['sidecar']=I.sha(sidecar)
  freeze=json.loads(self.files['freeze'].read_bytes());freeze.update(baseline_ledger_sha256=self.pins['baseline'],sidecar_sha256=self.pins['sidecar'])
  self.files['freeze'].write_text(json.dumps(freeze));self.pins['freeze']=I.sha(self.files['freeze'].read_bytes())
  self.policy=I.Policy(self.files,self.pins,self.source)
  delta=lambda records:{'execution_started':True,'CPU_interval_released':True,'baseline_ancestry':{'sha256':self.pins['baseline']},'records':records}
  values={'word_delta':json.dumps(delta(ancestors[:1])).encode(),'next100_delta':json.dumps(delta(ancestors[1:])).encode(),
   'terminal_audit':json.dumps({'audit_passed':True,'selected_cases':101,'cases':[{'path':r['path']} for r in ancestors]}).encode(),
   'results_archive':b'approved synthetic archive','independent_review_archive':b'approved synthetic independent review'}
  artifacts={}
  for role,data in values.items():
   p=root/role;p.write_bytes(data);artifacts[role]={'path':role,'sha256':I.sha(data)}
  selection={'purpose':'next-safe100','selection':['tests/word.bend'],'source_sha256_by_path':{'tests/word.bend':self.rows[0]['sha256']},
   'audited_ancestry':{'baseline_sha256':self.pins['baseline'],'artifacts':artifacts}}
  return root,selection
 def test_ancestry_drift_blocks_dispatch_before_callback(self):
  root,selection=self.ancestry_fixture()
  with patch.object(I,'ROOT',root):
   delta=self.policy.fresh_delta(selection,root/'out');self.assertIn('ancestry_results_archive',delta['binding']['approved_pins'])
   (root/'next100_delta').write_bytes(b'changed terminal ancestor');calls=[]
   with self.assertRaisesRegex(ValueError,'file identity changed'):self.policy.dispatch('tests/word.bend','next-safe100',delta['records'][0],lambda binding:calls.append(binding))
   self.assertEqual(calls,[])
 def test_completed_ancestry_path_cannot_be_selected(self):
  root,selection=self.ancestry_fixture();selection['selection']=['tests/ancestor0.bend'];selection['source_sha256_by_path']={'tests/ancestor0.bend':self.rows[0]['sha256']}
  with patch.object(I,'ROOT',root):
   with self.assertRaisesRegex(ValueError,'already-completed'):self.policy.fresh_delta(selection,root/'out')
 def test_independent_source_pin_mismatch_rejected(self):
  root,selection=self.ancestry_fixture();selection['source_sha256_by_path']['tests/word.bend']='0'*64
  with patch.object(I,'ROOT',root):
   with self.assertRaisesRegex(ValueError,'source hash changed'):self.policy.fresh_delta(selection,root/'out')
 def test_v3_ancestry_requires_paired_delta_and_audit(self):
  root,selection=self.ancestry_fixture()
  selection['audited_ancestry']['artifacts']['v3_delta']=dict(selection['audited_ancestry']['artifacts']['next100_delta'])
  with patch.object(I,'ROOT',root):
   with self.assertRaisesRegex(ValueError,'incomplete audited ancestry'):self.policy.fresh_delta(selection,root/'out')
 def test_v3_completed_exclusion_and_anchor_drift_before_callback(self):
  root,selection=self.ancestry_fixture();rows=json.loads(self.files['baseline'].read_bytes())['files'];records=[]
  for index in range(100):
   row=dict(self.rows[0]);row['path']='tests/v3ancestor'+str(index)+'.bend';rows.append(row)
   (self.source/row['path']).write_bytes((self.source/'tests/word.bend').read_bytes())
   records.append({'path':row['path'],'status':'pass-check-interpreter','stages':{'fixture':{}},'baseline_row_sha256':I.digest(row)})
  baseline=json.dumps({'files':rows}).encode();self.files['baseline'].write_bytes(baseline);self.pins['baseline']=I.sha(baseline)
  sidecar=json.dumps({'records':[G.source_record(r,(self.source/r['path']).read_bytes()) for r in rows]}).encode();self.files['sidecar'].write_bytes(sidecar);self.pins['sidecar']=I.sha(sidecar)
  freeze=json.loads(self.files['freeze'].read_bytes());freeze.update(baseline_ledger_sha256=self.pins['baseline'],sidecar_sha256=self.pins['sidecar'])
  self.files['freeze'].write_text(json.dumps(freeze));self.pins['freeze']=I.sha(self.files['freeze'].read_bytes());self.policy=I.Policy(self.files,self.pins,self.source)
  ancestry=selection['audited_ancestry'];ancestry['baseline_sha256']=self.pins['baseline']
  for role in ('word_delta','next100_delta'):
   p=root/role;d=json.loads(p.read_bytes());d['baseline_ancestry']['sha256']=self.pins['baseline'];p.write_text(json.dumps(d));ancestry['artifacts'][role]['sha256']=I.sha(p.read_bytes())
  values={'v3_delta':{'execution_started':True,'CPU_interval_released':True,'baseline_ancestry':{'sha256':self.pins['baseline']},'records':records},
   'v3_terminal_audit':{'audit_passed':True,'selected_cases':100,'cases':[{'path':r['path']} for r in records]}}
  for role,value in values.items():
   p=root/role;p.write_text(json.dumps(value));ancestry['artifacts'][role]={'path':role,'sha256':I.sha(p.read_bytes())}
  with patch.object(I,'ROOT',root):
   delta=self.policy.fresh_delta(selection,root/'out');self.assertIn('ancestry_v3_delta',delta['binding']['approved_pins'])
   bad=json.loads(json.dumps(selection));bad['selection']=['tests/v3ancestor0.bend'];bad['source_sha256_by_path']={'tests/v3ancestor0.bend':self.rows[0]['sha256']}
   with self.assertRaisesRegex(ValueError,'already-completed'):self.policy.fresh_delta(bad,root/'out')
   (root/'v3_terminal_audit').write_bytes(b'changed v3 audit');calls=[]
   with self.assertRaisesRegex(ValueError,'file identity changed'):self.policy.dispatch('tests/word.bend','next-safe100',delta['records'][0],lambda b:calls.append(b))
   self.assertEqual(calls,[])
 def test_v4_ancestry_requires_v3_and_paired_audit(self):
  root,selection=self.ancestry_fixture()
  selection['audited_ancestry']['artifacts']['v4_delta']=dict(selection['audited_ancestry']['artifacts']['next100_delta'])
  with patch.object(I,'ROOT',root):
   with self.assertRaisesRegex(ValueError,'incomplete audited ancestry'):self.policy.fresh_delta(selection,root/'out')
 def test_v4_completed_exclusion_and_delta_drift_before_callback(self):
  root,selection=self.ancestry_fixture();rows=json.loads(self.files['baseline'].read_bytes())['files'];extensions={}
  for version in ('v3','v4'):
   records=[]
   for index in range(100):
    row=dict(self.rows[0]);row['path']='tests/'+version+'ancestor'+str(index)+'.bend';rows.append(row)
    (self.source/row['path']).write_bytes((self.source/'tests/word.bend').read_bytes())
    records.append({'path':row['path'],'status':'pass-check-interpreter','stages':{'fixture':{}},'baseline_row_sha256':I.digest(row)})
   extensions[version]=records
  baseline=json.dumps({'files':rows}).encode();self.files['baseline'].write_bytes(baseline);self.pins['baseline']=I.sha(baseline)
  sidecar=json.dumps({'records':[G.source_record(r,(self.source/r['path']).read_bytes()) for r in rows]}).encode();self.files['sidecar'].write_bytes(sidecar);self.pins['sidecar']=I.sha(sidecar)
  freeze=json.loads(self.files['freeze'].read_bytes());freeze.update(baseline_ledger_sha256=self.pins['baseline'],sidecar_sha256=self.pins['sidecar'])
  self.files['freeze'].write_text(json.dumps(freeze));self.pins['freeze']=I.sha(self.files['freeze'].read_bytes());self.policy=I.Policy(self.files,self.pins,self.source)
  ancestry=selection['audited_ancestry'];ancestry['baseline_sha256']=self.pins['baseline']
  for role in ('word_delta','next100_delta'):
   p=root/role;d=json.loads(p.read_bytes());d['baseline_ancestry']['sha256']=self.pins['baseline'];p.write_text(json.dumps(d));ancestry['artifacts'][role]['sha256']=I.sha(p.read_bytes())
  for version,records in extensions.items():
   values={version+'_delta':{'execution_started':True,'CPU_interval_released':True,'baseline_ancestry':{'sha256':self.pins['baseline']},'records':records},
    version+'_terminal_audit':{'audit_passed':True,'selected_cases':100,'cases':[{'path':r['path']} for r in records]}}
   for role,value in values.items():
    p=root/role;p.write_text(json.dumps(value));ancestry['artifacts'][role]={'path':role,'sha256':I.sha(p.read_bytes())}
  with patch.object(I,'ROOT',root):
   delta=self.policy.fresh_delta(selection,root/'out');self.assertIn('ancestry_v4_terminal_audit',delta['binding']['approved_pins'])
   bad=json.loads(json.dumps(selection));bad['selection']=['tests/v4ancestor0.bend'];bad['source_sha256_by_path']={'tests/v4ancestor0.bend':self.rows[0]['sha256']}
   with self.assertRaisesRegex(ValueError,'already-completed'):self.policy.fresh_delta(bad,root/'out')
   (root/'v4_delta').write_bytes(b'changed v4 delta');calls=[]
   with self.assertRaisesRegex(ValueError,'file identity changed'):self.policy.dispatch('tests/word.bend','next-safe100',delta['records'][0],lambda b:calls.append(b))
   self.assertEqual(calls,[])
 def partial_remainder_fixture(self):
  root,selection=self.ancestry_fixture();rows=json.loads(self.files['baseline'].read_bytes())['files'];extensions={}
  for version in ('v3','v4','v5'):
   records=[]
   for index in range(100):
    row=dict(self.rows[0]);row['path']='tests/'+version+'ancestor'+str(index)+'.bend';rows.append(row)
    (self.source/row['path']).write_bytes((self.source/'tests/word.bend').read_bytes())
    pending=version=='v5' and index>=13
    stages={'check':{},'interp':{}} if version=='v5' and index==13 else {} if pending else {'fixture':{}}
    records.append({'path':row['path'],'status':'pending' if pending else 'pass-check-interpreter','stages':stages,'baseline_row_sha256':I.digest(row)})
   extensions[version]=records
  baseline=json.dumps({'files':rows}).encode();self.files['baseline'].write_bytes(baseline);self.pins['baseline']=I.sha(baseline)
  sidecar=json.dumps({'records':[G.source_record(r,(self.source/r['path']).read_bytes()) for r in rows]}).encode();self.files['sidecar'].write_bytes(sidecar);self.pins['sidecar']=I.sha(sidecar)
  freeze=json.loads(self.files['freeze'].read_bytes());freeze.update(baseline_ledger_sha256=self.pins['baseline'],sidecar_sha256=self.pins['sidecar'])
  self.files['freeze'].write_text(json.dumps(freeze));self.pins['freeze']=I.sha(self.files['freeze'].read_bytes());self.policy=I.Policy(self.files,self.pins,self.source)
  ancestry=selection['audited_ancestry'];ancestry['baseline_sha256']=self.pins['baseline']
  for role in ('word_delta','next100_delta'):
   p=root/role;d=json.loads(p.read_bytes());d['baseline_ancestry']['sha256']=self.pins['baseline'];p.write_text(json.dumps(d));ancestry['artifacts'][role]['sha256']=I.sha(p.read_bytes())
  for version,records in extensions.items():
   delta={'execution_started':True,'CPU_interval_released':True,'baseline_ancestry':{'sha256':self.pins['baseline']},'selection':{'selection':[r['path'] for r in records]},'records':records}
   audit={'audit_passed':True,'selected_cases':100,'cases':[{'path':r['path'],'fresh_status':r['status']} for r in records]}
   if version=='v5':audit.update(batch_complete=False,terminal_cases=13,attempted_cases=14,remaining_uncompleted_cases=87)
   roles=(version+'_delta',version+'_terminal_audit') if version!='v5' else ('v5_partial_delta','v5_partial_audit')
   for role,value in zip(roles,(delta,audit)):
    p=root/role;p.write_text(json.dumps(value));ancestry['artifacts'][role]={'path':role,'sha256':I.sha(p.read_bytes())}
  selection['selection']=[r['path'] for r in extensions['v5'] if r['status']=='pending']
  selection['source_sha256_by_path']={p:self.rows[0]['sha256'] for p in selection['selection']}
  selection['partial_receipt_reuse_policy']='none-fresh-case-execution';selection['pressure_qualification_required']=True
  hold=root/'pressure_hold';hold.write_bytes(b'{"resource_admission_granted":false}')
  selection['resource_hold_anchor']={'path':'pressure_hold','sha256':I.sha(hold.read_bytes())}
  return root,selection
 def test_partial_exact87_empty_delta_and_no_old_receipt_rebinding(self):
  root,selection=self.partial_remainder_fixture()
  with patch.object(I,'ROOT',root):
   delta=self.policy.fresh_delta(selection,root/'new-out')
  self.assertEqual(len(delta['records']),87);self.assertTrue(all(r['status']=='pending' and not r['stages'] for r in delta['records']))
  self.assertEqual(delta['baseline_ancestry']['receipts_reattached'],0);self.assertIn('pressure_hold',delta['binding']['approved_pins'])
 def test_partial_completed_and_reuse_policy_rejected(self):
  root,selection=self.partial_remainder_fixture()
  with patch.object(I,'ROOT',root):
   bad=json.loads(json.dumps(selection));bad['selection'][0]='tests/v5ancestor0.bend'
   with self.assertRaisesRegex(ValueError,'exact pending'):self.policy.fresh_delta(bad,root/'out')
   bad=json.loads(json.dumps(selection));bad['partial_receipt_reuse_policy']='retag-old-receipts'
   with self.assertRaisesRegex(ValueError,'fresh partial-case execution'):self.policy.fresh_delta(bad,root/'out')
 def test_partial_anchor_and_hold_drift_block_callback(self):
  for changed in ('v5_partial_audit','pressure_hold'):
   with self.subTest(changed=changed):
    root,selection=self.partial_remainder_fixture()
    with patch.object(I,'ROOT',root):delta=self.policy.fresh_delta(selection,root/'out')
    (root/changed).write_bytes(b'changed held ancestry');calls=[]
    with self.assertRaisesRegex(ValueError,'file identity changed'):self.policy.dispatch(selection['selection'][0],'next-safe100',delta['records'][0],lambda b:calls.append(b))
    self.assertEqual(calls,[])
 def test_pressure_qualification_cannot_be_inferred_from_cleanup(self):
  selection={'pressure_qualification_required':True,'resource_hold_anchor':{'sha256':'held-resource-decision'}}
  cleanup={'released':True,'process_cleanup_complete':True,'CPU_window_granted':True}
  with self.assertRaisesRegex(ValueError,'pressure hold remains'):I.require_pressure_qualification(selection,cleanup)
  grant={'resource_pressure_qualification_granted':True,'resource_admission_granted':True,'CPU_baseline_only':True,'supersedes_resource_hold_sha256':'wrong-hold'}
  with self.assertRaisesRegex(ValueError,'identify the held'):I.require_pressure_qualification(selection,grant)
  grant['supersedes_resource_hold_sha256']='held-resource-decision';I.require_pressure_qualification(selection,grant)

if __name__=='__main__':unittest.main()
