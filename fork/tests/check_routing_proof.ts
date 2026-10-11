// Separate recomputation rejects forged effects and gateway identities.
import * as fs from 'node:fs';
import {routingTables,type RoutingPlan} from '../compiler/routing.ts';
const source=JSON.parse(fs.readFileSync(process.argv[2],'utf8')) as RoutingPlan;
const sha='0'.repeat(64);let cases=0;
function rejected(p:RoutingPlan){let fail=false;try{routingTables(p,sha);}catch{fail=true;}if(!fail)throw Error('forged proof accepted');cases++;}
routingTables(source,sha);cases++;
let p=structuredClone(source);p.gateways[0].root_id=p.gateways[0].id;rejected(p);
p=structuredClone(source);p.gateways[0].id=p.gateways[0].root_id;rejected(p);
p=structuredClone(source);const affected=p.segments.find(s=>s.effect===1&&s.own_effect===0)!;affected.effect=0;rejected(p);
// A recursive SCC can acquire an effect from an edge discovered after its first
// traversal. The independent fixed point must propagate it to both members.
p=structuredClone(source);const gateway=p.gateways[0].fid;
p.native_helpers.push({fid:'cycle_a',own_effect:0,effect:1,executable:['cycle_b']},
 {fid:'cycle_b',own_effect:0,effect:1,executable:['cycle_a',gateway]});
routingTables(p,sha);cases++;
p.native_helpers[0].effect=0;rejected(p);
p=structuredClone(source);p.native_helpers.push({fid:'unknown_a',own_effect:0,effect:2,executable:['missing_executable']},
 {fid:'unknown_b',own_effect:0,effect:2,executable:['unknown_a','unknown_b']});
routingTables(p,sha);cases++;
p.native_helpers[1].effect=0;rejected(p);
// Merely constructing a closure/gateway is not executing it.
p=structuredClone(source);const leaf=p.segments.find(s=>s.own_effect===0&&s.executable.length===0)!;
leaf.constructed.push(gateway);routingTables(p,sha);cases++;
p=structuredClone(source);p.joins[0].children.pop();rejected(p);
p=structuredClone(source);p.joins[0].children[1].index=p.joins[0].children[0].index;rejected(p);
p=structuredClone(source);p.joins[0].children[0].id=65535;rejected(p);
p=structuredClone(source);p.joins.push(structuredClone(p.joins[0]));rejected(p);
p=structuredClone(source);delete (p.segments[0] as any).serial_continuation;rejected(p);
p=structuredClone(source);p.schema='bend-fork-cpu-routing-v1';rejected(p);
console.log(JSON.stringify({cases,recursive_SCC_gateway_and_unknown_propagation:true,construction_is_not_execution:true,forged_effects_and_bindings_rejected:true}));
