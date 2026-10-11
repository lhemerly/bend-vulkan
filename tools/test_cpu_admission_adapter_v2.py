"""Pure fixture/byte tests. No Bend, compiler, worker, namespace or GPU launch."""
import hashlib,json,pathlib,shutil,tempfile,unittest,zipfile
from unittest.mock import patch
import cpu_admission_adapter_v2 as A

class AdapterTrustTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.template=pathlib.Path(cls.temp.name)/'template';cls.template.mkdir()
  root=cls.template;source=root/'source';source.mkdir()
  review=A.REVIEW.read_bytes();(root/'review.zip').write_bytes(review)
  with zipfile.ZipFile(A.REVIEW) as z:
   manifest=z.read('PROPOSED-ADMISSION-MANIFEST.json');(root/'manifest.json').write_bytes(manifest)
   provenance=json.loads(z.read('REVIEW-PROVENANCE.json'))
  for item in provenance['source_hashes']:
   n=item['archive_path']
   if n.startswith('upstream/'):old=A.SOURCE/n[len('upstream/'):];dest=source/n[len('upstream/'):]
   elif n.startswith('local-review-context/'):old=A.ROOT/n[len('local-review-context/'):];dest=root/n[len('local-review-context/'):]
   else:continue
   dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old.read_bytes())
  wanted={e['path'] for e in json.loads(manifest)['entries']};real=json.loads(A.SEED.read_bytes())
  cls.seed_template={'pinned_commit':real['pinned_commit'],'files':[r for r in real['files'] if r['path'] in wanted]}
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)/'fixture';shutil.copytree(self.template,self.root)
  self.source=self.root/'source';self.out=self.root/'out';self.bins={}
  for tool in ('bun','clang'):
   p=self.root/'bin'/tool;p.parent.mkdir(exist_ok=True);p.write_bytes(('fixture '+tool+' NOT executable').encode());self.bins[tool]=str(p)
  seed=dict(self.seed_template);seed['bindings']={p:A.sha(p) for p in self.bins.values()};self.seed=self.root/'seed.json';self.seed.write_text(json.dumps(seed))
  for name,value in [('ROOT',self.root),('SOURCE',self.source),('OUT',self.out),('REVIEW',self.root/'review.zip'),('MANIFEST',self.root/'manifest.json'),('SEED',self.seed),('BASELINE_SHA',A.sha(self.seed))]:
   p=patch.object(A,name,value);p.start();self.addCleanup(p.stop)
  p=patch.object(A.shutil,'which',side_effect=lambda n:self.bins.get(n));p.start();self.addCleanup(p.stop)
 def adapter(self):return A.AdmissionAdapter()
 def entry(self,a,mode='bounded-stdout-cpu'):return next(e for e in a.entries.values() if e['mode']==mode)
 def identity(self,session):return {'fixture_only_NOT_real_qualification':True,'qualified_policy_sha256':'a'*64,'runtime_image_sha256':'b'*64,'execution_session':session}
 def receipt(self,a,e,stage,prior,session='1'*32,exit=0):
  outputs={};argv=a.stage_argv(e,stage,session)
  if stage in ('upstream-c','fork-c','build-c','upstream-js') and exit==0:
   p=pathlib.Path(argv[-1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture output NEVER executed');outputs[str(p)]=A.sha(p)
  r={'stage':stage,'argv':argv,'execution_session':session,'isolation_identity':self.identity(session),'isolated_execution_verified':True,
   'predecessor_receipt_sha256':next(reversed(prior.values()))['receipt_sha256'] if prior else None,
   'binding_sha256':a.receipt_binding(e,stage,session),'consumed_artifacts':a.consumed_artifacts(e,stage,session,prior),'produced_artifacts':outputs,
   'exit':exit,'timeout':False,'stdout_hex':(b'CHECK_OK\n' if stage=='check' and exit==0 else e['expected_contract'].get('stdout_utf8','').encode() if stage=='interp' and exit==0 else b'').hex(),'stderr_hex':''}
  if stage in ('upstream-c','fork-c') and exit==0:r['artifact_sha256']=next(iter(outputs.values()))
  r['receipt_sha256']=A.digest(r);return r
 def reseal(self,r):r['receipt_sha256']=A.digest({k:v for k,v in r.items() if k!='receipt_sha256'})
 def test_helper_mutation_rejected_before_any_import(self):
  p=self.root/'tools/strict_cpu_receipts.py';p.write_text('raise RuntimeError("MUST NEVER IMPORT")')
  with self.assertRaisesRegex(ValueError,'pre-import'):self.adapter()
 def test_probe_and_compiler_preconstruction_mutations(self):
  for rel in ('tools/cpu_ledger_probe_strict.ts','source/bend2/comp.ts'):
   p=self.root/rel;old=p.read_bytes();p.write_bytes(old+b'changed')
   with self.assertRaises(ValueError):self.adapter()
   p.write_bytes(old)
 def test_unapproved_baseline(self):
  self.seed.write_bytes(self.seed.read_bytes()+b' ')
  with self.assertRaisesRegex(ValueError,'unapproved baseline'):self.adapter()
 def test_unapproved_toolchain(self):
  pathlib.Path(self.bins['bun']).write_bytes(b'unreviewed tool')
  with self.assertRaises(ValueError):self.adapter()
 def test_postconstruction_dependency_mutation(self):
  a=self.adapter();e=self.entry(a);p=self.root/'tools/cpu_ledger_probe_strict.ts';p.write_bytes(p.read_bytes()+b'changed')
  with self.assertRaises(ValueError):a.lookup(e['path'],e['sha256'],e['mode'],e['expected_contract'])
 def test_returned_entry_mutations_cannot_change_reference(self):
  a=self.adapter()
  for field in ('mode','expected_contract','reviewed_stage_names'):
   e=self.entry(a)
   if field=='mode':e[field]='checker-only'
   elif field=='expected_contract':e[field]['stdout_utf8']='injected\n'
   else:e[field].reverse()
   with self.assertRaises(ValueError):a.classify(e,{})
  self.assertEqual(a.entries[self.entry(a)['path']]['mode'],'bounded-stdout-cpu')
 def test_outside_same_content_symlink_rejected(self):
  a=self.adapter();e=self.entry(a);p=self.source/e['path'];q=pathlib.Path(self.temp.name)/'outside.bend';q.write_bytes(p.read_bytes());p.unlink();p.symlink_to(q)
  with self.assertRaisesRegex(ValueError,'realpath'):a.lookup(e['path'],e['sha256'],e['mode'],e['expected_contract'])
 def test_direct_classify_order_and_missing_predecessor_rejected(self):
  a=self.adapter();e=self.entry(a)
  for history in ({'interp':{}},{'interp':{},'check':{}},{'check':{},'upstream-c':{}}):
   with self.assertRaisesRegex(ValueError,'order/closure'):a.classify(e,history)
 def test_checker_only_runtime_membership_rejected(self):
  a=self.adapter();e=self.entry(a,'checker-only')
  with self.assertRaisesRegex(ValueError,'order/closure'):a.classify(e,{'check':{},'interp':{}})
 def test_isolation_boolean_is_not_qualification(self):
  a=self.adapter();e=self.entry(a);r=self.receipt(a,e,'check',{})
  with self.assertRaisesRegex(ValueError,'qualified isolation absent'):a.classify(e,{'check':r})
 def test_qualified_policy_image_identity_mismatch(self):
  a=self.adapter();e=self.entry(a);r=self.receipt(a,e,'check',{});r['isolation_identity']['runtime_image_sha256']='c'*64;self.reseal(r)
  with patch.object(a,'qualified_isolation_identity',side_effect=self.identity):
   with self.assertRaisesRegex(ValueError,'identity changed'):a.classify(e,{'check':r})
 def test_mixed_execution_sessions_rejected(self):
  a=self.adapter();e=self.entry(a);rs={'check':self.receipt(a,e,'check',{})};rs['interp']=self.receipt(a,e,'interp',rs,session='2'*32)
  with patch.object(a,'qualified_isolation_identity',side_effect=self.identity):
   with self.assertRaisesRegex(ValueError,'mixed execution sessions'):a.classify(e,rs)
 def test_changed_predecessor_receipt_rejected(self):
  a=self.adapter();e=self.entry(a);rs={'check':self.receipt(a,e,'check',{})};rs['interp']=self.receipt(a,e,'interp',rs);rs['interp']['predecessor_receipt_sha256']='f'*64;self.reseal(rs['interp'])
  with patch.object(a,'qualified_isolation_identity',side_effect=self.identity):
   with self.assertRaisesRegex(ValueError,'chronology'):a.classify(e,rs)
 def test_upstream_C_replaced_before_build(self):
  a=self.adapter();e=self.entry(a);r=self.receipt(a,e,'upstream-c',{});p=pathlib.Path(next(iter(r['produced_artifacts'])));p.write_bytes(b'replaced')
  with self.assertRaisesRegex(ValueError,'replaced'):a.consumed_artifacts(e,'build-c','1'*32,{'upstream-c':r})
 def test_native_replaced_before_both_native_stages(self):
  a=self.adapter();e=self.entry(a);c=self.receipt(a,e,'upstream-c',{});b=self.receipt(a,e,'build-c',{'upstream-c':c});pathlib.Path(next(iter(b['produced_artifacts']))).write_bytes(b'replaced')
  for stage in ('native-t1','native-t2'):
   with self.assertRaisesRegex(ValueError,'replaced'):a.consumed_artifacts(e,stage,'1'*32,{'build-c':b})
 def test_JS_replaced_before_run(self):
  a=self.adapter();e=self.entry(a);r=self.receipt(a,e,'upstream-js',{});pathlib.Path(next(iter(r['produced_artifacts']))).write_bytes(b'replaced')
  with self.assertRaisesRegex(ValueError,'replaced'):a.consumed_artifacts(e,'js','1'*32,{'upstream-js':r})
 def test_detached_C_parity_rejected(self):
  a=self.adapter();e=self.entry(a);rs={}
  for s in ('check','interp','upstream-c'):rs[s]=self.receipt(a,e,s,rs)
  rs['upstream-c']['artifact_sha256']='f'*64;self.reseal(rs['upstream-c'])
  with patch.object(a,'qualified_isolation_identity',side_effect=self.identity):
   with self.assertRaisesRegex(ValueError,'detached'):a.classify(e,rs)
 def test_checker_unexpected_success_still_terminates(self):
  a=self.adapter();e=self.entry(a,'checker-only');rs={'check':self.receipt(a,e,'check',{})}
  with patch.object(a,'qualified_isolation_identity',side_effect=self.identity):
   self.assertEqual(a.classify(e,rs),'failure-checker-only-NO-promotion');self.assertIsNone(a.next_stage(e,rs))

if __name__=='__main__':unittest.main()
