// Source-only preparation: writes checked metadata/shader; never launches a worker.
import * as fs from 'node:fs';import * as path from 'node:path';
import {createHash} from 'node:crypto';
import * as Bend from '../evidence/upstream/bend.ts';
import {compile_book,nat_book} from './compiler/capture.ts';
import {routingTables,type RoutingPlan} from './compiler/routing.ts';
import {natShader} from './compiler/nat_emitter.ts';
try {
const args=process.argv.slice(2);if(args.length!==2)throw Error('usage: bun nat_source_cli.ts source.bend NEW_OUTPUT');
const file=path.resolve(args[0]),out=path.resolve(args[1]);if(fs.existsSync(out))throw Error('output must be new');
if(fs.readFileSync(file,'utf8').split('\n').filter(s=>/^\s*import\b/.test(s)).some(s=>s.trim()!=='import Base'))throw Error('local Base-only source');
const book=Bend.book_nil();await Bend.book_load(book,file,'',new Map());Bend.book_valid(book);if(book.hols)throw Error('unchecked holes');
const baseline=compile_book(book),captured=nat_book(book);
const hash=(text:string)=>createHash('sha256').update(text).digest('hex');
const plan=JSON.stringify(captured.plan,null,2)+'\n',routing=JSON.stringify(captured.routing,null,2)+'\n';
routingTables(captured.routing as RoutingPlan,hash(routing));
const shader=natShader(captured.plan);
const identity={schema:'bend-nat-source-preparation-v1',admitted:false,source_sha256:hash(fs.readFileSync(file,'utf8')),
 pinned_bend_commit:'11d483271b46e445b922756d5fd4127a1ea99ae8',
 compiler_sha256:hash(fs.readFileSync(new URL('./compiler/capture.ts',import.meta.url),'utf8')),
 base_sha256:hash(fs.readFileSync(new URL('../evidence/upstream/base.bend',import.meta.url),'utf8')),
 nat_plan_sha256:hash(plan),routing_plan_sha256:hash(routing),shader_sha256:hash(shader),
 routing_program_sha256:hash(captured.c),default_program_sha256:hash(baseline),
 roots:captured.plan.roots,gateways:(captured.routing as RoutingPlan).gateways};
fs.mkdirSync(out);
for(const[name,text]of Object.entries({'default.c':baseline,'routing.c':captured.c,'nat-plan.json':plan,
 'routing-plan.json':routing,'nat.comp':shader,'source-identity.json':JSON.stringify(identity,null,2)+'\n'}))fs.writeFileSync(path.join(out,name),text);
} catch(error) {
 // Bend checker errors contain the whole cyclic Book. Print its supported
 // concise diagnostic rather than allowing the runtime to dump that object.
 console.error((error as any)?.$==='Err'?Bend.err_show(error as Bend.Err):error instanceof Error?error.message:'Nat source preparation failed');
 process.exitCode=1;
}
