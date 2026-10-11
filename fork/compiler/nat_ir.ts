// Separate, bounded Nat ABI. Inputs must come from checked semantic capture;
// accepting this IR alone is not evidence that a source program was checked.
import type { Expr } from './emitter.ts';
export const NAT_LIMITS = Object.freeze({depth:5,tasks:63,joins:31,steps:192,segments:64,expr:64,words:772});
export type NatChild = {id:number;argument:{kind:'Nat';op:'guarded-predecessor'};slot:0|1};
export type NatResult = {op:'result';value:Expr};
export type NatFork = {op:'fork';join:number;children:[NatChild,NatChild]};
export type NatTask = {id:number;fid:string;role:'task';argument:'Nat';result:'U32';
  match:{kind:'Nat';zero:NatResult;successor:NatResult|NatFork}};
export type NatJoin = {id:number;fid:string;role:'join';arguments:['U32','U32'];result:'U32';value:Expr};
export type NatPlan = {schema:'bend-nat-fork-v1';roots:number[];limits:typeof NAT_LIMITS;segments:(NatTask|NatJoin)[]};

function expr(e:Expr,arity:number):void {
 let nodes=0;
 const visit=(x:Expr):void=>{
  if(++nodes>NAT_LIMITS.expr||!Array.isArray(x))throw Error('Nat expression bound/shape');
  if(x[0]==='lit'&&x.length===2&&Number.isInteger(x[1])&&x[1]>=0&&x[1]<=0xffffffff)return;
  if(x[0]==='arg'&&x.length===2&&Number.isInteger(x[1])&&x[1]>=0&&x[1]<arity)return;
  if(x[0]==='bin'&&x.length===4&&['+','-','*','&','|','^'].includes(x[1])){visit(x[2]);visit(x[3]);return;}
  throw Error('unsupported typed Nat U32 expression');
 };visit(e);
}
export function validateNat(plan:NatPlan):Map<number,NatTask|NatJoin> {
 if(plan.schema!=='bend-nat-fork-v1'||!plan.limits
   ||Object.entries(NAT_LIMITS).some(([k,v])=>(plan.limits as any)[k]!==v))throw Error('Nat ABI/policy mismatch');
 if(!Array.isArray(plan.segments)||!plan.segments.length||plan.segments.length>NAT_LIMITS.segments)
  throw Error('Nat segment count');
 const by=new Map(plan.segments.map(s=>[s.id,s]));
 if(by.size!==plan.segments.length||new Set(plan.segments.map(s=>s.fid)).size!==by.size)throw Error('duplicate Nat identity');
 for(const s of by.values()){
  // Sparse final compiler FIDs are valid. 64 limits entry count, not FID value.
  if(!Number.isInteger(s.id)||s.id<0||s.id>65535||typeof s.fid!=='string'||!s.fid)throw Error('invalid Nat identity');
  if(s.result!=='U32')throw Error('Nat result type');
  if(s.role==='join'){
   if(s.arguments.length!==2||s.arguments.some(a=>a!=='U32'))throw Error('Nat join types');
   expr(s.value,2);continue;
  }
  if(s.role!=='task'||s.argument!=='Nat'||s.match?.kind!=='Nat'||s.match.zero?.op!=='result')throw Error('Nat match/type');
  expr(s.match.zero.value,0);
  const succ=s.match.successor;
  if(succ?.op==='result'){expr(succ.value,0);continue;}
  if(succ?.op!=='fork'||succ.children.length!==2||!Number.isInteger(succ.join)||by.get(succ.join)?.role!=='join')throw Error('Nat binary join');
  const slots=new Set<number>();
  for(const c of succ.children){
   if(!Number.isInteger(c.id)||by.get(c.id)?.role!=='task'||c.argument?.kind!=='Nat'||c.argument.op!=='guarded-predecessor'
     ||![0,1].includes(c.slot)||slots.has(c.slot))throw Error('Nat child must receive guarded predecessor');
   slots.add(c.slot);
  }
 }
 if(!Array.isArray(plan.roots)||!plan.roots.length||new Set(plan.roots).size!==plan.roots.length
   ||plan.roots.some(id=>!Number.isInteger(id)||by.get(id)?.role!=='task'))throw Error('invalid Nat roots');
 // Cycles need no acyclic proof: *every* child edge decreases the current
 // discriminator, including mutual recursion and calls to distinct helpers.
 return by;
}

export function checkedNatInput(value:bigint):number {
 if(value<0n||value>((1n<<48n)-1n))throw Error('upstream Nat immediate range');
 if(value>BigInt(NAT_LIMITS.depth))throw Error('unsupported Nat depth');
 return Number(value); // Narrow only after both independent checks.
}
