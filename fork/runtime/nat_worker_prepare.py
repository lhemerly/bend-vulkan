"""Exact 772-word native worker/controller preparation, admission compiled off.

Never accepts merely spirv-val-valid arbitrary bytes: reproduces approved GLSL
from the checked plan and recompiles it with the exact flags before embedding.
"""
from pathlib import Path
import hashlib,json,subprocess,sys
from nat_oracle import validate,LIMITS
from nat_arena import CANARIES
ROOT=Path(__file__).resolve().parents[2]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def once(s,a,b):
    if s.count(a)!=1:raise RuntimeError('native source anchor mismatch: '+a[:70])
    return s.replace(a,b)

def prepare(directory):
    d=Path(directory).resolve();g=d/'generated' if (d/'generated').exists() else d
    ident=json.loads((g/'source-identity.json').read_text());plan=json.loads((g/'nat-plan.json').read_text());validate(plan)
    if ident.get('schema')!='bend-nat-source-preparation-v1' or ident.get('admitted') is not False:raise ValueError('checked non-admitted source required')
    for key,file in {'nat_plan':'nat-plan.json','routing_plan':'routing-plan.json','shader':'nat.comp','routing_program':'routing.c','default_program':'default.c'}.items():
        if digest(g/file)!=ident[key+'_sha256']:raise ValueError('source identity mismatch '+key)
    if digest(ROOT/'fork/compiler/capture.ts')!=ident['compiler_sha256']:raise ValueError('capture changed after source checking')
    w=d/'nat-worker';w.mkdir(exist_ok=False)
    reproduced=subprocess.run(['bun',str(ROOT/'fork/compiler/nat_regenerate.ts'),str(g/'nat-plan.json')],capture_output=True,timeout=10)
    (w/'regenerate.stderr').write_bytes(reproduced.stderr)
    if reproduced.returncode or reproduced.stdout!=(g/'nat.comp').read_bytes():raise ValueError('approved GLSL does not reproduce from checked plan')
    approved=w/'approved.comp';approved.write_bytes(reproduced.stdout)
    glslang=Path('/usr/bin/glslangValidator').resolve(strict=True)
    argv=[str(glslang),'-V','--target-env','vulkan1.2',str(approved),'-o',str(w/'regenerated.spv')]
    p=subprocess.run(argv,capture_output=True,timeout=10);(w/'glsl.stdout').write_bytes(p.stdout);(w/'glsl.stderr').write_bytes(p.stderr)
    if p.returncode:raise ValueError('GLSL compilation failed')
    spv=d/'nat.spv'
    if spv.read_bytes()!=(w/'regenerated.spv').read_bytes():raise ValueError('SPIR-V not generated from approved GLSL')
    p=subprocess.run(['spirv-val','--target-env','vulkan1.2',str(spv)],capture_output=True,timeout=10)
    (w/'spirv.stderr').write_bytes(p.stderr)
    if p.returncode:raise ValueError('SPIR-V invalid')
    generation={'schema':'bend-nat-approved-glsl-generation-v1','approved_GLSL_sha256':digest(g/'nat.comp'),'SPIRV_sha256':digest(spv),'plan_sha256':digest(g/'nat-plan.json'),'compiler_argv':argv,'glslang_binary_sha256':digest(glslang)}
    (w/'generation.json').write_text(json.dumps(generation,indent=2)+'\n')
    raw=spv.read_bytes();(w/'nat_spv.h').write_text('static const unsigned char generated_spv[]={'+','.join(map(str,raw))+'};\nstatic const uint32_t nat_canaries[]={'+','.join(str(v)+'u' for v in CANARIES)+'};\n')
    s=(ROOT/'native/runner.c').read_text()
    s=once(s,'#include "pair_spv.h"','#include "nat_spv.h"')
    s=once(s,'int main(int argc,char**argv){','''static int worker_bind_parent(pid_t expected){return expected<=0||getppid()!=expected||prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=expected;}
int main(int argc,char**argv){
 if(argc==3&&!strcmp(argv[1],"--parent-selftest"))return worker_bind_parent((pid_t)number(argv[2]))?2:0;
''')
    # Inventory must not create an instance in this non-admitted build.
    s=once(s,'if(argc==2&&!strcmp(argv[1],"--probe-inventory"))return probe_inventory();','if(argc==2&&!strcmp(argv[1],"--probe-inventory")){fprintf(stderr,"Nat admission disabled\\n");return 2;}')
    # Keep inventory function referenced without permitting its invocation.
    s=once(s,'int main(int argc,char**argv){','int main(int argc,char**argv){\n (void)probe_inventory;')
    s=once(s,'if(argc!=12){','if(argc!=13){')
    s=once(s,'CANONICAL_PCI_PATH\\n','CANONICAL_PCI_PATH EXPECTED_PARENT_PID\\n')
    s=once(s,' pid_t parent=getppid();\n if(prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=parent||parent==1)',' pid_t parent=(pid_t)number(argv[12]);\n if(worker_bind_parent(parent))')
    s=once(s,' /* sandbox pid namespace must not be trusted */\n host_init_guard();',' /* Static checks and compiled admission precede every Vulkan operation. */')
    a=s.index(' if((local_x!=1u&&local_x!=64u&&local_x!=128u)');b=s.index(' /* input: exactly WORDS*4 bytes',a)
    s=s[:a]+''' if(words!=772u||groups!=1u||local_x!=128u||local_y!=1u||local_z!=1u){fprintf(stderr,"Nat exact772-word/one128-lane ABI mismatch\\n");return 2;}
 if(!needs_mm||!needs_ds||(size_t)length!=sizeof generated_spv||memcmp(code,generated_spv,sizeof generated_spv)){fprintf(stderr,"Nat immutable approved module mismatch\\n");return 2;}
'''+s[b:]
    pre=''' int valid_root=0;switch(initial[1]){ROOT_CASES default:break;}
 if(initial[0]!=1u||!valid_root||initial[2]>5u||initial[3]!=63u||initial[4]!=31u||initial[5]!=192u||initial[13]>1u){fprintf(stderr,"Nat input/root/policy mismatch\\n");return 2;}
 for(uint32_t i=6;i<13;i++)if(initial[i]){fprintf(stderr,"Nat initial controls not zero\\n");return 2;}
 for(uint32_t i=14;i<768;i++)if(initial[i]){fprintf(stderr,"Nat initial records not zero\\n");return 2;}
 for(uint32_t i=0;i<4;i++)if(initial[768+i]!=nat_canaries[i]){fprintf(stderr,"Nat initial canary mismatch\\n");return 2;}
 /* Immutable non-admitted build. No external flag/config can bypass this. */
 fprintf(stderr,"Nat GPU admission disabled pending separate final gate\\n");return 2;
 host_init_guard();
'''.replace('ROOT_CASES',''.join(f'case {r}u:valid_root=1;break;' for r in plan['roots']))
    s=once(s,' VkInstance instance=instance_create();\n uint32_t devices=0;',pre+' VkInstance instance=instance_create();\n uint32_t devices=0;')
    a=s.index(' if(local_x==128u){\n  VkPhysicalDeviceSubgroupProperties');b=s.index(' /* native guard pass one',a);s=s[:a]+s[b:]
    s=once(s,'VkDeviceSize size=(VkDeviceSize)(words+4u)*4u;','VkDeviceSize size=(VkDeviceSize)words*4u; /*772 includes the four guard words*/')
    s=once(s,'for(uint32_t i=0;i<4u;i++)words_view[words+i]=CANARY;','/* Tail guard words already validated in the exact772-word input. */')
    s=once(s,'words_view[words+i]!=CANARY','words_view[words-4u+i]!=nat_canaries[i]')
    (w/'worker.c').write_text(s)
    p=subprocess.run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',str(w/'worker.c'),'-lvulkan','-o',str(w/'worker')],capture_output=True,timeout=20)
    (w/'build.stdout').write_bytes(p.stdout);(w/'build.stderr').write_bytes(p.stderr)
    if p.returncode:raise ValueError('Nat worker compile failed')
    bindings=[{'path':str(ROOT/'fork/runtime'/f),'sha256':digest(ROOT/'fork/runtime'/f)} for f in ('nat_controller.py','nat_oracle.py','nat_arena.py')]
    bindings.append({'path':str(ROOT/'tools/run_examples.py'),'sha256':digest(ROOT/'tools/run_examples.py')})
    caller={'schema':'bend-nat-vulkan-transport-v1','plan_schema':plan['schema'],'plan_sha256':digest(g/'nat-plan.json'),'routing_plan_sha256':digest(g/'routing-plan.json'),'shader_source_sha256':digest(g/'nat.comp'),'shader_sha256':digest(spv),'generation_sha256':digest(w/'generation.json'),'worker_source_sha256':digest(w/'worker.c'),'worker_sha256':digest(w/'worker'),'runtime_bindings':bindings}
    config={'schema':caller['schema'],'admitted':False,'words':772,'groups':1,'local_size':[128,1,1],'roots':plan['roots'],'device':None,'budget_file':None,
      'caller':caller,'plan':str(g/'nat-plan.json'),'routing_plan':str(g/'routing-plan.json'),'shader_source':str(g/'nat.comp'),'shader':str(spv),'generation':str(w/'generation.json'),'worker_source':str(w/'worker.c'),'worker':str(w/'worker'),'receipt_directory':str(d/'nat-receipts')}
    (d/'nat-caller.json').write_text(json.dumps(caller,indent=2)+'\n');(d/'nat-transport.json').write_text(json.dumps(config,indent=2)+'\n')
    return config
if __name__=='__main__':print(json.dumps(prepare(sys.argv[1]),indent=2))
