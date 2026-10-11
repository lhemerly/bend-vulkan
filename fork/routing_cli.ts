// Separate CPU prototype; leaves the reviewed Vulkan emitter unchanged.
import * as fs from 'node:fs';import * as path from 'node:path';
import {createHash} from 'node:crypto';
import * as Bend from '../evidence/upstream/bend.ts';
import * as Capture from './compiler/capture.ts';
import {routingTables,type RoutingPlan} from './compiler/routing.ts';
const [source,output]=process.argv.slice(2);const file=path.resolve(source),out=path.resolve(output);
if(fs.existsSync(out))throw Error('output directory must be new');
if(fs.readFileSync(file,'utf8').split('\n').filter(s=>/^\s*import\b/.test(s)).some(s=>s.trim()!=='import Base'))throw Error('local Base-only source');
const book=Bend.book_nil();await Bend.book_load(book,file,'',new Map());Bend.book_valid(book);if(book.hols)throw Error('unchecked holes');
const baseline=Capture.compile_book(book);const emitted=Capture.routing_book(book);
const plan=emitted.plan as RoutingPlan;const text=JSON.stringify(plan,null,2)+'\n';
const sha=createHash('sha256').update(text).digest('hex');
const declaration='OUTLINE Term corpus_eval(u64* H, Term t) {';
const yielded='    u64 tl = task_tail(t);';
const pending='    if ((u32)H[tl + 1] != 0) {';
const selection='  const char* why = gpu != 0 && BANGS != 0 ? gpu_probe() : "";';
for(const a of [declaration,yielded,pending,selection])if(emitted.c.split(a).length!==2)throw Error('pinned routing anchor mismatch');
const mode=`  const char* routing_mode=getenv("BEND_FORK_TRANSPORT");
  if(routing_mode && *routing_mode) {
    if(strcmp(routing_mode,"cpu-reference"))err_fail("routing: only explicit CPU-reference transport is implemented; GPU unavailable");
    if(gpu==1)err_fail("routing: CPU-reference conflicts with --gpu on");
    gpu=0;
  }
  if(gpu!=0)err_fail("routing: CPU prototype requires --gpu off; GPU dispatch disabled");
`;
const intercept=`
    const char* mode=getenv("BEND_FORK_TRANSPORT");
    if(mode && *mode && routing_root((u32)term_aux(t))>=0) {
      t=routing_reference(e,t);if(t==0)break;continue;
    }
`;
const check=`
      const char* mode=getenv("BEND_FORK_TRANSPORT");
      if(mode && *mode)routing_pending(H,t);
`;
const runtime=fs.readFileSync(new URL('./runtime/cpu_routing.c',import.meta.url),'utf8');
const c=emitted.c.replace(declaration,routingTables(plan,sha)+runtime+'\n'+declaration)
 .replace(yielded,yielded+intercept).replace(pending,pending+check).replace(selection,mode+selection);
fs.mkdirSync(out);fs.writeFileSync(out+'/default.c',baseline);fs.writeFileSync(out+'/program.c',c);
fs.writeFileSync(out+'/routing-plan.json',text);
fs.writeFileSync(out+'/caller-identity.json',JSON.stringify({schema:plan.schema,routing_plan_sha256:sha,gateways:plan.gateways,program_sha256:createHash('sha256').update(c).digest('hex')},null,2)+'\n');
