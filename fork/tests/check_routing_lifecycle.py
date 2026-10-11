"""Exact malformed lifecycle regressions with exit-time non-consumption checks."""
from pathlib import Path
import subprocess,json,os,sys,hashlib
r=Path(__file__).resolve().parents[2];group=r/'evidence'/(sys.argv[2] if len(sys.argv)>2 else 'fork-cpu-routing-lifecycle-v2')
out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-cpu-routing-lifecycle-faults');out.mkdir(exist_ok=False)
env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')};rows=[]
faults={
 'parent_remaining_zero':('gpu_mark','entry','Term p=H[tl];u64 pt=routing_tail(H,p);H[pt+1]&=0xffffffff00000000ull;','serial ancestor remaining count'),
 'parent_remaining_two':('gpu_mark','entry','Term p=H[tl];u64 pt=routing_tail(H,p);H[pt+1]=(H[pt+1]&0xffffffff00000000ull)|2u;','serial ancestor remaining count'),
 'upper_ancestor_remaining_zero':('gpu_mark','entry','Term p=H[tl];Term q=H[routing_tail(H,p)];u64 qt=routing_tail(H,q);H[qt+1]&=0xffffffff00000000ull;','serial ancestor remaining count'),
 'ancestor_result_published':('gpu_mark','entry','Term p=H[tl];H[term_loc(p)]=0;','serial ancestor result slot is already published'),
 'missing_child_matching_count':('gpu_mark','pending','H[term_loc(t)]=0;H[tl+1]=(H[tl+1]&0xffffffff00000000ull)|1u;','pending count differs from compiled join shape'),
 'missing_child_original_count':('gpu_mark','pending','H[term_loc(t)]=0;','required compiled child task is missing'),
 'extra_task_in_capture':('captured_join','pending','H[term_loc(t)]=H[term_loc(t)+1];','extra task outside compiled child slots'),
 'serial_capture_task':('gpu_mark','pending','Term p=H[tl];H[term_loc(p)]=H[term_loc(t)];','extra task in serial ancestor capture'),
}
globals_text='''
static bool lifecycle_active;
static u64* lifecycle_H;
static u64 lifecycle_loc, lifecycle_tail, lifecycle_count, lifecycle_root, lifecycle_done;
static u64 lifecycle_task[257], lifecycle_ancestor_tail[64], lifecycle_ancestor_count[64];
static unsigned lifecycle_words, lifecycle_ancestors;
static unsigned lifecycle_frees;
static void lifecycle_exit_check(void) {
  if(!lifecycle_active)return;
  bool unchanged=lifecycle_frees==0 && lifecycle_H[H_ROOT_DONE]==lifecycle_done && lifecycle_H[H_ROOT_WORD]==lifecycle_root;
  for(unsigned i=0;i<lifecycle_words;i++)unchanged &= lifecycle_H[lifecycle_loc+i]==lifecycle_task[i];
  for(unsigned i=0;i<lifecycle_ancestors;i++)unchanged &= lifecycle_H[lifecycle_ancestor_tail[i]+1]==lifecycle_ancestor_count[i];
  unchanged &= lifecycle_H[lifecycle_tail+1]==lifecycle_count;
  fprintf(stderr,"LIFECYCLE no-free=%u no-root-publication=%u task-and-count-unchanged=%u\\n",lifecycle_frees==0,
    lifecycle_H[H_ROOT_DONE]==lifecycle_done && lifecycle_H[H_ROOT_WORD]==lifecycle_root,unchanged);
  if(!unchanged)_Exit(91);
}
'''
for name,(case,where,mutate,error) in faults.items():
 d=out/name;d.mkdir();base=group/case/'generated/program.c';c=base.read_text()
 a='INLINE void heap_free(Env e, u32 cls, u64 loc) {';assert c.count(a)==1
 c=c.replace(a,globals_text+a+'\n  if(lifecycle_active && loc==lifecycle_loc)lifecycle_frees++;')
 # Upstream fail-stop uses _exit, so register the observation at that exact
 # boundary instead of relying on normal atexit handlers being executed.
 a='static void err_fail(const char* msg) {';assert c.count(a)==1
 c=c.replace(a,'static void lifecycle_exit_check(void);\n'+a)
 a='  _exit(1);';assert c.count(a)==1
 c=c.replace(a,'  lifecycle_exit_check();\n'+a)
 watch='lifecycle_active=true;lifecycle_H=H;lifecycle_loc=term_loc(t);lifecycle_tail=tl;lifecycle_count=H[tl+1];lifecycle_root=H[H_ROOT_WORD];lifecycle_done=H[H_ROOT_DONE];lifecycle_words=routing_arity[(u32)term_aux(t)]+2;for(unsigned i=0;i<lifecycle_words;i++)lifecycle_task[i]=H[lifecycle_loc+i];for(Term a=H[tl];a!=TERM_HOLE;){unsigned i=lifecycle_ancestors++;if(i==64)_Exit(92);u64 at=routing_tail(H,a);lifecycle_ancestor_tail[i]=at;lifecycle_ancestor_count[i]=H[at+1];a=H[at];}atexit(lifecycle_exit_check);'
 if where=='entry':
  a='t=routing_reference(e,t);if(t==0)break;continue;';assert c.count(a)==1
  c=c.replace(a,mutate+watch+a)
 else:
  a='if(mode && *mode)routing_pending(H,t);';assert c.count(a)==1
  c=c.replace(a,'if(mode && *mode){'+mutate+watch+'routing_pending(H,t);}')
 (d/'fault.c').write_text(c)
 p=subprocess.run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',str(d/'fault.c'),'-lpthread','-lm','-o',str(d/'program')],capture_output=True,timeout=30);assert p.returncode==0,p.stderr
 (d/'build.stderr').write_bytes(p.stderr)
 for n in [1,2]:
  p=subprocess.run([str(d/'program'),'--gpu','off','--threads',str(n)],capture_output=True,env={**env,'BEND_FORK_TRANSPORT':'cpu-reference','BEND_FORK_TRACE':'1'},timeout=10)
  (d/f't{n}.stdout').write_bytes(p.stdout);(d/f't{n}.stderr').write_bytes(p.stderr)
  assert p.returncode==1 and p.stdout==b'' and error.encode() in p.stderr and b'runtime error:' not in p.stderr,(name,p.returncode,p.stderr)
  if where=='entry':
   assert b'CPU-reference handoff' not in p.stderr and b'LIFECYCLE no-free=1 no-root-publication=1 task-and-count-unchanged=1' in p.stderr,(name,p.stderr)
  else:assert b'routing CPU pending' not in p.stderr and p.stderr.count(b'CPU-reference handoff')==1,(name,p.stderr)
  assert b'LIFECYCLE no-free=1 no-root-publication=1 task-and-count-unchanged=1' in p.stderr,(name,p.stderr)
  rows.append({'case':name,'threads':n,'exit':p.returncode,'no_successful_output':True,'rejected_before_handoff' :where=='entry','gateway_not_consumed_or_freed':where=='entry','watched_task_not_consumed_or_freed':True,'task_and_ancestor_counts_unchanged':True,'no_new_root_publication':True,'prior_legitimate_handoffs':0 if where=='entry' else 1,'rejected_before_CPU_pool_entry':True,'source_sha256':hashlib.sha256(c.encode()).hexdigest()})
 print(name,'PASS both threads',flush=True)
(out/'RESULT.json').write_text(json.dumps({'cases':rows,'GPU_dispatches':0,'scope':'exact reviewer count/tag corruptions plus ancestor publication/capture lifecycle; no valid-source trigger claimed'},indent=2)+'\n')
