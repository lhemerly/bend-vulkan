"""Narrow pure CPU approval equality checks, no preflight/build/child/GPU."""
from pathlib import Path
import sys,json,time,copy,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'));import nat_window_runner as w
out=ROOT/'evidence/nat-frozen-device-tests-v1';out.mkdir(exist_ok=False)
p=ROOT/'evidence/nat-window-runner-review-v2/HOST-BOUND-FROZEN.json';spec=json.loads(p.read_text());now=time.monotonic()
a=dict(schema='bend-nat-assigned-window-v1',admitted=True,assigned_window='PURE-CPU-VALIDATION-ONLY',spec_sha256=w.sha(p),start_monotonic=now,deadline_monotonic=now+600,max_calls=36,device=spec['device'],driver=spec['driver'])
assert w.validate_approval(spec,a,p)==a['deadline_monotonic'];cases=[]
for field,value in [('index',1),('index',False),('index',0.0),('node','/dev/dri/renderD129'),('major',227),('minor',129),('vendor',4099),('product',29696),('sysfs','/sys/devices/another-PCI'),('name','replacement GPU')]:
 b=copy.deepcopy(a);b['device'][field]=value
 try:w.validate_approval(spec,b,p)
 except RuntimeError:cases.append({'changed_device_field':field,'replacement':value,'rejected':True})
 else:raise AssertionError(field)
b=copy.deepcopy(a);b['driver']['sysfs_driver']='/sys/bus/pci/drivers/replacement'
try:w.validate_approval(spec,b,p)
except RuntimeError:cases.append({'changed_driver_association':True,'rejected':True})
else:raise AssertionError('driver accepted')
(out/'RESULT.json').write_text(json.dumps({'scope':'pure CPU validate_approval only; no preflight or child','GPU_dispatches':0,'valid_frozen_boundary_accepted':True,'negative_cases':cases,'runner_sha256':w.sha(ROOT/'tools/nat_window_runner.py')},indent=2)+'\n');print('Exact frozen device/driver equality and 11 CPU substitution negatives PASS')
