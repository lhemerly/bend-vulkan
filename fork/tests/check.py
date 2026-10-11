"""Actual checked compiler -> native host continuation + static Vulkan preparation. No GPU."""
from pathlib import Path
import subprocess,json,os,hashlib,sys
root=Path(__file__).resolve().parents[2];out=root/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-first-gate');out.mkdir(exist_ok=False);rows=[]
def run(cmd,d,tag,env=None,timeout=20):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,timeout=timeout,env=env);(d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr);(d/(tag+'.json')).write_text(json.dumps({'command':list(map(str,cmd)),'exit_code':p.returncode,'timeout_seconds':timeout,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()},indent=2)+'\n');return p
for name in ['scalar','pair_distinct','renamed_reordered','host_irrelevant','host_twice']:
 d=out/name;d.mkdir();source=root/'fork/tests'/f'{name}.bend';generated=d/'generated';p=run(['bun',root/'fork/cli.ts',source,generated],d,'emit');assert p.returncode==0,p.stderr
 for typ in ['default','program']:
  p=run(['clang','-std=c11','-O2',generated/f'{typ}.c','-lpthread','-lm','-o',d/typ],d,'build-'+typ);assert p.returncode==0,p.stderr
 base=run([d/'default','--gpu','off','--threads','1'],d,'baseline',timeout=5)
 plain=run([d/'program','--gpu','off','--threads','1'],d,'transport-off',env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')},timeout=5)
 enabled=run([d/'program','--gpu','off','--threads','1'],d,'cpu-reference',env={**os.environ,'BEND_FORK_TRANSPORT':'cpu-reference'},timeout=5)
 assert (base.returncode,base.stdout,base.stderr)==(plain.returncode,plain.stdout,plain.stderr)==(enabled.returncode,enabled.stdout,enabled.stderr),(name,base.stdout,enabled.stdout,enabled.stderr)
 trace=run([d/'program','--gpu','off','--threads','1'],d,'trace',env={**os.environ,'BEND_FORK_TRANSPORT':'cpu-reference','BEND_FORK_TRACE':'1'},timeout=5)
 assert trace.returncode==0 and trace.stdout==base.stdout and trace.stderr.count(b'fork cpu-reference root=')==(2 if name=='host_twice' else 1),trace.stderr
 rejected=run([d/'program','--gpu','on','--threads','1'],d,'vulkan-unapproved',env={**os.environ,'BEND_FORK_TRANSPORT':'vulkan'},timeout=5);assert rejected.returncode!=0 and b'awaits reviewed' in rejected.stderr
 p=run(['glslangValidator','-V','--target-env','vulkan1.2',generated/'program.comp','-o',generated/'program.spv'],d,'shader-compile');assert p.returncode==0,p.stderr
 p=run(['spirv-val','--target-env','vulkan1.2',generated/'program.spv'],d,'shader-validate');assert p.returncode==0,p.stderr
 rows.append({'case':name,'stdout_stderr_exit_equal':True,'actual_host_bridge_calls':trace.stderr.count(b'fork cpu-reference root='),'spirv_valid':True,'vulkan_rejected_before_dispatch':True,'gpu_dispatches':0});print(name,'PASS',flush=True)
for name in ['unused_f32_root','unused_bool_root','nested_inner_first']:
 d=out/name;d.mkdir();p=run(['bun',root/'fork/cli.ts',root/'fork/tests'/f'{name}.bend',d/'must-not-exist'],d,'emit');assert p.returncode!=0 and b'Vulkan unsupported' in p.stderr and not(d/'must-not-exist').exists();rows.append({'case':name,'correctly_rejected':True,'gpu_dispatches':0})
(out/'RESULT.json').write_text(json.dumps({'scope':'experimental fork native host continuation through explicit CPU-reference transport; generated shaders validated, Vulkan transport intentionally not enabled','cases':rows,'gpu_dispatches':0},indent=2)+'\n')
