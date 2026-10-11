"""Pending host join must not silently bypass the explicitly selected transport."""
from pathlib import Path
import subprocess, os, json, hashlib, sys
r=Path(__file__).resolve().parents[2]
d=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-host-parallel-gate');d.mkdir(exist_ok=False)
def run(cmd,tag,env=None):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,env=env,timeout=20)
 (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
 (d/(tag+'.json')).write_text(json.dumps({'command':list(map(str,cmd)),'exit_code':p.returncode,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()},indent=2)+'\n')
 return p
p=run(['bun',r/'fork/cli.ts',r/'fork/tests/host_parallel.bend',d/'generated'],'emit');assert p.returncode==0,p.stderr
for name in ['default','program']:
 p=run(['clang','-std=c11','-O2',d/'generated'/f'{name}.c','-lpthread','-lm','-o',d/name],'build-'+name);assert p.returncode==0,p.stderr
clean={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
base=run([d/'default','--gpu','off','--threads','1'],'default',clean)
plain=run([d/'program','--gpu','off','--threads','1'],'transport-off',clean)
assert (base.returncode,base.stdout,base.stderr)==(plain.returncode,plain.stdout,plain.stderr)==(0,b'17\n',b'')
for transport in ['cpu-reference','vulkan']:
 p=run([d/'program','--gpu',('on' if transport=='vulkan' else 'off'),'--threads','1'],transport,{**clean,'BEND_FORK_TRANSPORT':transport,'BEND_FORK_TRACE':'1'})
 assert p.returncode!=0 and p.stdout==b'' and b'pending host parallel joins; CPU fallback refused' in p.stderr and b'fork cpu-reference root=' not in p.stderr
(d/'RESULT.json').write_text(json.dumps({'default_CPU_raw_bytes_unchanged':True,'selected_cpu_reference':'explicitly rejected before CPU scheduler','selected_vulkan':'explicitly rejected before CPU scheduler','bridge_calls':0,'GPU_dispatches':0,'compatibility_status':'unsupported host-parallel path, not a pass'},indent=2)+'\n')
print('Default CPU exact bytes preserved; both selected transports reject pending join before scheduling, no fallback coverage claimed.')
