"""Tiny harness fault tests only: no Bend compilation or GPU."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import strict_cpu_receipts as h

class Receipts(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.d=Path(self.temp.name);self.input=self.d/'input.txt';self.input.write_text('a');self.output=self.d/'artifact.txt'
  code="import pathlib,sys; pathlib.Path(sys.argv[-1]).write_text(pathlib.Path(sys.argv[1]).read_text()); print('ok')"
  self.args=[sys.executable,'-c',code,str(self.input),'-o',str(self.output)];self.r=h.run_step(self.d,'step',self.args,3)
 def tearDown(self):self.temp.cleanup()
 def stale(self,args=None):
  with self.assertRaises(h.StaleReceipt):h.run_step(self.d,'step',args or self.args,3)
 def test_valid_resume(self):self.assertEqual(self.r,h.run_step(self.d,'step',self.args,3))
 def test_changed_argv(self):self.stale(self.args+['different'])
 def test_changed_input(self):self.input.write_text('b');self.stale()
 def test_changed_artifact(self):self.output.write_text('wrong');self.stale()
 def test_missing_artifact(self):self.output.unlink();self.stale()
 def test_changed_stdout(self):Path(self.r['stdout']).write_text('bad\n');self.stale()
 def test_changed_stderr(self):Path(self.r['stderr']).write_text('bad\n');self.stale()
 def test_changed_metadata(self):
  p=self.d/'step.json';r=json.loads(p.read_text());r['exit']=99;p.write_text(json.dumps(r));self.stale()
 def test_changed_compiler_identity(self):
  b=h.compiler_bindings();b['source']='changed'
  with patch.object(h,'compiler_bindings',return_value=b):self.stale()
 def test_exact_streams(self):
  self.assertTrue(h.runtime_exact(self.r,'ok'));Path(self.r['stdout']).write_bytes(b'ok \n');self.assertFalse(h.runtime_exact(self.r,'ok'));Path(self.r['stdout']).write_bytes(b'ok\n');Path(self.r['stderr']).write_bytes(b'\n');self.assertFalse(h.runtime_exact(self.r,'ok'));Path(self.r['stderr']).write_bytes(b'');r=dict(self.r,exit=1);self.assertFalse(h.runtime_exact(r,'ok'));r=dict(self.r,timeout=True);self.assertFalse(h.runtime_exact(r,'ok'))

if __name__=='__main__':unittest.main()
