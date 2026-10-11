"""No-hardware native controller/worker failures and transport selection precedence."""
from pathlib import Path
import sys,os,subprocess,struct,json
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'fork/runtime'));from prepare import prepare
out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-transport-failures');out.mkdir(exist_ok=False);g=r/'evidence/fork-parent-binding-regression/host_twice/generated';config=prepare(g);plan=json.loads((g/'plan.json').read_text());fid=plan['roots'][0];rows=[]
def run(cmd,tag,env=None,timeout=8):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,env=env,timeout=timeout);(out/(tag+'.stdout')).write_bytes(p.stdout);(out/(tag+'.stderr')).write_bytes(p.stderr);rows.append({'case':tag,'command':list(map(str,cmd)),'exit_code':p.returncode});return p
# Exact binary input reaches static admission check but never instance creation.
initial=[0]*24;initial[0]=fid;initial[1]=2;initial[11]=0;inp=out/'input.bin';inp.write_bytes(struct.pack('<24I',*initial))
args=[g/'worker',g/'program.spv',inp,out/'must-not-exist.bin',24,1,0,226,128,4098,29695,'/sys/devices/unselected',os.getpid()]
p=run(args,'native-admission');assert p.returncode!=0 and b'admission disabled' in p.stderr and not(out/'must-not-exist.bin').exists()
mutated=bytearray((g/'program.spv').read_bytes());mutated[-4]^=1;bad=out/'changed.spv';bad.write_bytes(mutated);p=run([args[0],bad,*args[2:]],'module-mutant');assert p.returncode!=0 and b'identity' in p.stderr
initial[4]=2;inp.write_bytes(struct.pack('<24I',*initial));p=run(args,'stale-done-input');assert p.returncode!=0 and b'zero-initialized' in p.stderr
p=run([r/'evidence/fork-parent-binding-regression/host_twice/program','--gpu','on','--threads','1'],'real-controller-unadmitted',{**os.environ,'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_VULKAN_CONFIG':str(g/'transport.json')});assert p.returncode!=0 and p.stdout==b'' and b'awaits reviewed' in p.stderr and b'fallback refused' in p.stderr
p=run([r/'evidence/fork-parent-binding-regression/host_twice/program','--gpu','off','--threads','1'],'gpu-off-veto',{**os.environ,'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_VULKAN_CONFIG':'/path/must/not/be/read'});assert p.returncode!=0 and p.stdout==b'' and b'--gpu off vetoes' in p.stderr
p=run([r/'evidence/fork-parent-binding-regression/host_twice/program','--gpu','off'],'unknown-transport',{**os.environ,'BEND_FORK_TRANSPORT':'unknown'});assert p.returncode!=0 and b'unknown transport' in p.stderr
# Isolated native transport framing harness, explicit fake controller used only here.
shim=out/'fake-controller.py';shim.write_text('import os,sys,time\nmode=sys.argv[1]\nif mode=="timeout":time.sleep(10)\nif mode=="nonzero":sys.exit(2)\nif mode=="short":sys.stdout.buffer.write(b"x")\nif mode=="extra":sys.stdout.buffer.write(b"12345")\nif mode=="valid":sys.stdout.buffer.write(bytes([47,0,0,0]))\n')
binding=''.join('#define '+name+' "test"\n' for name in ['FORK_CALLER_SCHEMA','FORK_PLAN_SCHEMA','FORK_PLAN_SHA256','FORK_SHADER_SOURCE_SHA256','FORK_SHADER_SHA256'])
header=binding+'#define _POSIX_C_SOURCE 200809L\n#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <unistd.h>\n#include <string.h>\n#include <time.h>\nstatic void err_fail(const char*s){fprintf(stderr,"%s\\n",s);exit(2);}\n#define FORK_CONTROLLER '+json.dumps(str(shim))+'\n'
cpp=out/'framing.c';cpp.write_text(header+(r/'fork/runtime/transport.c').read_text()+'\nint main(void){printf("%u\\n",fork_vulkan(1,2));}\n');p=run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',cpp,'-o',out/'framing'],'framing-build');assert p.returncode==0,p.stderr
for mode in ['valid','short','extra','nonzero','timeout']:
 p=run([out/'framing'],'framing-'+mode,{**os.environ,'BEND_FORK_VULKAN_CONFIG':mode})
 if mode=='valid':assert p.returncode==0 and p.stdout==b'47\n'
 else:assert p.returncode!=0 and p.stdout==b'' and b'fallback refused' in p.stderr
(out/'RESULT.json').write_text(json.dumps({'scope':'CPU/static failure paths only; framing uses explicit test fake, no device dispatch','cases':rows,'GPU_dispatches':0,'prepared_worker_admitted':False},indent=2)+'\n');print('Module/input/admission rejection, off-veto, controller errors/framing/timeout pass. No GPU.')
