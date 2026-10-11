"""Invoke actual strict main() on tiny completed ledgers; no Bend execution."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import cpu_compatibility_strict as runner
from cpu_resume import bind_completed
from strict_cpu_receipts import sha,StaleReceipt

class Resume(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';self.out=self.root/'evidence/ledger';self.out.mkdir(parents=True);self.file=self.source/'tests/check/toy.bend';self.file.parent.mkdir(parents=True);self.file.write_text('pinned source')
  self.effect=self.source/'bend2/effs/write.js';self.effect.parent.mkdir(parents=True);self.effect.write_text('pinned effect')
  self.artifact=self.out/'toy.c';self.artifact.write_text('pinned artifact')
  stdout=self.out/'check.stdout';stderr=self.out/'check.stderr';stdout.write_bytes(b'CHECK_OK\n');stderr.write_bytes(b'')
  self.stage={'argv':['fake-probe',str(self.file),str(self.artifact)],'exit':0,'timeout':False,'timeout_seconds':15,'elapsed_seconds':0,'stdout':str(stdout),'stderr':str(stderr),'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)};(self.out/'check.json').write_text(json.dumps(self.stage))
  self.row={'path':'tests/check/toy.bend','sha256':sha(self.file),'status':'pass-check-only','risk':[],'stages':{'check':self.stage}};bind_completed(self.row,self.source,self.root,self.context())
  self.ledger={'bindings':{'fixture':'pinned'},'files':[self.row],'summary':{'files':1},'previous_checkpoint':{'fixture':'already-seeded'}};self.save()
  inv=self.root/'evidence/compatibility-roadmap-v1/INVENTORY.json';inv.parent.mkdir();inv.write_text(json.dumps({'files':[],'summary':{}}))
  (self.root/'evidence/cpu-strict-selection.json').write_text(json.dumps({'selection':[self.row['path']]}));(self.root/'evidence/CPU-PAUSE').touch()
 def context(self):return {str(self.effect):sha(self.effect)}
 def save(self):(self.out/'LEDGER.json').write_text(json.dumps(self.ledger))
 def tearDown(self):self.tmp.cleanup()
 def resume(self):
  with patch.object(runner,'ROOT',self.root),patch.object(runner,'SOURCE',self.source),patch.object(runner,'ledger_bindings',return_value={'fixture':'pinned'}),patch.object(runner,'compiler_bindings',side_effect=self.context),patch.object(runner,'run_step',side_effect=AssertionError('must not execute')),patch.object(sys,'argv',['runner','--output','ledger']):runner.main()
 def stale(self):
  with self.assertRaises(StaleReceipt):self.resume()
 def test_valid_paused_resume(self):self.resume()
 def test_source_mutation_before_pause_or_skip(self):self.file.write_text('changed source');self.stale()
 def test_stdout_mutation_before_pause_or_skip(self):Path(self.stage['stdout']).write_text('changed\n');self.stale()
 def test_artifact_mutation(self):self.artifact.write_text('changed');self.stale()
 def test_effect_mutation(self):self.effect.write_text('changed effect');self.stale()
 def test_row_metadata_mutation(self):self.row['status']='pass-CPU-lanes-default-C-parity';self.save();self.stale()
 def test_missing_binding(self):self.row.pop('completed_binding');self.save();self.stale()
 def test_metadata_file_mutation(self):(self.out/'check.json').write_text('{}');self.stale()
 def test_completed_row_outside_selection(self):
  (self.root/'evidence/cpu-strict-selection.json').write_text(json.dumps({'selection':[]}));self.file.write_text('changed');self.stale()
 def test_valid_skip_without_pause(self):(self.root/'evidence/CPU-PAUSE').unlink();self.resume()

if __name__=='__main__':unittest.main()
