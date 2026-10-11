"""Native fault injection into generated host records before CPU scheduling."""
from pathlib import Path
import subprocess,json,hashlib,os,sys
r=Path(__file__).resolve().parents[2];base=r/'evidence'/(sys.argv[2] if len(sys.argv)>2 else 'fork-cpu-routing-lifecycle-v2')/'gpu_mark/generated'
out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-cpu-routing-dynamic');out.mkdir(exist_ok=False)
code=(base/'program.c').read_text();plan=json.loads((base/'routing-plan.json').read_text());env={**os.environ,'BEND_FORK_TRANSPORT':'cpu-reference','BEND_FORK_TRACE':'1'}
gateway=plan['gateways'][0];root=plan['segments'][gateway['root_id']]
join=next(j for j in plan['joins'] if j['children'][0]['id']==root['id'])
safe=next(s for s in plan['segments'] if not s['effect'] and s['arity']==2 and not s['frame_result_words'])
pending='if(mode && *mode)routing_pending(H,t);'
entry='t=routing_reference(e,t);if(t==0)break;continue;'
assert code.count(pending)==1 and code.count(entry)==1
faults={
 'child_wrong_FID':('pending',f'H[term_loc(t)]=term_tsk({safe["id"]},term_loc(H[term_loc(t)]));','dynamic child differs'),
 'child_wrong_slot':('pending','Term c=H[term_loc(t)];H[routing_tail(H,c)+1]=1ull<<32;','invalid continuation'),
 'child_wrong_parent':('pending','Term c=H[term_loc(t)];H[routing_tail(H,c)]=TERM_HOLE;','invalid continuation'),
 'join_wrong_continuation':('pending',f'H[tl]=term_tsk({safe["id"]},term_loc(H[tl]));','pending count differs'),
 'join_wrong_valid_slot':('pending','H[tl+1] &= 0xffffffffull;','compiled caller context'),
 'join_cycle':('pending','H[tl]=t;','cyclic continuation chain'),
 'join_count':('pending','H[tl+1]=(H[tl+1]&0xffffffff00000000ull)|1u;','pending count differs'),
 'missing_child_with_matching_count':('pending','H[term_loc(t)]=0;H[tl+1]=(H[tl+1]&0xffffffff00000000ull)|1u;','pending count differs'),
 'missing_child_without_count_change':('pending','H[term_loc(t)]=0;','required compiled child task is missing'),
 'already_completed_root':('pending','H[H_ROOT_DONE]=1;','pending scheduling with completed root'),
 'child_outside_heap':('pending',f'H[term_loc(t)]=term_tsk({root["id"]},corpus_size/8);','invalid dynamic task layout'),
 'gateway_wrong_slot':('entry','H[tl+1]=1ull<<32;','compiled caller context'),
 'full_u64_no_truncation':('entry','H[term_loc(t)]=4294967298ull;','supported depth five'),
 'upstream_nat_cap':('entry','H[term_loc(t)]=281474976710656ull;','upstream immediate cap'),
}
rows=[]
for name,(at,mutate,error) in faults.items():
 d=out/name;d.mkdir()
 if at=='pending':c=code.replace(pending,'if(mode && *mode){'+mutate+'routing_pending(H,t);}')
 else:c=code.replace(entry,mutate+entry)
 (d/'mutated.c').write_text(c)
 build=subprocess.run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',str(d/'mutated.c'),'-lpthread','-lm','-o',str(d/'program')],capture_output=True,timeout=30)
 (d/'build.stderr').write_bytes(build.stderr);assert build.returncode==0,build.stderr
 p=subprocess.run([str(d/'program'),'--gpu','off','--threads','1'],capture_output=True,env=env,timeout=10)
 (d/'stdout').write_bytes(p.stdout);(d/'stderr').write_bytes(p.stderr)
 assert p.returncode!=0 and error.encode() in p.stderr and b'runtime error:' not in p.stderr,(name,p.stderr)
 assert b'routing CPU pending' not in p.stderr,(name,p.stderr)
 rows.append({'case':name,'exit':p.returncode,'rejected_before_CPU_pool_entry':True,'expected_error':error,'mutated_source_sha256':hashlib.sha256(c.encode()).hexdigest()})
 print(name,'PASS',flush=True)
# Disk metadata/config swapping cannot change the compiled gateway table.
proof=subprocess.run(['bun',str(r/'fork/tests/check_routing_proof.ts'),str(base/'routing-plan.json')],capture_output=True,timeout=10)
(out/'proof.stdout').write_bytes(proof.stdout);(out/'proof.stderr').write_bytes(proof.stderr);assert proof.returncode==0,proof.stderr
(out/'RESULT.json').write_text(json.dumps({'cases':rows,'proof':json.loads(proof.stdout),'gpu_dispatches':0,'scope':'generated native host record faults and independent proof validation'},indent=2)+'\n')
