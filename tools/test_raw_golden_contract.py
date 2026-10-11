"""Pure byte-contract tests; no candidate, compiler, subprocess or GPU execution."""
import copy,json,unittest
import raw_golden_contract as G

class GoldenTests(unittest.TestCase):
 def fixture(self,source=b'#|hello \n',expected='hello',status='pending'):
  row={'path':'tests/example.bend','sha256':G.sha_bytes(source),'expected_output':expected,'main_marker_per_upstream_gate':True,'status':status,'risk':[]}
  baseline=json.dumps({'files':[row]}).encode();inventory=b'original inventory';parser=b'parser policy'
  sidecar=json.dumps({'records':[G.source_record(row,source)]}).encode()
  freeze={'sidecar_sha256':G.sha_bytes(sidecar),'parser_policy_sha256':G.sha_bytes(parser),'inventory_sha256':G.sha_bytes(inventory),'baseline_ledger_sha256':G.sha_bytes(baseline),'review_archive_sha256':'review-pinned'}
  return G.FrozenBundle(sidecar,freeze,parser,inventory,baseline),row,source,(sidecar,freeze,parser,inventory,baseline)
 def receipt(self,bundle,row,source,stdout=b'hello \n',stderr=b'',timeout=False,exit=0):
  r={'basis':bundle.bind_fresh_basis({'planned_execution_only':True},row,source),'stdout_sha256':G.sha_bytes(stdout),'stderr_sha256':G.sha_bytes(stderr),'timeout':timeout,'exit':exit};r['receipt_sha256']=G.digest(r);return r
 def test_absent_marker_is_not_empty_marker(self):
  absent=G.markers(b'def main(): 0\n');empty=G.markers(b'#|\n')
  self.assertFalse(absent['has_marker']);self.assertEqual(absent['marker_count'],0)
  self.assertTrue(empty['has_marker']);self.assertEqual(empty['marker_count'],1);self.assertEqual(empty['payload_lines'][0]['payload_hex'],'')
 def test_missing_marker_has_no_runtime_oracle(self):
  b,r,s,_=self.fixture(b'def main(): 0\n','')
  with self.assertRaises(ValueError):b.context(r,s)
 def test_empty_marker_runtime_LF_is_explicit_policy(self):
  b,r,s,_=self.fixture(b'#|\n','');c=b.context(r,s)
  self.assertEqual(bytes.fromhex(c['successful_runtime_contract']['stdout_hex']),b'\n');self.assertEqual(G.markers(s)['joined_payload_hex'],'')
 def test_trailing_spaces_tabs_preserved(self):
  b,r,s,_=self.fixture(b'#|hello \t\n','hello');self.assertEqual(bytes.fromhex(b.context(r,s)['successful_runtime_contract']['stdout_hex']),b'hello \t\n')
 def test_leading_trailing_empty_markers_and_multiline(self):
  raw=G.markers(b'#|\n#|one \n#|two\t\n#|\n');self.assertEqual(bytes.fromhex(raw['joined_payload_hex']),b'\none \ntwo\t\n');self.assertEqual(raw['marker_count'],4)
 def test_CR_and_literal_LF_handling(self):
  raw=G.markers(b'#|x\r\n#|y\n');self.assertEqual(bytes.fromhex(raw['joined_payload_hex']),b'x\r\ny')
 def test_diagnostic_leading_LF_does_not_change_branch(self):
  source=b'#|\n#|SOME PROOFS FAIL\n#|exit 1\n';r={'path':'tests/diagnostic.bend','sha256':G.sha_bytes(source),'expected_output':'SOME PROOFS FAIL\nexit 1','main_marker_per_upstream_gate':True,'status':'pending'}
  rec=G.source_record(r,source);self.assertEqual(rec['contract_group'],'checker-negative-contract');self.assertIsNone(rec['successful_runtime']);self.assertTrue(rec['frozen_expected_output'].startswith('SOME PROOFS FAIL'))
 def test_runtime_negative_not_stdout_success(self):
  b,r,s,_=self.fixture(b'#|error\n#|exit 1\n','error\nexit 1')
  with self.assertRaises(ValueError):b.context(r,s)
 def test_no_main_verdict_not_runtime(self):
  source=b'#|ALL PROOFS CHECK\n';r={'path':'tests/verdict.bend','sha256':G.sha_bytes(source),'expected_output':'ALL PROOFS CHECK','main_marker_per_upstream_gate':False,'status':'pending'}
  self.assertEqual(G.source_record(r,source)['contract_group'],'check-verdict-contract')
 def test_source_hash_drift_rejected(self):
  b,r,s,_=self.fixture()
  with self.assertRaises(ValueError):b.context(r,s+b'changed')
 def test_sidecar_parser_inventory_history_drift_rejected(self):
  _,_,_,args=self.fixture()
  for i in (0,2,3,4):
   changed=list(args);changed[i]+=b' '
   with self.assertRaises(ValueError):G.FrozenBundle(*changed)
 def test_in_memory_contract_mutation_rejected(self):
  b,r,s,_=self.fixture();b.records[r['path']]['successful_runtime']['stdout_hex']='00'
  with self.assertRaises(ValueError):b.context(r,s)
 def test_historical_failure_not_promoted(self):
  b,r,s,_=self.fixture(status='failure-interpreter');o=b.observe_historical(r,s,b'hello \n',b'',0,False)
  self.assertTrue(o['raw_contract_match']);self.assertEqual(o['original_status_preserved'],'failure-interpreter');self.assertFalse(o['fresh_execution']);self.assertFalse(o['status_promoted'])
 def test_old_receipt_cannot_pass_fresh_contract(self):
  b,r,s,_=self.fixture();old={'basis':{},'exit':0,'timeout':False,'stdout_sha256':G.sha_bytes(b'hello \n'),'stderr_sha256':G.sha_bytes(b'')};old['receipt_sha256']=G.digest(old)
  with self.assertRaises(ValueError):b.exact_fresh_runtime(old,r,s,b'hello \n',b'')
 def test_exact_fresh_bytes_and_failure_streams(self):
  b,r,s,_=self.fixture();good=self.receipt(b,r,s);self.assertTrue(b.exact_fresh_runtime(good,r,s,b'hello \n',b''))
  for stdout,stderr,timeout,exit in [(b'hello\n',b'',False,0),(b'hello \n',b'err',False,0),(b'hello \n',b'',True,0),(b'hello \n',b'',False,1)]:
   rec=self.receipt(b,r,s,stdout,stderr,timeout,exit);self.assertFalse(b.exact_fresh_runtime(rec,r,s,stdout,stderr))
 def test_receipt_bytes_and_binding_mutation_rejected(self):
  b,r,s,_=self.fixture();rec=self.receipt(b,r,s)
  with self.assertRaises(ValueError):b.exact_fresh_runtime(rec,r,s,b'hello\n',b'')
  rec['basis']['raw_golden_binding']['path']='tests/other.bend'
  with self.assertRaises(ValueError):b.exact_fresh_runtime(rec,r,s,b'hello \n',b'')

if __name__=='__main__':unittest.main()
