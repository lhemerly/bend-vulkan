"""Freeze separate admission-only binaries; never invoke a device entry."""
from pathlib import Path
import json,hashlib,shutil,subprocess,re,difflib
ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'evidence/nat-admission-candidate-v1';out.mkdir(exist_ok=False)
h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
rows=[]
for name in ['target','distinct_sub','sparse_root_FID','two_io_handoffs','root_order_a','root_order_b']:
 src=ROOT/('evidence/nat-missing-transports-v1/'+name if name in ['distinct_sub','sparse_root_FID'] else 'evidence/nat-host-contract-v2/'+name+'/generated')
 d=out/name;shutil.copytree(src,d,ignore=shutil.ignore_patterns('nat-receipts'))
 w=d/'nat-worker';before=(w/'worker.c').read_text()
 veto=' /* Immutable non-admitted build. No external flag/config can bypass this. */\n fprintf(stderr,"Nat GPU admission disabled pending separate final gate\\n");return 2;\n'
 assert before.count(veto)==1
 after=before.replace(veto,' /* Review candidate only: dispatch requires separately admitted controller/config/window. */\n')
 (w/'worker.c').write_text(after)
 (d/'worker-admission-only.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='disabled/worker.c',tofile='candidate/worker.c')))
 def run(tag,args,expect=0,env=None):
  p=subprocess.run(list(map(str,args)),capture_output=True,timeout=20,env=env)
  (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr);(d/(tag+'.json')).write_text(json.dumps({'argv':list(map(str,args)),'exit':p.returncode,'GPU_dispatches':0})+'\n');assert p.returncode==expect,(name,tag,p.stderr);return p
 run('worker-build',['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',w/'worker.c','-lvulkan','-o',w/'worker'])
 old=json.loads((d/'nat-caller.json').read_text());caller=dict(old)
 caller.update(worker_source_sha256=h(w/'worker.c'),worker_sha256=h(w/'worker'))
 # generation record contains the original exact build path; preserve its bytes,
 # and the associated module/glsl/plan identities, rather than inventing a rebuild.
 config=json.loads((d/'nat-transport.json').read_text());config.update(caller=caller,admitted=False,device=None,budget_file=None,receipt_directory=str(d/'nat-receipts'))
 for key in ['plan','routing_plan','shader_source','shader']:config[key]=str(d/Path(config[key]).name)
 for key,file in [('generation','generation.json'),('worker_source','worker.c'),('worker','worker')]:config[key]=str(w/file)
 for key in ['plan','routing_plan','shader_source','shader','generation','worker_source','worker']:assert h(config[key])==caller[key+'_sha256']
 (d/'nat-caller.json').write_text(json.dumps(caller,indent=2)+'\n');(d/'nat-transport.json').write_text(json.dumps(config,indent=2)+'\n')
 program=(d/'program.c').read_text();program,n=re.subn(r'^#define NAT_CALLER_JSON .*$',lambda m:'#define NAT_CALLER_JSON '+json.dumps(json.dumps(caller,separators=(',',':'))),program,flags=re.M);assert n==1
 (d/'program.c').write_text(program)
 binding=json.loads((d/'host-binding.json').read_text());binding.update(caller=caller,program_sha256=h(d/'program.c'),admitted=False);(d/'host-binding.json').write_text(json.dumps(binding,indent=2)+'\n')
 run('host-build',['clang','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',d/'program.c','-lm','-o',d/'host'])
 import os
 for threads in [1,2]:
  env=dict(os.environ,BEND_FORK_TRANSPORT='cpu-reference');p=run('cpu-reference-t'+str(threads),[d/'host','--gpu','off','--threads',str(threads)],env=env)
  # Compare to unchanged compiled default program with the identical source.
  run('default-build',['clang','-O1',d/'default.c','-lm','-o',d/'default-host']) if threads==1 else None
  baseline=run('default-t'+str(threads),[d/'default-host','--gpu','off','--threads',str(threads)])
  assert p.stdout==baseline.stdout
  if name=='target':assert p.stdout==b'1212\n'
 import sys
 sys.path.insert(0,str(ROOT/'fork/runtime'));from nat_controller import dispatch
 try:dispatch(config,config['roots'][0],2,0,caller)
 except RuntimeError as e:assert 'admission disabled' in str(e)
 else:raise AssertionError('config unexpectedly admitted')
 rows.append({'case':name,'source_identity':json.loads((d/'source-identity.json').read_text()),'original_caller':old,'final_caller':caller,'hashes':{f:h(d/f) for f in ['program.c','host','nat-caller.json','host-binding.json','nat-transport.json','worker-admission-only.patch']},'admitted':False,'CPU_reference_parity_threads':[1,2],'GPU_dispatches':0})
(out/'FINAL-MANIFEST.json').write_text(json.dumps({'schema':'bend-nat-six-fixture-admission-review-v1','admitted':False,'GPU_dispatches':0,'max_dispatches':36,'max_workload_seconds':660,'host_invocation_reserve_seconds':20,'host_invocation_dispatch_reservation':{'target':1,'two_io_handoffs':2,'root_order_a':2,'root_order_b':2},'reserve_includes':['all handoffs','device guard','772-word comparison','exit/EOF','kill/reap if needed','cleanup'],'stop_first_failure':True,'automatic_retry':False,'fixtures':rows},indent=2)+'\n')
print('Six candidate worker/host binaries frozen; exact admission-only worker diffs; CPU parity and disabled config PASS; GPU dispatches zero')
