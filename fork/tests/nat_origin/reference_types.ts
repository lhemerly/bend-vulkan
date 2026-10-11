// Validate actual source-derived metadata; mutation cases are rejection probes.
import {validateNat,type NatPlan} from '../../compiler/nat_ir.ts';
const plan=JSON.parse(await Bun.file(process.argv[2]).text()) as NatPlan;
validateNat(plan);
for(const role of ['child','join','root']){
 const bad=structuredClone(plan) as any;
 const task=bad.segments.find((s:any)=>s.role==='task');
 if(role==='child')task.match.successor.children[0].id=true;
 if(role==='join')task.match.successor.join=true;
 if(role==='root')bad.roots[0]=true;
 let rejected=false;try{validateNat(bad);}catch{rejected=true;}
 if(!rejected)throw Error('boolean '+role+' reference accepted');
}
console.log('PASS: TypeScript rejects boolean child/join/root references');
