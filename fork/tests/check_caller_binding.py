"""Actual native hosts with identical numeric FIDs must reject swapped program configs."""
from pathlib import Path
import sys,os,json,subprocess,hashlib
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'fork/runtime'));from prepare import prepare
out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-caller-binding-gate');out.mkdir(exist_ok=False);rows=[]
def run(cmd,d,tag,env=None):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,timeout=20,env=env)
 (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
 (d/(tag+'.json')).write_text(json.dumps({'command':list(map(str,cmd)),'exit_code':p.returncode,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()},indent=2)+'\n')
 return p
configs={}
for name,body,want in [('A','((x * 7 : U32) + 13 : U32)',307),('B','(x + 29 : U32)',71)]:
 d=out/name;d.mkdir();source=d/'input.bend'
 source.write_text(f'import Base\n\ndef calculate(x: U32) -> U32:\n  {body}\n\ndef main() -> U32:\n  calculate!(42)\n')
 p=run(['bun',r/'fork/cli.ts',source,d/'generated'],d,'emit');assert p.returncode==0,p.stderr
 plan=json.loads((d/'generated/plan.json').read_text());assert plan['roots']==[0]
 config=prepare(d/'generated');configs[name]=config
 p=run(['clang','-std=c11','-O2',d/'generated/program.c','-lpthread','-lm','-o',d/'program'],d,'build');assert p.returncode==0,p.stderr
 p=run([d/'program','--gpu','off','--threads','1'],d,'CPU-default',env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')});assert p.returncode==0 and p.stdout==f'{want}\n'.encode() and p.stderr==b''
# Config B is deliberately marked admitted and its worker path points to a trap.
# The identity mismatch must happen first; no trap/guard/device operation is allowed.
trap=out/'trap-worker';marker=out/'worker-was-invoked'
trap.write_text('#!/usr/bin/python3\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text("called")\n');trap.chmod(0o700)
for name,other in [('A','B'),('B','A')]:
 d=out/name;swapped=dict(configs[other]);swapped['admitted']=True;swapped['worker']=str(trap);swapped['worker_sha256']=hashlib.sha256(trap.read_bytes()).hexdigest();config=d/'wrong-program.json';config.write_text(json.dumps(swapped))
 p=run([d/'program','--gpu','on','--threads','1'],d,'wrong-program',{**os.environ,'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_VULKAN_CONFIG':str(config)})
 assert p.returncode!=0 and p.stdout==b'' and b'calling program/config identity mismatch' in p.stderr and b'fallback refused' in p.stderr and not marker.exists(),p.stderr
 # Matching config still fails the independent admission gate, not identity.
 p=run([d/'program','--gpu','on','--threads','1'],d,'matched-unadmitted',{**os.environ,'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_VULKAN_CONFIG':str(d/'generated/transport.json')})
 assert p.returncode!=0 and p.stdout==b'' and b'awaits reviewed' in p.stderr and b'identity mismatch' not in p.stderr
 rows.append({'caller':name,'wrong_config':other,'shared_root_FID':0,'different_computations':True,'wrong_config_rejected_before_worker':True,'matching_config_unadmitted':True,'GPU_dispatches':0})
(out/'RESULT.json').write_text(json.dumps({'scope':'actual native wrong-program config rejection, no GPU','cases':rows,'trap_worker_invoked':marker.exists()},indent=2)+'\n');print('A/B native hosts share FID0 but reject swapped admitted configs before worker/device; matching identity remains unadmitted.')
