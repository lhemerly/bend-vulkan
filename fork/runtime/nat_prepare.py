"""Native preflight preparation only. Cannot enable or execute a Nat dispatch.

The immutable wrapper permits guard/parent selftests and verifies exact module,
root/input/ABI; every normal invocation then fails before any Vulkan call. It
keeps the original native guard source verbatim for review. A real Nat worker
and host transport require a separately reviewed implementation/admission.
"""
from pathlib import Path
import hashlib,json,subprocess,sys
from nat_oracle import validate,LIMITS
from nat_arena import CANARIES
ROOT=Path(__file__).resolve().parents[2]


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare(directory):
    d=Path(directory).resolve();generated=d/'generated'
    identity=json.loads((generated/'source-identity.json').read_text())
    if identity.get('schema')!='bend-nat-source-preparation-v1' or identity.get('admitted') is not False:
        raise ValueError('non-admitted source identity required')
    mapping={'nat_plan':generated/'nat-plan.json','routing_plan':generated/'routing-plan.json',
      'shader':generated/'nat.comp','routing_program':generated/'routing.c','default_program':generated/'default.c'}
    for key,file in mapping.items():
        if digest(file)!=identity[key+'_sha256']:raise ValueError('source artifact identity '+key)
    if identity['compiler_sha256']!=digest(ROOT/'fork/compiler/capture.ts'):
        raise ValueError('compiler changed since checked emission')
    plan=json.loads(mapping['nat_plan'].read_text());validate(plan)
    routing=json.loads(mapping['routing_plan'].read_text())
    if routing.get('schema')!='bend-fork-cpu-routing-v2' or not all(any(g['root_id']==r and g['argument']=='Nat' for g in routing['gateways']) for r in plan['roots']):
        raise ValueError('compiled gateway/root binding')
    spv=d/'nat.spv';p=subprocess.run(['spirv-val','--target-env','vulkan1.2',str(spv)],capture_output=True,timeout=10)
    (d/'prepare-spirv.stdout').write_bytes(p.stdout);(d/'prepare-spirv.stderr').write_bytes(p.stderr)
    if p.returncode:raise ValueError('SPIR-V validation failed')
    prepared=d/'native-preflight';prepared.mkdir(exist_ok=False)
    original=ROOT/'native/runner.c';(prepared/'native_original.c').write_bytes(original.read_bytes())
    (prepared/'pair_spv.h').write_bytes((ROOT/'native/pair_spv.h').read_bytes())
    raw=spv.read_bytes()
    (prepared/'nat_module.h').write_text('static const unsigned char nat_module[]={'+','.join(map(str,raw))+'};\n')
    source=r'''/* No admission switch or environment override exists here. */
#define main original_native_main
#include "native_original.c"
#undef main
#include "nat_module.h"
static int bind_parent(pid_t expected){
 return expected<=0||getppid()!=expected||prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=expected;
}
int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--guard-selftest"))return original_native_main(argc,argv);
 if(argc==3&&!strcmp(argv[1],"--parent-selftest"))return bind_parent((pid_t)number(argv[2]))?2:0;
 if(argc!=13){fprintf(stderr,"Nat preflight SHADER INPUT OUTPUT WORDS GROUPS DEVICE MAJOR MINOR VENDOR PRODUCT SYSFS EXPECTED_PARENT_PID\n");return 2;}
 if(bind_parent((pid_t)number(argv[12]))){fprintf(stderr,"original parent mismatch/adoption\n");return 2;}
 if(number(argv[4])!=772u||number(argv[5])!=1u){fprintf(stderr,"Nat buffer/workgroup ABI mismatch\n");return 2;}
 FILE*f=fopen(argv[1],"rb");if(!f)return 2;
 unsigned char module[sizeof nat_module];
 int bad=fread(module,1,sizeof module,f)!=sizeof module||fgetc(f)!=EOF||memcmp(module,nat_module,sizeof module);
 fclose(f);if(bad){fprintf(stderr,"Nat immutable module mismatch\n");return 2;}
 f=fopen(argv[2],"rb");if(!f)return 2;uint32_t input[772];
 bad=fread(input,4,772,f)!=772||fgetc(f)!=EOF;fclose(f);
 if(bad){fprintf(stderr,"Nat exact input framing\n");return 2;}
 int root=0;switch(input[1]){ROOT_CASES default:break;}
 if(input[0]!=1u||!root||input[2]>5u||input[3]!=63u||input[4]!=31u||input[5]!=192u||input[13]>1u){fprintf(stderr,"Nat root/input/policy mismatch\n");return 2;}
 for(unsigned i=6;i<13;i++)if(input[i])bad=1;
 for(unsigned i=14;i<768;i++)if(input[i])bad=1;
 static const uint32_t canaries[]={CANARIES};
 for(unsigned i=0;i<4;i++)if(input[768+i]!=canaries[i])bad=1;
 if(bad){fprintf(stderr,"Nat initial controls/canaries mismatch\n");return 2;}
 /* No call to original dispatch main, Vulkan instance, inventory, device,
  * allocation, queue or pipeline is reachable after successful preflight. */
 fprintf(stderr,"Nat GPU admission disabled; preflight only\n");return 2;
}
'''.replace('ROOT_CASES',''.join(f'case {r}u:root=1;break;' for r in plan['roots'])).replace('CANARIES',','.join(f'{v}u' for v in CANARIES))
    (prepared/'worker.c').write_text(source)
    p=subprocess.run(['cc','-std=c11','-O1','-Wall','-Wextra','-Werror',str(prepared/'worker.c'),'-lvulkan','-o',str(prepared/'worker')],capture_output=True,timeout=20)
    (prepared/'build.stdout').write_bytes(p.stdout);(prepared/'build.stderr').write_bytes(p.stderr)
    if p.returncode:raise ValueError('native preflight build failed')
    config={'schema':'bend-nat-native-preflight-v1','admitted':False,'input_bytes':3088,'output_bytes':3088,
      'words':772,'record_words':768,'canaries':list(CANARIES),'groups':1,'local_size':[128,1,1],
      'limits':LIMITS,'roots':plan['roots'],'gateways':routing['gateways'],'device':None,
      'caller_source_identity':identity,'shader_spirv_sha256':digest(spv),
      'native_original_sha256':digest(original),'worker_source_sha256':digest(prepared/'worker.c'),
      'native_original_header_sha256':digest(prepared/'pair_spv.h'),
      'worker_sha256':digest(prepared/'worker'),
      'host_gpu_bridge_implemented':False,'normal_invocation':'unconditional rejection after static preflight; no GPU operations'}
    (prepared/'preparation.json').write_text(json.dumps(config,indent=2)+'\n')
    return config


if __name__=='__main__':print(json.dumps(prepare(sys.argv[1]),indent=2))
