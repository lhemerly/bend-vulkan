"""Sequential translation of the actual generated task-deliver shader, with UBSan.
This checks finite behavior and full buffers, not concurrent memory visibility.
"""
from pathlib import Path
import re,subprocess,random,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'shaders/pair.generated.comp').read_text()
def block(source,offset):
 start=source.index('{',offset)+1;depth=1
 for i in range(start,len(source)):
  if source[i]=='{':depth+=1
  elif source[i]=='}':
   depth-=1
   if depth==0:return source[start:i]
 raise ValueError('brace')
functions=SOURCE[:SOURCE.index('void main()')]
functions='\n'.join(line for line in functions.splitlines() if not line.startswith(('#','layout(')))
initialize=block(SOURCE,SOURCE.index('if(leader)'))
values=[0,1,12345,0xffffffff,0xfffffffe,0x80000000,0x7fffffff]+[random.Random(i+23).getrandbits(32) for i in range(128)]
oracle=ROOT/'evidence/pair-preparation/oracle.c'
subprocess.run(['cc','-O1','-std=c11','-fsanitize=undefined','-fno-sanitize-recover=all',oracle,'-o','/tmp/bend-pair-oracle'],check=True)
r=subprocess.run(['/tmp/bend-pair-oracle'],input='\n'.join(map(str,values))+'\n',text=True,capture_output=True,check=True)
expected=list(map(int,r.stdout.split()));assert len(expected)==len(values)
header='''#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <cstring>
using uint=uint32_t;
uint w[52];uint gl_SubgroupSize=64,gl_NumSubgroups=2;
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
uint add(uint *p,uint v){uint old=*p;*p+=v;return old;}
uint bitOr(uint *p,uint v){uint old=*p;*p|=v;return old;}
uint cas(uint *p,uint expect,uint v){uint old=*p;if(old==expect)*p=v;return old;}
#define atomicAdd(x,y,...) add(&(x),(y))
#define atomicOr(x,y,...) bitOr(&(x),(y))
#define atomicCompSwap(x,y,z,...) cas(&(x),(y),(z))
#define controlBarrier(...) ((void)0)
'''
driver='''
void init(uint x,uint order,uint arenaCapacity,uint queueCapacity,uint repeat){INIT}
void start(uint x,uint order,uint arenaCapacity,uint queueCapacity,uint repeat){
 for(uint i=0;i<52;i++)w[i]=0xdeadbeef;
 w[0]=x;w[1]=order;w[2]=arenaCapacity;w[3]=queueCapacity;w[22]=repeat;
 for(uint i=48;i<52;i++)w[i]=0x5a17cafe;
 init(x,order,arenaCapacity,queueCapacity,repeat);
}
void canaries(){for(uint i=48;i<52;i++)assert(w[i]==0x5a17cafe);}
uint inputs[]={INPUTS};uint expected[]={EXPECTED};
int main(){
 unsigned cases=0;
 for(uint i=0;i<sizeof inputs/sizeof *inputs;i++)for(uint order=0;order<2;order++){
  start(inputs[i],order,10,2,0);
  assert(w[5]==1 && w[REM]==2 && w[14]==10 && w[15]==2 && w[9]==0);
  assert(w[24]==4 && w[26]==7 && w[25]==termHigh(FID_AFFINE) && w[27]==termHigh(FID_AFFINE));
  complete_task(order);
  assert(w[REM]==1 && w[16]==1 && w[9]==0 && w[12]==0 && w[13]==0);
  complete_task(order^1u);
  assert(w[4]==0 && w[7]==3 && w[8]==1 && w[REM]==0 && w[9]==2);
  assert(w[10]==expected[i] && w[11]==0 && w[12]==1 && w[13]==1 && w[16]==2 && w[17]==order);
  assert(w[24]==generated_affine(w[32]) && w[26]==generated_affine(w[38]) && w[25]==0 && w[27]==0);
  // Immutable generated task parameters, continuation records and bounded queue terms.
  assert(w[28]==0xffffffffu && w[29]==0xffffffffu && w[31]==0);
  assert(w[32]==arg0(inputs[i]) && w[33]==0 && w[34]==0 && w[35]==termHigh(FID_PAIR_J2) && w[36]==0 && w[37]==0);
  assert(w[38]==arg1(inputs[i]) && w[39]==0 && w[40]==0 && w[41]==termHigh(FID_PAIR_J2) && w[42]==0 && w[43]==1);
  assert(w[44]==4 && w[45]==termHigh(FID_AFFINE) && w[46]==7 && w[47]==termHigh(FID_AFFINE));
  uint before[52];std::memcpy(before,w,sizeof w);complete_task(order);
  assert(w[4]==3);before[4]=3;assert(std::memcmp(before,w,sizeof w)==0);canaries();cases++;
 }
 for(uint order=0;order<2;order++){
  start(12345,order,10,2,0);complete_task(order);complete_task(order);complete_task(order^1u);
  assert(w[4]==3 && w[REM]==1 && w[9]==0 && w[12]==0 && w[13]==0 && w[16]==1);canaries();
 }
 for(uint arena=0;arena<10;arena++){
  start(12345,0,arena,2,0);assert(w[4]==1 && w[14]==0 && w[15]==0 && w[9]==0);
  for(uint i=24;i<48;i++){assert(w[i]==0);}
  complete_task(0);assert(w[9]==0);canaries();
 }
 for(uint queue=0;queue<2;queue++){
  start(12345,0,10,queue,0);assert(w[4]==1 && w[14]==0 && w[15]==0 && w[9]==0);complete_task(0);assert(w[9]==0);canaries();
 }
 start(12345,2,10,2,0);assert(w[4]==6 && w[9]==0);canaries();
 start(12345,0,11,2,0);assert(w[4]==6 && w[9]==0);canaries();
 start(12345,0,10,3,0);assert(w[4]==6 && w[9]==0);canaries();
 start(12345,0,10,2,2);assert(w[4]==6 && w[9]==0);canaries();
 start(12345,0,10,2,0);w[45]=termHigh(FID_PAIR_J2);complete_task(0);assert(w[4]==2 && w[REM]==2 && w[9]==0);canaries();
 start(12345,0,10,2,0);w[44]=99;complete_task(0);assert(w[4]==2 && w[REM]==2 && w[9]==0);canaries();
 std::printf("%u actual-shader task/join CPU cases, both orders, full record contracts, duplicates, capacity/input/corrupt task failures and canaries passed. Not GPU ordering evidence.\\n",cases);
}
'''.replace('INIT',initialize).replace('INPUTS',','.join(str(x)+'u' for x in values)).replace('EXPECTED',','.join(str(x)+'u' for x in expected))
output=ROOT/'evidence/pair-preparation/shader-cpu.cpp';output.write_text(header+functions+driver)
subprocess.run(['c++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',output,'-o','/tmp/bend-pair-shader-cpu'],check=True)
result=subprocess.run(['/tmp/bend-pair-shader-cpu'],text=True,capture_output=True,check=True)
(ROOT/'evidence/pair-preparation/shader-cpu-result.txt').write_text(result.stdout+result.stderr)
(ROOT/'evidence/pair-preparation/cpu-inputs.json').write_text(json.dumps({'inputs':values,'expected':expected,'gpu_dispatches':0,'shader_sha256':hashlib.sha256(SOURCE.encode()).hexdigest()},indent=2)+'\n')
print(result.stdout,end='')
