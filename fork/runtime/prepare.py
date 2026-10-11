"""Prepare exact-module private workers. Hardware admission is compiled OFF.
Preserves the original host/device guards; never modifies the old frozen worker.
"""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def replace_once(source,old,new):
 if source.count(old)!=1:raise RuntimeError('native source version mismatch')
 return source.replace(old,new)
def prepare(directory, *, admitted=False):
 d=Path(directory).resolve();spv=d/'program.spv';plan=json.loads((d/'plan.json').read_text())
 subprocess.run(['spirv-val','--target-env','vulkan1.2',str(spv)],check=True,timeout=10)
 raw=spv.read_bytes();(d/'generated_spv.h').write_text('static const unsigned char generated_spv[] = {'+','.join(map(str,raw))+'};\n')
 source=(ROOT/'native/runner.c').read_text()
 source=replace_once(source,'#include "pair_spv.h"','#include "generated_spv.h"')
 source=replace_once(source,'int main(int argc,char**argv){','''static int worker_bind_parent(pid_t expected_parent){
 return expected_parent<=0||getppid()!=expected_parent||prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=expected_parent;
}
int main(int argc,char**argv){
 if(argc==3&&!strcmp(argv[1],"--parent-selftest"))return worker_bind_parent((pid_t)number(argv[2]))?2:0;
''')
 source=replace_once(source,'if(argc!=12){','if(argc!=13){')
 source=replace_once(source,'PRODUCT CANONICAL_PCI_PATH\\n','PRODUCT CANONICAL_PCI_PATH EXPECTED_PARENT_PID\\n')
 source=replace_once(source,' pid_t parent=getppid();\n if(prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=parent||parent==1)',
   ' pid_t parent=(pid_t)number(argv[12]);\n if(worker_bind_parent(parent))')
 source=replace_once(source,' /* sandbox pid namespace must not be trusted */\n host_init_guard();',' /* Host namespace guard runs after static module/input checks, before instance creation. */')
 start=source.index(' if((local_x!=1u&&local_x!=64u&&local_x!=128u)')
 end=source.index(' /* input: exactly WORDS*4 bytes',start)
 source=source[:start]+''' if(words!=24u||groups!=1u||local_x!=128u||local_y!=1u||local_z!=1u){fprintf(stderr,"fork ABI requires exactly24 words and one128-thread workgroup\\n");return 2;}
 if(!needs_mm||!needs_ds||(size_t)length!=sizeof generated_spv||memcmp(code,generated_spv,sizeof generated_spv)){fprintf(stderr,"fork module identity/memory-model mismatch\\n");return 2;}
'''+source[end:]
 roots=','.join(str(x)+'u' for x in plan['roots']) or 'UINT32_MAX'
 admission=f''' static const uint32_t roots[]={{ {roots} }};
 int valid_root=0;for(size_t i=0;i<sizeof roots/sizeof *roots;i++)if(initial[0]==roots[i])valid_root=1;
 if(!valid_root||initial[11]>1u){{fprintf(stderr,"invalid root/order\\n");return 2;}}
 for(uint32_t i=2;i<24u;i++)if(i!=11u&&initial[i]!=0u){{fprintf(stderr,"control/output input must be zero-initialized\\n");return 2;}}
 /* Fresh prepared build is non-admitted. Enable only after module/host review and parent scheduling. */
 fprintf(stderr,"fork GPU admission disabled pending review and scheduling\\n");return 2;
 host_init_guard();
'''
 if admitted:
  admission=replace_once(admission,' fprintf(stderr,"fork GPU admission disabled pending review and scheduling\\n");return 2;\n',' /* Explicitly admitted finite correctness gate; guards remain unchanged. */\n')
 source=replace_once(source,' VkInstance instance=instance_create();\n uint32_t devices=0;',admission+' VkInstance instance=instance_create();\n uint32_t devices=0;')
 # No subgroup operations are used: lanes0/1 may share a subgroup.
 start=source.index(' if(local_x==128u){\n  VkPhysicalDeviceSubgroupProperties')
 end=source.index(' /* native guard pass one',start)
 source=source[:start]+source[end:]
 (d/'worker.c').write_text(source)
 subprocess.run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',str(d/'worker.c'),'-lvulkan','-o',str(d/'worker')],check=True,timeout=20)
 p=subprocess.run([str(d/'worker'),'--guard-selftest'],capture_output=True,check=True,timeout=3)
 (d/'worker-guard-selftest.stdout').write_bytes(p.stdout);(d/'worker-guard-selftest.stderr').write_bytes(p.stderr)
 config={'schema':'bend-fork-vulkan-transport-v1','admitted':admitted,'words':24,'groups':1,'local_size':[128,1,1],'roots':plan['roots'],'shader':str(spv),'shader_sha256':digest(spv),'worker':str(d/'worker'),'worker_sha256':digest(d/'worker'),'native_original_sha256':digest(ROOT/'native/runner.c'),'worker_source_sha256':digest(d/'worker.c'),'device':None}
 config.update(plan=str(d/'plan.json'),plan_schema=plan['schema'],plan_sha256=digest(d/'plan.json'),
   shader_source=str(d/'program.comp'),shader_source_sha256=digest(d/'program.comp'))
 caller=json.loads((d/'caller-identity.json').read_text())
 for key in ('schema','plan_schema','plan_sha256','shader_source_sha256','shader_sha256'):
  if config[key]!=caller[key]:raise RuntimeError('prepared artifacts no longer match calling program')
 (d/'transport.json').write_text(json.dumps(config,indent=2)+'\n');return config
if __name__=='__main__':print(json.dumps(prepare(sys.argv[1]),indent=2))
