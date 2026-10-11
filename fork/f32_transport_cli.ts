// Separate Nat host transport; old U32 CLI/worker and schema2 CLI stay intact.
import * as fs from 'node:fs';import * as path from 'node:path';
import {createHash} from 'node:crypto';import {execFileSync} from 'node:child_process';
import {routingTables,type RoutingPlan} from './compiler/routing_f32.ts';
const hash=(s:string|Buffer)=>createHash('sha256').update(s).digest('hex');
try{
 const[source,output]=process.argv.slice(2);if(!source||!output)throw Error('usage: bun nat_transport_cli.ts SOURCE.bend NEW_OUTPUT');
 const here=path.dirname(new URL(import.meta.url).pathname),out=path.resolve(output);
 execFileSync('bun',[path.join(here,'f32_routing_cli.ts'),path.resolve(source),out],{timeout:15000});
 execFileSync('glslangValidator',['-V','--target-env','vulkan1.2',path.join(out,'f32.comp'),'-o',path.join(out,'f32.spv')],{timeout:10000});
 execFileSync('/usr/bin/python3',[path.join(here,'runtime/f32_worker_prepare.py'),out],{timeout:30000});
 const caller=JSON.parse(fs.readFileSync(path.join(out,'f32-caller.json'),'utf8'));
 const routingText=fs.readFileSync(path.join(out,'routing-plan.json'),'utf8'),routing=JSON.parse(routingText) as RoutingPlan;
 const plan=JSON.parse(fs.readFileSync(path.join(out,'f32-plan.json'),'utf8'));
 const declaration='OUTLINE Term corpus_eval(u64* H, Term t) {',yielded='    u64 tl = task_tail(t);',pending='    if ((u32)H[tl + 1] != 0) {';
 const selection='  const char* why = gpu != 0 && BANGS != 0 ? gpu_probe() : "";';
 let c=fs.readFileSync(path.join(out,'routing.c'),'utf8');
 for(const anchor of[declaration,yielded,pending,selection])if(c.split(anchor).length!==2)throw Error('Nat pinned runtime anchor mismatch');
 const bootstrap=`import sys,json,hashlib,runpy\nfor b in json.loads(sys.argv[2]):\n if hashlib.sha256(open(b['path'],'rb').read()).hexdigest()!=b['sha256']:raise RuntimeError('Nat fixed runtime identity mismatch')\np=sys.argv[1];sys.argv=[p,*sys.argv[3:]];runpy.run_path(p,run_name='__main__')\n`;
 const defines=`#define NAT_CONTROLLER ${JSON.stringify(path.join(here,'runtime/f32_controller.py'))}\n#define NAT_RUNTIME_BINDINGS ${JSON.stringify(JSON.stringify(caller.runtime_bindings))}\n#define NAT_CALLER_JSON ${JSON.stringify(JSON.stringify(caller))}\n#define NAT_BOOTSTRAP ${JSON.stringify(bootstrap)}\n`;
 const cpu=fs.readFileSync(path.join(here,'runtime/cpu_routing_f32.c'),'utf8');
 const bridge=fs.readFileSync(path.join(here,'runtime/f32_host_bridge.c'),'utf8').replace('NAT_ROOT_CASES',plan.roots.map((r:number)=>`case ${r}u:return true;`).join(''));
 const intercept=`
    const char* mode=getenv("BEND_FORK_TRANSPORT");
    if(mode&&*mode&&routing_root((u32)term_aux(t))>=0){
      t=!strcmp(mode,"f32-vulkan")?nat_handoff(e,t):routing_reference(e,t);
      if(t==0)break;continue;
    }
`;
 const pendingCheck='\n      const char* mode=getenv("BEND_FORK_TRANSPORT");if(mode&&*mode)routing_pending(H,t);\n';
 const mode=`  const char* nat_mode=getenv("BEND_FORK_TRANSPORT");
  if(nat_mode&&*nat_mode){
    if(strcmp(nat_mode,"cpu-reference")&&strcmp(nat_mode,"f32-vulkan"))err_fail("Nat: unknown selected transport");
    if(!strcmp(nat_mode,"f32-vulkan")&&gpu==0)err_fail("Nat: --gpu off vetoes selected device transport");
    if(!strcmp(nat_mode,"cpu-reference")&&gpu==1)err_fail("Nat: --gpu on conflicts with CPU-reference");
    gpu=0; /* Host CPU ownership; only explicit Nat transport could dispatch. */
  }
  if(gpu!=0)err_fail("Nat: unselected prepared host requires --gpu off");
`;
 c=c.replace(declaration,defines+routingTables(routing,hash(routingText))+cpu+'\n'+bridge+'\n'+declaration)
   .replace(yielded,yielded+intercept).replace(pending,pending+pendingCheck).replace(selection,mode+selection);
 fs.writeFileSync(path.join(out,'program.c'),c);
 fs.writeFileSync(path.join(out,'host-binding.json'),JSON.stringify({schema:caller.schema,caller,program_sha256:hash(c),bridge_sha256:hash(bridge),admitted:false},null,2)+'\n');
}catch(error){console.error(error instanceof Error?error.message:String(error));process.exitCode=1;}
