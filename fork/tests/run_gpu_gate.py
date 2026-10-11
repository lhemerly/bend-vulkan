"""Parent-authorized exclusive finite correctness gate: <=5min and <=64 dispatches."""
from pathlib import Path
import sys,os,json,time,subprocess,shutil,hashlib
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'fork/runtime'));sys.path.insert(0,str(r/'tools'))
from prepare import prepare
from run_examples import identity
out=r/'evidence/fork-generated-gpu-gate';out.mkdir(exist_ok=False);receipts=out/'receipts';receipts.mkdir();names=['scalar','pair_distinct','renamed_reordered','host_irrelevant','host_twice']
matrix=[{'kind':'host','name':n,'order':o,'expected_dispatches':2 if n=='host_twice' else 1} for n in names for o in (0,1)]
matrix += [{'kind':'direct','name':n,'input':x,'order':o,'expected_dispatches':1} for n in names for x in (0,0x80000000,0xffffffff) for o in (0,1)]
matrix += [{'kind':'direct-repeat','name':n,'input':0xffffffff,'order':1,'expected_dispatches':1} for n in names]
matrix += [{'kind':'host-repeat','name':'host_twice','order':o,'expected_dispatches':2} for o in (0,1)]
assert sum(c['expected_dispatches'] for c in matrix)==51
(out/'MATRIX.json').write_text(json.dumps({'cases':matrix,'planned_dispatches':51,'max_dispatches':64,'wall_limit_seconds':300,'preflight_errors_per_module':['invalid root','invalid order','stale DONE input'],'reuse_scope':'fresh allocations on repeated calls; no physical buffer reuse hardware claim','subgroup_scope':'lanes0/1 may share subgroup'},indent=2)+'\n')
configs={};baselines={};summary={'status':'preparing','gpu_dispatches':0,'cases':[]}
def save(): (out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
def run(cmd,d,tag,env=None,timeout=20):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,env=env,timeout=timeout);(d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr);(d/(tag+'.json')).write_text(json.dumps({'command':list(map(str,cmd)),'exit_code':p.returncode,'timeout_seconds':timeout},indent=2)+'\n');return p
try:
 for name in names:
  d=out/name;d.mkdir();g=d/'generated';g.mkdir();old=r/'evidence/fork-parent-binding-regression'/name/'generated'
  for file in ['program.c','default.c','program.comp','program.spv','plan.json','caller-identity.json']:shutil.copy2(old/file,g/file)
  configs[name]=prepare(g,admitted=True)
  for kind in ['default','program']:
   p=run(['clang','-std=c11','-O2',g/f'{kind}.c','-lpthread','-lm','-o',d/kind],d,'build-'+kind);assert p.returncode==0,p.stderr
  p=run([d/'default','--gpu','off','--threads','1'],d,'CPU-reference',{k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')},5);assert p.returncode==0,p.stderr;baselines[name]=(p.stdout,p.stderr,p.returncode)
 # Public inventory/read-only query; no dispatch. Bind current exact selected render identity.
 first=out/'scalar/generated/worker';p=run([first,'--probe-inventory'],out,'inventory',timeout=3);assert p.returncode==0,p.stderr
 dev=identity(Path('/dev/dri/renderD128'),p.stdout.decode());summary['device']=dev
 # Native rejection coverage under each exact fresh module, before device creation.
 import struct
 summary['preflight_errors']=[]
 for name in names:
  d=out/name;g=d/'generated';fid=configs[name]['roots'][0]
  for error in ['invalid-root','invalid-order','stale-done']:
   words=[0]*24;words[0]=65535 if error=='invalid-root' else fid;words[11]=2 if error=='invalid-order' else 0;words[4]=2 if error=='stale-done' else 0
   inp=d/(error+'-input.bin');inp.write_bytes(struct.pack('<24I',*words));result=d/(error+'-must-not-exist.bin')
   args=[g/'worker',g/'program.spv',inp,result,24,1,*[dev[k] for k in ('index','major','minor','vendor','product','sysfs')],os.getpid()]
   p=run(args,d,error,timeout=3);assert p.returncode!=0 and not result.exists()
   summary['preflight_errors'].append({'name':name,'case':error,'rejected_before_device_creation':True})
 # Start the finite window after CPU builds, before any correctness call/dispatch.
 started=time.monotonic();budget=out/'budget.json';budget.write_text(json.dumps({'deadline_monotonic':started+300,'reserved_calls':0,'max_calls':64}))
 for name,config in configs.items():
  config.update(device=dev,budget_file=str(budget),receipt_directory=str(receipts));(out/name/'generated/transport.json').write_text(json.dumps(config,indent=2)+'\n')
 summary.update(status='running',started_monotonic=started,planned_dispatches=51);save()
 for i,case in enumerate(matrix):
  assert time.monotonic()-started<300,'wall gate deadline';name=case['name'];d=out/name;g=d/'generated';tag=f'gate-{i:02d}';before=set(receipts.iterdir());env={**os.environ,'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_VULKAN_CONFIG':str(g/'transport.json'),'BEND_FORK_ORDER':str(case['order'])};env.pop('BEND_FORK_TRACE',None)
  if case['kind'].startswith('host'):
   p=run([d/'program','--gpu','on','--threads','1'],d,tag,env,12)
   assert (p.stdout,p.stderr,p.returncode)==baselines[name],(case,p.stdout,p.stderr,p.returncode,baselines[name])
  else:
   caller=json.loads((g/'caller-identity.json').read_text());fid=configs[name]['roots'][0]
   args=['/usr/bin/python3',r/'fork/runtime/controller.py',g/'transport.json',fid,case['input'],*[caller[k] for k in ('schema','plan_schema','plan_sha256','shader_source_sha256','shader_sha256')],os.getpid()]
   p=run(args,d,tag,env,5);assert p.returncode==0 and len(p.stdout)==4 and p.stderr==b'',(case,p.stderr)
  fresh=sorted(set(receipts.iterdir())-before);assert len(fresh)==case['expected_dispatches'],(case,len(fresh))
  for receipt_dir in fresh:
   receipt=json.loads((receipt_dir/'receipt.json').read_text());assert receipt['status']=='passed' and receipt['native_exit_code']==0
   assert receipt['caller']==json.loads((g/'caller-identity.json').read_text())
   raw=(receipt_dir/'native.stdout').read_bytes();assert all(s in raw for s in [b'words=24\n',b'groups=1\n',b'workgroup=128\n',b'canaries_intact=1\n',b'vulkan_memory_model=enabled\n',b'vulkan_memory_model_device_scope=enabled\n'])
   assert receipt['device']==dev and receipt['worker_sha256']==configs[name]['worker_sha256'];summary['gpu_dispatches']+=1
  summary['cases'].append({**case,'status':'passed','receipt_directories':[str(p.relative_to(out)) for p in fresh]});save();print(i,name,case['kind'],'passed',summary['gpu_dispatches'],'dispatches',flush=True)
 summary.update(status='passed',wall_seconds=time.monotonic()-started,coverage='51 finite fresh-module one-workgroup dispatches; no throughput/full compatibility/concurrent cross-subgroup claim');save()
except Exception as error:
 summary.update(status='stopped',error=str(error));save();print('STOP:',str(error),file=sys.stderr);sys.exit(2)

finally:
 # Immediately revoke all gate configs and shared budget, including partial failures.
 for name in configs:
  file=out/name/'generated/transport.json'
  if file.exists():
   value=json.loads(file.read_text());value['admitted']=False;value['gate_revoked']=True;file.write_text(json.dumps(value,indent=2)+'\n')
 if (out/'budget.json').exists():
  value=json.loads((out/'budget.json').read_text());value['deadline_monotonic']=0;value['max_calls']=value['reserved_calls'];(out/'budget.json').write_text(json.dumps(value))
 summary['GPU_window_released']=True;save();print('GPU WINDOW RELEASED',flush=True)
