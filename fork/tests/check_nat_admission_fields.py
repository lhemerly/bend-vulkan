"""CPU-only budget and exact tool-path regression; never admits a worker."""
from pathlib import Path
import sys,copy,json,math,unittest.mock,os,shutil,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'fork/runtime'))
from nat_controller import validate_budget,check_launch_deadline
from nat_worker_prepare import prepare
out=ROOT/'evidence/nat-admission-fields-v1';out.mkdir(exist_ok=False)
base={'deadline_monotonic':150.0,'reserved_calls':0,'max_calls':2};assert validate_budget(base,100)==150
cases=[]
for field,values in [('deadline_monotonic',[float('nan'),float('inf'),-float('inf'),True,'150',None,100,761,2**54]),('reserved_calls',[True,-1,3,0.5,float('nan'),'0']),('max_calls',[True,0,4097,2.0,float('inf'),'2'])]:
 for value in values:
  b=copy.deepcopy(base);b[field]=value
  try:validate_budget(b,100)
  except RuntimeError:cases.append({'field':field,'value':repr(value),'rejected':True})
  else:raise AssertionError((field,value))
for b in [{},dict(base,unexpected=1),dict(base,reserved_calls=2)]:
 try:validate_budget(b,100)
 except RuntimeError:pass
 else:raise AssertionError(b)
# Simulates guard consuming the remaining window: no launch may follow it.
with unittest.mock.patch('nat_controller.time.monotonic',return_value=151):
 try:check_launch_deadline(validate_budget(base,100))
 except RuntimeError:pass
 else:raise AssertionError('expired after guard')
g=out/'generation';g.mkdir();old=ROOT/'evidence/nat-host-contract-v1/target/generated'
for name in ['source-identity.json','nat-plan.json','routing-plan.json','nat.comp','routing.c','default.c','nat.spv']:shutil.copy2(old/name,g/name)
shadow=out/'path-shadow';shadow.mkdir();fake=shadow/'glslangValidator';fake.write_text('#!/bin/sh\necho PATH-selected-validator-must-not-run >&2\nexit 99\n');fake.chmod(0o700)
with unittest.mock.patch.dict(os.environ,{'PATH':str(shadow)+':'+os.environ['PATH']}):prepare(g)
record=json.loads((g/'nat-worker/generation.json').read_text());approved=Path('/usr/bin/glslangValidator').resolve(strict=True)
assert record['compiler_argv'][0]==str(approved)
assert record['glslang_binary_sha256']==hashlib.sha256(approved.read_bytes()).hexdigest()
(out/'RESULT.json').write_text(json.dumps({'budget_negative_cases':cases,'unknown_missing_exhausted_rejected':True,'expiry_after_guard_rejected':True,'PATH_shadow_ignored':True,'invoked_and_hashed_same_resolved_binary':str(approved),'GPU_dispatches':0},indent=2)+'\n')
print('Finite typed bounded budgets, post-guard expiry and exact compiler path PASS')
