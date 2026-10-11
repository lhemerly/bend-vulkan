"""Bounded corrected Nat CPU validation. No GPU or host GPU bridge.

Translate actual generated GLSL statements mechanically to sequential C++.
Memory-ordering builtins become sequential operations, so this checks record
semantics/UBSan/full buffers, not concurrent Vulkan visibility.
"""
from pathlib import Path
import hashlib,json,os,re,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'fork/runtime'))
from nat_oracle import evaluate
from nat_arena import simulate,CANARIES,ROOT as SENTINEL,TASK_BASE,JOIN_BASE

HEADER=r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
using uint=uint32_t;
uint w[772],gl_LocalInvocationIndex;
unsigned mode;bool injected;
uint bitCount(uint v){return __builtin_popcount(v);}
#define gl_ScopeDevice 0
#define gl_ScopeWorkgroup 0
#define gl_StorageSemanticsBuffer 0
#define gl_SemanticsAcquire 0
#define gl_SemanticsRelease 0
#define gl_SemanticsAcquireRelease 0
#define atomicLoad(x,...) (x)
#define atomicStore(x,y,...) ((x)=(y))
#define controlBarrier(...) ((void)0)
void inject(){
 if(injected||mode==0)return;
 if(mode==6){w[6]=64;injected=true;return;}
 if(mode==7){w[7]=32;injected=true;return;}
 if(mode==8)for(uint i=1;i<w[6];i++){uint at=16+i*8;if(w[at+5]==1){w[at]=65535;w[at+2]=0xffffffff;w[at+3]=0;injected=true;return;}}
 if(mode<=2&&w[7]&&w[523]==1){w[mode==1?520:522]=mode==1?65535:1;injected=true;return;}
 if(mode==3)for(uint i=1;i<w[6];i++){uint at=16+i*8;if(w[at+5]==3){w[at+2]=0xffffffff;w[at+3]=0;injected=true;return;}}
 if(mode==4||mode==5)for(uint i=1;i<w[7];i++){uint at=520+i*8;
  if(mode==4?w[at+3]==1:w[at+6]==11){w[at+1]=0xffffffff;w[at+2]=0;injected=true;return;}}
}
'''
DRIVER=r'''
int main(){uint fid,arg,order,tc,jc,sc,probe;
 while(std::scanf("%u %u %u %u %u %u %u",&fid,&arg,&order,&tc,&jc,&sc,&probe)==7){
  // Re-poison storage before every logical reset, including repeated cases.
  for(uint i=0;i<772;i++)w[i]=0xdeadbeef;
  for(uint i=0;i<768;i++)w[i]=0;
  w[768]=0xa17ecafe;w[769]=0x5a5aa5a5;w[770]=0xdeadbeef;w[771]=0xc001d00d;
  w[0]=1;w[1]=fid;w[2]=arg;w[3]=tc;w[4]=jc;w[5]=sc;w[13]=order;
  mode=probe;injected=false;
  gl_LocalInvocationIndex=0;shader_main();
  gl_LocalInvocationIndex=1;shader_main();
  if(std::fwrite(w,4,772,stdout)!=772)return 2;
 }
 return 0;
}
'''


def fault(mode):
    injected=False
    def apply(w):
        nonlocal injected
        if injected or not mode:return
        if mode in (6,7):
            w[6 if mode==6 else 7]=64 if mode==6 else 32;injected=True;return
        if mode==8:
            for i in range(1,w[6]):
                at=TASK_BASE+i*8
                if w[at+5]==1:
                    w[at]=65535;w[at+2]=SENTINEL;w[at+3]=0;injected=True;return
        if mode<=2 and w[7] and w[JOIN_BASE+3]==1:
            w[JOIN_BASE if mode==1 else JOIN_BASE+2]=65535 if mode==1 else 1;injected=True;return
        if mode==3:
            for i in range(1,w[6]):
                at=TASK_BASE+i*8
                if w[at+5]==3:
                    w[at+2]=SENTINEL;w[at+3]=0;injected=True;return
        if mode in (4,5):
            for i in range(1,w[7]):
                at=JOIN_BASE+i*8
                if (w[at+3]==1 if mode==4 else w[at+6]==11):
                    w[at+1]=SENTINEL;w[at+2]=0;injected=True;return
    return apply


def main(destination):
    out=ROOT/'evidence'/destination;out.mkdir(exist_ok=False)
    env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
    report={'scope':'actual GLSL sequential translation/full772-word oracle, UBSan, SPIR-V validation and independent CPU/default source provenance; no GPU/memory-ordering proof','GPU_dispatches':0,'cases':[]}
    def run(argv,d,tag,data=None):
        argv=list(map(str,argv));p=subprocess.run(argv,input=data,capture_output=True,timeout=30,env=env)
        (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
        (d/(tag+'.json')).write_text(json.dumps({'argv':argv,'exit':p.returncode,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()},indent=2)+'\n')
        return p
    original=ROOT.parent/'bend-vulkan-feasibility/source/tests/run/gpu_mark.bend'
    text=original.read_text()
    fixtures={
      'gpu_mark':original,
      'identity_forwarding':ROOT/'fork/tests/nat_origin/identity_forwarding.bend',
      'recursive_source':ROOT/'fork/tests/nat_origin/recursive_source.bend',
      'sparse_root_FID':ROOT/'evidence/fork-cpu-routing-lifecycle-v2/sparse_root_FID/sparse_root_FID.bend',
    }
    variants={'renamed_base7':text.replace('gmark','reordered_probe').replace('      3\n','      7\n'),
      'recursive_sub':text.replace('gmark','subtract_probe').replace('U32.add(a, b)','U32.sub(a, b)'),
      'recursive_mul':text.replace('gmark','multiply_probe').replace('U32.add(a, b)','U32.mul(a, b)')}
    for name,source in variants.items():
        p=out/(name+'.bend');p.write_text(source);fixtures[name]=p
    distinct='''import Base
def left(d: Nat) -> U32:
  match d:
    case 0n:
      23
    case 1n+p:
      19
def right(d: Nat) -> U32:
  match d:
    case 0n:
      7
    case 1n+p:
      5
def combine(+d: Nat) -> U32:
  match d:
    case 0n:
      31
    case 1n+p:
      a b = left(p) right(p)
      U32.sub(a,b)
def main() -> U32:
  combine!(2n)
'''
    p=out/'distinct_sub.bend';p.write_text(distinct);fixtures['distinct_sub']=p
    capacities=[(63,31,192),(62,31,192),(63,30,192),(63,31,124),(63,31,125),(1,0,192),(63,31,0)]
    if len(sys.argv)>2:fixtures={name:src for name,src in fixtures.items() if name==sys.argv[2]}
    for name,src in fixtures.items():
        d=out/name;d.mkdir();generated=d/'generated'
        p=run(['bun',ROOT/'fork/nat_source_cli.ts',src,generated],d,'emit');assert p.returncode==0,(name,p.stderr)
        plan=json.loads((generated/'nat-plan.json').read_text())
        for tag,argv in [('glsl',['glslangValidator','-V','--target-env','vulkan1.2','-o',d/'nat.spv',generated/'nat.comp']),('spirv',['spirv-val','--target-env','vulkan1.2',d/'nat.spv'])]:
            p=run(argv,d,tag);assert p.returncode==0,(name,tag,p.stderr,p.stdout)
        source=(generated/'nat.comp').read_text()
        translated='\n'.join(line for line in source.splitlines() if not line.startswith(('#','layout(')))
        translated=re.sub(r'\b(?:inout|out) (uint|bool) ([A-Za-z0-9_]+)',r'\1& \2',translated)
        translated=translated.replace('void main()','void shader_main()')
        anchor='if(error!=0u||terminal)break;';assert translated.count(anchor)==1
        translated=translated.replace(anchor,anchor+'inject();')
        (d/'shader.cpp').write_text(HEADER+translated+DRIVER)
        p=run(['clang++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',d/'shader.cpp','-o',d/'shader-cpu'],d,'translate-build');assert p.returncode==0,(name,p.stderr)
        cases=[]
        for root in plan['roots']:
            for depth in range(6):
                for order in (0,1):
                    for tc,jc,sc in capacities:
                        cases.extend([(root,depth,order,tc,jc,sc,0)]*2)
            for order in (0,1):
                for probe in range(1,9):cases.append((root,2,order,63,31,192,probe))
        data=''.join(' '.join(map(str,c))+'\n' for c in cases).encode()
        p=run([d/'shader-cpu'],d,'complete-buffers',data);assert p.returncode==0,(name,p.stderr)
        assert len(p.stdout)==len(cases)*772*4,(name,len(p.stdout))
        fault_errors={}
        for i,(root,depth,order,tc,jc,sc,probe) in enumerate(cases):
            want=simulate(plan,root,depth,order,task_cap=tc,join_cap=jc,step_cap=sc,fault=fault(probe))
            got=list(struct.unpack('<772I',p.stdout[i*3088:(i+1)*3088]))
            if got!=want:
                (d/'FAILURE.json').write_text(json.dumps({'case':cases[i],'differences':[(k,a,b) for k,(a,b) in enumerate(zip(got,want)) if a!=b],'actual':got,'expected':want},indent=2)+'\n')
                raise AssertionError((name,i,'full buffer mismatch'))
            if not want[10]:assert want[9]==evaluate(plan,root,depth),(name,i)
            assert tuple(got[-4:])==CANARIES
            if probe:fault_errors[str(probe)]=fault_errors.get(str(probe),[])+[got[10]]
        (d/'cases.json').write_text(json.dumps(cases)+'\n')
        # Independent pinned compiler versus current default output, native
        # both thread modes. This executes CPU only, not the generated shader.
        p=run(['bun',ROOT/'tools/compile_example.ts',src,d/'upstream.c'],d,'upstream-emit');assert p.returncode==0,(name,p.stderr)
        assert (generated/'default.c').read_bytes()==(d/'upstream.c').read_bytes(),name
        for compiler,c in [('upstream',d/'upstream.c'),('default',generated/'default.c')]:
            p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',c,'-lpthread','-lm','-o',d/compiler],d,'build-'+compiler);assert p.returncode==0,(name,p.stderr)
        native=[]
        for threads in (1,2):
            base=run([d/'upstream','--gpu','off','--threads',threads],d,f'upstream-t{threads}')
            candidate=run([d/'default','--gpu','off','--threads',threads],d,f'default-t{threads}')
            assert (base.returncode,base.stdout,base.stderr)==(candidate.returncode,candidate.stdout,candidate.stderr),(name,threads)
            assert base.returncode==0,(name,base.stderr)
            native.append({'threads':threads,'stdout':base.stdout.decode(),'exit':base.returncode})
        report['cases'].append({'source':name,'shader_sha256':hashlib.sha256(source.encode()).hexdigest(),'full_buffers':len(cases),'fault_errors':fault_errors,'SPIRV_valid':True,'UBSan':True,'default_C_equal_upstream':True,'native':native,'roots':plan['roots']})
        (out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name,len(cases),'complete buffers / SPIR-V / native PASS',flush=True)


if __name__=='__main__':main(sys.argv[1])
