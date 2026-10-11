"""Translate this finite GLSL fixture to C for arithmetic/ABI checks, NOT GPU ordering proof."""
from pathlib import Path
import re, subprocess
root=Path(__file__).resolve().parents[1]
s=(root/'shaders/ring_fixture.comp').read_text()
s=re.sub(r'^#(?:version|extension|pragma).*\n','',s,flags=re.M);s=re.sub(r'layout\([^\n]*\) in;','',s);s=re.sub(r'layout\(std430[^\n]*\}\s*;','',s)
s=s.replace('void main()', 'void shader_main()').replace('    if (any(notEqual(gl_GlobalInvocationID, uvec3(0u)))) return;','').replace('    if (w.length() < 30) return;','')
s=s.replace('bool ringPop(out uint hi, out uint lo)', 'bool ringPop(uint *hi, uint *lo)')
a=s.index('bool ringPop(');b=s.index('\nvoid shader_main()',a)
part=s[a:b];start=part.index('{');head=part[:start];body=part[start:];body=re.sub(r'\bhi\b','(*hi)',body);body=re.sub(r'\blo\b','(*lo)',body);s=s[:a]+head+body+s[b:];s=s.replace('ringPop(hi, lo)', 'ringPop(&hi, &lo)')
prefix='''#define gl_ScopeDevice 1
#define gl_StorageSemanticsBuffer 64
#define gl_StorageSemanticsNone 0
#define gl_SemanticsAcquire 2
#define gl_SemanticsRelease 4
#define gl_SemanticsAcquireRelease 8
#define gl_SemanticsRelaxed 0
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <assert.h>
typedef uint32_t uint;
static uint w[31];
static void memoryBarrierBuffer(void) {}
static uint atomicAdd(uint *p,uint n,...){uint old=*p;*p+=n;return old;}
static uint atomicExchange(uint *p,uint n,...){uint old=*p;*p=n;return old;}
static uint atomicLoad(uint *p,...){return *p;}
static void atomicStore(uint *p,uint n,...){*p=n;}
static uint atomicCompSwap(uint *p,uint x,uint n,...){uint old=*p;if(old==x)*p=n;return old;}
'''
s=re.sub(r'atomicAdd\(w\[([^\]]+)\],',r'atomicAdd(&w[\1],',s);s=re.sub(r'atomicExchange\(w\[([^\]]+)\],',r'atomicExchange(&w[\1],',s)
for name in ['atomicLoad','atomicStore','atomicCompSwap']:
 s=re.sub(name+r'\(w\[([^\]]+)\],',name+r'(&w[\1],',s)
post='''
int main(void) {
 uint64_t state=1234567;
 for (uint test=0;test<128;test++) {
  for(uint i=0;i<31;i++)w[i]=0xdeadbeef;
  for(uint i=0;i<4;i++){
   state=state*6364136223846793005ULL+1;
   uint64_t term=((uint64_t)5<<56)|(((state>>40)&65535)<<40)|(state&((1ULL<<40)-1));
   if(test==0){uint64_t locs[4]={0,7,(1ULL<<32)+7,(1ULL<<40)-1};term=((uint64_t)5<<56)|((uint64_t)(i*21845)<<40)|locs[i];}
   w[11+2*i]=(uint)term;w[12+2*i]=(uint)(term>>32);
  }
  if(test==126)w[12]=6u<<24;
  if(test==127)w[12]|=0x80000000u;
  shader_main();assert(w[30]==0xdeadbeef);
  bool valid=test<126;assert(w[27]==(valid?4u:0u));assert(w[28]==(valid?4u:0u));assert(w[29]==(valid?0u:2u));
  for(uint i=0;i<8;i++)assert(w[19+i]==(valid?w[11+i]:0u));
  for(uint i=0;i<30;i++)printf("%08x%s",w[i],i==29?"\\n":" ");
 }
 uint starts[9]={0,1,3,4,8,0xfffffff8u,0xfffffffcu,0xfffffffeu,0xffffffffu};
 for(uint k=0;k<9;k++){
  for(uint i=0;i<31;i++)w[i]=0;
  w[W_GET]=w[W_PUT]=starts[k];
  for(uint slot=0;slot<4;slot++){uint pos=starts[k]+((slot-starts[k])&3u);w[W_SLOTS+2*slot+1]=(1u-lapOf(pos))<<31;}
  for(uint i=0;i<100000;i++){
   uint lo=i^0xa17b1234u,hi=(5u<<24)|((i&65535u)<<8)|(i&255u),got_hi,got_lo;
   assert(ringPush(hi,lo));assert(ringPop(&got_hi,&got_lo));assert(got_hi==hi&&got_lo==lo);
  }
 }
 // Invalid task/sticky error: no reservation. Overflow: first reservation advances put.
 for(uint i=0;i<31;i++)w[i]=0;
 assert(!ringPush(6u<<24,7));assert(w[W_PUT]==0&&w[W_ERR]==2);
 assert(!ringPush(5u<<24,8));assert(w[W_PUT]==0);
 for(uint i=0;i<31;i++)w[i]=0;
 for(uint i=0;i<4;i++)assert(ringPush(5u<<24,i));
 assert(!ringPush(5u<<24,9));assert(w[W_PUT]==5&&w[W_ERR]==1);
 assert(!ringPush(5u<<24,9));assert(w[W_PUT]==5);
 // Reserved slot whose high marker is still unpublished must not consume low.
 for(uint i=0;i<31;i++)w[i]=0;
 w[W_PUT]=1;w[W_SLOTS]=0x11223344u;uint hi,lo;
 assert(!ringPop(&hi,&lo));assert(w[W_GET]==0&&hi==0&&lo==0);
 storeRelease(W_SLOTS+1,(5u<<24)|(1u<<31));assert(ringPop(&hi,&lo));assert(hi==(5u<<24)&&lo==0x11223344u&&w[W_GET]==1);
 fprintf(stderr,"900000 sequential slot-reuse cases across9starts plus invalid/sticky/overflow/delayed-publication checks passed; not a concurrent-memory proof.\\n");
 return 0;
}
'''
p=root/'evidence/shader-translated.c';p.write_text(prefix+s+post)
subprocess.run(['cc','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',str(p),'-o',str(root/'evidence/shader-cpu-check')],check=True)
r=subprocess.run([str(root/'evidence/shader-cpu-check')],capture_output=True,text=True,check=True)
(root/'evidence/shader-cpu-vectors.txt').write_text(r.stdout)
(root/'evidence/shader-focused-checks.txt').write_text(r.stderr)
print('128 translated-shader fixtures pass full30-word ABI checks, invalid tags/RFC, canary and UBSan. Not GPU memory-model evidence.')
