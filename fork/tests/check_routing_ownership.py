"""Instrumented native handoff ownership and immutable compiled plan bindings."""
from pathlib import Path
import subprocess,json,os,hashlib,sys
r=Path(__file__).resolve().parents[2];out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-cpu-routing-ownership');out.mkdir(exist_ok=False)
env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')};rows=[]
for name,count,expected in [('gpu_mark',1,b'1212\n'),('two_io_handoffs',2,b'12\n6\n')]:
 d=out/name;d.mkdir();source=r/'evidence'/(sys.argv[2] if len(sys.argv)>2 else 'fork-cpu-routing-lifecycle-v2')/name/'generated/program.c';c=source.read_text()
 a='INLINE void heap_free(Env e, u32 cls, u64 loc) {';assert c.count(a)==1
 c=c.replace(a,'static _Thread_local u64 ownership_loc;\nstatic _Thread_local u32 ownership_frees;\nstatic _Thread_local bool ownership_active;\n'+a+'\n  if(ownership_active && loc==ownership_loc)ownership_frees++;')
 a='  H[tl]=TERM_HOLE;H[tl+1]=0;';assert c.count(a)==1
 c=c.replace(a,'  ownership_loc=term_loc(t);ownership_frees=0;ownership_active=true;\n'+a)
 a='  if(returned!=0 || !root_done(H) || err_seen(H))';assert c.count(a)==1
 c=c.replace(a,'  ownership_active=false;\n  if(ownership_frees!=1)err_fail("test: owned gateway not freed exactly once");\n  fprintf(stderr,"OWNERSHIP one-free original-cont=%u original-slot=%u\\n",cont==TERM_HOLE?65535u:(u32)term_aux(cont),idx);\n'+a)
 (d/'instrumented.c').write_text(c)
 p=subprocess.run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',str(d/'instrumented.c'),'-lpthread','-lm','-o',str(d/'program')],capture_output=True,timeout=30);assert p.returncode==0,p.stderr
 (d/'build.stderr').write_bytes(p.stderr)
 for threads in [1,2]:
  # Wrong external metadata/config must not alter the compiled mapping. The CPU
  # routing host never reads these files or delegates computation from them.
  wrong=d/'wrong-plan.json';wrong.write_text('{"gateways":[{"root_id":65535}]}\n')
  p=subprocess.run([str(d/'program'),'--gpu','off','--threads',str(threads)],capture_output=True,env={**env,'BEND_FORK_TRANSPORT':'cpu-reference','BEND_FORK_TRACE':'1','BEND_FORK_VULKAN_CONFIG':str(wrong),'BEND_FORK_ROUTING_PLAN':str(wrong)},timeout=10)
  (d/f't{threads}.stdout').write_bytes(p.stdout);(d/f't{threads}.stderr').write_bytes(p.stderr)
  assert p.returncode==0 and p.stdout==expected and p.stderr.count(b'OWNERSHIP one-free')==count and b'runtime error:' not in p.stderr,p.stderr
  rows.append({'case':name,'threads':threads,'handoffs':count,'one_free_each':True,'original_continuation_slot_observed':True,'external_metadata_cannot_change_mapping':True,'exit':p.returncode})
 # Native program rejects GPU/unsupported transport selections before handoff.
 for mode,args in [('vulkan',['--gpu','off']),('cpu-reference',['--gpu','on']),('', ['--gpu','on'])]:
  p=subprocess.run([str(d/'program'),*args],capture_output=True,env={**env,'BEND_FORK_TRANSPORT':mode,'BEND_FORK_TRACE':'1'},timeout=5)
  assert p.returncode!=0 and b'routing:' in p.stderr and b'handoff' not in p.stderr
  (d/('reject-'+(mode or 'absent')+'-'+args[-1]+'.stderr')).write_bytes(p.stderr)
(out/'RESULT.json').write_text(json.dumps({'cases':rows,'GPU_dispatches':0,'note':'Task free accounting covers selected CPU-reference handoffs; not general leak freedom or device arena semantics.'},indent=2)+'\n')
print('Four native ownership runs and six mode rejections passed.')
