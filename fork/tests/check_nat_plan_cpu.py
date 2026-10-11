"""Independent upstream CPU matrix before Nat lowering. No GPU/model calls."""
from pathlib import Path
import subprocess,json,hashlib,os,sys
root=Path(__file__).resolve().parents[2]
upstream=root.parent/'bend-vulkan-feasibility/source/tests/run'
out=root/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-nat-plan-cpu');out.mkdir(exist_ok=True)
rows=[]
env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
def run(cmd,d,tag):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,timeout=30,env=env)
 (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
 (d/(tag+'.json')).write_text(json.dumps({'argv':list(map(str,cmd)),'exit':p.returncode},indent=2)+'\n')
 return p
sources=[(name,upstream/(name+'.bend')) for name in ['gpu_mark','nat_native','nat_add_infix','nat_overflow','fork_shapes','fork_leaf_result_loop']]
original=(upstream/'gpu_mark.bend').read_text()
for depth in [0,1,3,5]:
 p=out/('gpu_mark_depth_'+str(depth)+'.bend')
 p.write_text(original.replace('2n',str(depth)+'n').split('#|')[0]+f'#|{303*(2**depth)}\n')
 sources.append((p.stem,p))
p=out/'renamed_depth3_base7.bend'
p.write_text(original.replace('gmark','renamed_probe').replace('2n','3n').replace('      3\n','      7\n').split('#|')[0]+'#|5656\n')
sources.append((p.stem,p))
for name,source in sources:
 d=out/name;d.mkdir(exist_ok=False)
 p=run(['bun',root/'fork/tests/plan_cpu_compile.ts',source,d],d,'emit')
 assert p.returncode==0,(name,p.stderr)
 assert (d/'upstream.c').read_bytes()==(d/'default.c').read_bytes(),name
 for compiler in ['upstream','default']:
  p=run(['clang','-std=c11','-O2',d/(compiler+'.c'),'-lpthread','-lm','-o',d/compiler],d,'build-'+compiler)
  assert p.returncode==0,(name,p.stderr)
 results=[]
 for threads in [1,2]:
  base=run([d/'upstream','--gpu','off','--threads',str(threads)],d,'upstream-t'+str(threads))
  candidate=run([d/'default','--gpu','off','--threads',str(threads)],d,'default-t'+str(threads))
  assert (base.returncode,base.stdout,base.stderr)==(candidate.returncode,candidate.stdout,candidate.stderr),name
  results.append({'threads':threads,'exit':base.returncode,'stdout':base.stdout.decode(),'stderr':base.stderr.decode()})
 rows.append({'case':name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'emitted_C_byte_equal':True,'raw_stdout_stderr_exit_equal':True,'runs':results})
 print(name,'PASS',flush=True)
(out/'RESULT.json').write_text(json.dumps({'scope':'pinned upstream CPU/default regression only; proposed Nat transport not implemented','gpu_dispatches':0,'cases':rows},indent=2)+'\n')
