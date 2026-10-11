"""Prepared fail-closed adapter tests. NOT run during source-only handoff.

Only synthetic receipt objects and temporary copies are used; no Bend worker,
compiler, namespace probe, network or candidate execution is used by these tests.
"""
import copy, hashlib, json, pathlib, tempfile, unittest
from unittest.mock import patch
import cpu_admission_adapter as A

class AdmissionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=pathlib.Path(self.temp.name);src=root/'source';src.mkdir()
  manifest=A.MANIFEST.read_bytes();entries=json.loads(manifest)['entries']
  for rel in [e['path'] for e in entries]+['bend2/base.bend']:
   p=src/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((A.SOURCE/rel).read_bytes())
  m=root/'manifest.json';m.write_bytes(manifest);seed=root/'seed.json'
  real=json.loads(A.SEED.read_bytes());seed.write_text(json.dumps({'pinned_commit':real['pinned_commit'],'files':[r for r in real['files'] if r['path'] in {e['path'] for e in entries}]}))
  for name,value in [('SOURCE',src),('MANIFEST',m),('SEED',seed)]:
   p=patch.object(A,name,value);p.start();self.addCleanup(p.stop)
  p=patch('strict_cpu_receipts.compiler_bindings',return_value={'test-fixture':'immutable-no-execution'});p.start();self.addCleanup(p.stop)
  self.adapter=A.AdmissionAdapter()
 def receipt(self,stage,exit=0,stdout=None,stderr=b''):
  if stdout is None:stdout=b'CHECK_OK\n' if stage=='check' and exit==0 else b''
  r={'stage':stage,'argv':self.adapter.stage_argv(self.active_entry,stage),'exit':exit,'stdout_hex':stdout.hex(),'stderr_hex':stderr.hex(),'timeout':False,'isolated_execution_verified':True,'binding_sha256':self.adapter.receipt_binding(self.active_entry,stage)};r['receipt_sha256']=A.digest(r);return r
 def entry(self,mode):
  self.active_entry=next(e for e in self.adapter.entries.values() if e['mode']==mode);return self.active_entry
 def test_wrong_path_hash_mode_and_golden_rejected(self):
  e=self.entry('bounded-stdout-cpu')
  for args in [('tests/../outside.bend',e['sha256'],e['mode'],e['expected_contract']), (e['path'],'0'*64,e['mode'],e['expected_contract']), (e['path'],e['sha256'],'missing',e['expected_contract']), (e['path'],e['sha256'],e['mode'],{})]:
   with self.assertRaises(ValueError):self.adapter.lookup(*args)
 def test_changed_source_and_import_rejected(self):
  e=self.entry('bounded-stdout-cpu');p=A.SOURCE/e['path'];p.write_bytes(p.read_bytes()+b'\nimport ./other.bend as X\n')
  with self.assertRaises(ValueError):self.adapter.lookup(e['path'],e['sha256'],e['mode'],e['expected_contract'])
 def test_manifest_mutation_rejected(self):
  A.MANIFEST.write_bytes(A.MANIFEST.read_bytes()+b' ')
  with self.assertRaises(ValueError):A.AdmissionAdapter()
 def test_checker_success_terminal_no_interpreter(self):
  e=self.entry('checker-only');rs={'check':self.receipt('check',stdout=b'CHECK_OK\n')}
  self.assertEqual(self.adapter.classify(e,rs),'failure-checker-only-NO-promotion');self.assertIsNone(self.adapter.next_stage(e,rs))
  rs['interp']=self.receipt('check');rs['interp']['stage']='interp'
  with self.assertRaises(ValueError):self.adapter.classify(e,rs)
 def test_stale_receipt_rejected(self):
  e=self.entry('checker-only');r=self.receipt('check',1);r['binding_sha256']='0'*64
  with self.assertRaises(ValueError):self.adapter.classify(e,{'check':r})
 def test_changed_receipt_bytes_rejected(self):
  e=self.entry('checker-only');r=self.receipt('check',1);r['stdout_hex']='20'
  with self.assertRaises(ValueError):self.adapter.classify(e,{'check':r})
 def test_unverified_isolation_rejected(self):
  e=self.entry('checker-only');r=self.receipt('check',1);r['isolated_execution_verified']=False;r['receipt_sha256']=A.digest({k:v for k,v in r.items() if k!='receipt_sha256'})
  with self.assertRaises(ValueError):self.adapter.classify(e,{'check':r})
 def test_extra_runtime_space_stays_failure(self):
  e=self.entry('bounded-stdout-cpu');raw=e['expected_contract']['stdout_utf8'].encode();rs={'check':self.receipt('check'),'interp':self.receipt('interp',stdout=raw[:-1]+b' \n')}
  self.assertEqual(self.adapter.classify(e,rs),'failure-interpreter');self.assertIsNone(self.adapter.next_stage(e,rs))
 def test_no_pure_case_compilation(self):
  e=self.entry('pure-interpreter-only');rs={'check':self.receipt('check'),'interp':self.receipt('interp',stdout=e['expected_contract']['stdout_utf8'].encode())}
  self.assertIn('C_JS-not-applicable',self.adapter.classify(e,rs));rs['upstream-c']=self.receipt('check');rs['upstream-c']['stage']='upstream-c'
  with self.assertRaises(ValueError):self.adapter.classify(e,rs)
 def test_printer_unexpected_success_blocks_promotion(self):
  e=self.entry('pure-interpreter-and-printer-refusal');rs={'check':self.receipt('check'),'interp':self.receipt('interp',stdout=e['expected_contract']['stdout_utf8'].encode()),'upstream-c':self.receipt('upstream-c')}
  with self.assertRaises(ValueError):self.adapter.next_stage(e,rs)
 def test_missing_C_parity_blocks_build(self):
  e=self.entry('bounded-stdout-cpu');rs={'check':self.receipt('check'),'interp':self.receipt('interp',stdout=e['expected_contract']['stdout_utf8'].encode()),'upstream-c':self.receipt('upstream-c'),'fork-c':self.receipt('fork-c')}
  with self.assertRaises(ValueError):self.adapter.next_stage(e,rs)

if __name__=='__main__':unittest.main()
