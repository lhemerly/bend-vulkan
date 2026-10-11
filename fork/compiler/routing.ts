// CPU-only host routing prototype. No Vulkan worker/module is generated here.
export type RoutingPlan = {
 schema:string;depth_limit:number;effect_fixed_point_rounds:number;
 gateways:{id:number;root_id:number;fid:string;target:string;argument:string;caller:string}[];
 joins:{id:number;children:{id:number;index:number}[]}[];
 segments:{id:number;fid:string;arity:number;kinds:string[];result_words:number;serial_continuation:boolean;frame_result_words:number;parent_contexts:{parent:number;index:number}[];own_effect:number;effect:number;executable:string[];constructed:string[]}[];
 native_helpers:{fid:string;own_effect:number;effect:number;executable:string[]}[];
};
export function routingTables(plan:RoutingPlan,sha:string):string {
 if(plan.schema!=="bend-fork-cpu-routing-v2"||!/^[a-f0-9]{64}$/.test(sha))throw Error('routing identity mismatch');
 const by=new Map([...plan.segments,...plan.native_helpers].map(s=>[s.fid,s]));
 for(const g of plan.gateways){
  const s=plan.segments[g.id],r=plan.segments[g.root_id];
  if(s?.fid!==g.fid||r?.fid!==g.target||s.arity!==1||r.arity!==1||s.result_words!==1||r.result_words!==1
    ||!['Nat','U32'].includes(g.argument))throw Error('invalid gateway/root binding');
 }
 // Independently recompute the monotone executable-edge fixed point.
 const flags=new Map([...by].map(([fid,s])=>[fid,s.own_effect]));
 if(by.size!==plan.segments.length+plan.native_helpers.length || plan.segments.some((s,i)=>s.id!==i))throw Error('invalid routing identities');
 for(const s of plan.segments)if(typeof s.serial_continuation!=='boolean'
   ||!Number.isInteger(s.frame_result_words)||s.frame_result_words<0||s.frame_result_words>s.arity
   ||!s.serial_continuation&&s.frame_result_words!==0)throw Error('invalid compiled serial lifecycle role');
 for(const s of plan.segments)for(const c of s.parent_contexts){
  if(!Number.isInteger(c.parent)||c.parent< -1||c.parent>=plan.segments.length
     ||!Number.isInteger(c.index)||c.index<0||c.index>65535
     ||c.parent===-1&&c.index!==0)throw Error('invalid checked continuation context');
 }
 const joinIds=new Set<number>();
 for(const j of plan.joins){
  const segment=plan.segments[j.id];const occupied=new Set<number>();
  if(!segment||joinIds.has(j.id)||segment.serial_continuation||j.children.length<2)throw Error('invalid compiled join role');
  joinIds.add(j.id);
  for(const child of j.children){
   const callee=plan.segments[child.id];
   if(!callee||!Number.isInteger(child.index)||child.index<0||child.index+callee.result_words>segment.arity)
    throw Error('invalid compiled child layout');
   for(let i=child.index;i<child.index+callee.result_words;i++){
    if(occupied.has(i))throw Error('overlapping compiled child result slots');occupied.add(i);
   }
  }
 }
 let changed:boolean;
 do{changed=false;for(const[fid,s]of by){const n=s.executable.reduce((v,e)=>v|(flags.get(e)??2),flags.get(fid)!);
 if(n!==flags.get(fid)){flags.set(fid,n);changed=true;}}}while(changed);
 for(const[fid,s]of by)if(flags.get(fid)!==s.effect)throw Error('routing fixed-point proof mismatch');
 return `#define ROUTING_PLAN_SHA256 "${sha}"\n#define ROUTING_SEGMENTS ${plan.segments.length}u\n`
 +`static const unsigned char routing_effect[] = {${plan.segments.map(s=>s.effect).join(',')}};\n`
 +`static const unsigned char routing_arity[] = {${plan.segments.map(s=>s.arity).join(',')}};\n`
 +`static const unsigned char routing_resw[] = {${plan.segments.map(s=>s.result_words).join(',')}};\n`
 +`static const unsigned char routing_frame_results[] = {${plan.segments.map(s=>s.frame_result_words).join(',')}};\n`
 +`static const unsigned char routing_serial[] = {${plan.segments.map(s=>Number(s.serial_continuation)).join(',')}};\n`
 +`static int routing_root(u32 f) {switch(f){${plan.gateways.map(g=>`case ${g.fid}:return ${g.target};`).join('')}default:return -1;}}\n`
 +`static bool routing_nat(u32 f) {switch(f){${plan.gateways.filter(g=>g.argument==='Nat').map(g=>`case ${g.fid}:return true;`).join('')}default:return false;}}\n`
 +`static bool routing_parent(u32 f,int p,u32 idx) {switch(f){${plan.segments.map(s=>`case ${s.id}:return ${s.parent_contexts.length?s.parent_contexts.map(c=>`(p==${c.parent} && idx==${c.index}u)`).join(' || '):'false'};`).join('')}default:return false;}}\n`
 +`static int routing_child(u32 f,u32 slot) {switch(f){${plan.joins.map(j=>`case ${j.id}:switch(slot){${j.children.map(c=>`case ${c.index}:return ${c.id};`).join('')}default:return -1;}`).join('')}default:return -1;}}\n`
 +`static u32 routing_join_count(u32 f) {switch(f){${plan.joins.map(j=>`case ${j.id}:return ${j.children.length}u;`).join('')}default:return 0;}}\n`
 +`static bool routing_reserved_result(u32 f,u32 slot) {switch(f){${plan.joins.map(j=>{
  const reserved=j.children.flatMap(c=>Array.from({length:plan.segments[c.id].result_words-1},(_,i)=>c.index+i+1));
  return `case ${j.id}:return ${reserved.length?reserved.map(i=>`slot==${i}u`).join(' || '):'false'};`;
 }).join('')}default:return false;}}\n`;
 // The compiler's initial fork shape owns every child slot, not merely the
 // surviving task-tagged words of a potentially corrupted buffer.
}
