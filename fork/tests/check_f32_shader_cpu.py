"""Actual emitted GLSL translated mechanically to sequential CPU; never Vulkan."""
from pathlib import Path
import json,re,struct,subprocess,sys,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'fork/runtime'))
from f32_oracle import bits,evaluate
from f32_arena import simulate
case=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir()
source=(case/'f32.comp').read_text();plan=json.loads((case/'f32-plan.json').read_text());root=plan['roots'][0]
translated='\n'.join(l for l in source.splitlines() if not l.startswith(('#','layout(')))
translated=re.sub(r'\b(?:inout|out) (uint|bool) ([A-Za-z0-9_]+)',r'\1& \2',translated)
translated=translated.replace('precise float','float').replace('void main()','void shader_main()')
for op in ('sin','cos','tan'):translated=re.sub(r'\b'+op+r'\(',op+'f(',translated)
header=r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
using uint=uint32_t;uint w[772],gl_LocalInvocationIndex;
using std::isnan;using std::isinf;
uint bitCount(uint x){return __builtin_popcount(x);}
float uintBitsToFloat(uint x){float f;memcpy(&f,&x,4);return f;}
uint floatBitsToUint(float f){uint x;memcpy(&x,&f,4);return x;}
#define gl_ScopeDevice 0
#define gl_ScopeWorkgroup 0
#define gl_StorageSemanticsBuffer 0
#define gl_SemanticsAcquire 0
#define gl_SemanticsRelease 0
#define gl_SemanticsAcquireRelease 0
#define atomicLoad(x,...) (x)
#define atomicStore(x,y,...) ((x)=(y))
#define controlBarrier(...) ((void)0)
'''
driver=r'''
int main(){uint fid,d,x,order;
while(scanf("%u %u %u %u",&fid,&d,&x,&order)==4){
memset(w,0,sizeof w);w[0]=1;w[1]=fid;w[2]=d;w[3]=63;w[4]=31;w[5]=192;w[13]=order;w[14]=x;
w[768]=0xa17ecafe;w[769]=0x5a5aa5a5;w[770]=0xdeadbeef;w[771]=0xc001d00d;
gl_LocalInvocationIndex=0;shader_main();gl_LocalInvocationIndex=1;shader_main();
if(fwrite(w,4,772,stdout)!=772)return 2;
}return 0;}
'''
(out/'shader.cpp').write_text(header+translated+driver)
def run(name,args,**kw):
 r=subprocess.run(args,capture_output=True,timeout=20,**kw);(out/(name+'.stdout')).write_bytes(r.stdout);(out/(name+'.stderr')).write_bytes(r.stderr)
 if r.returncode:raise RuntimeError(name+' failed '+r.stderr.decode())
 return r
run('build',['clang++','-std=c++17','-O1','-ffp-contract=off','-fsanitize=undefined','-fno-sanitize-recover=all',str(out/'shader.cpp'),'-o',str(out/'shader-cpu')])
cases=[(root,d,bits(x),o) for d in range(6) for x in (0.0,0.3,-1.0,1.5707964,-1.5707964) for o in (0,1)]
raw=run('buffers',[str(out/'shader-cpu')],input=''.join('%u %u %u %u\n'%c for c in cases).encode()).stdout
assert len(raw)==len(cases)*3088
for i,(fid,d,x,o) in enumerate(cases):
 words=list(struct.unpack_from('<772I',raw,i*3088));expected=simulate(plan,fid,d,x,o)
 assert words==expected,(i,'full buffer mismatch')
 assert words[9]==evaluate(plan,fid,d,x)
assert evaluate(plan,root,3,bits(.3))==78542
(out/'RESULT.json').write_text(json.dumps({'passed':True,'full_buffer_cases':len(cases),'unchanged_example_expected':78542,'shader_sha256':hashlib.sha256(source.encode()).hexdigest(),'GPU':False,'memory_visibility_proven':False},indent=2)+'\n')
