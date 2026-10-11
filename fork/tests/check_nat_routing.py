"""Diagnostic-only pinned CPU instrumentation; no transport/Nat implementation."""
from pathlib import Path
import subprocess,json,hashlib,os
r=Path(__file__).resolve().parents[2];d=r/'evidence/fork-nat-routing-review'
c=(r/'evidence/fork-nat-plan-cpu/gpu_mark/upstream.c').read_text()
anchor='  e.mem[loc + ar + 1] = ((u64)idx << 32) | rem;'
assert c.count(anchor)==1
c=c.replace(anchor,anchor+'\n  fprintf(stderr,"ROUTING task-node fid=%u loc=%llu cont_fid=%u idx=%u rem=%u\\n",fid,(unsigned long long)loc,cont==TERM_HOLE?65535u:(u32)term_aux(cont),idx,rem);')
anchor='    u64 tl = task_tail(t);'
assert c.count(anchor)==1
c=c.replace(anchor,anchor+'\n    fprintf(stderr,"ROUTING corpus-yield fid=%u rem=%u fid_bangs=%u\\n",(u32)term_aux(t),(u32)H[tl+1],(unsigned)fid_bangs((u32)term_aux(t)));')
anchor='    if ((u32)H[tl + 1] != 0) {'
assert c.count(anchor)==1
c=c.replace(anchor,anchor+'\n      fprintf(stderr,"ROUTING pending join enters CPU scheduler\\n");')
(d/'instrumented.c').write_text(c)
env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
rows=[]
for tag,cmd in [('build',['clang','-std=c11','-O2',d/'instrumented.c','-lpthread','-lm','-o',d/'instrumented'])]+[(f'threads{n}',[d/'instrumented','--gpu','off','--threads',str(n)]) for n in [1,2]]:
 p=subprocess.run(list(map(str,cmd)),capture_output=True,env=env,timeout=20)
 (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
 (d/(tag+'.json')).write_text(json.dumps({'argv':list(map(str,cmd)),'exit':p.returncode},indent=2)+'\n')
 assert p.returncode==0,p.stderr
 if tag!='build':
  assert p.stdout==b'1212\n'
  assert b'corpus-yield fid=4 rem=2 fid_bangs=0' in p.stderr and b'pending join enters CPU scheduler' in p.stderr
  assert b'cont_fid=7 idx=1 rem=2' in p.stderr
  rows.append({'threads':int(tag[-1]),'stdout':'1212\n','ordinary_pending_join_FID':4,'ordinary_pending_remaining':2,'ordinary_pending_fid_bangs':False,'ordinary_join_identified_by_continuation_FID':7,'note':'Ordinary join observed inside CPU pool; corpus-yield trace is first bang recursion under GPU off.'})
(d/'RESULT.json').write_text(json.dumps({'scope':'diagnostic CPU trace of unchanged pinned gpu_mark; no transport extension','source_sha256':hashlib.sha256((r/'evidence/fork-nat-plan-cpu/gpu_mark/upstream.c').read_bytes()).hexdigest(),'gpu_dispatches':0,'runs':rows,'finding':'Function-global fid_bangs does not encode call-site origin; ordinary recursive half yields pending CPU join.'},indent=2)+'\n')
