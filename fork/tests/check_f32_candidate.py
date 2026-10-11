"""Reproduce the one-example non-admitted candidate, CPU and static checks only."""
import json,os,subprocess,sys,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];source=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
if out.exists():raise SystemExit('output must be fresh')
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
def small_build():resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
rows=[]
def run(name,args,env=None,build=False):
 r=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,timeout=40,preexec_fn=small_build if build else None)
 if out.exists():
  (out/(name+'.stdout')).write_bytes(r.stdout);(out/(name+'.stderr')).write_bytes(r.stderr)
 rows.append(dict(name=name,exit=r.returncode,stdout=r.stdout.decode(),stderr=r.stderr.decode()))
 return r
r=run('prepare',['bun',str(ROOT/'fork/f32_transport_cli.ts'),str(source),str(out)],build=True)
if r.returncode:raise RuntimeError('candidate preparation failed '+r.stderr.decode())
r=run('upstream-source',['bun',str(ROOT/'fork/upstream_compile.ts'),str(source),str(out/'upstream.c')],build=True);assert r.returncode==0
assert (out/'default.c').read_bytes()==(out/'upstream.c').read_bytes()
for lane in ('upstream','program'):
 r=run('build-'+lane,['clang','-std=c11','-O1','-ffp-contract=off',str(out/(lane+'.c')),'-lpthread','-lm','-o',str(out/lane)],build=True);assert r.returncode==0
for threads in (1,2):
 for lane in ('upstream','program'):
  env=dict(os.environ);env.pop('BEND_FORK_TRANSPORT',None)
  if lane=='program':env['BEND_FORK_TRANSPORT']='cpu-reference'
  r=run(lane+'-t'+str(threads),[str(out/lane),'--gpu','off','--threads',str(threads)],env);assert r.returncode==0 and r.stdout==b'78542\n'
r=run('shader-cpu',['python3',str(ROOT/'fork/tests/check_f32_shader_cpu.py'),str(out),str(out/'shader-cpu-check')],build=True);assert r.returncode==0
config=out/'f32-transport.json';env=dict(os.environ,BEND_FORK_TRANSPORT='f32-vulkan',BEND_FORK_F32_CONFIG=str(config))
r=run('non-admitted-refusal',[str(out/'program'),'--threads','1'],env)
assert r.returncode!=0 and not r.stdout and b'admission disabled' in r.stderr
(out/'CANDIDATE-RESULT.json').write_text(json.dumps({'passed':True,'GPU_dispatches':0,'ordinary_C_byte_parity':True,'rows':rows,'hardware_status':'not admitted; independent review and assigned hardware gate required'},indent=2)+'\n')
print(str(out/'CANDIDATE-RESULT.json'))
