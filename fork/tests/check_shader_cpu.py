"""Sequential translation of actual emitted GLSL: full buffers/reuse, not GPU ordering proof."""
from pathlib import Path
import sys,json,subprocess,random,struct,hashlib
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'fork/runtime'));from abi import expected_words
out=r/'evidence/fork-shader-cpu';out.mkdir(exist_ok=False);rows=[]
header='''#include <cstdint>
#include <cstdio>
#include <cstdlib>
using uint=uint32_t;uint w[28];
#define gl_ScopeDevice 0
#define gl_ScopeWorkgroup 0
#define gl_StorageSemanticsBuffer 0
#define gl_StorageSemanticsNone 0
#define gl_StorageSemanticsShared 0
#define gl_SemanticsAcquire 0
#define gl_SemanticsRelease 0
#define gl_SemanticsAcquireRelease 0
#define gl_SemanticsRelaxed 0
#define atomicLoad(x,...) (x)
#define atomicStore(x,y,...) ((x)=(y))
uint add(uint*p,uint v){uint old=*p;*p+=v;return old;}
uint bitOr(uint*p,uint v){uint old=*p;*p|=v;return old;}
#define atomicAdd(x,y,...) add(&(x),(y))
#define atomicOr(x,y,...) bitOr(&(x),(y))
#define controlBarrier(...) ((void)0)
'''
for name in ['scalar','pair_distinct','renamed_reordered','host_irrelevant','host_twice']:
 d=out/name;d.mkdir();generated=r/'evidence/fork-transport-preparation'/name/'generated';source=(generated/'program.comp').read_text();plan=json.loads((generated/'plan.json').read_text());functions=source[:source.index('void main()')];functions='\n'.join(line for line in functions.splitlines() if not line.startswith(('#','layout(')))
 main=source[source.index('void main()'):];start=main.index('  for(uint i=2u');end=main.index('\n }\n phase();',start);initialize=main[start:end]
 driver='''void start(uint fid,uint x,uint order){w[0]=fid;w[1]=x;w[11]=order;INITIALIZE}
int main(){for(uint i=0;i<28;i++)w[i]=0xdeadbeef;for(uint i=24;i<28;i++)w[i]=0x5a17cafe;
 uint fid,x,order,repeat;while(std::scanf("%u %u %u %u",&fid,&x,&order,&repeat)==4){start(fid,x,order);if(order<2){complete(order);if(repeat==2u)complete(order);complete(order^1u);if(repeat==1u)complete(order);}
 if(acquireWord(4u)==2u){w[20]=w[2];}
 if(std::fwrite(w,4,28,stdout)!=28){return 2;}}return 0;}
'''.replace('INITIALIZE',initialize);cpp=d/'shader.cpp';cpp.write_text(header+functions+driver)
 subprocess.run(['c++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',cpp,'-o',d/'shader-cpu'],check=True,timeout=20)
 inputs=[0,1,42,0x7fffffff,0x80000000,0xfffffffe,0xffffffff]+[random.Random(i+53).getrandbits(32) for i in range(126)];cases=[]
 for fid in plan['roots']:
  for x in inputs:
   for order in (0,1):cases.append((fid,x,order,0))
  cases.extend([(fid,2,2,0),(fid,0,0,0),(fid,0xffffffff,1,0)])
  root=next(s for s in plan['segments'] if s['id']==fid)
  if 'fork' in root:cases.extend([(fid,42,0,1),(fid,42,1,1),(fid,42,0,2),(fid,42,1,2)])
 cases.append((65535,1,0,0));p=subprocess.run([d/'shader-cpu'],input=''.join('%d %d %d %d\n'%c for c in cases).encode(),capture_output=True,timeout=5);assert p.returncode==0,p.stderr;assert len(p.stdout)==len(cases)*112
 for i,(fid,x,order,repeat) in enumerate(cases):
  got=list(struct.unpack('<28I',p.stdout[i*112:(i+1)*112]));want=expected_words(plan,fid,x,order)
  if repeat:
   want[3]=3
   if repeat==2:
    want[2]=want[4]=want[20]=0;want[5]=1;want[6]=1<<order;want[8+(order^1)]=0
  want += [0x5a17cafe]*4;assert got==want,(name,i,got,want)
 (d/'cases.json').write_text(json.dumps(cases)+'\n');(d/'complete-buffers.bin').write_bytes(p.stdout);(d/'stderr').write_bytes(p.stderr);rows.append({'case':name,'complete_buffers':len(cases),'both_orders':True,'reused_array_no_ready_done_leak':True,'UBSan':True,'shader_sha256':hashlib.sha256(source.encode()).hexdigest(),'gpu_dispatches':0});print(name,len(cases),'full buffers PASS',flush=True)
(out/'RESULT.json').write_text(json.dumps({'scope':'sequential actual-GLSL translation only; no concurrent memory-model/GPU proof','cases':rows},indent=2)+'\n')
