// Single producer lane, finite scheduler. Source preparation only; not admitted.
import {expression} from './emitter.ts';
import {validateNat,type NatPlan} from './nat_ir.ts';
export function natShader(plan:NatPlan):string {
 const by=validateNat(plan);
 const tasks=[...by.values()].filter(s=>s.role==='task');
 const joins=[...by.values()].filter(s=>s.role==='join');
 const desc=tasks.map(s=>{
  const zero=expression(s.match.zero.value,[],true),succ=s.match.successor;
  const body=succ.op==='result'?`v=${expression(succ.value,[],true)};return true;`
    :`spawn=true;j=${succ.join}u;c0=${succ.children.find(c=>c.slot===0)!.id}u;c1=${succ.children.find(c=>c.slot===1)!.id}u;return true;`;
  return `case ${s.id}u:if(n==0u){v=${zero};return true;}${body}`;
 }).join('\n');
 const reductions=joins.map(s=>`case ${s.id}u:v=${expression(s.value,['a','b'],true)};return true;`).join('\n');
 return `#version 450
#extension GL_KHR_memory_scope_semantics : require
#pragma use_vulkan_memory_model
layout(local_size_x=128) in;
layout(std430,binding=0) devicecoherent buffer Words { uint w[]; };
const uint ROOT=0xffffffffu,TB=16u,JB=520u;
// Task states ready/expanded/pending/delivered = 1/2/3/4.
// Join state low two bits are valid slots; lifecycle = 4/8/12.
bool rootKnown(uint f){return ${plan.roots.map(r=>`f==${r}u`).join('||')};}
bool descriptor(uint f,uint n,out bool spawn,out uint v,out uint j,out uint c0,out uint c1){
 spawn=false;v=0u;j=0u;c0=0u;c1=0u;
 switch(f){${desc}default:return false;}
}
bool reduction(uint f,uint a,uint b,out uint v){v=0u;switch(f){${reductions}default:return false;}}
void deliver(uint parent,uint slot,uint value,uint rootJoin,inout uint error,inout bool terminal,inout uint result){
 // Root completion is owned by task0 or its actual allocated join. Queued
 // non-root deliveries never legitimately target the sentinel directly.
 if(parent==ROOT){error=4u;return;}
 if(parent>=w[7]||parent>=31u||slot>1u){error=4u;return;}
 uint at=JB+parent*8u,state=w[at+6u],valid=state&3u;
 if((state&~3u)!=4u||(valid&(1u<<slot))!=0u||w[at+3u]!=2u-uint(bitCount(valid))){error=5u;return;}
 uint a=slot==0u?value:w[at+4u],b=slot==1u?value:w[at+5u],joined=0u;
 // Resolve the checked join before mutating a final child slot.
 if(w[at+3u]==1u&&!reduction(w[at],a,b,joined)){error=6u;return;}
 if(w[at+3u]==1u&&(w[at+1u]==ROOT||parent==rootJoin)
   &&(parent!=rootJoin||w[at+1u]!=ROOT||w[at+2u]!=0u||terminal)){error=4u;return;}
 valid|=1u<<slot;w[at+4u+slot]=value;w[at+3u]-=1u;w[at+6u]=4u|valid;
 if(w[at+3u]==0u){w[at+7u]=joined;
  if(w[at+1u]==ROOT){w[at+6u]=12u|valid;terminal=true;result=joined;}
  else w[at+6u]=8u|valid;
 }
}
void producer(){
 uint error=0u,result=0u,rootJoin=ROOT;bool terminal=false;
 if(w[0]!=1u||!rootKnown(w[1])||w[2]>5u||w[3]==0u||w[3]>63u||w[4]>31u||w[5]>192u||w[13]>1u)error=1u;
 for(uint i=6u;i<13u;i++)if(w[i]!=0u)error=1u;
 for(uint i=14u;i<768u;i++)if(w[i]!=0u)error=1u;
 if(error==0u){w[6]=1u;w[TB]=w[1];w[TB+1u]=w[2];w[TB+2u]=ROOT;w[TB+5u]=1u;}
 for(uint turn=0u;turn<192u;turn++){
  if(error!=0u||terminal)break;
  if(w[8]>=w[5]){error=3u;break;}
  if(w[6]>w[3]||w[7]>w[4]){error=2u;break;}
  uint at=ROOT,kind=0u;
  for(uint i=0u;i<31u;i++)if(i<w[7]&&w[JB+i*8u+6u]==11u){at=JB+i*8u;kind=1u;break;}
  if(at==ROOT)for(uint i=0u;i<63u;i++)if(i<w[6]&&w[TB+i*8u+5u]==3u){at=TB+i*8u;kind=2u;break;}
  if(at==ROOT)for(uint i=0u;i<63u;i++){if(i>=w[6])break;uint k=w[13]==0u?i:w[6]-1u-i;
   if(w[TB+k*8u+5u]==1u){at=TB+k*8u;kind=3u;break;}}
  if(at==ROOT){error=5u;break;}
  w[8]+=1u;
  if(kind==1u){deliver(w[at+1u],w[at+2u],w[at+7u],rootJoin,error,terminal,result);if(error==0u)w[at+6u]=15u;continue;}
  if(kind==2u){deliver(w[at+2u],w[at+3u],w[at+6u],rootJoin,error,terminal,result);if(error==0u)w[at+5u]=4u;continue;}
  uint n=w[at+1u],depth=w[at+4u],v=0u,j=0u,c0=0u,c1=0u;bool spawn=false;
  if(n>5u||depth>5u||n+depth!=w[2]){error=5u;break;}
  if((at==TB||w[at+2u]==ROOT)&&(at!=TB||w[at+2u]!=ROOT||w[at+3u]!=0u)){error=4u;break;}
  if(!descriptor(w[at],n,spawn,v,j,c0,c1)){error=6u;break;}
  if(!spawn){w[at+6u]=v;
   if(w[at+2u]==ROOT){if(w[at+3u]!=0u){error=4u;break;}terminal=true;result=v;w[at+5u]=4u;}
   else w[at+5u]=3u;continue;
  }
  if(n==0u||w[6]+2u>w[3]||w[7]+1u>w[4]){error=2u;break;}
  uint ji=w[7],ja=JB+ji*8u,ca=TB+w[6]*8u;
  // Monotone allocation, checked together before the first descriptor write.
  w[ja]=j;w[ja+1u]=w[at+2u];w[ja+2u]=w[at+3u];w[ja+3u]=2u;w[ja+6u]=4u;
  for(uint slot=0u;slot<2u;slot++){uint child=ca+slot*8u;
   w[child]=slot==0u?c0:c1;w[child+1u]=n-1u;w[child+2u]=ji;w[child+3u]=slot;w[child+4u]=depth+1u;w[child+5u]=1u;}
  w[6]+=2u;w[7]+=1u;if(at==TB)rootJoin=ji;w[at+5u]=2u;
 }
 if(error==0u&&!terminal)error=3u;
 // One terminal publication path, including every error. No barrier in
 // producer/helpers and no early return from main; all 128 lanes converge.
 w[9]=error==0u?result:0u;w[10]=error;
 atomicStore(w[11],1u,gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsRelease);
}
void main(){
 if(gl_LocalInvocationIndex==0u)producer();
 controlBarrier(gl_ScopeWorkgroup,gl_ScopeWorkgroup,gl_StorageSemanticsBuffer,gl_SemanticsAcquireRelease);
 if(gl_LocalInvocationIndex==1u){uint done=atomicLoad(w[11],gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsAcquire);
  w[12]=done==1u&&w[10]==0u?w[9]:0u;}
}
`;
}
